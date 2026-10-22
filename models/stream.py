from typing import List, Optional
from pydantic import BaseModel, Field


class StreamItem(BaseModel):
    name: str  # Display badge, e.g. "EvoStream 4K REMUX"
    title: str  # Detailed torrent/file release name
    info_hash: str
    file_idx: int = 0
    quality: str = "Unknown"  # 4K, 1080p, 720p, 480p
    resolution: Optional[str] = None
    codec: Optional[str] = None
    audio: Optional[str] = None
    hdr: Optional[str] = None
    seeds: int = 0
    peers: int = 0
    size: str = "Unknown"
    size_bytes: int = 0
    tracker: str = "DHT"
    magnet: Optional[str] = None
    stream_url: Optional[str] = None
    score: float = 0.0
    is_debrid_cached: bool = False
    debrid_provider: Optional[str] = None
    is_cdn: bool = False
    embed_url: Optional[str] = None
    season: Optional[int] = None
    episode: Optional[int] = None


class StreamResolveResponse(BaseModel):
    streams: List[StreamItem] = Field(default_factory=list)
    total: int = 0
    imdb_id: Optional[str] = None
    title: str = ""
    season: Optional[int] = None
    episode: Optional[int] = None
    resolved_time_ms: float = 0.0


class LaunchVlcRequest(BaseModel):
    info_hash: Optional[str] = None
    file_idx: int = 0
    stream_url: Optional[str] = None
    title: Optional[str] = "EvoScrapper Stream"
    magnet: Optional[str] = None
    season: Optional[int] = None
    episode: Optional[int] = None
    player: Optional[str] = "vlc"
