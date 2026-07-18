use crate::state::AppState;
use axum::extract::State;
use axum::http::StatusCode;
use axum::response::{Html, IntoResponse, Response};
use axum::routing::get;
use axum::Router;
use tower_http::services::ServeDir;

async fn index(State(state): State<AppState>) -> Response {
    if !state.config.read().system.web_ui {
        return (
            StatusCode::NOT_FOUND,
            axum::Json(serde_json::json!({
                "code": 404,
                "msg": "Web UI 未启用"
            })),
        )
            .into_response();
    }

    let template_path = state.project_root.join("templates").join("index.html");
    match std::fs::read_to_string(&template_path) {
        Ok(html) => Html(html).into_response(),
        Err(_) => (
            StatusCode::INTERNAL_SERVER_ERROR,
            format!("无法读取模板: {}", template_path.display()),
        )
            .into_response(),
    }
}

pub fn routes(state: &AppState) -> Router<AppState> {
    let static_dir = state.project_root.join("static");
    let mut router = Router::new().route("/", get(index));

    if static_dir.exists() {
        router = router.nest_service("/static", ServeDir::new(static_dir));
    }

    router
}
