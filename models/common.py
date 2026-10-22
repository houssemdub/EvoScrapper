from enum import Enum
from typing import Dict, List, Optional
from pydantic import BaseModel, Field
from .torrent import TorrentItem
from .subtitle import SubtitleItem


class CircuitState(str, Enum):
    CLOSED = "closed"        # Healthy, operational
    OPEN = "open"            # Failing, skipped
    HALF_OPEN = "half_open"  # Probing for recovery


class ProviderHealth(BaseModel):
    name: str
    type: str                # "torrent" or "subtitle"
    status: CircuitState
    failure_count: int = 0
    total_calls: int = 0
    successful_calls: int = 0
    avg_latency_ms: float = 0.0
    last_error: Optional[str] = None


class UnifiedMediaBundle(BaseModel):
    query: Optional[str] = None
    imdb_id: Optional[str] = None
    total_torrents: int
    total_subtitles: int
    torrents: List[TorrentItem] = Field(default_factory=list)
    subtitles: List[SubtitleItem] = Field(default_factory=list)
    execution_time_seconds: float


class HealthResponse(BaseModel):
    app: str = "EvoScrapper"
    version: str = "2.0.0"
    status: str = "healthy"
    uptime_seconds: float
    total_providers: int
    healthy_providers: int
    providers: List[ProviderHealth]
