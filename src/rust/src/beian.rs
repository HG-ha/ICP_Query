//! MIIT ICP 查询客户端（对应 Python ymicp.beian）

use crate::captcha::match_slider_offset;
use crate::config::AppConfig;
use crate::http_client;
use crate::ipv6_pool::SharedIpv6Pool;
use crate::utils::get_local_ipv6_addresses;
use base64::{engine::general_purpose::STANDARD, Engine};
use parking_lot::Mutex;
use rand::Rng;
use serde_json::{json, Value};
use std::collections::HashMap;
use std::sync::Arc;
use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};
use tracing::{info, warn};
use uuid::Uuid;

const FALLBACK_SIGN: &str =
    "eyJ0eXBlIjozLCJleHREYXRhIjp7InZhZnljb2RlX2ltYWdlX2tleSI6IjUyZWI1ZTcyODViNzRmNWJhM2YwYzBkNTg0YTg3NmVmIn0sImUiOjE3NTY5NzAyNDg4MjN9.Ngpkwn4T7sQoQF9pCk_sQQpH61wQUEKnK2sQ8hDIq-Q";

const UA: &str = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/101.0.4951.41 Safari/537.36 Edg/101.0.1210.32";

const AUTH_URL: &str = "https://hlwicpfwc.miit.gov.cn/icpproject_query/api/auth";
const GET_CHECK_IMAGE: &str =
    "https://hlwicpfwc.miit.gov.cn/icpproject_query/api/image/getCheckImagePoint";
const CHECK_IMAGE: &str = "https://hlwicpfwc.miit.gov.cn/icpproject_query/api/image/checkImage";
const QUERY_BY_CONDITION: &str =
    "https://hlwicpfwc.miit.gov.cn/icpproject_query/api/icpAbbreviateInfo/queryByCondition";
const BLACK_QUERY: &str =
    "https://hlwicpfwc.miit.gov.cn/icpproject_query/api/blackListDomain/queryByCondition";
const BLACK_APP_QUERY: &str =
    "https://hlwicpfwc.miit.gov.cn/icpproject_query/api/blackListDomain/queryByCondition_appAndMini";
const DETAIL_URL: &str =
    "https://hlwicpfwc.miit.gov.cn/icpproject_query/api/icpAbbreviateInfo/queryDetailByAppAndMiniId";

pub type SharedBeian = Arc<Beian>;

struct TokenCache {
    token: String,
    expire_ms: u64,
}

pub struct Beian {
    config: Arc<parking_lot::RwLock<AppConfig>>,
    token: Mutex<TokenCache>,
    blocked_ips: Mutex<HashMap<String, Instant>>,
    ipv6_pool: Mutex<Option<SharedIpv6Pool>>,
    /// 无池时的本机 IPv6 列表（与 Python 启动时 get_local_ipv6_addresses 对齐）
    local_ipv6_addresses: Mutex<Vec<String>>,
    ipv6_index: Mutex<usize>,
    last_used_ipv6: Mutex<Option<String>>,
}

impl Beian {
    pub fn new(config: Arc<parking_lot::RwLock<AppConfig>>) -> Self {
        let enable = config.read().proxy.local_ipv6_pool.enable;
        let addrs = if enable {
            get_local_ipv6_addresses()
        } else {
            vec![]
        };
        Self {
            config,
            token: Mutex::new(TokenCache {
                token: String::new(),
                expire_ms: 0,
            }),
            blocked_ips: Mutex::new(HashMap::new()),
            ipv6_pool: Mutex::new(None),
            local_ipv6_addresses: Mutex::new(addrs),
            ipv6_index: Mutex::new(0),
            last_used_ipv6: Mutex::new(None),
        }
    }

    pub fn set_ipv6_pool(&self, pool: Option<SharedIpv6Pool>) {
        if let Some(ref p) = pool {
            *self.local_ipv6_addresses.lock() = p.get_all_addresses();
        }
        *self.ipv6_pool.lock() = pool;
    }

    fn now_ms() -> u64 {
        SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap_or_default()
            .as_millis() as u64
    }

    fn timeout(&self) -> Duration {
        Duration::from_secs(self.config.read().system.http_client_timeout.max(1))
    }

    fn ipv6_enabled(&self) -> bool {
        self.config.read().proxy.local_ipv6_pool.enable
    }

