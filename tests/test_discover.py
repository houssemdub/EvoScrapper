import asyncio
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from core.discover import fetch_catalog, fetch_discover_detail, search_catalog


async def test_discover_catalogs():
    # 1. Test Movie Catalog
    movie_cat = await fetch_catalog(media_type="movie", catalog="top")
    assert movie_cat is not None
    assert len(movie_cat.items) > 0, "Movie catalog should return items"
    first = movie_cat.items[0]
    assert first.id.startswith("tt"), f"Invalid ID: {first.id}"
    assert first.title, "Title should not be empty"
    print(f"[+] Movie catalog fetched {len(movie_cat.items)} items. First: {first.title} ({first.year})")

    # 2. Test Series Catalog
    series_cat = await fetch_catalog(media_type="series", catalog="top")
    assert series_cat is not None
    assert len(series_cat.items) > 0, "Series catalog should return items"
    print(f"[+] Series catalog fetched {len(series_cat.items)} items. First: {series_cat.items[0].title}")

    # 3. Test Series Episode Tree
    detail = await fetch_discover_detail("series", "tt0944947")  # Game of Thrones
    assert detail is not None, "Failed to fetch GoT detail"
    assert detail.id == "tt0944947"
    assert len(detail.seasons) > 0, "Should have seasons"
    assert detail.total_episodes > 0, "Should have total episodes"
    s1 = next((s for s in detail.seasons if s.season_number == 1), None)
    assert s1 is not None, "Season 1 should exist"
    assert len(s1.episodes) >= 10, f"Season 1 should have at least 10 episodes, got {len(s1.episodes)}"
    ep1 = s1.episodes[0]
    assert ep1.episode == 1
    print(f"[+] Detail & Episode Tree passed: {detail.title} has {len(detail.seasons)} seasons, {detail.total_episodes} episodes. S01E01: {ep1.title}")

    # 4. Test Search
    results = await search_catalog("Dune", media_type="movie")
    assert len(results) > 0, "Search for Dune should return results"
    print(f"[+] Discover search passed: found {len(results)} matches for 'Dune'")

    # 5. Test Fairy Tail Anime Search & Episodic Detail Resolution
    anime_results = await search_catalog("Fairy Tail", media_type="anime")
    assert len(anime_results) > 0, "Anime search for Fairy Tail should return results"
    ft_item = next((it for it in anime_results if it.id == "tt1528406"), None)
    assert ft_item is not None, "Fairy Tail series (tt1528406) must be in anime search results"
    assert ft_item.type == "anime", f"Expected type 'anime', got {ft_item.type}"
    print(f"[+] Anime search passed: Fairy Tail found with type='{ft_item.type}' at position {anime_results.index(ft_item)}")

    # 6. Test Fairy Tail Anime Detail (must be Fairy Tail, NOT Don't Be Afraid of the Dark!)
    ft_detail_anime = await fetch_discover_detail("anime", "tt1528406")
    assert ft_detail_anime is not None, "Failed to fetch Fairy Tail anime detail"
    assert "Fairy Tail" in ft_detail_anime.title, f"Expected 'Fairy Tail', got '{ft_detail_anime.title}'"
    assert ft_detail_anime.type == "anime", f"Expected type 'anime', got '{ft_detail_anime.type}'"
    assert len(ft_detail_anime.seasons) >= 9, f"Expected >= 9 seasons, got {len(ft_detail_anime.seasons)}"
    assert ft_detail_anime.total_episodes >= 300, f"Expected >= 300 episodes, got {ft_detail_anime.total_episodes}"
    print(f"[+] Fairy Tail anime detail verified: '{ft_detail_anime.title}' has {len(ft_detail_anime.seasons)} seasons, {ft_detail_anime.total_episodes} episodes")

    # 7. Test Fairy Tail Series Detail
    ft_detail_series = await fetch_discover_detail("series", "tt1528406")
    assert ft_detail_series is not None, "Failed to fetch Fairy Tail series detail"
    assert "Fairy Tail" in ft_detail_series.title, f"Expected 'Fairy Tail', got '{ft_detail_series.title}'"
    assert ft_detail_series.type == "series", f"Expected type 'series', got '{ft_detail_series.type}'"
    assert len(ft_detail_series.seasons) >= 9, f"Expected >= 9 seasons, got {len(ft_detail_series.seasons)}"
    print(f"[+] Fairy Tail series detail verified: '{ft_detail_series.title}' has {len(ft_detail_series.seasons)} seasons, {ft_detail_series.total_episodes} episodes")


if __name__ == "__main__":
    asyncio.run(test_discover_catalogs())
    print("[+] All Discover tests passed successfully!")
