import urllib.parse
from typing import Any, Dict, List, Optional
from core.client import http_client
from models.subtitle import SubtitleItem
from providers.base import BaseProvider


class GestdownProvider(BaseProvider):
    """
    Gestdown Provider (Addic7ed Zero-Auth Proxy) for TV series subtitles.
    Maps show names to TVDB identifiers and retrieves synchronized episode subtitles.
    """

    def __init__(self):
        super().__init__(
            name="gestdown",
            provider_type="subtitle",
            base_urls=["https://api.gestdown.info"],
        )

    async def _do_search(
        self,
        query: str,
        season: Optional[int] = None,
        episode: Optional[int] = None,
        language: str = "en",
        limit: int = 50,
        **kwargs,
    ) -> List[SubtitleItem]:
        if not query:
            return []

        # 1. Search for the show to get its internal show UUID
        clean_q = urllib.parse.quote(query)
        search_endpoint = f"{self.base_url}/shows/search/{clean_q}"
        search_res = await http_client.get_json(search_endpoint)
        shows = search_res.get("shows") or []
        if not shows:
            return []

        show_id = shows[0].get("id")
        show_name = shows[0].get("name")
        if not show_id:
            return []

        # Default to S1 E1 if no season/episode specified
        s = season or 1
        e = episode or 1

        # 2. Query subtitles for the target episode
        target_lang = "en" if (not language or language.lower() in ("all", "any", "*")) else language.lower()
        ep_endpoint = f"{self.base_url}/subtitles/get/{show_id}/{s}/{e}/{target_lang}"
        ep_res = await http_client.get_json(ep_endpoint)
        matching = ep_res.get("matchingSubtitles") or []

        items: List[SubtitleItem] = []
        for idx, sub in enumerate(matching):
            download_uri = sub.get("downloadUri") or ""
            if download_uri.startswith("/"):
                download_url = f"{self.base_url}{download_uri}"
            else:
                download_url = download_uri

            version = sub.get("version") or f"Release {idx+1}"
            sub_id = download_uri.split("/")[-1] if "/" in download_uri else str(idx)

            item = SubtitleItem(
                id=f"gestdown_{sub_id}",
                provider=self.name,
                language=language.upper(),
                lang_code=language.lower(),
                format="srt",
                download_url=download_url,
                release_name=f"{show_name} S{s:02d}E{e:02d} - {version}",
                is_hearing_impaired=bool(sub.get("hearingImpaired", False)),
                rating=None,
                downloads_count=None,
                season=s,
                episode=e,
                fps=None,
            )
            items.append(item)
            if len(items) >= limit:
                break

        return items
