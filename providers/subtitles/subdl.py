from typing import Any, Dict, List, Optional
from config import settings
from core.client import http_client
from models.subtitle import SubtitleItem
from providers.base import BaseProvider


class SubdlProvider(BaseProvider):
    """
    SubDL v1 API Provider.
    Supports full season pack inspection and unpacked individual .srt links.
    """

    def __init__(self):
        super().__init__(
            name="subdl",
            provider_type="subtitle",
            base_urls=["https://api.subdl.com"],
        )

    async def _do_search(
        self,
        query: str = "",
        imdb_id: Optional[str] = None,
        languages: str = "EN",
        limit: int = 50,
        **kwargs,
    ) -> List[SubtitleItem]:
        # SubDL requires an API key for queries
        api_key = settings.SUBDL_API_KEY
        if not api_key:
            return []

        endpoint = f"{self.base_url}/api/v1/subtitles"
        params: Dict[str, Any] = {
            "api_key": api_key,
            "languages": languages.upper(),
            "subs_per_page": min(limit, 30),
            "releases": 1,
            "unpack": 1,
        }
        if imdb_id:
            params["imdb_id"] = imdb_id
        elif query:
            params["film_name"] = query
        else:
            return []

        data = await http_client.get_json(endpoint, params=params)
        raw_subs = data.get("subtitles") or []
        items: List[SubtitleItem] = []

        for s in raw_subs:
            sub_id = str(s.get("sd_id") or len(items) + 1)
            raw_url = s.get("url") or ""
            download_url = f"https://dl.subdl.com{raw_url}?api_key={api_key}" if raw_url.startswith("/") else raw_url
            lang = s.get("lang") or "English"

            item = SubtitleItem(
                id=f"subdl_{sub_id}",
                provider=self.name,
                language=lang,
                lang_code=lang[:3].lower(),
                format="srt",
                download_url=download_url,
                release_name=s.get("release_name"),
                is_hearing_impaired=bool(s.get("hi", False)),
                rating=None,
                downloads_count=None,
                season=s.get("season"),
                episode=s.get("episode"),
                fps=None,
            )
            items.append(item)
            if len(items) >= limit:
                break

        return items
