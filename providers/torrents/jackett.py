"""
T4.5: Jackett / Prowlarr Torznab passthrough provider.

Queries a user-hosted Jackett or Prowlarr instance through its Torznab
compatibility API, unlocking private and specialized trackers. Only registered
in the provider registry when JACKETT_URL is configured.
"""
import datetime
import xml.etree.ElementTree as ET
from typing import Any, Dict, List, Optional
from urllib.parse import urlencode

from core.client import http_client
from core.title_parser import format_bytes, parse_release_title
from models.torrent import TorrentItem
from providers.base import BaseProvider


def _torznab_attr(item: ET.Element, name: str) -> Optional[str]:
    for attr in item.findall("attr"):
        if (attr.get("name") or "").lower() == name:
            return attr.get("value")
    return None


class JackettProvider(BaseProvider):
    """
    Torznab passthrough to a local Jackett/Prowlarr aggregate endpoint.
    """

    def __init__(self, base_url: str = "", api_key: str = ""):
        super().__init__(
            name="jackett",
            provider_type="torrent",
            base_urls=[(base_url or "").rstrip("/") or "http://127.0.0.1:9117"],
        )
        self.api_key = api_key

    @property
    def is_configured(self) -> bool:  # type: ignore[override]
        return bool(self.base_urls[0] and self.api_key)

    def _parse_response(self, xml_text: str, limit: int) -> List[TorrentItem]:
        items: List[TorrentItem] = []
        root = ET.fromstring(xml_text)
        channel = root.find("channel")
        if channel is None:
            return items
        for element in channel.findall("item"):
            if len(items) >= limit:
                break
            info_hash = (_torznab_attr(element, "infohash") or "").strip().lower()
            title = element.findtext("title") or "Unknown Jackett Release"
            if not info_hash:
                # Without a hash we cannot stream via the P2P engine; skip.
                continue
            seeders = int(_torznab_attr(element, "seeders") or 0)
            peers = int(_torznab_attr(element, "peers") or 0)
            size_bytes = int(_torznab_attr(element, "size") or 0)
            link = element.findtext("link") or ""
            magnet = element.findtext("guid") or ""
            if not magnet.startswith("magnet:"):
                magnet = f"magnet:?xt=urn:btih:{info_hash}"
            pub_date = element.findtext("pubDate") or ""
            upload_date = None
            if pub_date:
                try:
                    upload_date = datetime.datetime.strptime(
                        pub_date, "%a, %d %b %Y %H:%M:%S %z"
                    ).strftime("%Y-%m-%d")
                except ValueError:
                    upload_date = None

            parsed = parse_release_title(title)
            items.append(TorrentItem(
                id=info_hash,
                title=title,
                info_hash=info_hash,
                magnet_uri=magnet,
                size_bytes=size_bytes,
                size_formatted=format_bytes(size_bytes),
                seeders=seeders,
                leechers=peers,
                category="movie" if parsed.resolution else "general",
                upload_date=upload_date,
                provider="jackett",
                sources=[link] if link else [],
                details_url=element.findtext("comments") or None,
            ))
        return items

    async def _do_search(self, query: str, **kwargs) -> List[TorrentItem]:
        if not self.is_configured:
            return []
        limit = int(kwargs.get("limit") or 50)
        params = urlencode({
            "apikey": self.api_key,
            "t": "search",
            "q": query,
            "limit": str(limit),
        })
        endpoint = f"{self.base_url}/api/v2.0/indexers/all/results/torznab/api?{params}"
        xml_text = await http_client.get_text(endpoint, timeout=15.0)
        return self._parse_response(xml_text, limit)
