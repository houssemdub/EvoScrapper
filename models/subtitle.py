from typing import List, Optional
from pydantic import BaseModel, Field


class SubtitleItem(BaseModel):
    id: str
    provider: str
    language: str
    lang_code: str                        # en, es, fr, etc.
    format: str = "srt"                   # srt, vtt, ass
    download_url: str
    release_name: Optional[str] = None
    is_hearing_impaired: bool = False
    rating: Optional[float] = None
    downloads_count: Optional[int] = None
    season: Optional[int] = None
    episode: Optional[int] = None
    fps: Optional[float] = None


class SubtitleSearchResponse(BaseModel):
    query: Optional[str] = None
    imdb_id: Optional[str] = None
    total: int
    time_taken: float
    data: List[SubtitleItem]
