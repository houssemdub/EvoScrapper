import urllib.parse
from typing import Any, Dict, List, Optional
from core.client import http_client
from core.title_parser import format_bytes, parse_release_title
from models.torrent import TorrentItem
from providers.base import BaseProvider


TRACKERS = [
    "udp://open.stealth.si:80/announce",
    "udp://tracker.opentrackr.org:1337/announce",
    "udp://tracker.torrent.eu.org:451/announce",
    "udp://tracker.coppersurfer.tk:6969/announce",
    "udp://glotorrents.pw:6969/announce",
]


class YtsProvider(BaseProvider):
    """
    High-performance YTS Provider utilizing official JSON API.
    Bypasses DOM scraping and supports multi-mirror failover.
    """

    def __init__(self):
        super().__init__(
            name="yts",
            provider_type="torrent",
            base_urls=[
                "https://yts.bz",
                "https://yts.mx",
                "https://yts.lt",
                "https://yts.rs",
                "https://yts.do",
            ],
        )

    def _build_magnet(self, info_hash: str, movie_title: str) -> str:
        dn = urllib.parse.quote(movie_title)
        tr = "&tr=".join(urllib.parse.quote(t) for t in TRACKERS)
        return f"magnet:?xt=urn:btih:{info_hash}&dn={dn}&tr={tr}"

    def _parse_movies(self, movies_json: List[Dict[str, Any]]) -> List[TorrentItem]:
        items: List[TorrentItem] = []
        for movie in movies_json:
            title = movie.get("title_long") or movie.get("title") or "Unknown Movie"
            imdb_code = movie.get("imdb_code")
            torrents = movie.get("torrents") or []

            for t in torrents:
                info_hash = (t.get("hash") or "").lower()
                if not info_hash:
                    continue

                quality = t.get("quality", "")
                t_type = t.get("type", "")
                release_name = f"{title} [{quality}] [{t_type}] [YTS]"
                size_bytes = t.get("size_bytes") or 0
                seeders = t.get("seeds") or 0
                leechers = t.get("peers") or 0
                upload_date = t.get("date_uploaded")
                magnet = self._build_magnet(info_hash, release_name)

                meta = parse_release_title(release_name)
                if quality and not meta.resolution:
                    meta.resolution = quality

                item = TorrentItem(
                    id=info_hash,
                    title=release_name,
                    info_hash=info_hash,
                    magnet_uri=magnet,
                    size_bytes=size_bytes,
                    size_formatted=format_bytes(size_bytes),
                    seeders=seeders,
                    leechers=leechers,
                    category="movies",
                    upload_date=upload_date,
                    uploader="YTS",
                    provider=self.name,
                    sources=[self.name],
                    details_url=movie.get("url"),
                    metadata=meta,
                )
                items.append(item)
        return items

    async def _do_search(self, query: str, limit: int = 50, **kwargs) -> List[TorrentItem]:
        endpoint = f"{self.base_url}/api/v2/list_movies.json"
        params = {
            "query_term": query,
            "limit": min(limit, 50),
            "sort_by": "seeds",
        }
        data = await http_client.get_json(endpoint, params=params)
        movies = data.get("data", {}).get("movies") or []
        return self._parse_movies(movies)

    async def trending(self, limit: int = 50, **kwargs) -> List[TorrentItem]:
        if not await self.circuit_breaker.can_execute():
            return []
        try:
            endpoint = f"{self.base_url}/api/v2/list_movies.json"
            params = {
                "sort_by": "download_count",
                "limit": min(limit, 50),
            }
            data = await http_client.get_json(endpoint, params=params)
            movies = data.get("data", {}).get("movies") or []
            return self._parse_movies(movies)
        except Exception as e:
            await self.circuit_breaker.record_failure(str(e))
            return []
