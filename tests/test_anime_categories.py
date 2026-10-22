import asyncio
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from core.anime_client import AnimeClient
from core.discover import fetch_catalog, fetch_discover_detail


async def test_anime_categories():
    # 1. Test fetching anime by sub-categories
    for cat in ["tv", "movie", "ova", "special"]:
        res = await fetch_catalog(media_type="anime", genre=cat)
        assert res is not None, f"Anime category {cat} should return response"
        assert len(res.items) > 0, f"Anime category {cat} should return items"
        first = res.items[0]
        assert first.id, "Anime item must have ID"
        assert first.title, "Anime item must have title"
        assert first.type == "anime", f"Item type should be anime, got {first.type}"
        print(f"[+] Anime category '{cat}' passed: {len(res.items)} items. First: {first.title} ({first.year}) [{first.anime_format}]")

    # 2. Test fetching detail for a kitsu anime title
    ova_cat = await fetch_catalog(media_type="anime", genre="ova")
    ova_item = ova_cat.items[0]
    detail = await fetch_discover_detail("anime", ova_item.id)
    assert detail is not None, f"Failed to fetch detail for {ova_item.id}"
    assert detail.title, "Detail must have title"
    assert len(detail.seasons) > 0, "Detail must have seasons"
    assert detail.total_episodes > 0, "Detail must have episodes"
    print(f"[+] Kitsu anime detail passed: '{detail.title}' has {detail.total_episodes} episodes, status: {detail.anime_status}, format: {detail.anime_format}")


if __name__ == "__main__":
    asyncio.run(test_anime_categories())
    print("[+] All Anime category and enrichment tests passed successfully!")
