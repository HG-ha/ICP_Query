//! IPv6 地址池管理（对应 Python ipv6_pool.py）

use crate::config::AppConfig;
use crate::utils::{
    check_has_permanent_ipv6, configure_ipv6_addresses, get_local_ipv6_addresses, is_public_ipv6,
};
use parking_lot::Mutex;
use rand::seq::SliceRandom;
use std::collections::HashMap;
use std::sync::Arc;
use std::time::{Duration, Instant};
use tokio::sync::Mutex as AsyncMutex;
use tracing::{debug, error, info, warn};

pub type SharedIpv6Pool = Arc<Ipv6AddressPool>;

pub struct Ipv6AddressPool {
    config: Arc<parking_lot::RwLock<AppConfig>>,
    active_addresses: Mutex<HashMap<String, Instant>>,
    system_addresses: Mutex<Vec<String>>,
    lock: AsyncMutex<()>,
    last_prefix: Mutex<Option<String>>,
    stop: tokio::sync::Notify,
    running: Mutex<bool>,
}

impl Ipv6AddressPool {
    pub fn new(config: Arc<parking_lot::RwLock<AppConfig>>) -> Self {
        Self {
            config,
            active_addresses: Mutex::new(HashMap::new()),
            system_addresses: Mutex::new(Vec::new()),
            lock: AsyncMutex::new(()),
            last_prefix: Mutex::new(None),
            stop: tokio::sync::Notify::new(),
            running: Mutex::new(false),
        }
    }

    fn pool_size(&self) -> usize {
        self.config.read().proxy.local_ipv6_pool.pool_num
    }

    fn check_interval(&self) -> Duration {
        Duration::from_secs(
            self.config
                .read()
                .proxy
                .local_ipv6_pool
                .check_interval
                .max(1),
        )
    }

    fn network_card(&self) -> String {
        self.config
            .read()
            .proxy
            .local_ipv6_pool
            .ipv6_network_card
            .clone()
    }

    pub async fn initialize(self: &Arc<Self>) -> bool {
        info!("初始化IPv6地址池...");
        self.refresh_system_addresses().await;

        if self.system_addresses.lock().is_empty() {
            error!("未找到任何公网IPv6地址,无法启用IPv6池");
            return false;
        }

        let (has_permanent, sample_addr) = check_has_permanent_ipv6();
        if has_permanent {
            warn!("{}", "=".repeat(80));
            warn!("⚠️  检测到系统中存在永久有效的IPv6地址（valid_lft forever）");
            if let Some(ref addr) = sample_addr {
                warn!("⚠️  地址: {addr}");
            }
            warn!("⚠️  这通常说明您正在使用云服务器环境（如阿里云、腾讯云等）");
            warn!("⚠️  在云服务器环境中，新增的IPv6地址可能需要通过云服务商控制台配置才能使用");
            warn!("⚠️  如果遇到新增IPv6地址无法访问外网的情况，请联系您的云服务提供商");
            warn!("⚠️  或在云服务商控制台中为您的实例分配和绑定IPv6地址段");
            warn!("{}", "=".repeat(80));
        }

        {
            let sys = self.system_addresses.lock();
            if let Some(first) = sys.first() {
                let prefix = extract_prefix(first);
                info!("检测到IPv6前缀: {prefix}");
                *self.last_prefix.lock() = Some(prefix);
            }
        }

        let addrs = self.system_addresses.lock().clone();
        info!("开始验证 {} 个系统IPv6地址的可用性...", addrs.len());
        let mut verified_count = 0usize;
        for addr in &addrs {
            if !is_public_ipv6(addr) {
                warn!("IPv6地址不是公网地址（网段检测）: {addr}");
                continue;
            }
            self.active_addresses
                .lock()
                .insert(addr.clone(), Instant::now());
            verified_count += 1;
            info!("✓ IPv6地址可用: {addr}");
        }
        info!("验证完成：{verified_count}/{} 个地址可用", addrs.len());

        if verified_count == 0 {
            error!("没有任何可用的公网IPv6地址，无法启用IPv6池");
            return false;
        }

        let current = self.active_addresses.lock().len();
        let pool_size = self.pool_size();
        if current < pool_size {
            let needed = pool_size - current;
            info!("当前有 {current} 个可用IPv6地址，需要补充 {needed} 个");
            self.add_addresses(needed).await;
        } else {
            info!("已有 {current} 个可用IPv6地址，满足需求");
        }

        self.start_maintenance().await;
        true
    }

