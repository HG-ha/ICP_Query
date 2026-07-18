mod auth;
mod beian;
mod captcha;
mod config;
mod database;
mod http_client;
mod ipv6_pool;
mod log_collector;
mod mcp;
mod proxy_pool;
mod routes;
mod state;
mod task_manager;
mod utils;

use crate::beian::Beian;
use crate::config::{find_config_path, shared_config, AppConfig};
use crate::database::Database;
use crate::ipv6_pool::{cleanup_ipv6_pool, init_ipv6_pool};
use crate::log_collector::{CollectorLayer, LogCollector};
use crate::proxy_pool::ProxyPool;
use crate::state::AppState;
use crate::task_manager::TaskManager;
use crate::utils::{find_project_root, is_valid_url};
use axum::http::{header, HeaderValue, Method, StatusCode};
use axum::response::IntoResponse;
use axum::Json;
use std::net::SocketAddr;
use std::sync::Arc;
use tower_http::cors::{Any, CorsLayer};
use tower_http::set_header::SetResponseHeaderLayer;
use tracing::{info, warn};
use tracing_subscriber::layer::SubscriberExt;
use tracing_subscriber::util::SubscriberInitExt;
use tracing_appender::non_blocking::WorkerGuard;

const VERSION: &str = "0.7.0";

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum RunMode {
    /// 主 HTTP API / Web UI
    Api,
    /// MCP stdio
    McpStdio,
    /// 仅 MCP Streamable HTTP
    McpHttp,
}

fn parse_mode() -> RunMode {
    let mut mode = RunMode::Api;
    for arg in std::env::args().skip(1) {
        match arg.as_str() {
            "--mcp" => mode = RunMode::McpStdio,
            "--mcp-http" => mode = RunMode::McpHttp,
            "-h" | "--help" => {
                eprintln!(
                    "ICP_Query Rust v{VERSION}\n\n\
                     用法:\n  ymicp                 启动 Web/API\n  ymicp --mcp          MCP stdio\n  ymicp --mcp-http     MCP Streamable HTTP（端口见 config mcp.port）\n"
                );
                std::process::exit(0);
            }
            _ => {}
        }
    }
    mode
}

fn print_banner() {
    println!(
        r#"
┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
                         🎗️  赞助商                          
┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛

    ☁️  林枫云
    ├─ 企业级业务云、专业高频游戏云提供商
    └─ 🌐 https://www.dkdun.cn

    🚀  ANT PING
    ├─ 一站式网络检测工具
    └─ 🌐 https://antping.com

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  ICP_Query Rust 版 v{VERSION}
"#
    );
}

fn init_tracing(cfg: &AppConfig, logs: &Arc<LogCollector>, stderr_only: bool) -> Option<WorkerGuard> {
    let collector_layer = CollectorLayer::new(Arc::clone(logs));
    let level = tracing_subscriber::filter::LevelFilter::INFO;

    if cfg.log.save_log {
        let _ = std::fs::create_dir_all(&cfg.log.dir);
        let file_appender = tracing_appender::rolling::daily(&cfg.log.dir, &cfg.log.file_head);
        let (non_blocking, guard) = tracing_appender::non_blocking(file_appender);
        let file_layer = tracing_subscriber::fmt::layer()
            .with_writer(non_blocking)
            .with_ansi(false);

        if stderr_only {
            tracing_subscriber::registry()
                .with(level)
                .with(file_layer)
                .with(tracing_subscriber::fmt::layer().with_writer(std::io::stderr))
                .with(collector_layer)
                .init();
        } else if cfg.log.output_console {
            tracing_subscriber::registry()
                .with(level)
                .with(file_layer)
                .with(tracing_subscriber::fmt::layer().with_writer(std::io::stdout))
                .with(collector_layer)
                .init();
        } else {
            tracing_subscriber::registry()
                .with(level)
                .with(file_layer)
                .with(collector_layer)
                .init();
        }
        Some(guard)
    } else if stderr_only {
        tracing_subscriber::registry()
            .with(level)
            .with(tracing_subscriber::fmt::layer().with_writer(std::io::stderr))
            .with(collector_layer)
            .init();
        None
    } else if cfg.log.output_console {
        tracing_subscriber::registry()
            .with(level)
            .with(tracing_subscriber::fmt::layer())
            .with(collector_layer)
            .init();
        None
    } else {
        tracing_subscriber::registry()
            .with(level)
            .with(collector_layer)
            .init();
        None
    }
}

