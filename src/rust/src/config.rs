use anyhow::{Context, Result};
use serde::{Deserialize, Serialize};
use std::fs;
use std::path::{Path, PathBuf};
use std::sync::Arc;

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct AppConfig {
    pub system: SystemConfig,
    pub captcha: CaptchaConfig,
    pub proxy: ProxyConfig,
    pub risk_avoidance: RiskAvoidanceConfig,
    pub log: LogConfig,
    #[serde(default)]
    pub history: HistoryConfig,
    #[serde(default)]
    pub auth: AuthConfig,
    #[serde(default)]
    pub mcp: McpConfig,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct AuthUser {
    pub username: String,
    #[serde(default)]
    pub password: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct AuthConfig {
    #[serde(default)]
    pub enable: bool,
    #[serde(default = "default_secret")]
    pub secret: String,
    #[serde(default = "default_session_hours")]
    pub session_hours: u64,
    #[serde(default = "default_users")]
    pub users: Vec<AuthUser>,
}

impl Default for AuthConfig {
    fn default() -> Self {
        Self {
            enable: false,
            secret: default_secret(),
            session_hours: default_session_hours(),
            users: default_users(),
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct McpConfig {
    #[serde(default)]
    pub enable: bool,
    #[serde(default = "default_mcp_port")]
    pub port: u16,
}

impl Default for McpConfig {
    fn default() -> Self {
        Self {
            enable: false,
            port: default_mcp_port(),
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SystemConfig {
    #[serde(default = "default_host")]
    pub host: String,
    #[serde(default = "default_port")]
    pub port: u16,
    #[serde(default = "default_timeout")]
    pub http_client_timeout: u64,
    #[serde(default = "default_true")]
    pub web_ui: bool,
    #[serde(default = "default_detail_concurrency")]
    pub detail_concurrency: usize,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct CaptchaConfig {
    #[serde(default = "default_true")]
    pub enable: bool,
    #[serde(default)]
    pub save_failed_img: bool,
    #[serde(default = "default_failed_path")]
    pub save_failed_img_path: String,
    #[serde(default = "default_retry")]
    pub retry_times: u32,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ProxyConfig {
    pub local_ipv6_pool: LocalIpv6PoolConfig,
    pub tunnel: TunnelConfig,
    pub extra_api: ExtraApiConfig,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct LocalIpv6PoolConfig {
    #[serde(default)]
    pub enable: bool,
    #[serde(default = "default_pool_num_ipv6")]
    pub pool_num: usize,
    #[serde(default = "default_one")]
    pub check_interval: u64,
    #[serde(default = "default_eth0")]
    pub ipv6_network_card: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct TunnelConfig {
    #[serde(default)]
    pub url: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ExtraApiConfig {
    #[serde(default)]
    pub url: Option<String>,
    #[serde(default = "default_extra_interval")]
    pub extra_interval: u64,
    #[serde(default = "default_proxy_timeout_ttl")]
    pub timeout: u64,
    #[serde(default = "default_timeout_drop")]
    pub timeout_drop: u64,
    #[serde(default = "default_true")]
    pub check_proxy: bool,
    #[serde(default = "default_proxy_check_timeout")]
    pub proxy_timeout: f64,
    #[serde(default = "default_check_proxy_num")]
    pub check_proxy_num: usize,
    #[serde(default = "default_true")]
    pub auto_maintenace: bool,
    #[serde(default = "default_pool_num")]
    pub pool_num: usize,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct RiskAvoidanceConfig {
    #[serde(default = "default_allow_types")]
    pub allow_type: Vec<String>,
    #[serde(default)]
    pub prohibit_suffix: Vec<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct LogConfig {
    #[serde(default = "default_log_dir")]
    pub dir: String,
    #[serde(default = "default_file_head")]
    pub file_head: String,
    #[serde(default = "default_backup")]
    pub backup_count: u32,
    #[serde(default)]
    pub save_log: bool,
    #[serde(default = "default_true")]
    pub output_console: bool,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct HistoryConfig {
    #[serde(default)]
    pub save_query_history: bool,
}

impl Default for HistoryConfig {
    fn default() -> Self {
        Self {
            save_query_history: false,
        }
    }
}

fn default_host() -> String {
    "0.0.0.0".into()
}
fn default_port() -> u16 {
    16181
}
fn default_timeout() -> u64 {
    30
}
fn default_true() -> bool {
    true
}
fn default_detail_concurrency() -> usize {
    5
}
fn default_failed_path() -> String {
    "faile_captcha".into()
}
fn default_retry() -> u32 {
    10
}
fn default_pool_num_ipv6() -> usize {
    88
}
fn default_one() -> u64 {
    1
}
fn default_eth0() -> String {
    "eth0".into()
}
fn default_extra_interval() -> u64 {
    3
}
fn default_proxy_timeout_ttl() -> u64 {
    100
}
fn default_timeout_drop() -> u64 {
    8
}
fn default_proxy_check_timeout() -> f64 {
    0.5
}
fn default_check_proxy_num() -> usize {
    20
}
fn default_pool_num() -> usize {
    100
}
fn default_allow_types() -> Vec<String> {
    vec![
        "web", "app", "mapp", "kapp", "bweb", "bapp", "bmapp", "bkapp",
    ]
    .into_iter()
    .map(String::from)
    .collect()
}
fn default_log_dir() -> String {
    "logs".into()
}
fn default_file_head() -> String {
    "ymicp".into()
}
fn default_backup() -> u32 {
    7
}
fn default_secret() -> String {
    "change-me".into()
}
fn default_session_hours() -> u64 {
    72
}
fn default_users() -> Vec<AuthUser> {
    vec![AuthUser {
        username: "admin".into(),
        password: "admin123".into(),
    }]
}
fn default_mcp_port() -> u16 {
    16182
}

impl AppConfig {
    pub fn load(path: impl AsRef<Path>) -> Result<Self> {
        let content = fs::read_to_string(path.as_ref())
            .with_context(|| format!("无法读取配置文件: {:?}", path.as_ref()))?;
        let cfg: AppConfig =
            serde_yaml::from_str(&content).context("解析 config.yml 失败")?;
        Ok(cfg)
    }

    pub fn save(&self, path: impl AsRef<Path>) -> Result<()> {
        let content = serde_yaml::to_string(self).context("序列化配置失败")?;
        fs::write(path.as_ref(), content)
            .with_context(|| format!("写入配置文件失败: {:?}", path.as_ref()))?;
        Ok(())
    }

    /// 规范化 tunnel / extra_api 的空字符串为 None
    pub fn normalize(&mut self) {
        if let Some(ref u) = self.proxy.tunnel.url {
            if u.trim().is_empty() {
                self.proxy.tunnel.url = None;
            }
        }
        if let Some(ref u) = self.proxy.extra_api.url {
            if u.trim().is_empty() {
                self.proxy.extra_api.url = None;
            }
        }
    }
}

/// 查找配置文件路径：优先工作目录，其次相对项目根
pub fn find_config_path() -> PathBuf {
    let candidates = [
        PathBuf::from("config.yml"),
        PathBuf::from("../../config.yml"),
        PathBuf::from("../config.yml"),
    ];
    for p in &candidates {
        if p.exists() {
            return p.clone();
        }
    }
    PathBuf::from("config.yml")
}

pub type SharedConfig = Arc<parking_lot::RwLock<AppConfig>>;

pub fn shared_config(cfg: AppConfig) -> SharedConfig {
    Arc::new(parking_lot::RwLock::new(cfg))
}
