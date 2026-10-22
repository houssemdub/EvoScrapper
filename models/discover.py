from typing import List, Optional
from pydantic import BaseModel, Field


class DiscoverItem(BaseModel):
    id: str
    title: str
    type: str = "movie"  # movie, series, anime
    year: Optional[str] = None
    poster: Optional[str] = None
    backdrop: Optional[str] = None
    rating: Optional[str] = None
    genres: List[str] = Field(default_factory=list)
    description: Optional[str] = None
    trailer: Optional[str] = None
    anime_format: Optional[str] = None  # TV, OVA, Movie, Special, ONA
    anime_status: Optional[str] = None  # Airing, Finished, Upcoming
    studio: Optional[str] = None


class EpisodeItem(BaseModel):
    id: str
    season: int
    episode: int
    title: str
    released: Optional[str] = None
    overview: Optional[str] = None
    thumbnail: Optional[str] = None


class SeasonInfo(BaseModel):
    season_number: int
    episodes: List[EpisodeItem] = Field(default_factory=list)


class DiscoverDetail(DiscoverItem):
    runtime: Optional[str] = None
    director: Optional[str] = None
    cast: List[str] = Field(default_factory=list)
    seasons: List[SeasonInfo] = Field(default_factory=list)
    total_episodes: int = 0


class DiscoverCatalogResponse(BaseModel):
    items: List[DiscoverItem]
    total: int
    type: str
    catalog: str
    genre: Optional[str] = None
