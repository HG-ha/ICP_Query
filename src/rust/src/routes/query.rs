use crate::beian::Beian;
use crate::state::AppState;
use crate::utils::is_valid_url;
use axum::extract::{Path, Query, State};
use axum::routing::get;
use axum::{Json, Router};
use serde::Deserialize;
use serde_json::{json, Value};
use tracing::{error, info, warn};

#[derive(Debug, Deserialize, Default)]
pub struct QueryParams {
    pub search: Option<String>,
    #[serde(rename = "pageNum")]
    pub page_num: Option<Value>,
    #[serde(rename = "pageSize")]
    pub page_size: Option<Value>,
    pub proxy: Option<String>,
}

#[derive(Debug, Deserialize)]
pub struct QueryBody {
    pub search: Option<String>,
    #[serde(rename = "pageNum")]
    pub page_num: Option<Value>,
    #[serde(rename = "pageSize")]
    pub page_size: Option<Value>,
    pub proxy: Option<String>,
}

pub async fn resolve_proxy(state: &AppState, specified: Option<&str>) -> Result<Option<String>, Value> {
    if let Some(p) = specified {
        info!("使用指定代理：{p}");
        return Ok(Some(format!("http://{p}")));
    }

    let cfg = state.config.read().clone();

    if cfg.proxy.local_ipv6_pool.enable {
        return Ok(Some(String::new()));
    }

    if let Some(ref tunnel) = cfg.proxy.tunnel.url {
        if is_valid_url(tunnel) {
            info!("使用隧道代理：{tunnel}");
            return Ok(Some(tunnel.clone()));
        } else {
            error!("当前启用隧道代理，但代理地址无效：{tunnel}");
            return Err(json!({"code":500,"message":"当前启用隧道代理，但代理地址无效"}));
        }
    }

    if let Some(ref api_url) = cfg.proxy.extra_api.url {
        if !is_valid_url(api_url) {
            error!("当前启用API提取代理，但API地址无效：{api_url}");
            return Err(json!({"code":500,"message":"当前启用API提取代理，但API地址无效"}));
        }
        if cfg.proxy.extra_api.auto_maintenace {
            if let Some(ref pool) = state.proxy_pool {
                match pool.getproxy().await {
                    Ok(p) => {
                        info!("从本地地址池获得代理：{p}");
                        return Ok(Some(p));
                    }
                    Err(e) => {
                        return Err(json!({"code":500,"message": e}));
                    }
                }
            }
        } else {
            let client = reqwest::Client::builder()
                .timeout(std::time::Duration::from_secs(
                    cfg.system.http_client_timeout.max(1),
                ))
                .danger_accept_invalid_certs(true)
                .build()
                .map_err(|e| json!({"code":500,"message": e.to_string()}))?;
            let text = client
                .get(api_url)
                .send()
                .await
                .map_err(|e| json!({"code":500,"message": e.to_string()}))?
                .text()
                .await
                .map_err(|e| json!({"code":500,"message": e.to_string()}))?;
            let parts: Vec<&str> = text.split_whitespace().collect();
            if let Some(p) = parts.first() {
                let proxy = format!("http://{}", p.trim());
                info!("从代理提取接口获得代理：{proxy}");
                return Ok(Some(proxy));
            }
        }
    }

    Ok(None)
}

pub async fn do_query(
    state: &AppState,
    path: &str,
    search: &str,
    page_num: Option<Value>,
    page_size: Option<Value>,
    specified_proxy: Option<&str>,
) -> Value {
    let cfg = state.config.read().clone();

    if !Beian::is_normal_type(path) && !Beian::is_black_type(path) {
        return json!({"code":102,"msg":"不是支持的查询类型"});
    }
    if !cfg.risk_avoidance.allow_type.iter().any(|t| t == path) {
        return json!({"code":102,"msg":"不是支持的查询类型"});
    }
    if cfg
        .risk_avoidance
        .prohibit_suffix
        .iter()
        .any(|s| search.ends_with(s))
    {
        return json!({"code": 405,"message":"不允许的查询内容"});
    }
    if search.is_empty() {
        return json!({"code":101,"msg":"参数错误,请指定search参数"});
    }

    let retry = cfg.captcha.retry_times.max(1);
    let mut last = json!({"code":500,"message":"查询失败"});

    for _ in 0..retry {
        let proxy = match resolve_proxy(state, specified_proxy).await {
            Ok(p) => p,
            Err(e) => return e,
        };

        let data = state
            .beian
            .query(
                path,
                search,
                page_num.clone(),
                page_size.clone(),
                proxy.as_deref(),
            )
            .await;

        if data.get("code").and_then(|c| c.as_i64()) == Some(200) {
            if cfg.history.save_query_history {
                let result_count = if Beian::is_normal_type(path) {
                    data["params"]["list"]
                        .as_array()
                        .map(|a| a.len() as i64)
                        .unwrap_or(0)
                } else {
                    data["params"]
                        .as_array()
                        .map(|a| a.len() as i64)
                        .unwrap_or(0)
                };
                state
                    .db
                    .add_history(path, search, result_count, data.get("params"));
            }
            return data;
        }
        if data.get("message").and_then(|m| m.as_str()) == Some("当前访问已被创宇盾拦截") {
            warn!("当前访问已被创宇盾拦截");
            return data;
        }
        last = data;
    }
    last
}

async fn query_get(
    State(state): State<AppState>,
    Path(path): Path<String>,
    Query(q): Query<QueryParams>,
) -> Json<Value> {
    let search = q.search.unwrap_or_default();
    Json(
        do_query(
            &state,
            &path,
            &search,
            q.page_num,
            q.page_size,
            q.proxy.as_deref(),
        )
        .await,
    )
}

async fn query_post(
    State(state): State<AppState>,
    Path(path): Path<String>,
    Json(body): Json<QueryBody>,
) -> Json<Value> {
    let search = body.search.unwrap_or_default();
    Json(
        do_query(
            &state,
            &path,
            &search,
            body.page_num,
            body.page_size,
            body.proxy.as_deref(),
        )
        .await,
    )
}

pub fn routes() -> Router<AppState> {
    Router::new()
        .route("/query/{path}", get(query_get).post(query_post))
}
