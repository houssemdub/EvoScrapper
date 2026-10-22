import html
import re
from typing import Any, Dict, List
from core.client import http_client
from core.title_parser import parse_release_title
from models.torrent import TorrentItem
from providers.base import BaseProvider


class BluDVProvider(BaseProvider):
    """
    WordPress REST API Provider for BluDV Portuguese releases.
    Extracts magnet links grouped by resolution and audio streams.
    """

    def __init__(self):
        super().__init__(
            name="bludv",
            provider_type="torrent",
            base_urls=[
                "https://bludv.net",
                "https://bludvfilmes.com",
            ],
        )

    def _clean_title(self, raw: str) -> str:
        unescaped = html.unescape(raw)
        return re.sub(r"<[^>]+>", "", unescaped).strip()

    async def _do_search(self, query: str, limit: int = 50, **kwargs) -> List[TorrentItem]:
        endpoint = f"{self.base_url}/wp-json/wp/v2/posts"
        params = {"search": query, "per_page": min(limit, 20)}
        # Use stealth curl_cffi for BluDV as it can enforce Cloudflare
        posts = await http_client.get_json(endpoint, params=params, use_stealth=True)

        if not isinstance(posts, list):
            return []

        items: List[TorrentItem] = []
        for post in posts:
            title = self._clean_title(post.get("title", {}).get("rendered", "Unknown Release"))
            content = post.get("content", {}).get("rendered", "")
            date_uploaded = post.get("date")

            magnets = re.findall(r'href="(magnet:\?[^"]+)"', content)
            if not magnets:
                magnets = re.findall(r'magnet:\?xt=urn:btih:[a-zA-Z0-9]+[^"\'\s<]*', content)

            for idx, magnet in enumerate(magnets):
                info_hash = ""
                if "xt=urn:btih:" in magnet:
                    raw_hash = magnet.split("xt=urn:btih:")[1].split("&")[0]
                    info_hash = raw_hash.lower()

                sub_title = f"{title} (Version {idx+1})" if len(magnets) > 1 else title

                item = TorrentItem(
                    id=info_hash or f"{post.get('id')}_{idx}",
                    title=sub_title,
                    info_hash=info_hash if info_hash else None,
                    magnet_uri=magnet,
                    size_bytes=0,
                    size_formatted="Unknown",
                    seeders=15,
                    leechers=1,
                    category="movies",
                    upload_date=date_uploaded,
                    uploader="BluDV",
                    provider=self.name,
                    sources=[self.name],
                    details_url=post.get("link"),
                    metadata=parse_release_title(sub_title),
                )
                items.append(item)
                if len(items) >= limit:
                    break

            if len(items) >= limit:
                break

        return items
