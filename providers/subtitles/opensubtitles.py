import re
from typing import Any, Dict, List, Optional
from config import settings
from core.client import http_client
from models.subtitle import SubtitleItem
from providers.base import BaseProvider


class OpenSubtitlesProvider(BaseProvider):
    """
    OpenSubtitles provider with zero-auth Stremio v3 fallback.
    Can resolve by IMDb ID, Series S:E, or binary video file hash.
    """

    def __init__(self):
        super().__init__(
            name="opensubtitles",
            provider_type="subtitle",
            base_urls=[
                "https://opensubtitles-v3.strem.io",
                "https://api.opensubtitles.com/api/v1",
            ],
        )

    def _clean_imdb(self, imdb_id: str) -> str:
        s = (imdb_id or "").strip()
        match = re.search(r"tt\d+", s, re.IGNORECASE)
        if match:
            return match.group(0).lower()
        if s.isdigit():
            return f"tt{s}"
        return ""

    async def _search_stremio_fallback(
        self,
        imdb_id: str,
        season: Optional[int] = None,
        episode: Optional[int] = None,
        video_hash: Optional[str] = None,
        video_size: Optional[int] = None,
        limit: int = 50,
    ) -> List[SubtitleItem]:
        clean_id = self._clean_imdb(imdb_id)
        if not clean_id and not (video_hash and video_size):
            return []
        
        if season is not None and episode is not None:
            media_path = f"series/{clean_id}:{season}:{episode}"
        else:
            media_path = f"movie/{clean_id}"

        if video_hash and video_size:
            endpoint = f"https://opensubtitles-v3.strem.io/subtitles/{media_path}/videoHash={video_hash}&videoSize={video_size}.json"
        else:
            endpoint = f"https://opensubtitles-v3.strem.io/subtitles/{media_path}.json"

        data = await http_client.get_json(endpoint)
        raw_subs = data.get("subtitles") or []

        items: List[SubtitleItem] = []
        for s in raw_subs:
            sub_id = str(s.get("id") or len(items) + 1)
            url = s.get("url") or ""
            raw_lang = (s.get("lang") or "eng").strip().lower()

            ISO_MAP = {
                "eng": ("en", "English"),
                "spa": ("es", "Spanish"),
                "fre": ("fr", "French"),
                "fra": ("fr", "French"),
                "ara": ("ar", "Arabic"),
                "ger": ("de", "German"),
                "deu": ("de", "German"),
                "ita": ("it", "Italian"),
                "por": ("pt", "Portuguese"),
                "pob": ("pt", "Portuguese (BR)"),
                "rus": ("ru", "Russian"),
                "jpn": ("ja", "Japanese"),
                "kor": ("ko", "Korean"),
                "chi": ("zh", "Chinese"),
                "zho": ("zh", "Chinese"),
                "hin": ("hi", "Hindi"),
                "tur": ("tr", "Turkish"),
                "pol": ("pl", "Polish"),
                "dut": ("nl", "Dutch"),
                "nld": ("nl", "Dutch"),
                "swe": ("sv", "Swedish"),
                "dan": ("da", "Danish"),
                "nor": ("no", "Norwegian"),
                "fin": ("fi", "Finnish"),
                "gre": ("el", "Greek"),
                "ell": ("el", "Greek"),
                "heb": ("he", "Hebrew"),
                "rum": ("ro", "Romanian"),
                "ron": ("ro", "Romanian"),
                "cze": ("cs", "Czech"),
                "ces": ("cs", "Czech"),
                "hun": ("hu", "Hungarian"),
                "vie": ("vi", "Vietnamese"),
                "tha": ("th", "Thai"),
                "ind": ("id", "Indonesian"),
                "ukr": ("uk", "Ukrainian"),
            }
            lang_code, language_name = ISO_MAP.get(raw_lang, (raw_lang[:2] if len(raw_lang) >= 2 else raw_lang, raw_lang.title()))

            release_name = (
                s.get("subtitleFileName")
                or s.get("movieReleaseName")
                or s.get("SubFileName")
                or s.get("releaseGroup")
            )
            fps_val = None
            if s.get("fpsMilli"):
                try:
                    fps_val = round(float(s.get("fpsMilli")) / 1000.0, 2)
                except Exception:
                    pass

            item = SubtitleItem(
                id=f"opensubs_{sub_id}",
                provider=self.name,
                language=language_name,
                lang_code=lang_code,
                format="srt",
                download_url=url,
                release_name=release_name,
                is_hearing_impaired=bool(s.get("hearing_impaired", False)),
                rating=None,
                downloads_count=None,
                season=season,
                episode=episode,
                fps=fps_val,
            )
            items.append(item)
            if len(items) >= limit:
                break

        return items

    async def _do_search(
        self,
        query: str = "",
        imdb_id: Optional[str] = None,
        season: Optional[int] = None,
        episode: Optional[int] = None,
        video_hash: Optional[str] = None,
        video_size: Optional[int] = None,
        limit: int = 50,
        **kwargs,
    ) -> List[SubtitleItem]:
        clean_id = self._clean_imdb(imdb_id or "")

        # If no valid clean_id, check if query contains tt or resolve via Cinemeta catalog
        if not clean_id and query:
            match = re.search(r"tt\d+", query, re.IGNORECASE)
            if match:
                clean_id = match.group(0).lower()
            else:
                try:
                    from routers.subtitles import resolve_imdb_id
                    resolved = await resolve_imdb_id(query, is_series=bool(season or episode))
                    if resolved:
                        clean_id = self._clean_imdb(resolved)
                except Exception:
                    pass

        if not clean_id and not video_hash:
            return []

        # Zero-auth Stremio endpoint is faster and requires no quota consumption.
        return await self._search_stremio_fallback(
            imdb_id=clean_id,
            season=season,
            episode=episode,
            video_hash=video_hash,
            video_size=video_size,
            limit=limit,
        )
