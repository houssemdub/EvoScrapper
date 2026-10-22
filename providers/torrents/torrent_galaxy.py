import asyncio
import re
from typing import List, Optional
from bs4 import BeautifulSoup
from core.client import http_client
from core.title_parser import parse_release_title, parse_size_str
from models.torrent import TorrentItem
from providers.base import BaseProvider


class TorrentGalaxyProvider(BaseProvider):
    """
    TorrentGalaxy DOM Scraper with Cloudflare stealth and mirror rotation.
    Queries /get-posts/?keywords= and resolves magnets from post details in parallel.
    """

    def __init__(self):
        super().__init__(
            name="torrentgalaxy",
            provider_type="torrent",
            base_urls=[
                "https://torrentgalaxy.one",
                "https://torrentgalaxy.buzz",
                "https://torrentgalaxy.info",
            ],
        )

    async def _fetch_magnet(self, detail_url: str) -> Optional[str]:
        try:
            html = await http_client.get_text(detail_url, use_stealth=True, timeout=4.0)
            soup = BeautifulSoup(html, "html.parser")
            magnet_a = soup.find("a", href=lambda h: bool(h and h.startswith("magnet:")))
            return magnet_a["href"] if magnet_a else None
        except Exception:
            return None

    async def _do_search(self, query: str, limit: int = 50, **kwargs) -> List[TorrentItem]:
        endpoint = f"{self.base_url}/get-posts/"
        params = {"keywords": query}
        html_text = await http_client.get_text(endpoint, params=params, use_stealth=True)

        soup = BeautifulSoup(html_text, "html.parser")
        rows = soup.select("div.tgxtablerow")
        if not rows:
            return []

        candidates = []
        for row in rows:
            title_a = row.find("a", class_="txlight")
            if not title_a:
                continue

            title = title_a.text.strip()
            href = title_a.get("href")
            if not href:
                continue

            details_url = f"{self.base_url}{href}" if href.startswith("/") else href

            # Category
            cat_elem = row.find("small")
            cat_raw = cat_elem.text.strip().lower() if cat_elem else "movies"
            category = "movies"
            if "tv" in cat_raw:
                category = "tv"
            elif "anime" in cat_raw:
                category = "anime"
            elif "game" in cat_raw:
                category = "games"
            elif "app" in cat_raw:
                category = "apps"
            elif "book" in cat_raw:
                category = "books"

            # Size
            size_badge = row.find("span", class_="badge-secondary") or row.find("span", class_="badge")
            size_formatted = size_badge.text.strip().replace("\xa0", " ") if size_badge else "Unknown"
            size_bytes = parse_size_str(size_formatted)

            # Seeders & Leechers
            seeds_font = row.find("font", color="green")
            seeders = int(seeds_font.text.strip()) if seeds_font and seeds_font.text.strip().isdigit() else 0

            leech_font = row.find("font", color="#ff0000") or row.find("font", color="red")
            leechers = int(leech_font.text.strip()) if leech_font and leech_font.text.strip().isdigit() else 0

            # Check for direct magnet link in row (avoids secondary N+1 HTTP calls)
            magnet_a = row.find("a", href=lambda h: bool(h and h.startswith("magnet:")))
            direct_magnet = magnet_a["href"] if magnet_a else None

            candidates.append({
                "title": title,
                "details_url": details_url,
                "category": category,
                "size_formatted": size_formatted,
                "size_bytes": size_bytes,
                "seeders": seeders,
                "leechers": leechers,
                "magnet": direct_magnet,
            })
            if len(candidates) >= min(limit, 20):
                break

        if not candidates:
            return []

        # Only fetch details pages if magnet was not present in the table row
        missing_magnets = [c for c in candidates if not c.get("magnet")]
        if missing_magnets:
            tasks = [self._fetch_magnet(c["details_url"]) for c in missing_magnets]
            fetched = await asyncio.gather(*tasks, return_exceptions=True)
            for c, mag in zip(missing_magnets, fetched):
                if isinstance(mag, str) and mag.startswith("magnet:"):
                    c["magnet"] = mag

        items: List[TorrentItem] = []
        for cand in candidates:
            mag = cand.get("magnet")
            if not isinstance(mag, str) or not mag.startswith("magnet:"):
                continue

            info_hash = ""
            if "xt=urn:btih:" in mag:
                info_hash = mag.split("xt=urn:btih:")[1].split("&")[0].lower()

            items.append(
                TorrentItem(
                    id=info_hash or cand["title"],
                    title=cand["title"],
                    info_hash=info_hash if info_hash else None,
                    magnet_uri=mag,
                    size_bytes=cand["size_bytes"],
                    size_formatted=cand["size_formatted"],
                    seeders=cand["seeders"],
                    leechers=cand["leechers"],
                    category=cand["category"],
                    upload_date=None,
                    uploader="TGx",
                    provider=self.name,
                    sources=[self.name],
                    details_url=cand["details_url"],
                    metadata=parse_release_title(cand["title"]),
                )
            )

        return items
