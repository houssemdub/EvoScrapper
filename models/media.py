from typing import List, Optional
from pydantic import BaseModel, Field


class MediaDetails(BaseModel):
    title: str
    year: Optional[str] = None
    imdb_id: Optional[str] = None
    type: str = "movie"
    poster_url: Optional[str] = None
    backdrop_url: Optional[str] = None
    rating: Optional[str] = None
    runtime: Optional[str] = None
    genres: List[str] = Field(default_factory=list)
    plot: Optional[str] = None
    director: Optional[str] = None
    cast: List[str] = Field(default_factory=list)
    trailer_url: Optional[str] = None
    trailer_embed: Optional[str] = None
    source: str = "cinemeta"
