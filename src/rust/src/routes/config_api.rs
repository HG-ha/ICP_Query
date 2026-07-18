use crate::auth::hash_users_inplace;
use crate::config::{AppConfig, AuthUser};
use crate::state::AppState;
use crate::utils::get_network_interfaces;
use axum::extract::State;
use axum::routing::{get, post};
use axum::{Json, Router};
use serde_json::{json, Value};
use tracing::{error, info, warn};

async fn get_config(State(state): State<AppState>) -> Json<Value> {
    let cfg = state.config.read().clone();
    let tunnel_url = cfg.proxy.tunnel.url.clone().unwrap_or_default();
    let extra_url = cfg.proxy.extra_api.url.clone().unwrap_or_default();
    Json(json!({
        "code": 200,
        "data": {
            "system": {
                "host": cfg.system.host,
                "port": cfg.system.port,
                "http_client_timeout": cfg.system.http_client_timeout,
                "web_ui": cfg.system.web_ui,
                "detail_concurrency": cfg.system.detail_concurrency
            },
            "captcha": {
                "enable": cfg.captcha.enable,
                "save_failed_img": cfg.captcha.save_failed_img,
                "save_failed_img_path": cfg.captcha.save_failed_img_path,
                "retry_times": cfg.captcha.retry_times
            },
            "proxy": {
                "local_ipv6_pool": {
                    "enable": cfg.proxy.local_ipv6_pool.enable,
                    "pool_num": cfg.proxy.local_ipv6_pool.pool_num,
                    "check_interval": cfg.proxy.local_ipv6_pool.check_interval,
                    "ipv6_network_card": cfg.proxy.local_ipv6_pool.ipv6_network_card
                },
                "tunnel": { "url": tunnel_url },
                "extra_api": {
                    "url": extra_url,
                    "extra_interval": cfg.proxy.extra_api.extra_interval,
                    "timeout": cfg.proxy.extra_api.timeout,
                    "timeout_drop": cfg.proxy.extra_api.timeout_drop,
                    "check_proxy": cfg.proxy.extra_api.check_proxy,
                    "proxy_timeout": cfg.proxy.extra_api.proxy_timeout,
                    "check_proxy_num": cfg.proxy.extra_api.check_proxy_num,
                    "auto_maintenace": cfg.proxy.extra_api.auto_maintenace,
                    "pool_num": cfg.proxy.extra_api.pool_num
                }
            },
            "risk_avoidance": {
                "allow_type": cfg.risk_avoidance.allow_type,
                "prohibit_suffix": cfg.risk_avoidance.prohibit_suffix
            },
            "log": {
                "dir": cfg.log.dir,
                "file_head": cfg.log.file_head,
                "backup_count": cfg.log.backup_count,
                "save_log": cfg.log.save_log,
                "output_console": cfg.log.output_console
            },
            "history": {
                "save_query_history": cfg.history.save_query_history
            },
            "auth": {
                "enable": cfg.auth.enable,
                "secret": cfg.auth.secret,
                "session_hours": cfg.auth.session_hours,
                "users": cfg.auth.users.iter().map(|u| json!({
                    "username": u.username,
                    "password": "",
                    "password_set": !u.password.is_empty()
                })).collect::<Vec<_>>()
            },
            "mcp": {
                "enable": cfg.mcp.enable,
                "port": cfg.mcp.port
            }
        }
    }))
}

async fn save_config(
    State(state): State<AppState>,
    Json(data): Json<Value>,
) -> Json<Value> {
    let old = state.config.read().clone();
    match build_config_from_json(&data, &old) {
        Ok(mut new_cfg) => {
            new_cfg.normalize();
            hash_users_inplace(&mut new_cfg.auth.users);
            let backup = state.config_path.with_extension("yml.backup");
            if state.config_path.exists() {
                let _ = std::fs::copy(&state.config_path, &backup);
            }
            match new_cfg.save(&state.config_path) {
                Ok(()) => {
                    *state.config.write() = new_cfg;
                    info!("配置文件已更新，需要重启服务生效");
                    state
                        .logs
                        .add_log("配置文件已更新，需要重启服务生效", "INFO");
                    Json(json!({"code": 200, "message": "配置保存成功，重启服务后生效"}))
                }
                Err(e) => {
                    error!("保存配置文件失败: {e}");
                    Json(json!({"code": 500, "message": format!("保存配置失败: {e}")}))
                }
            }
        }
        Err(e) => Json(json!({"code": 500, "message": format!("保存配置失败: {e}")})),
    }
}

fn build_config_from_json(data: &Value, old: &AppConfig) -> Result<AppConfig, String> {
    let wrapped = json!({
        "system": data.get("system").cloned().unwrap_or(json!({})),
        "captcha": data.get("captcha").cloned().unwrap_or(json!({})),
        "proxy": data.get("proxy").cloned().unwrap_or(json!({})),
        "risk_avoidance": data.get("risk_avoidance").cloned().unwrap_or(json!({})),
        "log": data.get("log").cloned().unwrap_or(json!({})),
        "history": data.get("history").cloned().unwrap_or(json!({})),
        "auth": data.get("auth").cloned().unwrap_or(json!({})),
        "mcp": data.get("mcp").cloned().unwrap_or(json!({})),
    });
    let yaml = serde_yaml::to_string(&wrapped).map_err(|e| e.to_string())?;
    let mut cfg: AppConfig = serde_yaml::from_str(&yaml).map_err(|e| e.to_string())?;

    if let Some(Value::String(u)) = data.pointer("/proxy/tunnel/url") {
        cfg.proxy.tunnel.url = if u.is_empty() {
            None
        } else {
            Some(u.clone())
        };
    }
    if let Some(Value::String(u)) = data.pointer("/proxy/extra_api/url") {
        cfg.proxy.extra_api.url = if u.is_empty() {
            None
        } else {
            Some(u.clone())
        };
    }

    // 空密码保留原密码
    let old_map: std::collections::HashMap<String, String> = old
        .auth
        .users
        .iter()
        .map(|u| (u.username.clone(), u.password.clone()))
        .collect();
    let mut merged = Vec::new();
    if let Some(arr) = data.pointer("/auth/users").and_then(|v| v.as_array()) {
        for u in arr {
            let uname = u.get("username").and_then(|x| x.as_str()).unwrap_or("").trim();
            if uname.is_empty() {
                continue;
            }
            let pwd = u.get("password").and_then(|x| x.as_str()).unwrap_or("");
            let password = if pwd.is_empty() {
                old_map.get(uname).cloned().unwrap_or_default()
            } else {
                pwd.to_string()
            };
            merged.push(AuthUser {
                username: uname.to_string(),
                password,
            });
        }
    }
    if !merged.is_empty() {
        cfg.auth.users = merged;
    }
    cfg.normalize();
    Ok(cfg)
}

async fn network_interfaces() -> Json<Value> {
    Json(json!({"code": 200, "data": get_network_interfaces()}))
}

async fn restart_service(State(state): State<AppState>) -> Json<Value> {
    warn!("收到重启服务请求，将在3秒后重启...");
    state
        .logs
        .add_log("收到重启服务请求，将在3秒后重启...", "WARNING");

    tokio::spawn(async {
        tokio::time::sleep(std::time::Duration::from_secs(3)).await;
        crate::task_manager::delayed_restart().await;
    });

    Json(json!({"code": 200, "message": "服务将在3秒后重启"}))
}

pub fn routes() -> Router<AppState> {
    Router::new()
        .route("/config", get(get_config))
        .route("/config/save", post(save_config))
        .route("/config/network-interfaces", get(network_interfaces))
        .route("/config/restart", post(restart_service))
}
