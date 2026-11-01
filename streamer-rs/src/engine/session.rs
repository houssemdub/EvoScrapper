use crate::engine::disk::DiskStorage;
use crate::engine::piece_picker::PiecePicker;
use crate::engine::swarm::SwarmManager;
use crate::stats::{StremioFile, StremioStatistics};
use crate::types::{EngineConfig, EngineError, FileMetadata, InfoHash};
use std::collections::HashMap;
use std::sync::Arc;
use tokio::sync::RwLock;

pub struct TorrentSession {
    pub info_hash: InfoHash,
    pub name: String,
    pub files: Vec<FileMetadata>,
    pub piece_length: usize,
    pub total_pieces: usize,
    pub piece_picker: PiecePicker,
    pub swarm: SwarmManager,
    pub downloaded_bytes: u64,
    pub uploaded_bytes: u64,
    pub download_speed: f64,
    pub upload_speed: f64,
}

impl TorrentSession {
    pub fn new(info_hash: InfoHash, name: String, files: Vec<FileMetadata>) -> Self {
        let piece_len = 1024 * 1024; // 1MB default
        let total_size: u64 = files.iter().map(|f| f.length).sum();
        let total_pieces = ((total_size as usize + piece_len - 1) / piece_len).max(1);

        Self {
            info_hash,
            name,
            files,
            piece_length: piece_len,
            total_pieces,
            piece_picker: PiecePicker::new(piece_len, total_pieces),
            swarm: SwarmManager::new(55),
            downloaded_bytes: 0,
            uploaded_bytes: 0,
            download_speed: 0.0,
            upload_speed: 0.0,
        }
    }

    pub fn to_statistics(&self, file_idx: Option<usize>) -> StremioStatistics {
        let mut stats = StremioStatistics::default();
        stats.name = self.name.clone();
        stats.info_hash = self.info_hash.0.clone();
        stats.download_speed = self.download_speed;
        stats.upload_speed = self.upload_speed;
        stats.downloaded = self.downloaded_bytes;
        stats.uploaded = self.uploaded_bytes;
        stats.peers = self.swarm.peer_count() as u64;
        stats.unchoked = self.swarm.unchoked_count() as u64;

        stats.files = self
            .files
            .iter()
            .map(|f| StremioFile {
                name: f.name.clone(),
                path: f.path.clone(),
                length: f.length,
                offset: f.offset,
            })
            .collect();

        if let Some(idx) = file_idx {
            if let Some(f) = self.files.get(idx) {
                stats.stream_len = Some(f.length);
                stats.stream_name = Some(f.name.clone());
                stats.stream_progress = Some(0.0);
            }
        }

        stats
    }
}

pub struct SessionManager {
    config: EngineConfig,
    storage: DiskStorage,
    sessions: Arc<RwLock<HashMap<String, TorrentSession>>>,
}

impl SessionManager {
    pub fn new(config: EngineConfig) -> Result<Self, EngineError> {
        let storage = DiskStorage::new(&config.cache_dir)?;
        Ok(Self {
            config,
            storage,
            sessions: Arc::new(RwLock::new(HashMap::new())),
        })
    }

    pub async fn get_or_create(
        &self,
        info_hash_str: &str,
        name_hint: Option<String>,
    ) -> Result<InfoHash, EngineError> {
        let hash = InfoHash::new(info_hash_str)
            .ok_or_else(|| EngineError::TorrentNotFound(info_hash_str.to_string()))?;

        let mut lock = self.sessions.write().await;
        if !lock.contains_key(&hash.0) {
            let session_name = name_hint.unwrap_or_else(|| format!("Torrent_{}", &hash.0[0..8]));
            // Register a default file until metadata is resolved
            let dummy_file = FileMetadata {
                idx: 0,
                name: format!("{}.mp4", session_name),
                path: format!("{}.mp4", session_name),
                length: 1_000_000_000, // 1GB placeholder
                offset: 0,
            };
            let session = TorrentSession::new(hash.clone(), session_name, vec![dummy_file]);
            lock.insert(hash.0.clone(), session);
        }

        Ok(hash)
    }

    pub async fn get_files(&self, hash: &InfoHash) -> Result<Vec<FileMetadata>, EngineError> {
        let lock = self.sessions.read().await;
        let session = lock
            .get(&hash.0)
            .ok_or_else(|| EngineError::TorrentNotFound(hash.0.clone()))?;
        Ok(session.files.clone())
    }

    pub async fn get_statistics(
        &self,
        hash: &InfoHash,
        file_idx: Option<usize>,
    ) -> Result<StremioStatistics, EngineError> {
        let lock = self.sessions.read().await;
        let session = lock
            .get(&hash.0)
            .ok_or_else(|| EngineError::TorrentNotFound(hash.0.clone()))?;
        Ok(session.to_statistics(file_idx))
    }

    pub async fn get_all_statistics(&self) -> Vec<StremioStatistics> {
        let lock = self.sessions.read().await;
        lock.values().map(|s| s.to_statistics(None)).collect()
    }
}
