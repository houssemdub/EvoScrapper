use std::net::SocketAddr;

#[derive(Clone, Debug)]
pub struct SwarmPeer {
    pub addr: SocketAddr,
    pub is_choked: bool,
    pub is_interested: bool,
    pub download_rate: u64,
    pub upload_rate: u64,
}

pub struct SwarmManager {
    pub max_peers: usize,
    pub peers: Vec<SwarmPeer>,
    pub trackers: Vec<String>,
}

impl SwarmManager {
    pub fn new(max_peers: usize) -> Self {
        Self {
            max_peers: max_peers.clamp(15, 200),
            peers: Vec::new(),
            trackers: vec![
                "udp://tracker.opentrackr.org:1337/announce".into(),
                "udp://open.demonii.com:1337/announce".into(),
                "udp://tracker.openbittorrent.com:6969/announce".into(),
                "udp://tracker.torrent.eu.org:451/announce".into(),
            ],
        }
    }

    pub fn peer_count(&self) -> usize {
        self.peers.len()
    }

    pub fn unchoked_count(&self) -> usize {
        self.peers.iter().filter(|p| !p.is_choked).count()
    }
}
