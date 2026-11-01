use serde::{Deserialize, Serialize};
use std::path::PathBuf;

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct EngineConfig {
    pub port: u16,
    pub bind_host: String,
    pub cache_dir: PathBuf,
    pub token: String,
    pub allow_anonymous: bool,
    pub torrent_port: u16,
    pub dht_port: u16,
    pub max_active_torrents: usize,
}

impl Default for EngineConfig {
    fn default() -> Self {
        Self {
            port: 8891,
            bind_host: "127.0.0.1".to_string(),
            cache_dir: PathBuf::from(".stream_cache"),
            token: String::new(),
            allow_anonymous: false,
            torrent_port: 50000,
            dht_port: 50001,
            max_active_torrents: 3,
        }
    }
}

#[derive(Clone, Debug, PartialEq, Eq, Hash, Serialize, Deserialize)]
pub struct InfoHash(pub String);

impl InfoHash {
    pub fn new(hash: &str) -> Option<Self> {
        let clean = hash.trim().to_lowercase();
        if clean.len() == 40 && clean.chars().all(|c| c.is_ascii_hexdigit()) {
            Some(Self(clean))
        } else {
            None
        }
    }
}

#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct FileMetadata {
    pub idx: usize,
    pub name: String,
    pub path: String,
    pub length: u64,
    pub offset: u64,
}

#[derive(Debug, thiserror::Error)]
pub enum EngineError {
    #[error("Unauthorized: invalid or missing control-plane token")]
    Unauthorized,

    #[error("Torrent not found: {0}")]
    TorrentNotFound(String),

    #[error("File index out of bounds: {0}")]
    FileNotFound(usize),

    #[error("Range not satisfiable: {0}")]
    InvalidRange(String),

    #[error("I/O error: {0}")]
    Io(#[from] std::io::Error),

    #[error("Internal error: {0}")]
    Internal(String),
}

impl axum::response::IntoResponse for EngineError {
    fn into_response(self) -> axum::response::Response {
        use axum::http::StatusCode;
        use axum::Json;

        let (status, message) = match &self {
            EngineError::Unauthorized => (StatusCode::UNAUTHORIZED, self.to_string()),
            EngineError::TorrentNotFound(_) => (StatusCode::NOT_FOUND, self.to_string()),
            EngineError::FileNotFound(_) => (StatusCode::NOT_FOUND, self.to_string()),
            EngineError::InvalidRange(_) => (StatusCode::RANGE_NOT_SATISFIABLE, self.to_string()),
            EngineError::Io(_) => (StatusCode::INTERNAL_SERVER_ERROR, self.to_string()),
            EngineError::Internal(_) => (StatusCode::INTERNAL_SERVER_ERROR, self.to_string()),
        };

        let body = Json(serde_json::json!({
            "error": message,
            "status": status.as_u16()
        }));

        (status, body).into_response()
    }
}
