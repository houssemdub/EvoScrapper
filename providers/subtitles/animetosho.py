import asyncio
from typing import Any, Dict, List, Optional
from core.client import http_client
from models.subtitle import SubtitleItem
from providers.base import BaseProvider


class AnimeToshoProvider(BaseProvider):
    """
    AnimeTosho Provider for softsub demuxing directly from anime torrents.
    Maps Nyaa/TokyoTosho SHA1 infoHashes or titles to extracted .ass/.srt subtitle files.
    """

    def __init__(self):
        super().__init__(
            name="animetosho",
            provider_type="subtitle",
            base_urls=["https://animetosho.org"],
        )

    async def get_by_torrent_hash(self, info_hash: str) -> List[SubtitleItem]:
        """Looks up extracted subtitles matching a specific BitTorrent infoHash."""
        if not info_hash or len(info_hash) < 32:
            return []

        endpoint = f"{self.base_url}/json"
        params = {"show": "torrent", "btih": info_hash.lower()}
        try:
            data = await http_client.get_json(endpoint, params=params)
        except Exception:
            return []

        if not isinstance(data, dict):
            return []

        items: List[SubtitleItem] = []
        files = data.get("files") or []

        for f in files:
            subtitles = f.get("subtitles") or []
            for idx, s in enumerate(subtitles):
                lang = s.get("lang_name") or s.get("lang") or "Japanese"
                url = s.get("url") or ""
                if not url:
                    continue

                fmt = "ass" if ".ass" in url.lower() else "srt"

                item = SubtitleItem(
                    id=f"atosho_{info_hash[:8]}_{idx}",
                    provider=self.name,
                    language=lang,
                    lang_code=s.get("lang_code", lang[:3].lower()),
                    format=fmt,
                    download_url=url,
                    release_name=f.get("name"),
                    is_hearing_impaired=False,
                    rating=None,
                    downloads_count=None,
                    season=None,
                    episode=None,
                    fps=None,
                )
                items.append(item)

        return items

    async def _do_search(
        self,
        query: str,
        info_hash: Optional[str] = None,
        limit: int = 50,
        **kwargs,
    ) -> List[SubtitleItem]:
        if info_hash:
            return await self.get_by_torrent_hash(info_hash)

        if not query:
            return []

        endpoint = f"{self.base_url}/json"
        params = {"t": "search", "q": query}
        try:
            data = await http_client.get_json(endpoint, params=params)
        except Exception:
            return []

        if not isinstance(data, list):
            return []

        hashes = [entry.get("btih") for entry in data if entry.get("btih")]
        if not hashes:
            return []

        # Gather subtitle results in parallel bounded by semaphore to prevent sequential blocking loop
        sem = asyncio.Semaphore(5)

        async def _bounded_lookup(h: str):
            async with sem:
                return await self.get_by_torrent_hash(h)

        tasks = [_bounded_lookup(h) for h in hashes[:min(limit, 10)]]
        batches = await asyncio.gather(*tasks, return_exceptions=True)

        items: List[SubtitleItem] = []
        for b in batches:
            if isinstance(b, list):
                items.extend(b)
                if len(items) >= limit:
                    break

        return items[:limit]
