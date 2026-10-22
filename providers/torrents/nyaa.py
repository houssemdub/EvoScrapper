import urllib.parse
import xml.etree.ElementTree as ET
from typing import List
from core.client import http_client
from core.title_parser import parse_release_title, parse_size_str
from models.torrent import TorrentItem
from providers.base import BaseProvider


TRACKERS = [
    "http://nyaa.tracker.wf:7777/announce",
    "udp://open.stealth.si:80/announce",
    "udp://tracker.opentrackr.org:1337/announce",
    "udp://exodus.desync.com:6969/announce",
]

NYAA_NS = {"nyaa": "https://nyaa.si/xmlns/nyaa"}


class NyaaProvider(BaseProvider):
    """
    High-speed Nyaa.si provider utilizing structured RSS XML feed.
    Directly extracts official <nyaa:infoHash>, seeders, and sizes.
    """

    BASE_URL = "https://nyaa.si"
    TRUSTED_GROUPS = {
        "subsplease", "erai-raws", "judas", "ember", "asw", "kametsu",
        "commie", "horriblesubs", "bluray", "doki", "nep", "scy"
    }

    def __init__(self):
        super().__init__(
            name="nyaa",
            provider_type="torrent",
            base_urls=["https://nyaa.si", "https://nyaa.land"],
        )

    def _build_magnet(self, info_hash: str, title: str) -> str:
        dn = urllib.parse.quote(title)
        tr = "&tr=".join(urllib.parse.quote(t) for t in TRACKERS)
        return f"magnet:?xt=urn:btih:{info_hash}&dn={dn}&tr={tr}"

    async def _do_search(self, query: str, limit: int = 50, **kwargs) -> List[TorrentItem]:
        endpoint = f"{self.base_url}/"
        params = {"page": "rss", "q": query, "c": "0_0", "f": "0"}
        xml_text = await http_client.get_text(endpoint, params=params)

        root = ET.fromstring(xml_text)
        channel = root.find("channel")
        if channel is None:
            return []

        items: List[TorrentItem] = []
        for it in channel.findall("item"):
            title_el = it.find("title")
            title = title_el.text if title_el is not None and title_el.text else "Unknown Anime Release"

            hash_el = it.find("nyaa:infoHash", NYAA_NS)
            info_hash = (hash_el.text or "").lower() if hash_el is not None else ""

            # If infoHash tag wasn't present, check guid or link
            if not info_hash:
                link_el = it.find("link")
                if link_el is not None and link_el.text and "magnet:?xt=urn:btih:" in link_el.text:
                    info_hash = link_el.text.split("magnet:?xt=urn:btih:")[1][:40].lower()

            if not info_hash:
                continue

            seeds_el = it.find("nyaa:seeders", NYAA_NS)
            seeders = int(seeds_el.text) if seeds_el is not None and seeds_el.text else 0

            leech_el = it.find("nyaa:leechers", NYAA_NS)
            leechers = int(leech_el.text) if leech_el is not None and leech_el.text else 0

            size_el = it.find("nyaa:size", NYAA_NS)
            size_formatted = size_el.text if size_el is not None and size_el.text else "Unknown"
            size_bytes = parse_size_str(size_formatted)

            pub_el = it.find("pubDate")
            upload_date = pub_el.text if pub_el is not None else None

            guid_el = it.find("guid")
            details_url = guid_el.text if guid_el is not None else None

            magnet = self._build_magnet(info_hash, title)

            item = TorrentItem(
                id=info_hash,
                title=title,
                info_hash=info_hash,
                magnet_uri=magnet,
                size_bytes=size_bytes,
                size_formatted=size_formatted,
                seeders=seeders,
                leechers=leechers,
                category="anime",
                upload_date=upload_date,
                uploader="Nyaa",
                provider=self.name,
                sources=[self.name],
                details_url=details_url,
                metadata=parse_release_title(title),
            )
            items.append(item)
            if len(items) >= limit:
                break

        return items

    async def trending(self, limit: int = 50, **kwargs) -> List[TorrentItem]:
        if not await self.circuit_breaker.can_execute():
            return []
        try:
            endpoint = f"{self.base_url}/"
            params = {"page": "rss", "q": "", "c": "0_0", "f": "0", "s": "seeders", "o": "desc"}
            xml_text = await http_client.get_text(endpoint, params=params)
            root = ET.fromstring(xml_text)
            channel = root.find("channel")
            if channel is None:
                return []
            items: List[TorrentItem] = []
            for it in channel.findall("item"):
                title_el = it.find("title")
                title = title_el.text if title_el is not None and title_el.text else "Unknown Anime Release"
                hash_el = it.find("nyaa:infoHash", NYAA_NS)
                info_hash = (hash_el.text or "").lower() if hash_el is not None else ""
                if not info_hash:
                    link_el = it.find("link")
                    if link_el is not None and link_el.text and "magnet:?xt=urn:btih:" in link_el.text:
                        info_hash = link_el.text.split("magnet:?xt=urn:btih:")[1][:40].lower()
                if not info_hash:
                    continue
                seeds_el = it.find("nyaa:seeders", NYAA_NS)
                seeders = int(seeds_el.text) if seeds_el is not None and seeds_el.text else 0
                leech_el = it.find("nyaa:leechers", NYAA_NS)
                leechers = int(leech_el.text) if leech_el is not None and leech_el.text else 0
                size_el = it.find("nyaa:size", NYAA_NS)
                size_formatted = size_el.text if size_el is not None and size_el.text else "Unknown"
                size_bytes = parse_size_str(size_formatted)
                pub_el = it.find("pubDate")
                upload_date = pub_el.text if pub_el is not None else None
                guid_el = it.find("guid")
                details_url = guid_el.text if guid_el is not None else None
                magnet = self._build_magnet(info_hash, title)
                item = TorrentItem(
                    id=info_hash,
                    title=title,
                    info_hash=info_hash,
                    magnet_uri=magnet,
                    size_bytes=size_bytes,
                    size_formatted=size_formatted,
                    seeders=seeders,
                    leechers=leechers,
                    category="anime",
                    upload_date=upload_date,
                    uploader="Nyaa",
                    provider=self.name,
                    sources=[self.name],
                    details_url=details_url,
                    metadata=parse_release_title(title),
                )
                items.append(item)
                if len(items) >= limit:
                    break
            return items
        except Exception as e:
            await self.circuit_breaker.record_failure(str(e))
            return []

