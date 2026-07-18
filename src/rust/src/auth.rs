//! 账号鉴权（与 Python auth.py 对齐）

use crate::config::{AppConfig, AuthUser};
use axum::body::Body;
use axum::extract::State;
use axum::http::{header, Request, StatusCode};
use axum::middleware::Next;
use axum::response::{IntoResponse, Response};
use axum::Json;
use base64::{engine::general_purpose::URL_SAFE_NO_PAD, Engine};
use hmac::{Hmac, Mac};
use serde_json::json;
use sha2::{Digest, Sha256};
use std::time::{SystemTime, UNIX_EPOCH};

type HmacSha256 = Hmac<Sha256>;

pub const COOKIE_NAME: &str = "ymicp_session";
const HASH_PREFIX: &str = "sha256$";

pub fn auth_enabled(cfg: &AppConfig) -> bool {
    cfg.auth.enable
}

pub fn hash_password(plain: &str) -> String {
    let dig = Sha256::digest(plain.as_bytes());
    format!("{HASH_PREFIX}{}", hex::encode(dig))
}

pub fn verify_password(stored: &str, plain: &str) -> bool {
    if stored.starts_with(HASH_PREFIX) {
        let h = hash_password(plain);
        constant_eq(stored.as_bytes(), h.as_bytes())
    } else {
        constant_eq(stored.as_bytes(), plain.as_bytes())
    }
}

fn constant_eq(a: &[u8], b: &[u8]) -> bool {
    if a.len() != b.len() {
        return false;
    }
    a.iter().zip(b.iter()).fold(0u8, |acc, (x, y)| acc | (x ^ y)) == 0
}

pub fn authenticate(cfg: &AppConfig, username: &str, password: &str) -> bool {
    cfg.auth
        .users
        .iter()
        .any(|u| u.username == username && verify_password(&u.password, password))
}

pub fn create_token(cfg: &AppConfig, username: &str) -> String {
    let exp = now_secs() + cfg.auth.session_hours.saturating_mul(3600).max(3600);
    let payload = json!({"u": username, "e": exp}).to_string();
    let body = URL_SAFE_NO_PAD.encode(payload.as_bytes());
    let sig = sign(cfg.auth.secret.as_bytes(), body.as_bytes());
    format!("{body}.{sig}")
}

pub fn verify_token(cfg: &AppConfig, token: &str) -> Option<String> {
    let (body, sig) = token.rsplit_once('.')?;
    let expect = sign(cfg.auth.secret.as_bytes(), body.as_bytes());
    if !constant_eq(expect.as_bytes(), sig.as_bytes()) {
        return None;
    }
    let raw = URL_SAFE_NO_PAD.decode(body).ok()?;
    let data: serde_json::Value = serde_json::from_slice(&raw).ok()?;
    let exp = data.get("e")?.as_u64()?;
    if exp < now_secs() {
        return None;
    }
    let username = data.get("u")?.as_str()?.to_string();
    if !cfg.auth.users.iter().any(|u| u.username == username) {
        return None;
    }
    Some(username)
}

fn sign(secret: &[u8], body: &[u8]) -> String {
    let mut mac = HmacSha256::new_from_slice(secret).expect("HMAC key");
    mac.update(body);
    hex::encode(mac.finalize().into_bytes())
}

fn now_secs() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_secs()
}

pub fn extract_token(req: &Request<Body>) -> Option<String> {
    if let Some(auth) = req.headers().get(header::AUTHORIZATION) {
        if let Ok(s) = auth.to_str() {
            if let Some(t) = s.strip_prefix("Bearer ").or_else(|| s.strip_prefix("bearer ")) {
                return Some(t.trim().to_string());
            }
        }
    }
    if let Some(cookie) = req.headers().get(header::COOKIE) {
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

pub fn is_public_path(path: &str, method: &str) -> bool {
    if path.starts_with("/static/") {
        return true;
    }
    if path == "/api/auth/login" || path == "/api/auth/status" {
        return true;
    }
    if (path == "/" || path.is_empty()) && method.eq_ignore_ascii_case("GET") {
        return true;
    }
    false
}

pub async fn auth_middleware(
    State(state): State<crate::state::AppState>,
    req: Request<Body>,
    next: Next,
) -> Response {
    if req.method() == axum::http::Method::OPTIONS {
        return next.run(req).await;
    }
    let cfg = state.config.read().clone();
    if !auth_enabled(&cfg) {
        return next.run(req).await;
    }
    let path = req.uri().path();
    let method = req.method().as_str();
    if is_public_path(path, method) {
        return next.run(req).await;
    }
    let token = extract_token(&req);
    let ok = token
        .as_deref()
        .and_then(|t| verify_token(&cfg, t))
        .is_some();
    if !ok {
        return (
            StatusCode::UNAUTHORIZED,
            Json(json!({"code": 401, "message": "未登录或会话已过期"})),
        )
            .into_response();
    }
    next.run(req).await
}

pub fn hash_users_inplace(users: &mut [AuthUser]) {
    for u in users.iter_mut() {
        if !u.password.is_empty() && !u.password.starts_with(HASH_PREFIX) {
            u.password = hash_password(&u.password);
        }
    }
}
