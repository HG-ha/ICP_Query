//! HTTP 代理池（对应 Python proxy_pool.py）

use crate::config::AppConfig;
use parking_lot::Mutex;
use rand::seq::SliceRandom;
use std::collections::HashMap;
use std::sync::Arc;
use std::time::{Duration, Instant};
use tokio::sync::Mutex as AsyncMutex;
use tracing::{error, info};

pub type SharedProxyPool = Arc<ProxyPool>;

struct ProxyEntry {
    added_at: Instant,
}

pub struct ProxyPool {
    config: Arc<parking_lot::RwLock<AppConfig>>,
    pool: Mutex<HashMap<String, ProxyEntry>>,
    update_lock: AsyncMutex<()>,
    stop: tokio::sync::Notify,
    running: Mutex<bool>,
}

impl ProxyPool {
    pub fn new(config: Arc<parking_lot::RwLock<AppConfig>>) -> Self {
        Self {
            config,
            pool: Mutex::new(HashMap::new()),
            update_lock: AsyncMutex::new(()),
            stop: tokio::sync::Notify::new(),
            running: Mutex::new(false),
        }
    }

    fn ttl(&self) -> Duration {
        let cfg = self.config.read();
        let secs = cfg
            .proxy
            .extra_api
            .timeout
            .saturating_sub(cfg.proxy.extra_api.timeout_drop)
            .max(1);
        Duration::from_secs(secs)
    }

    fn purge_expired(&self) {
        let ttl = self.ttl();
        let mut pool = self.pool.lock();
        pool.retain(|_, e| e.added_at.elapsed() < ttl);
    }

    pub async fn start(self: &Arc<Self>) {
        {
            let mut r = self.running.lock();
            if *r {
                return;
            }
            *r = true;
        }
        let this = Arc::clone(self);
        tokio::spawn(async move {
            this.cron_update().await;
        });
        info!("初始化地址池维护任务");
    }

    pub async fn stop(&self) {
        *self.running.lock() = false;
        self.stop.notify_waiters();
        info!("清理地址池维护任务");
    }

    async fn cron_update(self: Arc<Self>) {
        let period = {
            let cfg = self.config.read();
            Duration::from_secs(cfg.proxy.extra_api.extra_interval.max(1))
        };
        loop {
            if !*self.running.lock() {
                break;
            }
            self.update().await;
            tokio::select! {
                _ = tokio::time::sleep(period) => {}
                _ = self.stop.notified() => break,
            }
        }
        info!("代理池更新任务已取消");
    }

    async fn update(&self) {
        let _guard = self.update_lock.lock().await;
        let (url, pool_num, check_proxy, check_num, proxy_timeout, http_timeout) = {
            let cfg = self.config.read();
            (
                cfg.proxy.extra_api.url.clone(),
                cfg.proxy.extra_api.pool_num,
                cfg.proxy.extra_api.check_proxy,
                cfg.proxy.extra_api.check_proxy_num,
                cfg.proxy.extra_api.proxy_timeout,
                cfg.system.http_client_timeout,
            )
        };

        let Some(url) = url else { return };
        if url.trim().is_empty() {
            return;
        }

        self.purge_expired();
        {
            let pool = self.pool.lock();
            if pool.len() >= pool_num {
                info!("代理池饱满，无需更新代理，当前池内数量：{}", pool.len());
                return;
            }
        }

        let client = match reqwest::Client::builder()
            .timeout(Duration::from_secs(http_timeout.max(1)))
            .danger_accept_invalid_certs(true)
            .build()
        {
            Ok(c) => c,
            Err(e) => {
                error!("更新代理池失败：{e}");
                return;
            }
        };

        let text = match client.get(&url).send().await {
            Ok(r) => match r.text().await {
                Ok(t) => t,
                Err(e) => {
                    error!("更新代理池失败：{e}");
                    return;
                }
            },
            Err(e) => {
                error!("更新代理池失败：{e}");
                return;
            }
        };

        let proxy_list: Vec<String> = text
            .split(|c: char| c == '\n' || c == '\r' || c.is_whitespace())
            .map(|s| s.trim().to_string())
            .filter(|s| !s.is_empty())
            .collect();

        if proxy_list.is_empty() {
            error!("提取到的 IP 为 0");
            return;
        }

        if check_proxy {
            self.check_and_add(&proxy_list, pool_num, check_num, proxy_timeout)
                .await;
        } else {
            let mut pool = self.pool.lock();
            for address in proxy_list {
                if pool.len() >= pool_num {
                    break;
                }
                pool.insert(address, ProxyEntry { added_at: Instant::now() });
            }
        }

        info!("更新代理池成功，当前代理数量：{}", self.pool.lock().len());
    }

    async fn check_and_add(
        &self,
        proxy_list: &[String],
        pool_num: usize,
        check_num: usize,
        proxy_timeout: f64,
    ) {
        use futures::stream::{self, StreamExt};
        let timeout = Duration::from_secs_f64(proxy_timeout.max(0.1));
        let this = self;

        stream::iter(proxy_list.iter().cloned())
            .for_each_concurrent(check_num.max(1), |address| async move {
                {
                    let pool = this.pool.lock();
                    if pool.len() >= pool_num {
                        return;
                    }
                }
                let ok = check_proxy_alive(&address, timeout).await;
                if ok {
                    let mut pool = this.pool.lock();
                    if pool.len() < pool_num {
                        pool.insert(address.clone(), ProxyEntry { added_at: Instant::now() });
                        info!("入库代理成功：{address}");
                    }
                } else {
                    info!("入库检测代理不可用：{address}");
                }
            })
            .await;
    }

    /// 移除无效代理（host:port 不含 http://）
    #[allow(dead_code)]
    pub fn remove(&self, address: &str) {
        let key = address.trim_start_matches("http://");
        self.pool.lock().remove(key);
    }

    pub async fn getproxy(&self) -> Result<String, String> {
        let start = Instant::now();
        loop {
            self.purge_expired();
            {
                let pool = self.pool.lock();
                let keys: Vec<String> = pool.keys().cloned().collect();
                if let Some(k) = keys.choose(&mut rand::thread_rng()) {
                    return Ok(format!("http://{k}"));
                }
            }
            if start.elapsed() > Duration::from_secs(30) {
                return Err("等待代理超时".into());
            }
            tokio::time::sleep(Duration::from_millis(100)).await;
        }
    }
}

async fn check_proxy_alive(address: &str, timeout: Duration) -> bool {
    let proxy_url = format!("http://{address}");
    let Ok(proxy) = reqwest::Proxy::all(&proxy_url) else {
        return false;
    };
    let Ok(client) = reqwest::Client::builder()
        .timeout(timeout)
        .danger_accept_invalid_certs(true)
        .proxy(proxy)
        .build()
    else {
        return false;
    };
    match client.get("http://ifconfig.me/ip").send().await {
        Ok(r) => r.text().await.is_ok(),
        Err(_) => false,
    }
}
