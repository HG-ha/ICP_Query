//! 任务管理器（对应 Python task_manager.py）

use parking_lot::Mutex;
use std::collections::HashMap;
use std::sync::Arc;
use tokio::task::JoinHandle;
use tracing::{error, info, warn};

pub type SharedTaskManager = Arc<TaskManager>;

pub struct TaskManager {
    tasks: Mutex<HashMap<String, JoinHandle<()>>>,
}

impl TaskManager {
    pub fn new() -> Self {
        Self {
            tasks: Mutex::new(HashMap::new()),
        }
    }

    pub fn add_task(&self, name: &str, handle: JoinHandle<()>) {
        self.tasks.lock().insert(name.to_string(), handle);
    }

    pub fn remove_task(&self, name: &str) {
        if let Some(h) = self.tasks.lock().remove(name) {
            if !h.is_finished() {
                h.abort();
            }
        }
    }

    pub async fn shutdown(&self) {
        info!("开始关闭所有任务...");
        let handles: Vec<_> = {
            let mut map = self.tasks.lock();
            map.drain().map(|(_, h)| h).collect()
        };
        for h in handles {
            h.abort();
        }
        tokio::time::sleep(std::time::Duration::from_secs(1)).await;
        info!("所有任务已关闭");
    }
}

impl Default for TaskManager {
    fn default() -> Self {
        Self::new()
    }
}

/// 延迟重启：对齐 restart_helper.py
pub async fn delayed_restart() {
    warn!("正在重启服务...");
    tokio::time::sleep(std::time::Duration::from_secs(2)).await;

    let exe = match std::env::current_exe() {
        Ok(p) => p,
        Err(e) => {
            error!("获取可执行文件路径失败: {e}");
            std::process::exit(1);
        }
    };
    let args: Vec<String> = std::env::args().skip(1).collect();

    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        const CREATE_NEW_CONSOLE: u32 = 0x00000010;
        match std::process::Command::new(&exe)
            .args(&args)
            .creation_flags(CREATE_NEW_CONSOLE)
            .spawn()
        {
            Ok(_) => {
                info!("✓ 新服务进程已启动");
                tokio::time::sleep(std::time::Duration::from_secs(1)).await;
                std::process::exit(0);
            }
            Err(e) => {
                error!("✗ 启动失败: {e}");
                std::process::exit(1);
            }
        }
    }

    #[cfg(unix)]
    {
        use std::os::unix::process::CommandExt;
        let err = std::process::Command::new(&exe).args(&args).exec();
        error!("重启失败: {err}");
        std::process::exit(1);
    }

    #[cfg(not(any(unix, windows)))]
    {
        let _ = std::process::Command::new(&exe).args(&args).spawn();
        std::process::exit(0);
    }
}