async fn build_state(
    cfg: &AppConfig,
    config_path: std::path::PathBuf,
    logs: Arc<LogCollector>,
) -> anyhow::Result<(
    AppState,
    Option<crate::ipv6_pool::SharedIpv6Pool>,
    Option<crate::proxy_pool::SharedProxyPool>,
    Arc<TaskManager>,
)> {
    let shared_cfg = shared_config(cfg.clone());
    let db = Arc::new(Database::new("icp_history.db")?);
    let beian = Arc::new(Beian::new(Arc::clone(&shared_cfg)));
    let project_root = find_project_root();
    let task_manager = Arc::new(TaskManager::new());

    let (ipv6_pool, proxy_pool) = {
        let c = shared_cfg.read();
        if c.proxy.local_ipv6_pool.enable {
            drop(c);
            let pool = init_ipv6_pool(Arc::clone(&shared_cfg)).await;
            beian.set_ipv6_pool(pool.clone());
            (pool, None)
        } else if c.proxy.tunnel.url.is_none() {
            if let Some(ref url) = c.proxy.extra_api.url {
                if is_valid_url(url) && c.proxy.extra_api.auto_maintenace {
                    info!(
                        "自动维护本地地址池 提取间隔：{}秒 ，超时时间：{} 秒 ，提前丢弃：{} 秒 ",
                        c.proxy.extra_api.extra_interval,
                        c.proxy.extra_api.timeout,
                        c.proxy.extra_api.timeout_drop
                    );
                    drop(c);
                    let pool = Arc::new(ProxyPool::new(Arc::clone(&shared_cfg)));
                    pool.start().await;
                    (None, Some(pool))
                } else if !is_valid_url(url) {
                    warn!("当前启用了API提取代理，但该地址似乎无效，将不使用该代理");
                    (None, None)
                } else {
                    (None, None)
                }
            } else {
                (None, None)
            }
        } else {
            (None, None)
        }
    };

    let state = AppState {
        config: shared_cfg,
        db,
        beian,
        logs,
        proxy_pool: proxy_pool.clone(),
        ipv6_pool: ipv6_pool.clone(),
        task_manager: Arc::clone(&task_manager),
        tasks: Arc::new(parking_lot::Mutex::new(Default::default())),
        config_path,
        project_root,
    };

    Ok((state, ipv6_pool, proxy_pool, task_manager))
}

#[tokio::main]
async fn main() -> anyhow::Result<()> {
    let mode = parse_mode();
    if mode != RunMode::McpStdio {
        print_banner();
    }

    let config_path = find_config_path();
    let mut cfg = AppConfig::load(&config_path).unwrap_or_else(|e| {
        eprintln!("加载配置文件失败: {e}");
        std::process::exit(1);
    });
    cfg.normalize();

    let logs = Arc::new(LogCollector::new(1000));
    let _guard = init_tracing(&cfg, &logs, mode == RunMode::McpStdio);

    let (state, ipv6_pool, proxy_pool, task_manager) =
        build_state(&cfg, config_path.clone(), logs).await?;

    match mode {
        RunMode::McpStdio => {
            mcp::run_stdio(state).await?;
        }
        RunMode::McpHttp => {
            let host = cfg.system.host.clone();
            let port = cfg.mcp.port;
            mcp::run_http(state, &host, port).await?;
        }
        RunMode::Api => {
            let host = cfg.system.host.clone();
            let port = cfg.system.port;
            let web_ui = cfg.system.web_ui;
            let captcha_enable = cfg.captcha.enable;

            if cfg.mcp.enable {
                mcp::spawn_http(state.clone(), host.clone(), cfg.mcp.port);
                info!("MCP HTTP: 启用 (端口 {})", cfg.mcp.port);
            }

            let cors = CorsLayer::new()
                .allow_origin(Any)
                .allow_methods([Method::GET, Method::POST, Method::OPTIONS, Method::DELETE])
                .allow_headers(Any);

            let server_header = SetResponseHeaderLayer::overriding(
                header::SERVER,
                HeaderValue::from_static("are you ok?"),
            );

            let app = routes::router(state)
                .layer(cors)
                .layer(server_header)
                .fallback(|| async {
                    (
                        StatusCode::NOT_FOUND,
                        Json(serde_json::json!({
                            "code": 404,
                            "msg": "查询请访问服务根路径"
                        })),
                    )
                        .into_response()
                });

            let addr: SocketAddr = format!("{host}:{port}")
                .parse()
                .unwrap_or_else(|_| SocketAddr::from(([0, 0, 0, 0], port)));

            if web_ui {
                let display_host = if host == "0.0.0.0" {
                    "127.0.0.1"
                } else {
                    &host
                };
                println!("\nweb ui: http://{display_host}:{port}\n\n按两次 Ctrl + C 可以退出程序\n");
            }

            info!("服务启动 - 监听地址: {host}:{port}");
            info!(
                "验证码识别: {}",
                if captcha_enable { "启用" } else { "禁用" }
            );
            info!(
                "账号认证: {}",
                if cfg.auth.enable { "启用" } else { "禁用" }
            );

            let listener = tokio::net::TcpListener::bind(addr).await?;
            axum::serve(listener, app)
                .with_graceful_shutdown(shutdown_signal(Arc::clone(&task_manager)))
                .await?;
        }
    }

    if let Some(ref pool) = ipv6_pool {
        cleanup_ipv6_pool(pool).await;
    }
    if let Some(pool) = proxy_pool {
        pool.stop().await;
    }

    drop(_guard);
    Ok(())
}

async fn shutdown_signal(task_manager: Arc<TaskManager>) {
    let ctrl_c = async {
        tokio::signal::ctrl_c()
            .await
            .expect("failed to install Ctrl+C handler");
    };

    #[cfg(unix)]
    {
        let mut stream =
            tokio::signal::unix::signal(tokio::signal::unix::SignalKind::terminate())
                .expect("failed to install SIGTERM handler");
        tokio::select! {
            _ = ctrl_c => {},
            _ = stream.recv() => {},
        }
    }

    #[cfg(not(unix))]
    ctrl_c.await;

    warn!("收到关闭信号，程序停止");
    task_manager.shutdown().await;
}
