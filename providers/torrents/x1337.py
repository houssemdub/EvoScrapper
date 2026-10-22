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


class X1337Provider(BaseProvider):
    """
    1337x provider with stealth TLS session and mirror rotation.
    Scrapes search listings and resolves true BitTorrent infoHashes and magnets.
    """

    def __init__(self):
        super().__init__(
            name="1337x",
            provider_type="torrent",
            base_urls=[
                "https://1337x.to",
                "https://1337x.st",
                "https://1337x.ws",
                "https://1377x.to",
            ],
        )
        self._semaphore = asyncio.Semaphore(5)

    async def _fetch_details(self, details_url: str, title: str) -> Tuple[Optional[str], Optional[str]]:
        async with self._semaphore:
            try:
                html = await http_client.get_text(details_url, use_stealth=True, timeout=6.0)
                return _extract_hash_and_magnet(html, title)
            except Exception:
                return None, None

    async def _do_search(self, query: str, limit: int = 50, **kwargs) -> List[TorrentItem]:
        endpoint = f"{self.base_url}/sort-search/{query}/seeders/desc/1/"
        html_text = await http_client.get_text(endpoint, use_stealth=True)

        # Handle JS redirect challenge if present
        js_match = re.search(r"window\.location\.replace\('([^']+)'\)", html_text)
        if js_match:
            redir_url = js_match.group(1)
            html_text = await http_client.get_text(redir_url, use_stealth=True)

        soup = BeautifulSoup(html_text, "html.parser")
        rows = soup.select("table.table-list tr")
        candidates = []

        for tr in rows[1:]:
            tds = tr.find_all("td")
            if len(tds) < 5:
                continue

            links = tds[0].find_all("a")
            if not links:
                continue

            title_a = links[-1]
            title = title_a.text.strip()
            href = title_a.get("href", "")

            # Seeds and Leeches
            seeds_text = tds[1].text.strip()
            seeders = int(seeds_text) if seeds_text.isdigit() else 0

            leech_text = tds[2].text.strip()
            leechers = int(leech_text) if leech_text.isdigit() else 0

            # Size
            size_formatted = tds[4].text.strip()
            size_clean = re.sub(r"[^\d.\sA-Za-z]", "", size_formatted).strip()
            size_bytes = parse_size_str(size_clean)

            # Extract torrent ID from /torrent/12345/slug/
            id_match = re.search(r"/torrent/(\d+)/", href)
            torrent_id = id_match.group(1) if id_match else href

            details_url = f"{self.base_url}{href}" if href.startswith("/") else href

            candidates.append({
                "id": torrent_id,
                "title": title,
                "details_url": details_url,
                "seeds": seeders,
                "leeches": leechers,
                "size_clean": size_clean,
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
                size_formatted=c["size_clean"],
                seeders=c["seeds"],
                leechers=c["leeches"],
                category="general",
                upload_date=None,
                uploader="1337x",
                provider=self.name,
                sources=[self.name],
                details_url=c["details_url"],
                metadata=parse_release_title(c["title"]),
            )
            items.append(item)

        return items