    fn base_headers() -> HashMap<String, String> {
        let mut h = HashMap::new();
        h.insert("User-Agent".into(), UA.into());
        h.insert("Origin".into(), "https://beian.miit.gov.cn".into());
        h.insert("Referer".into(), "https://beian.miit.gov.cn/".into());
        h.insert(
            "Cookie".into(),
            format!("__jsluid_s={}", Uuid::new_v4().simple()),
        );
        h.insert("Accept".into(), "application/json, text/plain, */*".into());
        h
    }

    fn purge_blocked(&self) {
        self.blocked_ips
            .lock()
            .retain(|_, t| t.elapsed() < Duration::from_secs(300));
    }

    fn is_ip_blocked(&self, ip: &str) -> bool {
        self.blocked_ips.lock().contains_key(ip)
    }

    fn add_blocked_ip(&self, ip: &str) {
        if ip.is_empty() {
            return;
        }
        self.blocked_ips
            .lock()
            .insert(ip.to_string(), Instant::now());
        info!("IP {ip} 被创宇盾拦截已添加到黑名单缓存，5 分钟后恢复使用");
    }

    /// 解析 proxy：非空为 HTTP 代理；空/None 且启用 IPv6 池时绑定本地 IPv6（对齐 Python `if not proxy`）
    async fn resolve_transport(
        &self,
        proxy: Option<&str>,
    ) -> (Option<String>, Option<String>) {
        if let Some(p) = proxy {
            if !p.is_empty() {
                return (Some(p.to_string()), None);
            }
        }
        if self.ipv6_enabled() {
            let ip = self.get_next_ipv6().await;
            return (None, ip);
        }
        (None, None)
    }

    async fn get_next_ipv6(&self) -> Option<String> {
        self.purge_blocked();

        // 优先从地址池取
        let pool = self.ipv6_pool.lock().clone();
        if let Some(pool) = pool {
            // 同步刷新本地列表
            *self.local_ipv6_addresses.lock() = pool.get_all_addresses();
            let blocked = |ip: &str| self.is_ip_blocked(ip);
            if let Some(addr) = pool.get_next_unblocked(blocked).await {
                *self.last_used_ipv6.lock() = Some(addr.clone());
                return Some(addr);
            }
            return None;
        }

        // 回退：本机地址轮询
        let addrs = self.local_ipv6_addresses.lock().clone();
        if addrs.is_empty() {
            return None;
        }
        let mut idx = self.ipv6_index.lock();
        let max_attempts = addrs.len() * 2;
        for _ in 0..max_attempts {
            let current = addrs[*idx % addrs.len()].clone();
            *idx = (*idx + 1) % addrs.len();
            if !self.is_ip_blocked(&current) {
                *self.last_used_ipv6.lock() = Some(current.clone());
                return Some(current);
            }
        }
        warn!("所有 IPv6 地址都被拦截，暂无可用地址");
        None
    }

    async fn post(
        &self,
        url: &str,
        headers: &HashMap<String, String>,
        body: Vec<u8>,
        content_type: Option<&str>,
        proxy: Option<&str>,
    ) -> Result<String, String> {
        let (proxy_url, local_ip) = self.resolve_transport(proxy).await;
        let text = http_client::post_text(
            url,
            headers,
            body,
            content_type,
            proxy_url.as_deref(),
            local_ip.as_deref(),
            self.timeout(),
        )
        .await?;

        if text.contains("当前访问疑似黑客攻击") {
            if let Some(ip) = local_ip.or_else(|| self.last_used_ipv6.lock().clone()) {
                self.add_blocked_ip(&ip);
            }
            return Err("当前访问已被创宇盾拦截".into());
        }
        Ok(text)
    }

