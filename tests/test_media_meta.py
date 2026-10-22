import asyncio
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from core.media_meta import clean_title_and_extract_meta, fetch_media_details


def test_title_cleaning():
    cases = [
        ("Dune.Part.Two.2024.2160p.UHD.Remux.HEVC.DV.Atmos.TrueHD.7.1-FraMeSToR", "Dune Part Two", 2024, False),
        ("Breaking.Bad.S05E16.Felina.1080p.BluRay.x264", "Breaking Bad", None, True),
        ("Inception (2010) [1080p] [YTS.MX]", "Inception", 2010, False),
    ]
    for raw, expected_clean, expected_year, expected_series in cases:
        clean, year, is_series = clean_title_and_extract_meta(raw)
        assert clean.lower() == expected_clean.lower(), f"Expected {expected_clean}, got {clean}"
        assert year == expected_year, f"Expected {expected_year}, got {year}"
        assert is_series == expected_series, f"Expected {expected_series}, got {is_series}"
    print("[+] Title cleaning & extraction tests passed!")


async def test_meta_scraping_async():
    meta = await fetch_media_details(query="Inception", year=2010)
    assert meta is not None, "Failed to resolve Inception"
    assert meta.imdb_id == "tt1375666", f"Expected tt1375666, got {meta.imdb_id}"
    assert meta.poster_url is not None, "Poster URL should not be None"
    assert meta.rating is not None, "Rating should not be None"
    print(f"[+] Metadata & Jacket scraping passed: {meta.title} (IMDb: {meta.imdb_id}, Rating: {meta.rating})")


if __name__ == "__main__":
    test_title_cleaning()
    asyncio.run(test_meta_scraping_async())
    print("[+] All media metadata tests passed!")
