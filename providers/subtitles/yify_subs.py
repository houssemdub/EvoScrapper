import re
from typing import List, Optional
from bs4 import BeautifulSoup
from core.client import http_client
from models.subtitle import SubtitleItem
from providers.base import BaseProvider


class YifySubtitlesProvider(BaseProvider):
    """
    YIFY Subtitles Provider featuring 1-Step Direct ZIP URL rewrite bypass.
    Extracts multi-language movie subtitles indexed by IMDb ID.
    """

    def __init__(self):
        super().__init__(
            name="yifysubtitles",
            provider_type="subtitle",
            base_urls=[
                "https://yifysubtitles.ch",
                "https://yts-subs.com",
            ],
        )

    def _clean_imdb(self, imdb_id: str) -> str:
        imdb_id = imdb_id.strip()
        if not imdb_id.startswith("tt"):
            return f"tt{imdb_id}"
        return imdb_id

    async def _do_search(
        self,
        query: str = "",
        imdb_id: Optional[str] = None,
        language: Optional[str] = None,
        limit: int = 50,
        **kwargs,
    ) -> List[SubtitleItem]:
        if not imdb_id and query:
            match = re.search(r"tt\d+", query, re.IGNORECASE)
            if match:
                imdb_id = match.group(0)

        if not imdb_id:
            return []

        clean_id = self._clean_imdb(imdb_id)
        endpoint = f"{self.base_url}/movie-imdb/{clean_id}"
        headers = {"Referer": f"{self.base_url}/"}
        html_text = await http_client.get_text(endpoint, headers=headers)

        soup = BeautifulSoup(html_text, "html.parser")
        rows = soup.select("tbody tr")
        items: List[SubtitleItem] = []

        for tr in rows:
            lang_span = tr.find("span", class_="sub-lang")
            lang_name = lang_span.text.strip() if lang_span else "English"

            # Map standard 2-letter codes for common languages
            lower_name = lang_name.lower()
            if "english" in lower_name:
                code = "en"
            elif "spanish" in lower_name:
                code = "es"
            elif "french" in lower_name:
                code = "fr"
            elif "arabic" in lower_name:
                code = "ar"
            elif "german" in lower_name:
                code = "de"
            elif "italian" in lower_name:
                code = "it"
            elif "portuguese" in lower_name:
                code = "pt"
            elif "russian" in lower_name:
                code = "ru"
            else:
                code = lower_name[:3]

            # Filter by language if requested
            if language and language.lower() not in ("all", "any", "*", ""):
                tgt = language.lower()
                if tgt in ("en", "eng", "english"):
                    if code != "en":
                        continue
                elif tgt != code and tgt not in lower_name:
                    continue

            sub_link = tr.find("a", href=lambda h: bool(h and h.startswith("/subtitles/")))
            if not sub_link:
                continue

            href = sub_link["href"]
            slug = href.replace("/subtitles/", "").strip("/")
            
            # 1-Step Direct ZIP bypass: /subtitle/{slug}.zip
            download_url = f"{self.base_url}/subtitle/{slug}.zip"

            rating_cell = tr.find("td", class_="rating-cell")
            rating = None
            if rating_cell and rating_cell.text.strip().replace("+", "").replace("-", "").isdigit():
                rating = float(rating_cell.text.strip())

            sub_id = slug.split("-")[-1] if "-" in slug else slug

            item = SubtitleItem(
                id=f"yify_{sub_id}",
                provider=self.name,
                language=lang_name,
                lang_code=code,
                format="zip",
                download_url=download_url,
                release_name=slug,
                is_hearing_impaired=bool(tr.find("span", class_="hi")),
                rating=rating,
                downloads_count=None,
                season=None,
                episode=None,
                fps=None,
            )
            items.append(item)
            if len(items) >= limit:
                break

        return items