    async fn refresh_system_addresses(&self) {
        let all = get_local_ipv6_addresses();
        let public: Vec<String> = all.into_iter().filter(|a| is_public_ipv6(a)).collect();
        debug!("系统中有 {} 个公网IPv6地址", public.len());
        *self.system_addresses.lock() = public;
    }

    async fn add_addresses(&self, count: usize) -> usize {
        let prefix = match self.last_prefix.lock().clone() {
            Some(p) => p,
            None => {
                error!("无法添加IPv6地址：未知前缀");
                return 0;
            }
        };
        let network_card = self.network_card();
        info!("尝试添加 {count} 个IPv6地址...");
        let mut added = 0usize;
        let max_attempts = count * 3;
        let mut attempts = 0usize;

        while added < count && attempts < max_attempts {
            attempts += 1;
            let old_system: std::collections::HashSet<String> =
                self.system_addresses.lock().iter().cloned().collect();

            configure_ipv6_addresses(&prefix, 1, &network_card);
            tokio::time::sleep(Duration::from_millis(500)).await;

            self.refresh_system_addresses().await;
            let active_keys: std::collections::HashSet<String> =
                self.active_addresses.lock().keys().cloned().collect();
            let new_addresses: Vec<String> = self
                .system_addresses
                .lock()
                .iter()
                .filter(|a| !old_system.contains(*a) && !active_keys.contains(*a))
                .cloned()
                .collect();

            if let Some(new_addr) = new_addresses.into_iter().next() {
                if is_public_ipv6(&new_addr) {
                    self.active_addresses
                        .lock()
                        .insert(new_addr.clone(), Instant::now());
                    info!("✓ 成功添加IPv6地址: {new_addr}");
                    added += 1;
                } else {
                    warn!("新添加的IPv6地址不是公网地址: {new_addr}");
                }
            } else {
                warn!("添加IPv6地址可能失败，未检测到新地址（尝试 {attempts}/{max_attempts}）");
            }

            if added < count {
                tokio::time::sleep(Duration::from_millis(500)).await;
            }
        }

        info!("添加完成：成功 {added}/{count} 个，共尝试 {attempts} 次");
        added
    }

    async fn cleanup_invalid_addresses(&self) -> usize {
        let _g = self.lock.lock().await;
        self.refresh_system_addresses().await;
        let system_set: std::collections::HashSet<String> =
            self.system_addresses.lock().iter().cloned().collect();
        let mut removed = 0usize;
        {
            let mut active = self.active_addresses.lock();
            let invalid: Vec<String> = active
                .keys()
                .filter(|a| !system_set.contains(*a))
                .cloned()
                .collect();
            for addr in invalid {
                active.remove(&addr);
                warn!("IPv6地址已失效，已移除: {addr}");
                removed += 1;
            }
        }
        if removed > 0 {
            info!("清理了 {removed} 个失效的IPv6地址");
        }
        removed
    }

    async fn check_prefix_change(&self) -> bool {
        let sys = self.system_addresses.lock().clone();
        if sys.is_empty() {
            return false;
        }
        let current_prefix = extract_prefix(&sys[0]);
        let mut last = self.last_prefix.lock();
        if last.as_ref() != Some(&current_prefix) {
            warn!(
                "检测到IPv6前缀变化: {:?} -> {current_prefix}",
                *last
            );
            *last = Some(current_prefix.clone());
            drop(last);

            let old_count = self.active_addresses.lock().len();
            self.active_addresses.lock().clear();
            for addr in &sys {
                if extract_prefix(addr) == current_prefix {
                    self.active_addresses
                        .lock()
                        .insert(addr.clone(), Instant::now());
                }
            }
            let new_count = self.active_addresses.lock().len();
            info!("前缀变化导致清理了 {old_count} 个旧地址，重新加载了 {new_count} 个地址");
            return true;
        }
        false
    }

