use crate::state::AppState;
use axum::extract::{Query, State};
use axum::routing::get;
use axum::{Json, Router};
use serde::Deserialize;
use serde_json::{json, Value};

#[derive(Debug, Deserialize)]
pub struct LogsQuery {
    #[serde(default = "default_limit")]
    pub limit: usize,
}

fn default_limit() -> usize {
    500
}

async fn get_realtime_logs(
    State(state): State<AppState>,
    Query(q): Query<LogsQuery>,
) -> Json<Value> {
    let logs = state.logs.get_logs(q.limit);
    let total = logs.len();
    Json(json!({"code": 200, "data": logs, "total": total}))
}

async fn clear_logs(State(state): State<AppState>) -> Json<Value> {
    state.logs.clear();
    Json(json!({"code": 200, "message": "日志已清空"}))
}

pub fn routes() -> Router<AppState> {
    Router::new()
        .route("/logs/realtime", get(get_realtime_logs))
        .route("/logs/clear", get(clear_logs).post(clear_logs))
}
