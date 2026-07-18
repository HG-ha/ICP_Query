use crate::beian::SharedBeian;
use crate::config::SharedConfig;
use crate::database::SharedDb;
use crate::ipv6_pool::SharedIpv6Pool;
use crate::log_collector::SharedLogCollector;
use crate::proxy_pool::SharedProxyPool;
use crate::task_manager::SharedTaskManager;
use parking_lot::Mutex;
use serde_json::Value;
use std::collections::HashMap;
use std::sync::atomic::{AtomicBool, AtomicUsize, Ordering};
use std::sync::Arc;

#[derive(Clone)]
pub struct BatchTask {
    pub curpro: Arc<AtomicUsize>,
    pub numpro: usize,
    pub domains: Arc<Mutex<Vec<Value>>>,
    pub query_keywords: Arc<Mutex<Vec<String>>>,
    pub appname: String,
    pub cancelled: Arc<AtomicBool>,
    pub completed: Arc<AtomicBool>,
}

impl BatchTask {
    pub fn new(numpro: usize, appname: String) -> Self {
        Self {
            curpro: Arc::new(AtomicUsize::new(0)),
            numpro,
            domains: Arc::new(Mutex::new(Vec::new())),
            query_keywords: Arc::new(Mutex::new(Vec::new())),
            appname,
            cancelled: Arc::new(AtomicBool::new(false)),
            completed: Arc::new(AtomicBool::new(false)),
        }
    }

    pub fn progress_pct(&self) -> i32 {
        if self.numpro == 0 {
            return 0;
        }
        ((self.curpro.load(Ordering::Relaxed) as f64 / self.numpro as f64) * 100.0) as i32
    }
}

#[derive(Clone)]
pub struct AppState {
    pub config: SharedConfig,
    pub db: SharedDb,
    pub beian: SharedBeian,
    pub logs: SharedLogCollector,
    pub proxy_pool: Option<SharedProxyPool>,
    #[allow(dead_code)]
    pub ipv6_pool: Option<SharedIpv6Pool>,
    pub task_manager: SharedTaskManager,
    pub tasks: Arc<Mutex<HashMap<String, BatchTask>>>,
    pub config_path: std::path::PathBuf,
    pub project_root: std::path::PathBuf,
}
