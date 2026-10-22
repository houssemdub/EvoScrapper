import base64
import re
import xml.etree.ElementTree as ET
from typing import List
from core.client import http_client
from core.title_parser import parse_release_title, parse_size_str
from models.torrent import TorrentItem
from providers.base import BaseProvider


class TokyoToshoProvider(BaseProvider):
    """
    Anime RSS provider using TokyoTosho RSS XML feed.
    Extracts base32/hex magnet hashes and size descriptors.
    """

    def __init__(self):
        super().__init__(
            name="tokyotosho",
            provider_type="torrent",
            base_urls=["https://www.tokyotosho.info"],
        )

    def _normalize_hash(self, raw_hash: str) -> str:
        """Converts 32-char Base32 hashes into 40-char SHA1 hex if needed."""
        raw_hash = raw_hash.strip()
        if len(raw_hash) == 32:
            try:
                return base64.b32decode(raw_hash.upper()).hex().lower()
            except Exception:
                pass
        return raw_hash.lower()

    async def _do_search(self, query: str, limit: int = 50, **kwargs) -> List[TorrentItem]:
        endpoint = f"{self.base_url}/rss.php"
        params = {"terms": query, "type": 1}
        xml_text = await http_client.get_text(endpoint, params=params)

        root = ET.fromstring(xml_text)
        channel = root.find("channel")
        if channel is None:
            return []

        items: List[TorrentItem] = []
        for it in channel.findall("item"):
            title_el = it.find("title")
            title = title_el.text if title_el is not None and title_el.text else "Unknown Anime Release"

            desc_el = it.find("description")
            desc_text = desc_el.text if desc_el is not None and desc_el.text else ""

            # Extract magnet link from description
            magnet_match = re.search(r'href="(magnet:\?[^"]+)"', desc_text)
            magnet_uri = magnet_match.group(1) if magnet_match else ""

            # Extract hash
            info_hash = ""
            if "xt=urn:btih:" in magnet_uri:
                raw_hash = magnet_uri.split("xt=urn:btih:")[1].split("&")[0]
                info_hash = self._normalize_hash(raw_hash)

            # If no magnet found, check <link>
            if not magnet_uri:
                link_el = it.find("link")
                link_text = link_el.text if link_el is not None else ""
                if link_text and "magnet:" in link_text:
                    magnet_uri = link_text
                    raw_hash = magnet_uri.split("xt=urn:btih:")[1].split("&")[0]
                    info_hash = self._normalize_hash(raw_hash)

            if not info_hash and not magnet_uri:
                continue

            # Extract size from description: "Size: 34.28MB"
            size_match = re.search(r"Size:\s*([\d.]+\s*[a-zA-Z]+)", desc_text)
            size_formatted = size_match.group(1) if size_match else "Unknown"
            size_bytes = parse_size_str(size_formatted)

            pub_el = it.find("pubDate")
            upload_date = pub_el.text if pub_el is not None else None

            # Details URL
            details_match = re.search(r'href="(https://www\.tokyotosho\.info/details\.php\?id=\d+)"', desc_text)
            details_url = details_match.group(1) if details_match else None

            item = TorrentItem(
                id=info_hash or title,
                title=title,
                info_hash=info_hash if info_hash else None,
                magnet_uri=magnet_uri,
                size_bytes=size_bytes,
                size_formatted=size_formatted,
                seeders=0,  # TokyoTosho RSS does not report real-time live seeders
                leechers=0,
                category="anime",
                upload_date=upload_date,
                uploader="TokyoTosho",
                provider=self.name,
                sources=[self.name],
                details_url=details_url,
                metadata=parse_release_title(title),
            )
            items.append(item)
            if len(items) >= limit:
                break

        return items
