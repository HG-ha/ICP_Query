mod auth_api;
mod batch;
mod config_api;
mod history;
mod logs;
pub mod query;
mod ui;

use crate::auth::auth_middleware;
use crate::state::AppState;
use axum::middleware;
use axum::Router;

pub fn router(state: AppState) -> Router {
    Router::new()
        .merge(auth_api::routes())
        .merge(query::routes())
        .merge(batch::routes())
        .merge(history::routes())
        .merge(config_api::routes())
        .merge(logs::routes())
        .merge(ui::routes(&state))
        .layer(middleware::from_fn_with_state(
            state.clone(),
            auth_middleware,
        ))
        .with_state(state)
}