    async fn get_token(
        &self,
        proxy: Option<&str>,
    ) -> Result<(String, HashMap<String, String>), String> {
        let headers = Self::base_headers();
        {
            let cache = self.token.lock();
            if cache.expire_ms > Self::now_ms() && !cache.token.is_empty() {
                return Ok((cache.token.clone(), headers));
            }
        }

        let time_stamp = Self::now_ms();
        let auth_secret = format!("testtest{time_stamp}");
        let auth_key = format!("{:x}", md5::compute(auth_secret.as_bytes()));
        let body = format!("authKey={auth_key}&timeStamp={time_stamp}");

        let text = self
            .post(
                AUTH_URL,
                &headers,
                body.into_bytes(),
                Some("application/x-www-form-urlencoded"),
                proxy,
            )
            .await
            .map_err(|e| {
                if e.contains("创宇盾") {
                    e
                } else {
                    warn!("get_token Faile : {e}");
                    e
                }
            })?;

        let t: Value = serde_json::from_str(&text).map_err(|e| e.to_string())?;
        let token = t["params"]["bussiness"]
            .as_str()
            .ok_or("token 响应缺少 bussiness")?
            .to_string();
        let expire_add = t["params"]["expire"].as_u64().unwrap_or(0);

        {
            let mut cache = self.token.lock();
            cache.token = token.clone();
            cache.expire_ms = Self::now_ms() + expire_add;
        }

        Ok((token, headers))
    }

    fn get_client_uid() -> String {
        let chars: Vec<char> = "0123456789abcdef".chars().collect();
        let mut rng = rand::thread_rng();
        let mut unique_id: Vec<char> = (0..36).map(|_| chars[rng.gen_range(0..16)]).collect();
        unique_id[14] = '4';
        let idx19 = unique_id[19].to_digit(16).unwrap_or(0) as usize;
        unique_id[19] = chars[(3 & idx19) | 8];
        unique_id[8] = '-';
        unique_id[13] = '-';
        unique_id[18] = '-';
        unique_id[23] = '-';
        let point_id: String = unique_id.iter().collect();
        json!({"clientUid": format!("point-{point_id}")}).to_string()
    }

    async fn check_img(
        &self,
        proxy: Option<&str>,
    ) -> Result<(String, String, String, HashMap<String, String>), String> {
        let (token, mut base_header) = self.get_token(proxy).await?;
        let data = Self::get_client_uid();
        base_header.insert("token".into(), token.clone());

        let text = self
            .post(
                GET_CHECK_IMAGE,
                &base_header,
                data.into_bytes(),
                Some("application/json"),
                proxy,
            )
            .await
            .map_err(|e| format!("请求验证码时失败：{e}"))?;

        let res: Value =
            serde_json::from_str(&text).map_err(|e| format!("请求验证码时失败：{e}"))?;

        let p_uuid = res["params"]["uuid"]
            .as_str()
            .ok_or("验证码响应缺少 uuid")?
            .to_string();
        let big_image = res["params"]["bigImage"]
            .as_str()
            .ok_or("验证码响应缺少 bigImage")?
            .to_string();
        let small_image = res["params"]["smallImage"]
            .as_str()
            .ok_or("验证码响应缺少 smallImage")?
            .to_string();

        let start = Instant::now();
        let offset_x = match_slider_offset(&small_image, &big_image)
            .map_err(|e| format!("滑块匹配失败：{e}"))?;
        info!(
            "滑块匹配用时 {:.3}ms",
            start.elapsed().as_secs_f64() * 1000.0
        );

        let check_data = json!({"key": p_uuid, "value": offset_x.to_string()}).to_string();
        info!("checkImage 请求体：{check_data}");

        let text = self
            .post(
                CHECK_IMAGE,
                &base_header,
                check_data.into_bytes(),
                Some("application/json"),
                proxy,
            )
            .await?;
        let data: Value = serde_json::from_str(&text).map_err(|e| e.to_string())?;
        info!(
            "checkImage 响应：code={:?}, msg={:?}, success={:?}",
            data.get("code"),
            data.get("msg"),
            data.get("success")
        );

        if !data["success"].as_bool().unwrap_or(false) {
            let cfg = self.config.read();
            if cfg.captcha.save_failed_img {
                let save_path = &cfg.captcha.save_failed_img_path;
                let _ = std::fs::create_dir_all(format!("{save_path}/ibig"));
                let _ = std::fs::create_dir_all(format!("{save_path}/isma"));
                let filename = format!("{}.jpg", Uuid::new_v4());
                if let Ok(bytes) = STANDARD.decode(&small_image) {
                    let _ = std::fs::write(format!("{save_path}/isma/{filename}"), bytes);
                }
                if let Ok(bytes) = STANDARD.decode(&big_image) {
                    let _ = std::fs::write(format!("{save_path}/ibig/{filename}"), bytes);
                }
                info!("失败验证码已保存：{filename}");
            }
            return Err("验证码识别失败".into());
        }

        let sign = match &data["params"] {
            Value::String(s) => s.clone(),
            other => other.to_string().trim_matches('"').to_string(),
        };

        Ok((p_uuid, token, sign, base_header))
    }

