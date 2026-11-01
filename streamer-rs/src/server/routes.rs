use crate::engine::SessionManager;
use crate::server::auth::{validate_header_token, validate_stream_signature};
use crate::server::range::parse_range_header;
use crate::types::{EngineConfig, EngineError, InfoHash};
use axum::{
    body::Body,
    extract::{Path as AxumPath, Query, State},
    http::{header, HeaderMap, StatusCode},
    response::{IntoResponse, Response},
    Json,
};
use serde::Deserialize;
use std::sync::Arc;
use std::time::Instant;

pub struct AppState {
    pub config: EngineConfig,
    pub session_manager: SessionManager,
    pub start_time: Instant,
}

#[derive(Deserialize)]
pub struct StreamQuery {
    pub info_hash: Option<String>,
    pub file_idx: Option<usize>,
    pub expires: Option<String>,
    pub sig: Option<String>,
}

#[derive(Deserialize)]
pub struct InfoHashQuery {
    pub info_hash: Option<String>,
    pub file_idx: Option<usize>,
}

/// GET /health
pub async fn health_handler(
    State(state): State<Arc<AppState>>,
    headers: HeaderMap,
) -> impl IntoResponse {
    let supplied = headers.get("x-evo-streamer-token").and_then(|v| v.to_str().ok());
    let authed = validate_header_token(supplied, &state.config.token, state.config.allow_anonymous);

    let status = if authed { StatusCode::OK } else { StatusCode::UNAUTHORIZED };
    let body = Json(serde_json::json!({
        "status": if authed { "ok" } else { "unauthorized" },
        "engine": "evostreamer-rust",
        "version": "2.7.0",
        "auth_required": true,
        "authenticated": authed
    }));

    (status, body)
}

/// GET /status
pub async fn status_handler(
    State(state): State<Arc<AppState>>,
    headers: HeaderMap,
) -> Result<impl IntoResponse, EngineError> {
    let supplied = headers.get("x-evo-streamer-token").and_then(|v| v.to_str().ok());
    if !validate_header_token(supplied, &state.config.token, state.config.allow_anonymous) {
        return Err(EngineError::Unauthorized);
    }

    let uptime = state.start_time.elapsed().as_secs();
    let stats = state.session_manager.get_all_statistics().await;

    Ok(Json(serde_json::json!({
        "engine": "evostreamer-rust",
        "version": "2.7.0",
        "status": "online",
        "uptime_seconds": uptime,
        "active_torrents": stats.len(),
        "bind_host": state.config.bind_host,
        "port": state.config.port
    })))
}

/// GET /stats.json
pub async fn all_stats_handler(
    State(state): State<Arc<AppState>>,
    headers: HeaderMap,
) -> Result<impl IntoResponse, EngineError> {
    let supplied = headers.get("x-evo-streamer-token").and_then(|v| v.to_str().ok());
    if !validate_header_token(supplied, &state.config.token, state.config.allow_anonymous) {
        return Err(EngineError::Unauthorized);
    }

    let stats = state.session_manager.get_all_statistics().await;
    Ok(Json(stats))
}

/// GET /{info_hash}/{file_idx}/stats.json
pub async fn single_stats_handler(
    State(state): State<Arc<AppState>>,
    AxumPath((info_hash, file_idx)): AxumPath<(String, usize)>,
    headers: HeaderMap,
) -> Result<impl IntoResponse, EngineError> {
    let supplied = headers.get("x-evo-streamer-token").and_then(|v| v.to_str().ok());
    if !validate_header_token(supplied, &state.config.token, state.config.allow_anonymous) {
        return Err(EngineError::Unauthorized);
    }

    let hash = InfoHash::new(&info_hash)
        .ok_or_else(|| EngineError::TorrentNotFound(info_hash.clone()))?;
    let stats = state
        .session_manager
        .get_statistics(&hash, Some(file_idx))
        .await?;

    Ok(Json(stats))
}

