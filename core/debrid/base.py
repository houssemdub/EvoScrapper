import abc
from dataclasses import dataclass
from typing import Any, Dict, List, Optional


@dataclass
class DebridStreamResult:
    url: str
    filename: str
    size: int
    provider: str
    cached: bool = True
    mime_type: str = "video/mp4"


class DebridClient(abc.ABC):
    """
    Abstract base class for all Debrid providers (Real-Debrid, AllDebrid, TorBox, Premiumize).
    """

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or ""
        self.provider_name = "Debrid"

    @property
    def is_configured(self) -> bool:
        return bool(self.api_key and len(self.api_key.strip()) > 3)

    @abc.abstractmethod
    async def check_cache(self, info_hashes: List[str]) -> Dict[str, bool]:
        """
        Batches torrent info_hashes and checks instant availability on debrid servers.
        Returns a dictionary mapping hash -> bool (True if cached).
        """
        pass

    @abc.abstractmethod
    async def resolve_stream(
        self,
        info_hash: str,
        file_idx: int = 0,
        magnet: Optional[str] = None,
        season: Optional[int] = None,
        episode: Optional[int] = None,
    ) -> Optional[DebridStreamResult]:
        """
        Resolves a cached torrent to an unthrottled, direct 1Gbps HTTPS CDN download link.
        """
        pass

    @abc.abstractmethod
    async def get_user_info(self) -> Dict[str, Any]:
        """
        Fetches account status, expiration timestamp, and premium status.
        """
        pass
