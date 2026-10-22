import re
from typing import List, Optional, Tuple


class AnimeOffsetEngine:
    """
    Anime Episode Offset and Query Generator.
    Ported and adapted from stremio-kitsu-anime-master.
    Translates between Western IMDb/TMDB seasonal notation and Japanese absolute episode numbering.
    """

    # Well-known anime series with cumulative continuous episode counts
    CONTINUOUS_SERIES_MAP = {
        "one piece": 0,
        "naruto": 0,
        "naruto shippuden": 0,
        "bleach": 0,
        "detective conan": 0,
        "case closed": 0,
        "boruto": 0,
        "black clover": 0,
        "fairy tail": 0,
        "dragon ball super": 0,
        "dragon ball z": 0,
        "hunter x hunter": 0,
        "gintama": 0,
    }

    # Season base episode offsets for popular segmented anime
    SEASON_OFFSETS = {
        # Attack on Titan
        ("attack on titan", 2): 25,
        ("attack on titan", 3): 37,
        ("attack on titan", 4): 59,
        # My Hero Academia
        ("my hero academia", 2): 13,
        ("my hero academia", 3): 38,
        ("my hero academia", 4): 63,
        ("my hero academia", 5): 88,
        ("my hero academia", 6): 113,
        ("my hero academia", 7): 138,
        # Demon Slayer
        ("demon slayer", 2): 26,
        ("demon slayer", 3): 44,
        ("demon slayer", 4): 55,
        # Jujutsu Kaisen
        ("jujutsu kaisen", 2): 24,
    }

    @classmethod
    def get_search_queries(
        cls,
        title: str,
        season: Optional[int] = None,
        episode: Optional[int] = None,
    ) -> List[str]:
        """
        Generates comprehensive search queries for anime trackers (Nyaa, Tokyo Toshokan, etc.)
        covering both Western format (S01E05) and Japanese absolute numbering (Episode 05 / 05).
        """
        clean_title = re.sub(r"[^\w\s-]", "", title).strip()
        queries = []

        if season and episode:
            # 1. Standard Western format
            queries.append(f"{clean_title} S{season:02d}E{episode:02d}")
            queries.append(f"{clean_title} Season {season} {episode:02d}")

            # 2. Check for absolute continuous series
            norm_key = clean_title.lower()
            if norm_key in cls.CONTINUOUS_SERIES_MAP:
                # Continuous numbering matches episode directly
                queries.append(f"{clean_title} {episode:02d}")
                queries.append(f"{clean_title} - {episode:02d}")
                queries.append(f"{clean_title} {episode:03d}")
                queries.append(f"{clean_title} {episode:04d}")

            # 3. Check season base offset
            offset_key = (norm_key, season)
            if offset_key in cls.SEASON_OFFSETS:
                abs_ep = cls.SEASON_OFFSETS[offset_key] + episode
                queries.append(f"{clean_title} {abs_ep:02d}")
                queries.append(f"{clean_title} - {abs_ep:02d}")
            elif season == 1:
                # Season 1 absolute is the same as episode
                queries.append(f"{clean_title} {episode:02d}")
                queries.append(f"{clean_title} - {episode:02d}")
        else:
            queries.append(clean_title)

        # Deduplicate while preserving priority order
        seen = set()
        deduped = []
        for q in queries:
            if q.lower() not in seen:
                seen.add(q.lower())
                deduped.append(q)

        return deduped
