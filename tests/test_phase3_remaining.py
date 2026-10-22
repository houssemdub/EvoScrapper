import asyncio
import copy
import hmac
import os
import sys
import unittest
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi import HTTPException

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


class TestPhase3RemainingFlaws(unittest.IsolatedAsyncioTestCase):

    # --------------------------------------------------------------------------
    # MED-01: Kitsu Anime Episode Pagination (>20 episodes)
    # --------------------------------------------------------------------------
    async def test_med01_kitsu_pagination_beyond_20_episodes(self):
        from core.anime_client import AnimeClient

        detail_resp = {
            "data": {
                "id": "123",
                "attributes": {
                    "canonicalTitle": "One Piece",
                    "episodeCount": 35,
                    "synopsis": "Pirates",
                }
            }
        }

        # Page 1 (20 eps), Page 2 (15 eps)
        page1 = {
            "data": [{"id": f"ep_{i}", "attributes": {"number": i, "canonicalTitle": f"Ep {i}"}} for i in range(1, 21)]
        }
        page2 = {
            "data": [{"id": f"ep_{i}", "attributes": {"number": i, "canonicalTitle": f"Ep {i}"}} for i in range(21, 36)]
        }

        async def mock_get_json(url, *args, **kwargs):
            if "episodes" in url:
                if "page[offset]=20" in url or "offset=20" in url:
                    return page2
                return page1
            return detail_resp

        with patch("core.client.http_client.get_json", side_effect=mock_get_json):
            detail = await AnimeClient.fetch_kitsu_detail("123")
            self.assertIsNotNone(detail)
            self.assertEqual(detail.total_episodes, 35, "Kitsu must paginate beyond 20 episodes when episodeCount > 20")
            self.assertEqual(len(detail.seasons[0].episodes), 35, "All 35 episodes must be present in season")

    # --------------------------------------------------------------------------
    # MED-02: URL Path Quoting in Rutor and Gestdown
    # --------------------------------------------------------------------------
    async def test_med02_url_encoding_for_spaces(self):
        from providers.torrents.rutor import RutorProvider
        from providers.subtitles.gestdown import GestdownProvider

        captured_urls = []

        async def mock_get_text(url, *args, **kwargs):
            captured_urls.append(url)
            return "<html></html>"

        async def mock_get_json(url, *args, **kwargs):
            captured_urls.append(url)
            return {"matchingShows": []}

        with patch("core.client.http_client.get_text", side_effect=mock_get_text), \
             patch("core.client.http_client.get_json", side_effect=mock_get_json):
            rutor = RutorProvider()
            await rutor.search("Breaking Bad S01", limit=5)

            gestdown = GestdownProvider()
            await gestdown.search("Breaking Bad S01", limit=5)

            for u in captured_urls:
                self.assertNotIn(" ", u, f"URL path must not contain unescaped spaces: {u}")
                self.assertIn("Breaking%20Bad", u, f"URL should contain quoted query: {u}")

    # --------------------------------------------------------------------------
    # MED-03: TorrentGalaxy Direct Magnet Extraction (No N+1)
    # --------------------------------------------------------------------------
    async def test_med03_torrent_galaxy_no_n_plus_one_requests(self):
        from providers.torrents.torrent_galaxy import TorrentGalaxyProvider

        sample_table = """
        <div class="tgxtablerow">
            <div class="tgxtablecell">
                <a href="/torrent/123/Movie-Title" class="txlight">Movie.Title.1080p</a>
                <a role="button" class="btn btn-primary" href="magnet:?xt=urn:btih:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa&dn=Movie.Title">Magnet</a>
            </div>
            <div class="tgxtablecell"><span class="badge">1.5 GB</span></div>
            <div class="tgxtablecell"><font color="green"><b>100</b></font></div>
            <div class="tgxtablecell"><font color="red"><b>10</b></font></div>
        </div>
        """

        call_count = 0

        async def mock_get_text(url, *args, **kwargs):
            nonlocal call_count
            call_count += 1
            return sample_table

        with patch("core.client.http_client.get_text", side_effect=mock_get_text):
            tgx = TorrentGalaxyProvider()
            items = await tgx._do_search("Movie Title", limit=5)

            self.assertEqual(len(items), 1)
            self.assertEqual(items[0].info_hash, "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa")
            self.assertEqual(call_count, 1, "TorrentGalaxy should only make 1 search table request, NOT secondary N+1 details requests")

    # --------------------------------------------------------------------------
    # MED-04: AnimeTosho Concurrency (Async Gather)
    # --------------------------------------------------------------------------
    async def test_med04_animetosho_parallel_gather(self):
        from providers.subtitles.animetosho import AnimeToshoProvider

        provider = AnimeToshoProvider()
        mock_search_data = [{"btih": f"hash_{i}"} for i in range(5)]

        concurrency_levels = []
        active_calls = 0

        async def mock_get_by_torrent_hash(h):
            nonlocal active_calls
            active_calls += 1
            concurrency_levels.append(active_calls)
            await asyncio.sleep(0.01)
            active_calls -= 1
            return []

        with patch("core.client.http_client.get_json", AsyncMock(return_value=mock_search_data)), \
             patch.object(provider, "get_by_torrent_hash", side_effect=mock_get_by_torrent_hash):
            await provider._do_search("Frieren", limit=5)
            # Concurrency should exceed 1 if parallel gather is implemented
            max_concurrency = max(concurrency_levels) if concurrency_levels else 0
            self.assertGreater(max_concurrency, 1, "AnimeTosho must gather hashes concurrently")

    # --------------------------------------------------------------------------
    # MED-05: Stremio Addon Magnet URL Encoding
    # --------------------------------------------------------------------------
    def test_med05_stremio_addon_magnet_url_encoding(self):
        import urllib.parse
        from core.stremio_addon import build_magnet_uri

        title_with_newlines_and_emojis = "Dune: Part Two\n💾 14.5 GB 👤 1500 ⚙️ Torrentio"
        info_hash = "c1205d5e0e64cc0aab4f7e60cfb669e4b477bc4c"
        magnet = build_magnet_uri(info_hash, title_with_newlines_and_emojis)

        self.assertNotIn("\n", magnet)
        self.assertIn("xt=urn:btih:c1205d5e0e64cc0aab4f7e60cfb669e4b477bc4c", magnet)
        # Should be properly URL encoded
        self.assertNotIn(" ", magnet)

    # --------------------------------------------------------------------------
    # MED-06: Torbox RequestDL Headers
    # --------------------------------------------------------------------------
    async def test_med06_torbox_requestdl_has_authorization_headers(self):
        from core.debrid.torbox import TorboxClient

        client = TorboxClient(api_key="mock_torbox_key")

        captured_headers = None

        class MockPostResponse:
            status = 200
            async def json(self):
                return {
                    "success": True,
                    "data": {
                        "torrent_id": 123,
                        "files": [{"id": 0, "name": "test.mkv"}]
                    }
                }
            async def __aenter__(self):
                return self
            async def __aexit__(self, exc_type, exc_val, exc_tb):
                pass

        class MockGetResponse:
            status = 200
            async def json(self):
                return {
                    "success": True,
                    "data": "https://stream.torbox.app/file.mkv"
                }
            async def __aenter__(self):
                return self
            async def __aexit__(self, exc_type, exc_val, exc_tb):
                pass

        class MockSession:
            def __init__(self, *args, **kwargs):
                pass
            async def __aenter__(self):
                return self
            async def __aexit__(self, exc_type, exc_val, exc_tb):
                pass
            def get(self, url, headers=None):
                nonlocal captured_headers
                captured_headers = headers
                return MockGetResponse()
            def post(self, url, headers=None, data=None, json=None):
                return MockPostResponse()

        with patch("aiohttp.ClientSession", MockSession):
            # Test that resolve_stream passes authorization headers when requesting download link
            await client.resolve_stream("c1205d5e0e64cc0aab4f7e60cfb669e4b477bc4c")
            self.assertIsNotNone(captured_headers, "TorboxClient.resolve_stream must pass headers to session.get(req_url)")
            self.assertIn("Authorization", captured_headers, "Headers must include Authorization token")

    # --------------------------------------------------------------------------
    # MED-07: In-Memory Cache Mutability Isolation (Deepcopy)
    # --------------------------------------------------------------------------
    async def test_med07_cache_returns_deep_copies(self):
        from core.cache import MemoryCache

        cache = MemoryCache()
        original = {"title": "Avatar", "nested": {"score": 100}}
        await cache.set("test_key", original, ttl=60)

        retrieved = await cache.get("test_key")
        retrieved["nested"]["score"] = 999  # Mutate retrieved object

        retrieved2 = await cache.get("test_key")
        self.assertEqual(retrieved2["nested"]["score"], 100, "Mutating retrieved cache object must not corrupt cached copy")

    # --------------------------------------------------------------------------
    # MED-08: Movie Title Clean Scene Tag Collision (*1917*, *2001*, *2012*)
    # --------------------------------------------------------------------------
    def test_med08_numeric_movie_title_preservation(self):
        from core.media_meta import clean_title_and_extract_meta

        # Title "1917 (2019)"
        clean1, year1, _ = clean_title_and_extract_meta("1917.2019.1080p.BluRay.x264")
        self.assertEqual(clean1.strip(), "1917", f"Expected '1917', got '{clean1}'")
        self.assertEqual(year1, 2019)

        # Title "2001: A Space Odyssey (1968)"
        clean2, year2, _ = clean_title_and_extract_meta("2001.A.Space.Odyssey.1968.720p.WEB-DL")
        self.assertIn("2001", clean2)

        # Title "2012 (2009)"
        clean3, year3, _ = clean_title_and_extract_meta("2012.2009.1080p.BluRay")
        self.assertEqual(clean3.strip(), "2012")

        # Title "Season of the Witch"
        clean4, _, _ = clean_title_and_extract_meta("Season.of.the.Witch.2011.1080p")
        self.assertEqual(clean4.strip().lower(), "season of the witch")

    # --------------------------------------------------------------------------
    # MED-09: Deduplicate Nyaa Scraper Implementations
    # --------------------------------------------------------------------------
    def test_med09_nyaa_scraper_unification(self):
        from scrappers.nyaa import get_nyaa_scraper
        from providers.torrents.nyaa import NyaaProvider

        scraper = get_nyaa_scraper()
        # Ensure scrappers.nyaa uses NyaaProvider or unified BaseProvider architecture with circuit breakers
        self.assertTrue(isinstance(scraper, NyaaProvider) or hasattr(scraper, "circuit_breaker"),
                        "Nyaa scraper should be unified with NyaaProvider architecture")

    # --------------------------------------------------------------------------
    # MED-10: CometNet Gossip Stubs Handled Gracefully
    # --------------------------------------------------------------------------
    async def test_med10_cometnet_graceful_lifecycle(self):
        from core.cometnet import CometNetNode

        node = CometNetNode()
        # Verify it has safe initialization and doesn't crash without relays
        self.assertTrue(hasattr(node, "node_id"))
        self.assertIsNotNone(node.node_id)
        # Test start/stop lifecycle methods exist and run safely
        if hasattr(node, "start"):
            await node.start()
        if hasattr(node, "stop"):
            await node.stop()

    # --------------------------------------------------------------------------
    # LOW-01: Constant-Time API Key Comparison
    # --------------------------------------------------------------------------
    async def test_low01_constant_time_api_key_check(self):
        import inspect
        from core.security import verify_api_key

        src = inspect.getsource(verify_api_key)
        self.assertTrue("compare_digest" in src, "verify_api_key must use secrets.compare_digest or hmac.compare_digest")

    # --------------------------------------------------------------------------
    # LOW-02: Protect Streaming Routes with verify_api_key Dependency
    # --------------------------------------------------------------------------
    def test_low02_stream_router_has_security_dependency(self):
        from routers.stream import router

        # Verify router has dependencies applied
        dep_callables = [d.dependency for d in router.dependencies]
        from core.security import verify_api_key
        self.assertIn(verify_api_key, dep_callables, "routers/stream.py router must include verify_api_key dependency")

    # --------------------------------------------------------------------------
    # LOW-03: Circuit Breaker Recording on BaseProvider.trending()
    # --------------------------------------------------------------------------
    async def test_low03_trending_records_circuit_breaker_metrics(self):
        from providers.base import BaseProvider

        class DummyProvider(BaseProvider):
            def __init__(self):
                super().__init__(name="dummy_test", provider_type="torrent", base_urls=["http://example.com"])
            async def _do_search(self, query, limit=50, **kwargs):
                return []
            async def _do_trending(self, category=None, limit=50):
                return []

        prov = DummyProvider()
        cb = prov.circuit_breaker
        initial_successes = cb.successful_calls
        await prov.trending()
        self.assertGreater(cb.successful_calls, initial_successes, "trending() must record circuit breaker success")

    # --------------------------------------------------------------------------
    # LOW-04: Subtitle ZIP Language Disambiguation
    # --------------------------------------------------------------------------
    def test_low04_subtitle_zip_language_disambiguation(self):
        from routers.subtitles import select_zip_subtitle_member

        members = [
            "Subs/Russian.srt",
            "Subs/Spanish.srt",
            "Subs/English.srt",
            "Subs/French.srt",
        ]
        chosen_en = select_zip_subtitle_member(members, target_lang="en")
        self.assertEqual(chosen_en, "Subs/English.srt")

        chosen_es = select_zip_subtitle_member(members, target_lang="es")
        self.assertEqual(chosen_es, "Subs/Spanish.srt")

    # --------------------------------------------------------------------------
    # LOW-05: curl_cffi HTTP Error Safety in HttpClient
    # --------------------------------------------------------------------------
    async def test_low05_curl_cffi_error_handling(self):
        from core.client import http_client

        class MockCurlResp:
            status_code = 403
            text = "Forbidden"

        class MockCurlSession:
            async def get(self, *args, **kwargs):
                return MockCurlResp()

        with patch.object(http_client, "get_curl_session", AsyncMock(return_value=MockCurlSession())):
            with self.assertRaises(Exception) as ctx:
                await http_client.get_text("http://example.com", use_stealth=True)
            # Must raise without signature mismatch
            self.assertIn("403", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