    async fn maintain_pool(&self) {
        let removed = self.cleanup_invalid_addresses().await;
        let prefix_changed = self.check_prefix_change().await;
        let current_count = self.active_addresses.lock().len();
        let pool_size = self.pool_size();
        if current_count < pool_size {
            let needed = pool_size - current_count;
            info!("IPv6地址池不足，当前 {current_count}/{pool_size}，需要补充 {needed} 个");
            let added = self.add_addresses(needed).await;
            if added == 0 && current_count == 0 {
                error!("无法添加IPv6地址，地址池为空！");
            }
        }
        if removed > 0 || prefix_changed {
            info!(
                "IPv6地址池维护完成：当前有 {} 个可用地址",
                self.active_addresses.lock().len()
            );
        }
    }

    pub async fn start_maintenance(self: &Arc<Self>) {
        {
            let mut r = self.running.lock();
            if *r {
                return;
            }
            *r = true;
        }
        let this = Arc::clone(self);
        let interval = self.check_interval();
        info!(
            "IPv6地址池维护任务已启动，检查间隔: {}秒",
            interval.as_secs()
        );
        tokio::spawn(async move {
            loop {
                tokio::select! {
                    _ = tokio::time::sleep(interval) => {
                        this.maintain_pool().await;
                    }
                    _ = this.stop.notified() => {
                        info!("IPv6地址池维护任务已取消");
                        break;
                    }
                }
                if !*this.running.lock() {
                    break;
                }
            }
        });
        info!("IPv6地址池维护任务已启动");
    }

    pub async fn stop_maintenance(&self) {
        *self.running.lock() = false;
        self.stop.notify_waiters();
        info!("IPv6地址池维护任务已停止");
    }

    #[allow(dead_code)]
    pub async fn get_random_address(&self) -> Option<String> {
        let _g = self.lock.lock().await;
        let active = self.active_addresses.lock();
        if active.is_empty() {
            error!("IPv6地址池为空，无法获取地址");
            return None;
        }
        let keys: Vec<String> = active.keys().cloned().collect();
        let address = keys.choose(&mut rand::thread_rng())?.clone();
        debug!("使用IPv6地址: {address}");
        Some(address)
    }

    pub fn get_address_count(&self) -> usize {
        self.active_addresses.lock().len()
    }

    pub fn get_all_addresses(&self) -> Vec<String> {
        self.active_addresses.lock().keys().cloned().collect()
    }

    /// 供 beian 轮询：跳过黑名单中的地址
    pub async fn get_next_unblocked(
        &self,
        is_blocked: impl Fn(&str) -> bool,
    ) -> Option<String> {
        let _g = self.lock.lock().await;
        let keys: Vec<String> = self.active_addresses.lock().keys().cloned().collect();
        if keys.is_empty() {
            return None;
        }
        for _ in 0..(keys.len() * 2) {
            if let Some(addr) = keys.choose(&mut rand::thread_rng()) {
                if !is_blocked(addr) {
                    return Some(addr.clone());
                }
            }
        }
        warn!("所有 IPv6 地址都被拦截，暂无可用地址");
        None
    }
}

fn extract_prefix(address: &str) -> String {
    let parts: Vec<&str> = address.split(':').collect();
    parts.iter().take(4).cloned().collect::<Vec<_>>().join(":")
}

/// 初始化 IPv6 地址池
pub async fn init_ipv6_pool(
    config: Arc<parking_lot::RwLock<AppConfig>>,
) -> Option<SharedIpv6Pool> {
    info!("启用本地IPv6地址池管理");
    let pool = Arc::new(Ipv6AddressPool::new(config));
    if pool.initialize().await {
        info!(
            "IPv6地址池初始化成功，当前有 {} 个可用地址",
            pool.get_address_count()
        );
        Some(pool)
    } else {
        error!("IPv6地址池初始化失败");
        None
    }
}

pub async fn cleanup_ipv6_pool(pool: &SharedIpv6Pool) {
    pool.stop_maintenance().await;
    info!("IPv6地址池已清理");
}
