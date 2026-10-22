import datetime
import re
from typing import Any, Dict, List
from core.client import http_client
from core.title_parser import format_bytes, parse_release_title
from models.torrent import TorrentItem
from providers.base import BaseProvider


class EztvProvider(BaseProvider):
    """
    EZTV official JSON API provider for TV series.
    Supports IMDb IDs directly and filename keyword filtering.
    """

    def __init__(self):
        super().__init__(
            name="eztv",
            provider_type="torrent",
            base_urls=[
                "https://eztvx.to",
                "https://eztv.re",
                "https://eztv.wf",
                "https://eztv.tf",
            ],
        )

    def _parse_torrents(self, torrents: List[Dict[str, Any]], limit: int = 50) -> List[TorrentItem]:
        items: List[TorrentItem] = []
        for t in torrents:
            info_hash = (t.get("hash") or "").lower()
            if not info_hash:
                continue

            title = t.get("title") or t.get("filename") or "Unknown TV Release"
            magnet = t.get("magnet_url") or f"magnet:?xt=urn:btih:{info_hash}"
            size_bytes = int(t.get("size_bytes") or 0)
            seeders = int(t.get("seeds") or 0)
            leechers = int(t.get("peers") or 0)
            
            date_unix = t.get("date_released_unix")
            upload_date = None
            if date_unix:
                try:
                    upload_date = datetime.datetime.fromtimestamp(int(date_unix)).strftime("%Y-%m-%d")
                except Exception:
                    pass

            item = TorrentItem(
                id=info_hash,
                title=title,
                info_hash=info_hash,
                magnet_uri=magnet,
                size_bytes=size_bytes,
                size_formatted=format_bytes(size_bytes),
                seeders=seeders,
                leechers=leechers,
                category="tv",
                upload_date=upload_date,
                uploader="EZTV",
                provider=self.name,
                sources=[self.name],
                details_url=t.get("episode_url"),
                metadata=parse_release_title(title),
            )
            items.append(item)
            if len(items) >= limit:
                break
        return items

    async def _do_search(self, query: str, limit: int = 50, **kwargs) -> List[TorrentItem]:
        endpoint = f"{self.base_url}/api/get-torrents"
        params: Dict[str, Any] = {"limit": min(limit, 100)}

        # Check if query is an IMDb ID
        imdb_match = re.search(r"tt(\d+)", query, re.IGNORECASE)
        if imdb_match:
            params["imdb_id"] = imdb_match.group(1)
            data = await http_client.get_json(endpoint, params=params)
            torrents = data.get("torrents") or []
            return self._parse_torrents(torrents, limit=limit)

        # Keyword search
        data = await http_client.get_json(endpoint, params=params)
        torrents = data.get("torrents") or []
        query_words = query.lower().split()
        filtered = [
            t for t in torrents
            if all(w in (t.get("title") or t.get("filename") or "").lower() for w in query_words)
        ]
        return self._parse_torrents(filtered, limit=limit) if filtered else []
