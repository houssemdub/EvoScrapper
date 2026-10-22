import re
import urllib.parse
from typing import List
from bs4 import BeautifulSoup
from core.client import http_client
from core.title_parser import parse_release_title, parse_size_str
from models.torrent import TorrentItem
from providers.base import BaseProvider


class RutorProvider(BaseProvider):
    """
    1-Step Search Table Scraper for Rutor.
    Magnet link, seeders, leechers, and size are extracted in a single request.
    """

    def __init__(self):
        super().__init__(
            name="rutor",
            provider_type="torrent",
            base_urls=["http://rutor.info", "http://rutor.is"],
        )

    async def _do_search(self, query: str, limit: int = 50, **kwargs) -> List[TorrentItem]:
        clean_q = urllib.parse.quote(query)
        endpoint = f"{self.base_url}/search/0/0/000/0/{clean_q}"
        html_text = await http_client.get_text(endpoint)

        soup = BeautifulSoup(html_text, "html.parser")
        table = soup.select_one("div#index table") or soup.select_one("div#index")
        if not table:
            return []

        rows = table.find_all("tr")
        items: List[TorrentItem] = []

        for tr in rows:
            tds = tr.find_all("td")
            if len(tds) < 4:
                continue

            date_str = tds[0].text.strip()
            title_td = tds[1]

            # Find detail link and magnet link
            magnet_el = title_td.find("a", href=lambda h: bool(h and h.startswith("magnet:")))
            if not magnet_el:
                continue

            magnet_uri = magnet_el["href"]
            info_hash = ""
            if "xt=urn:btih:" in magnet_uri:
                info_hash = magnet_uri.split("xt=urn:btih:")[1].split("&")[0].lower()

            # Find title text
            detail_links = [a for a in title_td.find_all("a") if not a["href"].startswith("magnet:")]
            title = detail_links[-1].text.strip() if detail_links else "Unknown Release"
            details_url = f"{self.base_url}{detail_links[-1]['href']}" if detail_links else None

            # Size is usually in second-to-last or 3rd td
            size_formatted = tds[-2].text.strip().replace("\xa0", " ")
            size_bytes = parse_size_str(size_formatted)

            # Seeders & Leechers are in last td
            peers_td = tds[-1]
            seeds_span = peers_td.find("span", class_="green")
            seeders = int(seeds_span.text.strip()) if seeds_span and seeds_span.text.strip().isdigit() else 0

            leech_span = peers_td.find("span", class_="red")
            leechers = int(leech_span.text.strip()) if leech_span and leech_span.text.strip().isdigit() else 0

            item = TorrentItem(
                id=info_hash or title,
                title=title,
                info_hash=info_hash if info_hash else None,
                magnet_uri=magnet_uri,
                size_bytes=size_bytes,
                size_formatted=size_formatted,
                seeders=seeders,
                leechers=leechers,
                category="general",
                upload_date=date_str,
                uploader="Rutor",
                provider=self.name,
                sources=[self.name],
                details_url=details_url,
                metadata=parse_release_title(title),
            )
            items.append(item)
            if len(items) >= limit:
                break

        return items