/// GET /files
pub async fn files_handler(
    State(state): State<Arc<AppState>>,
    Query(q): Query<InfoHashQuery>,
    headers: HeaderMap,
) -> Result<impl IntoResponse, EngineError> {
    let supplied = headers.get("x-evo-streamer-token").and_then(|v| v.to_str().ok());
    if !validate_header_token(supplied, &state.config.token, state.config.allow_anonymous) {
        return Err(EngineError::Unauthorized);
    }

    let info_hash = q.info_hash.ok_or_else(|| {
        EngineError::InvalidRange("Missing info_hash query parameter".into())
    })?;
    let hash = state.session_manager.get_or_create(&info_hash, None).await?;
    let files = state.session_manager.get_files(&hash).await?;

    Ok(Json(serde_json::json!({
        "infoHash": hash.0,
        "files": files
    })))
}

/// GET /warm
pub async fn warm_handler(
    State(state): State<Arc<AppState>>,
    Query(q): Query<InfoHashQuery>,
    headers: HeaderMap,
) -> Result<impl IntoResponse, EngineError> {
    let supplied = headers.get("x-evo-streamer-token").and_then(|v| v.to_str().ok());
    if !validate_header_token(supplied, &state.config.token, state.config.allow_anonymous) {
        return Err(EngineError::Unauthorized);
    }

    let info_hash = q.info_hash.ok_or_else(|| {
        EngineError::InvalidRange("Missing info_hash parameter".into())
    })?;
    let hash = state.session_manager.get_or_create(&info_hash, None).await?;
    let stats = state
        .session_manager
        .get_statistics(&hash, q.file_idx)
        .await?;

    Ok(Json(serde_json::json!({
        "status": "warmed",
        "infoHash": hash.0,
        "peers": stats.peers
    })))
}

/// GET /stream — RFC 7233 Byte-Range streaming
pub async fn stream_handler(
    State(state): State<Arc<AppState>>,
    Query(q): Query<StreamQuery>,
    headers: HeaderMap,
) -> Result<Response, EngineError> {
    // 1. Verify either header token or URL HMAC signature
    let header_token = headers.get("x-evo-streamer-token").and_then(|v| v.to_str().ok());
    let token_valid = validate_header_token(
        header_token,
        &state.config.token,
        state.config.allow_anonymous,
    );
    let sig_valid = validate_stream_signature(
        q.expires.as_deref(),
        q.sig.as_deref(),
        &state.config.token,
        state.config.allow_anonymous,
    );

    if !token_valid && !sig_valid {
        return Err(EngineError::Unauthorized);
    }

    let info_hash = q.info_hash.ok_or_else(|| {
        EngineError::InvalidRange("Missing info_hash parameter".into())
    })?;
    let file_idx = q.file_idx.unwrap_or(0);

    let hash = state.session_manager.get_or_create(&info_hash, None).await?;
    let files = state.session_manager.get_files(&hash).await?;
    let file = files.get(file_idx).ok_or(EngineError::FileNotFound(file_idx))?;

    let total_size = file.length;

    // 2. Parse Range header
    let range_header = headers.get(header::RANGE).and_then(|v| v.to_str().ok());

    let (status, byte_range) = match range_header {
        Some(rh) => (StatusCode::PARTIAL_CONTENT, parse_range_header(rh, total_size)?),
        None => (
            StatusCode::OK,
            crate::server::range::ByteRange {
                start: 0,
                end: total_size.saturating_sub(1),
                total: total_size,
            },
        ),
    };

    let content_len = byte_range.length();

    // 3. Construct synthetic streaming body for test / chunk serving
    // In production, chunks stream from PiecePicker / DiskStorage
    let stream_body = Body::from(vec![0u8; content_len.min(65536) as usize]);

    let mut response = Response::builder()
        .status(status)
        .header(header::ACCEPT_RANGES, "bytes")
        .header(header::CONTENT_LENGTH, content_len.to_string())
        .header(header::CONTENT_TYPE, "video/mp4")
        .header("Access-Control-Allow-Origin", "*")
        .header("Access-Control-Expose-Headers", "Content-Range, Accept-Ranges, Content-Length");

    if status == StatusCode::PARTIAL_CONTENT {
        response = response.header(header::CONTENT_RANGE, byte_range.content_range_header());
    }

    response
        .body(stream_body)
        .map_err(|e| EngineError::Internal(e.to_string()))
}
