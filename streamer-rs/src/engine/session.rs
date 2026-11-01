use crate::stats::{StremioFile, StremioStatistics};
use crate::types::{EngineConfig, EngineError, FileMetadata};
use librqbit::{AddTorrent, ManagedTorrent, Session, SessionOptions};
use std::collections::HashMap;
use std::sync::Arc;
use tokio::sync::RwLock;

pub struct SessionManager {
    config: EngineConfig,
    rqbit: Arc<Session>,
    torrents: Arc<RwLock<HashMap<String, Arc<ManagedTorrent>>>>,
}

impl SessionManager {
    pub async fn new(config: EngineConfig) -> Result<Self, EngineError> {
        let _ = std::fs::create_dir_all(&config.cache_dir);

        let mut opts = SessionOptions::default();
        opts.fastresume = true;
        opts.peer_limit = Some(150);

        let rqbit = Session::new_with_opts(config.cache_dir.clone(), opts)
            .await
            .map_err(|e| EngineError::Internal(format!("Failed to start librqbit session: {}", e)))?;

        Ok(Self {
            config,
            rqbit,
            torrents: Arc::new(RwLock::new(HashMap::new())),
        })
    }

    pub fn canonical_hash(hash_or_magnet: &str) -> String {
        let s = hash_or_magnet.trim();
        if s.starts_with("magnet:?") {
            if let Some(pos) = s.to_lowercase().find("xt=urn:btih:") {
                let sub = &s[pos + 11..];
                let end = sub.find('&').unwrap_or(sub.len());
                return sub[..end].to_lowercase();
            }
        }
        s.to_lowercase()
    }

    pub async fn get_or_create(
        &self,
        info_hash_str: &str,
        magnet_opt: Option<String>,
    ) -> Result<Arc<ManagedTorrent>, EngineError> {
        let hash_clean = Self::canonical_hash(info_hash_str);

        {
            let lock = self.torrents.read().await;
            if let Some(t) = lock.get(&hash_clean) {
                return Ok(t.clone());
            }
        }

        let magnet_url = match magnet_opt {
            Some(m) if m.starts_with("magnet:?") => m,
            _ => {
                format!(
                    "magnet:?xt=urn:btih:{}&tr=udp%3A%2F%2Ftracker.opentrackr.org%3A1337%2Fannounce&tr=udp%3A%2F%2Fopen.stealth.si%3A80%2Fannounce&tr=udp%3A%2F%2Ftracker.torrent.eu.org%3A451%2Fannounce&tr=udp%3A%2F%2Fexplodie.org%3A6969%2Fannounce",
                    hash_clean
                )
            }
        };

        let add_resp = self
            .rqbit
            .add_torrent(AddTorrent::from_url(magnet_url), None)
            .await
            .map_err(|e| EngineError::Internal(format!("Failed to add torrent: {}", e)))?;

        let managed = add_resp.into_handle().ok_or_else(|| {
            EngineError::Internal("Torrent handle could not be initialized".into())
        })?;

        // Wait up to 10 seconds for torrent metadata to resolve from DHT/trackers
        let _ = tokio::time::timeout(
            std::time::Duration::from_secs(10),
            managed.wait_until_initialized(),
        )
        .await;

        let mut lock = self.torrents.write().await;
        lock.insert(hash_clean, managed.clone());

        Ok(managed)
    }

    pub async fn get_files(
        &self,
        managed: &Arc<ManagedTorrent>,
    ) -> Result<Vec<FileMetadata>, EngineError> {
        let files = managed
            .with_metadata(|meta| {
                meta.file_infos
                    .iter()
                    .enumerate()
                    .map(|(idx, fi)| FileMetadata {
                        idx,
                        name: fi
                            .relative_filename
                            .file_name()
                            .map(|n| n.to_string_lossy().to_string())
                            .unwrap_or_else(|| format!("file_{}", idx)),
                        path: fi.relative_filename.to_string_lossy().to_string(),
                        length: fi.len,
                        offset: fi.offset_in_torrent,
                    })
                    .collect::<Vec<_>>()
            })
            .unwrap_or_default();

        Ok(files)
    }

    pub async fn get_statistics(
        &self,
        info_hash: &str,
        managed: &Arc<ManagedTorrent>,
        file_idx: Option<usize>,
    ) -> Result<StremioStatistics, EngineError> {
        let mut stats = StremioStatistics::default();
        stats.info_hash = info_hash.to_string();
        stats.name = managed.name().unwrap_or_default();

        let t_stats = managed.stats();
        stats.downloaded = t_stats.progress_bytes;
        stats.uploaded = t_stats.uploaded_bytes;

        if let Some(live) = &t_stats.live {
            stats.download_speed = (live.download_speed.mbps * 125_000.0) as f64;
            stats.upload_speed = (live.upload_speed.mbps * 125_000.0) as f64;
            stats.peers = live.snapshot.peer_stats.live as u64;
            stats.unchoked = live.snapshot.peer_stats.live as u64;
        }

        let files = self.get_files(managed).await.unwrap_or_default();
        stats.files = files
            .iter()
            .map(|f| StremioFile {
                name: f.name.clone(),
                path: f.path.clone(),
                length: f.length,
                offset: f.offset,
            })
            .collect();

        if let Some(idx) = file_idx {
            if let Some(f) = files.get(idx) {
                stats.stream_len = Some(f.length);
                stats.stream_name = Some(f.name.clone());
                let prog = if f.length > 0 {
                    t_stats
                        .file_progress
                        .get(idx)
                        .copied()
                        .unwrap_or(0) as f64
                        / f.length as f64
                } else {
                    0.0
                };
                stats.stream_progress = Some(prog);
            }
        }

        Ok(stats)
    }

    pub async fn get_all_statistics(&self) -> Vec<StremioStatistics> {
        let lock = self.torrents.read().await;
        let mut result = Vec::new();
        for (hash, managed) in lock.iter() {
            if let Ok(st) = self.get_statistics(hash, managed, None).await {
                result.push(st);
            }
        }
        result
    }
}
