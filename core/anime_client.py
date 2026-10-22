import asyncio
import re
from typing import Any, Dict, List, Optional
from core.cache import cache
from core.client import http_client
from models.discover import DiscoverDetail, DiscoverItem, EpisodeItem, SeasonInfo


class AnimeClient:
    """
    Kitsu & Anime metadata integration engine.
    Fetches rich anime categories (TV, Movie, OVA, Specials, ONA),
    airing status, studios, ratings, and full episode trees.
    """

    BASE_URL = "https://kitsu.io/api/edge"

    @classmethod
    async def fetch_anime_category(
        cls,
        category: str = "all",
        page: int = 1,
        limit: int = 20,
    ) -> List[DiscoverItem]:
        """
        Fetches curated anime by category: 'all', 'tv', 'movie', 'ova', 'special'.
        """
        safe_limit = min(limit, 20)
        cache_key = f"anime:catalog:{category}:{page}"
        cached = await cache.get(cache_key)
        if cached:
            return cached

        # Map frontend category to Kitsu subtype filter
        subtype_param = ""
        cat_lower = (category or "all").lower()
        if cat_lower == "tv":
            subtype_param = "&filter[subtype]=TV"
        elif cat_lower == "movie":
            subtype_param = "&filter[subtype]=movie"
        elif cat_lower in ("ova", "ona"):
            subtype_param = "&filter[subtype]=ova,ona"
        elif cat_lower in ("special", "specials", "off-season"):
            subtype_param = "&filter[subtype]=special"

        offset = (page - 1) * safe_limit
        url = f"{cls.BASE_URL}/anime?sort=-userCount{subtype_param}&page[limit]={safe_limit}&page[offset]={offset}"

        items: List[DiscoverItem] = []
        try:
            headers = {"Accept": "application/vnd.api+json"}
            data = await http_client.get_json(url, headers=headers, timeout=6.0)
            records = (data.get("data") or []) if isinstance(data, dict) else []

            for r in records:
                k_id = r.get("id")
                attrs = r.get("attributes") or {}
                canonical_title = attrs.get("canonicalTitle") or attrs.get("en") or "Unknown Anime"

                poster_wrap = attrs.get("posterImage") or {}
                poster_url = poster_wrap.get("medium") or poster_wrap.get("large") or poster_wrap.get("original")

                cover_wrap = attrs.get("coverImage") or {}
                backdrop_url = cover_wrap.get("large") or cover_wrap.get("original")

                rating_raw = attrs.get("averageRating")
                rating_str = f"{float(rating_raw) / 10.0:.1f}" if rating_raw else None

                subtype = (attrs.get("subtype") or "TV").upper()

                status_raw = (attrs.get("status") or "").lower()
                status_str = "Airing" if status_raw == "current" else ("Upcoming" if status_raw in ("upcoming", "unreleased") else "Finished")

                start_date = attrs.get("startDate") or ""
                year_str = start_date[:4] if len(start_date) >= 4 else None

                items.append(
                    DiscoverItem(
                        id=f"kitsu:{k_id}",
                        title=canonical_title,
                        type="anime",
                        year=year_str,
                        poster=poster_url,
                        backdrop=backdrop_url,
                        rating=rating_str,
                        genres=["Animation", "Anime"],
                        description=attrs.get("synopsis"),
                        anime_format=subtype,
                        anime_status=status_str,
                    )
                )
        except Exception as e:
            print(f"[AnimeClient] Error fetching anime category '{category}': {e}")

        if items:
            await cache.set(cache_key, items, ttl=21600)  # 6 hours

        return items

    @classmethod
    async def fetch_kitsu_detail(cls, kitsu_id: str) -> Optional[DiscoverDetail]:
        """
        Fetches full metadata and episode list for a Kitsu anime title.
        """
        clean_id = kitsu_id.replace("kitsu:", "").strip()
        cache_key = f"anime:detail:kitsu:{clean_id}"
        cached = await cache.get(cache_key)
        if cached:
            return cached

        try:
            headers = {"Accept": "application/vnd.api+json"}
            url = f"{cls.BASE_URL}/anime/{clean_id}"
            data = await http_client.get_json(url, headers=headers, timeout=6.0)
            item_data = (data.get("data") or {}) if isinstance(data, dict) else {}
            attrs = item_data.get("attributes") or {}

            canonical_title = attrs.get("canonicalTitle") or "Unknown Anime"
            poster_wrap = attrs.get("posterImage") or {}
            poster_url = poster_wrap.get("large") or poster_wrap.get("original")

            cover_wrap = attrs.get("coverImage") or {}
            backdrop_url = cover_wrap.get("large") or cover_wrap.get("original")

            rating_raw = attrs.get("averageRating")
            rating_str = f"{float(rating_raw) / 10.0:.1f}" if rating_raw else None

            subtype = (attrs.get("subtype") or "TV").upper()
            status_raw = (attrs.get("status") or "").lower()
            status_str = "Airing" if status_raw == "current" else ("Upcoming" if status_raw in ("upcoming", "unreleased") else "Finished")

            start_date = attrs.get("startDate") or ""
            year_str = start_date[:4] if len(start_date) >= 4 else None

            # Fetch episodes with pagination up to episodeCount (max 500)
            episodes_list: List[EpisodeItem] = []
            offset = 0
            limit = 20
            total_expected = attrs.get("episodeCount") or 20

            while offset < min(total_expected, 500):
                ep_url = f"{cls.BASE_URL}/anime/{clean_id}/episodes?page[limit]={limit}&page[offset]={offset}"
                ep_data = await http_client.get_json(ep_url, headers=headers, timeout=6.0)
                ep_records = (ep_data.get("data") or []) if isinstance(ep_data, dict) else []
                if not ep_records:
                    break
                for it in ep_records:
                    ep_attrs = it.get("attributes") or {}
                    num = ep_attrs.get("number") or (len(episodes_list) + 1)
                    ep_thumb = (ep_attrs.get("thumbnail") or {}).get("original")
                    episodes_list.append(
                        EpisodeItem(
                            id=f"kitsu:{clean_id}:1:{num}",
                            season=1,
                            episode=int(num),
                            title=ep_attrs.get("canonicalTitle") or f"Episode {num}",
                            released=ep_attrs.get("airdate"),
                            overview=ep_attrs.get("synopsis"),
                            thumbnail=ep_thumb,
                        )
                    )
                offset += len(ep_records)
                if len(ep_records) < limit:
                    break

            # If episodes endpoint had no records (e.g. movie or 1-shot OVA), synthesize Episode 1
            if not episodes_list:
                ep_count = attrs.get("episodeCount") or 1
                for n in range(1, ep_count + 1):
                    episodes_list.append(
                        EpisodeItem(
                            id=f"kitsu:{clean_id}:1:{n}",
                            season=1,
                            episode=n,
                            title=canonical_title if n == 1 else f"Episode {n}",
                            released=start_date,
                            overview=attrs.get("synopsis"),
                            thumbnail=backdrop_url,
                        )
                    )

            season_info = SeasonInfo(season_number=1, episodes=episodes_list)

            detail = DiscoverDetail(
                id=f"kitsu:{clean_id}",
                title=canonical_title,
                type="anime",
                year=year_str,
                poster=poster_url,
                backdrop=backdrop_url,
                rating=rating_str,
                genres=["Animation", "Anime"],
                description=attrs.get("synopsis"),
                anime_format=subtype,
                anime_status=status_str,
                seasons=[season_info],
                total_episodes=len(episodes_list),
            )

            await cache.set(cache_key, detail, ttl=86400)
            return detail
        except Exception as e:
            print(f"[AnimeClient] Error fetching Kitsu detail '{clean_id}': {e}")
            return None
