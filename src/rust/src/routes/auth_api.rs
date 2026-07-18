use crate::auth::{authenticate, auth_enabled, create_token, verify_token, COOKIE_NAME};
use crate::state::AppState;
use axum::extract::State;
use axum::http::{header, HeaderMap, StatusCode};
use axum::response::IntoResponse;
use axum::routing::{get, post};
use axum::{Json, Router};
use serde::Deserialize;
use serde_json::{json, Value};

#[derive(Deserialize)]
pub struct LoginBody {
    pub username: Option<String>,
    pub password: Option<String>,
}

async fn auth_status(State(state): State<AppState>, headers: HeaderMap) -> Json<Value> {
    let cfg = state.config.read().clone();
    let enabled = auth_enabled(&cfg);
    if !enabled {
        return Json(json!({
            "code": 200,
            "data": { "enable": false, "authenticated": true, "username": null }
        }));
    }
    let req_like = fake_extract(&headers);
    let user = req_like.and_then(|t| verify_token(&cfg, &t));
    Json(json!({
        "code": 200,
        "data": {
            "enable": true,
            "authenticated": user.is_some(),
            "username": user,
        }
    }))
}

fn fake_extract(headers: &HeaderMap) -> Option<String> {
    if let Some(auth) = headers.get(header::AUTHORIZATION) {
        if let Ok(s) = auth.to_str() {
            if let Some(t) = s.strip_prefix("Bearer ").or_else(|| s.strip_prefix("bearer ")) {
                return Some(t.trim().to_string());
            }
        }
    }
    if let Some(cookie) = headers.get(header::COOKIE) {
        if let Ok(s) = cookie.to_str() {
            for part in s.split(';') {
                let part = part.trim();
                if let Some(v) = part.strip_prefix(&format!("{COOKIE_NAME}=")) {
                    return Some(v.to_string());
                }
            }
        }
    }
    None
}

async fn auth_login(
    State(state): State<AppState>,
    Json(body): Json<LoginBody>,
) -> impl IntoResponse {
    let cfg = state.config.read().clone();
    if !auth_enabled(&cfg) {
        return (
            StatusCode::OK,
            Json(json!({"code": 200, "message": "认证未启用", "data": {"enable": false}})),
        )
            .into_response();
    }
    let username = body.username.unwrap_or_default().trim().to_string();
    let password = body.password.unwrap_or_default();
    if username.is_empty() || password.is_empty() {
        return (
            StatusCode::OK,
            Json(json!({"code": 400, "message": "请输入用户名和密码"})),
        )
            .into_response();
    }
    if !authenticate(&cfg, &username, &password) {
        return (
            StatusCode::OK,
            Json(json!({"code": 401, "message": "用户名或密码错误"})),
        )
            .into_response();
    }
    let token = create_token(&cfg, &username);
    let max_age = cfg.auth.session_hours.saturating_mul(3600).max(3600);
    let cookie = format!(
        "{COOKIE_NAME}={token}; Path=/; Max-Age={max_age}; HttpOnly; SameSite=Lax"
    );
    (
        StatusCode::OK,
        [(header::SET_COOKIE, cookie)],
        Json(json!({
            "code": 200,
            "message": "登录成功",
            "data": { "username": username, "token": token }
        })),
    )
        .into_response()
}

async fn auth_logout() -> impl IntoResponse {
    let cookie = format!("{COOKIE_NAME}=; Path=/; Max-Age=0; HttpOnly; SameSite=Lax");
    (
        StatusCode::OK,
        [(header::SET_COOKIE, cookie)],
        Json(json!({"code": 200, "message": "已退出"})),
    )
}

async fn auth_me(State(state): State<AppState>, headers: HeaderMap) -> impl IntoResponse {
    let cfg = state.config.read().clone();
    if !auth_enabled(&cfg) {
        return Json(json!({"code": 200, "data": {"enable": false, "username": null}}));
    }
    match fake_extract(&headers).and_then(|t| verify_token(&cfg, &t)) {
        Some(u) => Json(json!({"code": 200, "data": {"enable": true, "username": u}})),
        None => Json(json!({"code": 401, "message": "未登录"})),
    }
}

pub fn routes() -> Router<AppState> {
    Router::new()
        .route("/api/auth/status", get(auth_status))
        .route("/api/auth/login", post(auth_login))
        .route("/api/auth/logout", post(auth_logout))
        .route("/api/auth/me", get(auth_me))
}
