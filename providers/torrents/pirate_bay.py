import datetime
import urllib.parse
from typing import Any, Dict, List, Optional
from core.client import http_client
from core.title_parser import format_bytes, parse_release_title
from models.torrent import TorrentItem
from providers.base import BaseProvider


TRACKERS = [
    "udp://tracker.opentrackr.org:1337/announce",
    "udp://open.stealth.si:80/announce",
    "udp://tracker.torrent.eu.org:451/announce",
    "udp://tracker.bittor.pw:1337/announce",
    "udp://public.popcorn-tracker.org:6969/announce",
    "udp://tracker.dler.org:6969/announce",
]

CATEGORY_MAP = {
    "1": "audio",
    "2": "video",
    "3": "apps",
    "4": "games",
    "5": "xxx",
    "6": "other",
}


class PirateBayProvider(BaseProvider):
    """
    High-performance The Pirate Bay provider querying the official apibay backend.
    Bypasses mirror proxies, ads, and Cloudflare challenges.
    """

    def __init__(self):
        super().__init__(
            name="thepiratebay",
            provider_type="torrent",
            base_urls=["https://apibay.org"],
        )

    def _build_magnet(self, info_hash: str, name: str) -> str:
        dn = urllib.parse.quote(name)
        tr = "&tr=".join(urllib.parse.quote(t) for t in TRACKERS)
        return f"magnet:?xt=urn:btih:{info_hash}&dn={dn}&tr={tr}"

    def _map_category(self, cat_code: str) -> str:
        first_digit = str(cat_code)[0] if cat_code else "6"
        return CATEGORY_MAP.get(first_digit, "other")

    def _parse_items(self, rows: List[Dict[str, Any]], limit: int = 50) -> List[TorrentItem]:
        items: List[TorrentItem] = []
        for row in rows:
            if row.get("id") == "0" or not row.get("info_hash"):
                continue

            name = row.get("name", "Unknown Torrent")
            info_hash = row.get("info_hash", "").lower()
            seeders = int(row.get("seeders") or 0)
            leechers = int(row.get("leechers") or 0)
            size_bytes = int(row.get("size") or 0)
            uploader = row.get("username")
            cat_code = str(row.get("category", "600"))

            added = row.get("added")
            date_str = None
            if added and str(added).isdigit():
                try:
                    date_str = datetime.datetime.fromtimestamp(int(added)).strftime("%Y-%m-%d")
                except Exception:
                    pass

            item = TorrentItem(
                id=info_hash,
                title=name,
                info_hash=info_hash,
                magnet_uri=self._build_magnet(info_hash, name),
                size_bytes=size_bytes,
                size_formatted=format_bytes(size_bytes),
                seeders=seeders,
                leechers=leechers,
                category=self._map_category(cat_code),
                upload_date=date_str,
                uploader=uploader,
                provider=self.name,
                sources=[self.name],
                details_url=f"https://thepiratebay.org/description.php?id={row.get('id')}",
                metadata=parse_release_title(name),
            )
            items.append(item)
            if len(items) >= limit:
                break
        return items

    async def _do_search(self, query: str, limit: int = 50, **kwargs) -> List[TorrentItem]:
        endpoint = f"{self.base_url}/q.php"
        params = {"q": query, "cat": 0}
        data = await http_client.get_json(endpoint, params=params)
        if not isinstance(data, list):
            return []
        return self._parse_items(data, limit=limit)

    async def trending(self, limit: int = 50, **kwargs) -> List[TorrentItem]:
        if not await self.circuit_breaker.can_execute():
            return []
        try:
            endpoint = f"{self.base_url}/precompiled/data_top100_all.json"
            data = await http_client.get_json(endpoint)
            if not isinstance(data, list):
                return []
            return self._parse_items(data, limit=limit)
        except Exception as e:
            await self.circuit_breaker.record_failure(str(e))
            return []
