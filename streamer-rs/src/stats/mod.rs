use serde::{Deserialize, Serialize};

#[derive(Clone, PartialEq, Serialize, Deserialize, Debug)]
#[serde(rename_all = "camelCase")]
pub struct StremioFile {
    pub name: String,
    pub path: String,
    pub length: u64,
    pub offset: u64,
}

#[derive(Clone, PartialEq, Serialize, Deserialize, Debug, Default)]
#[serde(rename_all = "camelCase")]
pub struct StremioSource {
    pub url: String,
    pub num_found: u64,
    pub num_found_uniq: u64,
    pub num_requests: u64,
    pub last_started: String,
}

#[derive(Clone, PartialEq, Serialize, Deserialize, Debug, Default)]
#[serde(rename_all = "camelCase")]
pub struct StremioOptions {
    pub connections: Option<u64>,
    pub dht: bool,
    pub path: String,
    pub timeout: Option<u64>,
    pub tracker: bool,
}

#[derive(Clone, PartialEq, Serialize, Deserialize, Debug)]
#[serde(rename_all = "camelCase")]
pub struct StremioStatistics {
    pub name: String,
    pub info_hash: String,
    pub files: Vec<StremioFile>,
    pub sources: Vec<StremioSource>,
    pub opts: StremioOptions,
    pub download_speed: f64,
    pub upload_speed: f64,
    pub downloaded: u64,
    pub uploaded: u64,
    pub unchoked: u64,
    pub peers: u64,
    pub queued: u64,
    pub unique: u64,
    pub connection_tries: u64,
    pub peer_search_running: bool,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub stream_len: Option<u64>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub stream_name: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub stream_progress: Option<f64>,
    pub swarm_connections: u64,
    pub swarm_paused: bool,
}

impl Default for StremioStatistics {
    fn default() -> Self {
        Self {
            name: "EvoScrapper Stream".into(),
            info_hash: "".into(),
            files: vec![],
            sources: vec![],
            opts: StremioOptions {
                connections: Some(55),
                dht: true,
                path: ".stream_cache".into(),
                timeout: Some(30),
                tracker: true,
            },
            download_speed: 0.0,
            upload_speed: 0.0,
            downloaded: 0,
            uploaded: 0,
            unchoked: 0,
            peers: 0,
            queued: 0,
            unique: 0,
            connection_tries: 0,
            peer_search_running: false,
            stream_len: None,
            stream_name: None,
            stream_progress: None,
            swarm_connections: 0,
            swarm_paused: false,
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_stremio_statistics_json_serialization() {
        let mut stats = StremioStatistics::default();
        stats.info_hash = "0123456789abcdef0123456789abcdef01234567".into();
        stats.download_speed = 1048576.0;
        stats.peers = 12;
        stats.stream_progress = Some(0.45);
        stats.files.push(StremioFile {
            name: "video.mp4".into(),
            path: "video.mp4".into(),
            length: 100000000,
            offset: 0,
        });

        let json_str = serde_json::to_string(&stats).unwrap();
        assert!(json_str.contains("\"infoHash\":"));
        assert!(json_str.contains("\"downloadSpeed\":1048576.0"));
        assert!(json_str.contains("\"peers\":12"));
        assert!(json_str.contains("\"streamProgress\":0.45"));
        assert!(json_str.contains("\"swarmPaused\":false"));
    }
}