    async fn get_app_detail(
        &self,
        data_id: &str,
        service_type: i64,
        p_uuid: &str,
        token: &str,
        sign: &str,
        base_header: &HashMap<String, String>,
        proxy: Option<&str>,
        captcha_enable: bool,
    ) -> Result<Value, String> {
        let info = json!({"dataId": data_id, "serviceType": service_type});
        let mut detail_header = base_header.clone();
        detail_header.insert("uuid".into(), p_uuid.into());
        detail_header.insert("token".into(), token.into());
        detail_header.insert("sign".into(), sign.into());

        if !captcha_enable {
            detail_header.remove("uuid");
        }

        let text = self
            .post(
                DETAIL_URL,
                &detail_header,
                info.to_string().into_bytes(),
                Some("application/json"),
                proxy,
            )
            .await?;
        serde_json::from_str(&text).map_err(|e| e.to_string())
    }

    async fn getbeian(
        &self,
        name: &str,
        sp: i32,
        page_num: Option<Value>,
        page_size: Option<Value>,
        proxy: Option<&str>,
    ) -> Result<Value, String> {
        let service_type = match sp {
            0 => 1,
            1 => 6,
            2 => 7,
            3 => 8,
            _ => 1,
        };
        let info = json!({
            "pageNum": page_num.unwrap_or(Value::String(String::new())),
            "pageSize": page_size.unwrap_or(Value::String(String::new())),
            "unitName": name,
            "serviceType": service_type,
        });

        let captcha_enable = self.config.read().captcha.enable;
        let (p_uuid, token, sign, base_header) = if captcha_enable {
            self.check_img(proxy).await?
        } else {
            let (token, mut headers) = self.get_token(proxy).await?;
            headers.insert("sign".into(), FALLBACK_SIGN.into());
            headers.insert("token".into(), token.clone());
            (String::new(), token, FALLBACK_SIGN.to_string(), headers)
        };

        let mut headers = base_header.clone();
        headers.insert("token".into(), token.clone());
        headers.insert("sign".into(), sign.clone());
        if captcha_enable {
            headers.insert("uuid".into(), p_uuid.clone());
        }

        let url = if captcha_enable {
            QUERY_BY_CONDITION.to_string()
        } else {
            format!("{QUERY_BY_CONDITION}/")
        };

        let text = self
            .post(
                &url,
                &headers,
                info.to_string().into_bytes(),
                Some("application/json"),
                proxy,
            )
            .await?;

        let mut result: Value = serde_json::from_str(&text).map_err(|e| e.to_string())?;

        if matches!(sp, 1 | 2 | 3)
            && result["success"].as_bool().unwrap_or(false)
            && result["params"]["list"].as_array().is_some()
        {
            let items = result["params"]["list"]
                .as_array()
                .cloned()
                .unwrap_or_default();
            if !items.is_empty() {
                info!("需要并发获取详细信息数量：{}", items.len());
                let max_concurrency = {
                    let cfg = self.config.read();
                    cfg.system
                        .detail_concurrency
                        .min(items.len())
                        .min(20)
                        .max(1)
                };
                let service_type_detail: i64 = match sp {
                    1 => 6,
                    2 => 7,
                    _ => 8,
                };
                let sign_use = if captcha_enable {
                    sign.clone()
                } else {
                    FALLBACK_SIGN.to_string()
                };

                let mut detailed = Vec::with_capacity(items.len());
                for chunk in items.chunks(max_concurrency) {
                    let mut handles = Vec::new();
                    for item in chunk {
                        let item = item.clone();
                        let data_id = item["dataId"].as_str().unwrap_or("").to_string();
                        if data_id.is_empty() {
                            detailed.push(item);
                            continue;
                        }
                        let this = self;
                        let p_uuid = p_uuid.clone();
                        let token = token.clone();
                        let sign_use = sign_use.clone();
                        let base_header = base_header.clone();
                        let proxy_owned = proxy.map(|s| s.to_string());
                        handles.push(async move {
                            match this
                                .get_app_detail(
                                    &data_id,
                                    service_type_detail,
                                    &p_uuid,
                                    &token,
                                    &sign_use,
                                    &base_header,
                                    proxy_owned.as_deref(),
                                    captcha_enable,
                                )
                                .await
                            {
                                Ok(d) if d["success"].as_bool().unwrap_or(false) => {
                                    d["params"].clone()
                                }
                                Ok(_) => {
                                    warn!("详情获取失败 dataId={data_id}");
                                    item
                                }
                                Err(e) => {
                                    warn!("详情获取异常 dataId={data_id} err={e}");
                                    item
                                }
                            }
                        });
                    }
                    detailed.extend(futures::future::join_all(handles).await);
                }
                result["params"]["list"] = Value::Array(detailed);
                info!(
                    "并发详情完成，总计 {} 条",
                    result["params"]["list"]
                        .as_array()
                        .map(|a| a.len())
                        .unwrap_or(0)
                );
            }
        }

        Ok(result)
    }

