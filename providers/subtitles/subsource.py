from typing import Any, Dict, List, Optional
from config import settings
from core.client import http_client
from models.subtitle import SubtitleItem
from providers.base import BaseProvider


class SubSourceProvider(BaseProvider):
    """
    SubSource REST API Provider.
    Supports official API Key access for precision subtitle lookups.
    """

    def __init__(self):
        super().__init__(
            name="subsource",
            provider_type="subtitle",
            base_urls=["https://api.subsource.net/api/v1"],
        )

    async def _do_search(
        self,
        query: str,
        language: str = "english",
        season: Optional[int] = None,
        limit: int = 50,
        **kwargs,
    ) -> List[SubtitleItem]:
        api_key = settings.SUBSOURCE_API_KEY
        if not api_key or not query:
            return []

        headers = {"X-API-Key": api_key}

        # 1. Search movie/show
        search_endpoint = f"{self.base_url}/movies/search"
        data = await http_client.get_json(search_endpoint, params={"q": query}, headers=headers)
        movies = data.get("data") or []
        if not movies:
            return []

        movie_id = movies[0].get("id")
        if not movie_id:
            return []

        # 2. List subtitles
        subs_endpoint = f"{self.base_url}/subtitles"
        params: Dict[str, Any] = {"movieId": movie_id, "language": language.lower()}
        if season is not None:
            params["season"] = season

        subs_res = await http_client.get_json(subs_endpoint, params=params, headers=headers)
        raw_subs = subs_res.get("data") or []

        items: List[SubtitleItem] = []
        for s in raw_subs:
            sub_id = str(s.get("id"))
            download_url = f"{self.base_url}/subtitles/{sub_id}/download"

            item = SubtitleItem(
                id=f"subsource_{sub_id}",
                provider=self.name,
                language=language.capitalize(),
                lang_code=language[:3].lower(),
                format="srt",
                download_url=download_url,
                release_name=s.get("releaseName"),
                is_hearing_impaired=bool(s.get("hearingImpaired", False)),
                rating=s.get("rating"),
                downloads_count=s.get("downloadCount"),
                season=season,
                episode=s.get("episode"),
                fps=s.get("fps"),
            )
            items.append(item)
            if len(items) >= limit:
                break

        return items
