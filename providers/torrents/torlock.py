import asyncio
import base64
import re
import urllib.parse
from typing import List, Optional, Tuple
from bs4 import BeautifulSoup
from core.client import http_client
from core.title_parser import parse_release_title, parse_size_str
from models.torrent import TorrentItem
from providers.base import BaseProvider


def _extract_hash_and_magnet(details_html: str, default_title: str) -> Tuple[Optional[str], Optional[str]]:
    soup = BeautifulSoup(details_html, "html.parser")
    magnet_a = soup.find("a", href=lambda h: bool(h and h.startswith("magnet:")))
    magnet_uri = magnet_a["href"] if magnet_a else None
    info_hash = None
    if magnet_uri:
        m = re.search(r"xt=urn:btih:([a-zA-Z0-9]{32,40})", magnet_uri, re.IGNORECASE)
        if m:
            raw_hash = m.group(1).lower()
            if len(raw_hash) == 40:
                info_hash = raw_hash
            elif len(raw_hash) == 32:
                try:
                    info_hash = base64.b32decode(raw_hash.upper()).hex().lower()
                except Exception:
                    info_hash = raw_hash

    if not info_hash:
        hash_match = re.search(r"\b([0-9a-fA-F]{40})\b", details_html)
        if hash_match:
            info_hash = hash_match.group(1).lower()
            if not magnet_uri:
                clean_dn = urllib.parse.quote(default_title)
                magnet_uri = f"magnet:?xt=urn:btih:{info_hash}&dn={clean_dn}"

    return info_hash, magnet_uri


class TorlockProvider(BaseProvider):
    """
    Torlock verified torrents provider.
    Parses verified table rows, resolves true BitTorrent infoHashes and magnets.
    """

    def __init__(self):
        super().__init__(
            name="torlock",
            provider_type="torrent",
            base_urls=["https://www.torlock.com", "https://www.torlock2.com"],
        )
        self._semaphore = asyncio.Semaphore(5)

    async def _fetch_details(self, details_url: str, title: str) -> Tuple[Optional[str], Optional[str]]:
        async with self._semaphore:
            try:
                html = await http_client.get_text(details_url, timeout=6.0)
                return _extract_hash_and_magnet(html, title)
            except Exception:
                return None, None

    async def _do_search(self, query: str, limit: int = 50, **kwargs) -> List[TorrentItem]:
        clean_q = query.replace(" ", "-").lower()
        endpoint = f"{self.base_url}/all/torrents/{clean_q}.html"
        html_text = await http_client.get_text(endpoint)

        soup = BeautifulSoup(html_text, "html.parser")
        rows = soup.select("table.table-striped tr")
        candidates = []

        for tr in rows:
            tds = tr.find_all("td")
            if len(tds) < 5:
                continue

            links = tds[0].find_all("a")
            if len(links) < 2:
                continue

            title_a = links[1]
            title = title_a.text.strip()
            href = title_a.get("href", "")
            if not href.startswith("/torrent/"):
                continue

            # In torlock, href is like /torrent/123456/title.html
            parts = href.strip("/").split("/")
            torrent_id = parts[1] if len(parts) > 1 else href

            size_formatted = tds[2].text.strip()
            size_bytes = parse_size_str(size_formatted)

            seeds_text = tds[3].text.strip()
            seeders = int(seeds_text) if seeds_text.isdigit() else 0

            leech_text = tds[4].text.strip()
            leechers = int(leech_text) if leech_text.isdigit() else 0

            details_url = f"{self.base_url}{href}"

            candidates.append({
                "id": torrent_id,
                "title": title,
                "details_url": details_url,
                "seeds": seeders,
                "leeches": leechers,
                "size_formatted": size_formatted,
                "size_bytes": size_bytes,
            })
            if len(candidates) >= limit:
                break

        tasks = [self._fetch_details(c["details_url"], c["title"]) for c in candidates]
        resolved = await asyncio.gather(*tasks, return_exceptions=True)

        items: List[TorrentItem] = []
        for c, res in zip(candidates, resolved):
            info_hash = None
            magnet_uri = None
            if isinstance(res, tuple) and res[0]:
                info_hash, magnet_uri = res

            effective_id = info_hash or c["id"]
            effective_magnet = magnet_uri or f"magnet:?xt=urn:btih:{c['id']}&dn={urllib.parse.quote(c['title'])}"

            item = TorrentItem(
                id=effective_id,
                title=c["title"],
                info_hash=info_hash,
                magnet_uri=effective_magnet,
                size_bytes=c["size_bytes"],
                size_formatted=c["size_formatted"],
                seeders=c["seeds"],
                leechers=c["leeches"],
                category="general",
                upload_date=None,
                uploader="Torlock",
                provider=self.name,
                sources=[self.name],
                details_url=c["details_url"],
                metadata=parse_release_title(c["title"]),
            )
            items.append(item)

        return items
