pub mod auth;
pub mod range;
pub mod routes;

use axum::routing::get;
use axum::Router;
use routes::{
    all_stats_handler, files_handler, health_handler, single_stats_handler, status_handler,
    stream_handler, warm_handler, AppState,
};
use std::sync::Arc;
use tower_http::cors::CorsLayer;

pub fn create_router(state: Arc<AppState>) -> Router {
    Router::new()
        .route("/health", get(health_handler))
        .route("/status", get(status_handler))
        .route("/stats.json", get(all_stats_handler))
        .route("/:info_hash/:file_idx/stats.json", get(single_stats_handler))
        .route("/files", get(files_handler))
        .route("/warm", get(warm_handler))
        .route("/stream", get(stream_handler))
        .layer(CorsLayer::permissive())
        .with_state(state)
}
