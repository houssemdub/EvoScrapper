import asyncio
import os
import sys
import tempfile
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


class TestPhase2HighFlaws(unittest.IsolatedAsyncioTestCase):

    # --------------------------------------------------------------------------
    # HIGH-01: Codec & Audio Regex Corruption in Title Parser
    # --------------------------------------------------------------------------
    def test_high01_title_parser_preserves_codecs_and_audio(self):
        from core.title_parser import parse_release_title

        # Test H.264, DDP5.1, Atmos, and release group with .mkv extension
        meta1 = parse_release_title("Avatar.2009.1080p.BluRay.H.264.DDP5.1.Atmos-FraMeSToR.mkv")
        self.assertEqual(meta1.codec, "x264", f"Expected x264 from H.264, got {meta1.codec}")
        self.assertEqual(meta1.audio, "Atmos", f"Expected Atmos from DDP5.1.Atmos, got {meta1.audio}")
        self.assertEqual(meta1.group, "FraMeSToR", f"Expected group FraMeSToR, got {meta1.group}")

        # Test h.265 and AC3 5.1
        meta2 = parse_release_title("Show.S01E01.720p.HDTV.h.265.AC3.5.1-GROUP.mp4")
        self.assertEqual(meta2.codec, "HEVC", f"Expected HEVC from h.265, got {meta2.codec}")
        self.assertEqual(meta2.audio, "5.1", f"Expected 5.1 from AC3 5.1, got {meta2.audio}")
        self.assertEqual(meta2.group, "GROUP", f"Expected group GROUP, got {meta2.group}")

        # Test 7.1 audio
        meta3 = parse_release_title("Movie.2024.2160p.UHD.Remux.HEVC.DV.TrueHD.7.1-EVO")
        self.assertEqual(meta3.codec, "HEVC", f"Expected HEVC, got {meta3.codec}")
        self.assertEqual(meta3.audio, "TrueHD", f"Expected TrueHD, got {meta3.audio}")
        self.assertIn("DV", meta3.hdr)

    # --------------------------------------------------------------------------
    # HIGH-02: Bounded Scraper Concurrency and Media-Type Provider Capabilities
    # --------------------------------------------------------------------------
    async def test_high02_bounded_concurrency_and_provider_routing(self):
        from core.stream_resolver import resolve_streams, PROVIDER_MEDIA_CAPABILITIES

        # Check capabilities mapping exists
        self.assertIn("movie", PROVIDER_MEDIA_CAPABILITIES)
        self.assertIn("series", PROVIDER_MEDIA_CAPABILITIES)
        self.assertIn("anime", PROVIDER_MEDIA_CAPABILITIES)

        # EZTV should only be queried for series, never movies
        self.assertNotIn("eztv", PROVIDER_MEDIA_CAPABILITIES["movie"])
        self.assertIn("eztv", PROVIDER_MEDIA_CAPABILITIES["series"])

        # YTS should only be queried for movies, never anime
        self.assertNotIn("yts", PROVIDER_MEDIA_CAPABILITIES["anime"])
        self.assertIn("yts", PROVIDER_MEDIA_CAPABILITIES["movie"])

        # Verify resolve_streams filters providers based on media_type
        from core.cache import cache
        await cache.clear()

        mock_eztv = MagicMock()
        mock_eztv.search = AsyncMock(return_value=[])
        mock_yts = MagicMock()
        mock_yts.search = AsyncMock(return_value=[])

        providers = {"eztv": mock_eztv, "yts": mock_yts}
        with patch("core.stream_resolver.TORRENT_PROVIDERS", providers), \
             patch("core.stream_resolver.fetch_torrentio_streams", return_value=[]):
            # For a movie, eztv should not be searched
            await resolve_streams(title="Interstellar", imdb_id="tt0816692", year="2014", media_type="movie")
            mock_eztv.search.assert_not_called()
            mock_yts.search.assert_called()

    # --------------------------------------------------------------------------
    # HIGH-03: Subtitle Cross-Contamination Across TV Series
    # --------------------------------------------------------------------------
    def test_high03_subtitle_cache_matching_scoped_by_info_hash(self):
        from routers.stream import _find_cached_media_path

        # Test requires info_hash parameter and validates 40-char hash
        self.assertIsNone(_find_cached_media_path("invalid_hash"))
        self.assertIsNone(_find_cached_media_path(None))

    # --------------------------------------------------------------------------
    # HIGH-04: Unevicted Stream Disk Cache Enforcement (destroyStore: true)
    # --------------------------------------------------------------------------
    def test_high04_webtorrent_engine_destroy_store_on_idle_cleanup(self):
        engine_path = os.path.join(os.path.dirname(__file__), "..", "streamer", "torrent_engine.js")
        with open(engine_path, "r", encoding="utf-8") as f:
            content = f.read()

        # In cleanupIdleSessions method definition, destroyStore must be true
        self.assertIn("cleanupIdleSessions(idleTimeoutMs", content)
        cleanup_idx = content.find("cleanupIdleSessions(idleTimeoutMs")
        cleanup_section = content[cleanup_idx:cleanup_idx + 800]
        self.assertIn("destroyStore: true", cleanup_section, "cleanupIdleSessions must call remove with destroyStore: true")

    # --------------------------------------------------------------------------
    # HIGH-05: EZTV Unfiltered Fallback Leakage
    # --------------------------------------------------------------------------
    async def test_high05_eztv_returns_empty_on_miss(self):
        from providers.torrents.eztv import EztvProvider

        provider = EztvProvider()
        mock_torrents_data = {
            "torrents": [
                {"id": 1, "title": "Random.Show.S01E01.720p", "filename": "random1.torrent", "hash": "1111111111111111111111111111111111111111"},
                {"id": 2, "title": "Other.Reality.Show.S02E05.1080p", "filename": "random2.torrent", "hash": "2222222222222222222222222222222222222222"},
            ]
        }

        with patch("core.client.http_client.get_json", AsyncMock(return_value=mock_torrents_data)):
            # Search for a query that does NOT match any of the returned torrents
            results = await provider._do_search(query="Breaking Bad S05E16", limit=10)
            self.assertEqual(results, [], "EZTV must return empty list when no torrent matches the query words")

    # --------------------------------------------------------------------------
    # HIGH-06: Non-Atomic JSON Library Storage
    # --------------------------------------------------------------------------
    async def test_high06_library_manager_atomic_persistence(self):
        from core.library_manager import LibraryManager
        from models.library import LibraryItem

        with tempfile.TemporaryDirectory() as tmpdir:
            test_file = os.path.join(tmpdir, "library.json")
            mgr = LibraryManager(storage_path=test_file)

            item = LibraryItem(
                id="tt1375666",
                title="Inception",
                year="2010",
                type="movie",
            )
            # Verify atomic save uses os.replace
            with patch("os.replace", wraps=os.replace) as mock_replace:
                await mgr.upsert_item(item)
                mock_replace.assert_called_once()

            self.assertTrue(os.path.exists(test_file))
            saved = await mgr.get_item("tt1375666")
            self.assertIsNotNone(saved)
            self.assertEqual(saved.title, "Inception")

    # --------------------------------------------------------------------------
    # HIGH-07: Web CDN Score Inflation
    # --------------------------------------------------------------------------
    async def test_high07_web_cdn_score_rebalanced(self):
        from scrappers.web_cdn import get_web_cdn_scraper

        scraper = get_web_cdn_scraper()
        streams = await scraper.get_streams(imdb_id="tt1375666", media_type="movie")
        self.assertGreater(len(streams), 0)
        cdn_stream = streams[0]

        # Web CDN stream score must NOT be 350.0 (which was artificially outranking real debrid 4K/1080p torrents)
        # It should have a modest score and seed count <= 50, flagged as web cdn / embed
        self.assertLessEqual(cdn_stream.get("score", 0), 100.0, "Web CDN score must be <= 100.0 to prevent outranking verified debrid/p2p streams")
        self.assertLessEqual(cdn_stream.get("seeds", 0), 50, "Web CDN seeds must be realistic (<= 50)")


if __name__ == "__main__":
    unittest.main()
