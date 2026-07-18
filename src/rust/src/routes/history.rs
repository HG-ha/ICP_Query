use crate::state::AppState;
use axum::extract::{Path, Query, State};
use axum::routing::{get, post};
use axum::{Json, Router};
use serde::Deserialize;
use serde_json::{json, Value};

#[derive(Debug, Deserialize)]
pub struct HistoryQuery {
    #[serde(default = "default_limit")]
    pub limit: i64,
    #[serde(default)]
    pub offset: i64,
    #[serde(rename = "type")]
    pub search_type: Option<String>,
}

fn default_limit() -> i64 {
    50
}

#[derive(Debug, Deserialize)]
pub struct ClearBody {
    #[serde(rename = "type")]
    pub search_type: Option<String>,
}

async fn get_history(
    State(state): State<AppState>,
    Query(q): Query<HistoryQuery>,
) -> Json<Value> {
    let st = q.search_type.as_deref();
    let history_list = state.db.get_history(q.limit, q.offset, st);
    let total_count = state.db.get_history_count(st);
    Json(json!({
        "code": 200,
        "data": history_list,
        "total": total_count,
        "limit": q.limit,
        "offset": q.offset
    }))
}

async fn get_history_detail(
    State(state): State<AppState>,
    Path(history_id): Path<i64>,
) -> Json<Value> {
    match state.db.get_history_detail(history_id) {
        Some(d) => Json(json!({"code": 200, "data": d})),
        None => Json(json!({"code": 404, "message": "历史记录不存在"})),
    }
}

async fn delete_history(
    State(state): State<AppState>,
    Path(history_id): Path<i64>,
) -> Json<Value> {
    if state.db.delete_history(history_id) {
        Json(json!({"code": 200, "message": "删除成功"}))
    } else {
        Json(json!({"code": 500, "message": "删除失败"}))
    }
}

async fn clear_history(
    State(state): State<AppState>,
    Json(body): Json<ClearBody>,
) -> Json<Value> {
    if state.db.clear_history(body.search_type.as_deref()) {
        Json(json!({"code": 200, "message": "清空成功"}))
    } else {
        Json(json!({"code": 500, "message": "清空失败"}))
    }
}

pub fn routes() -> Router<AppState> {
    Router::new()
        .route("/history", get(get_history))
        .route("/history/{history_id}", get(get_history_detail))
        .route(
            "/history/delete/{history_id}",
            get(delete_history).post(delete_history).delete(delete_history),
        )
        .route("/history/clear", post(clear_history))
}
