from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class LibraryItem(BaseModel):
    id: str  # tt ID or kitsu ID
    title: str
    type: str = "movie"  # movie, series, anime
    poster: Optional[str] = None
    backdrop: Optional[str] = None
    year: Optional[str] = None
    rating: Optional[str] = None
    status: str = "plan_to_watch"  # watching, plan_to_watch, completed, on_hold, dropped
    current_season: Optional[int] = None
    current_episode: Optional[int] = None
    total_episodes: Optional[int] = 0
    progress_percent: Optional[int] = 0
    playback_seconds: Optional[float] = 0.0
    duration_seconds: Optional[float] = 0.0
    episode_progress: Optional[Dict[str, Any]] = Field(default_factory=dict)
    created_at: float = Field(default_factory=float)
    updated_at: float = Field(default_factory=float)


class LibraryResponse(BaseModel):
    items: List[LibraryItem]
    total: int
    counts: Dict[str, int]