    async fn getblackbeian(
        &self,
        name: &str,
        sp: i32,
        proxy: Option<&str>,
    ) -> Result<Value, String> {
        let info = if sp == 0 {
            json!({"domainName": name})
        } else {
            let st = match sp {
                1 => 6,
                2 => 7,
                3 => 8,
                _ => 6,
            };
            json!({"serviceName": name, "serviceType": st})
        };

        let captcha_enable = self.config.read().captcha.enable;
        let (p_uuid, token, sign, mut headers) = if captcha_enable {
            self.check_img(proxy).await?
        } else {
            let (token, mut headers) = self.get_token(proxy).await?;
            headers.insert("sign".into(), FALLBACK_SIGN.into());
            headers.insert("token".into(), token.clone());
            (String::new(), token, FALLBACK_SIGN.to_string(), headers)
        };

        headers.insert("token".into(), token);
        headers.insert("sign".into(), sign);
        if captcha_enable {
            headers.insert("uuid".into(), p_uuid);
        }

        let url = if sp == 0 {
            if captcha_enable {
                BLACK_QUERY.to_string()
            } else {
                format!("{BLACK_QUERY}/")
            }
        } else if captcha_enable {
            BLACK_APP_QUERY.to_string()
        } else {
            format!("{BLACK_APP_QUERY}/")
        };

        let text = self
            .post(
                &url,
                &headers,
                info.to_string().into_bytes(),
                Some("application/json"),
                proxy,
            )
            .await?;
        serde_json::from_str(&text).map_err(|e| e.to_string())
    }

    async fn autoget(
        &self,
        name: &str,
        sp: i32,
        page_num: Option<Value>,
        page_size: Option<Value>,
        proxy: Option<&str>,
        normal: bool,
    ) -> Value {
        self.purge_blocked();
        let result = if normal {
            self.getbeian(name, sp, page_num, page_size, proxy).await
        } else {
            self.getblackbeian(name, sp, proxy).await
        };

        match result {
            Ok(data) => {
                if data["code"].as_i64() == Some(500) {
                    json!({"code": 122, "message": "工信部服务器异常"})
                } else {
                    data
                }
            }
            Err(e) => json!({"code": 500, "message": e}),
        }
    }

    pub async fn query(
        &self,
        qtype: &str,
        name: &str,
        page_num: Option<Value>,
        page_size: Option<Value>,
        proxy: Option<&str>,
    ) -> Value {
        match qtype {
            "web" => self.autoget(name, 0, page_num, page_size, proxy, true).await,
            "app" => self.autoget(name, 1, page_num, page_size, proxy, true).await,
            "mapp" => self.autoget(name, 2, page_num, page_size, proxy, true).await,
            "kapp" => self.autoget(name, 3, page_num, page_size, proxy, true).await,
            "bweb" => self.autoget(name, 0, None, None, proxy, false).await,
            "bapp" => self.autoget(name, 1, None, None, proxy, false).await,
            "bmapp" => self.autoget(name, 2, None, None, proxy, false).await,
            "bkapp" => self.autoget(name, 3, None, None, proxy, false).await,
            _ => json!({"code": 102, "msg": "不是支持的查询类型"}),
        }
    }

    pub fn is_normal_type(qtype: &str) -> bool {
        matches!(qtype, "web" | "app" | "mapp" | "kapp")
    }

    pub fn is_black_type(qtype: &str) -> bool {
        matches!(qtype, "bweb" | "bapp" | "bmapp" | "bkapp")
    }
}
