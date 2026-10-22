from typing import List, Optional
from pydantic import BaseModel, Field


class QualityMetadata(BaseModel):
    resolution: Optional[str] = None      # 2160p, 1080p, 720p, etc.
    source: Optional[str] = None          # REMUX, BluRay, WEB-DL, WEBRip, HDTV, CAM
    codec: Optional[str] = None           # HEVC, x265, x264, AV1, XviD
    audio: Optional[str] = None           # Atmos, TrueHD, DDP5.1, AAC
    hdr: List[str] = Field(default_factory=list)  # DV, HDR10+, HDR
    group: Optional[str] = None           # FraMeSToR, YTS, NTb, etc.


class TorrentItem(BaseModel):
    id: str
    title: str
    info_hash: Optional[str] = None       # 40-char SHA1 hex
    magnet_uri: str
    size_bytes: int = 0
    size_formatted: str = "Unknown"
    seeders: int = 0
    leechers: int = 0
    category: str = "other"
    upload_date: Optional[str] = None
    uploader: Optional[str] = None
    provider: str
    sources: List[str] = Field(default_factory=list)
    details_url: Optional[str] = None
    metadata: QualityMetadata = Field(default_factory=QualityMetadata)


class TorrentSearchResponse(BaseModel):
    query: str
    provider: str
    total: int
    time_taken: float
    data: List[TorrentItem]
