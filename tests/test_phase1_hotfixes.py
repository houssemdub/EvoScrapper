import asyncio
import os
import sys
import unittest
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi import HTTPException

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


class TestPhase1Hotfixes(unittest.IsolatedAsyncioTestCase):

    # --------------------------------------------------------------------------
    # CRIT-01: 1337x & Torlock infoHash extraction & magnet generation
    # --------------------------------------------------------------------------
    async def test_x1337_resolves_real_info_hash_and_magnet(self):
        from providers.torrents.x1337 import X1337Provider

        provider = X1337Provider()
        mock_list_html = """
        <table class="table-list">
            <tr><th>Name</th><th>SE</th><th>LE</th><th>Date</th><th>Size</th></tr>
            <tr>
                <td class="name"><a href="/sub/1">cat</a><a href="/torrent/5938472/Big-Buck-Bunny-1080p/">Big Buck Bunny 1080p</a></td>
                <td class="seeds">42</td>
                <td class="leeches">5</td>
                <td class="coll-date">May 10th</td>
                <td class="size">1.4 GB<span class="seeds"></span></td>
            </tr>
        </table>
        """
        mock_details_html = """
        <html>
            <body>
                <a href="magnet:?xt=urn:btih:c1205d5e0e64cc0aab4f7e60cfb669e4b477bc4c&dn=Big+Buck+Bunny">Magnet Download</a>
            </body>
        </html>
        """

        with patch("core.client.http_client.get_text") as mock_get:
            async def side_effect(url, **kwargs):
                if "/torrent/5938472/" in url:
                    return mock_details_html
                return mock_list_html
            mock_get.side_effect = side_effect

            items = await provider._do_search("Big Buck Bunny", limit=10)
            self.assertEqual(len(items), 1)
            item = items[0]
            self.assertEqual(item.info_hash, "c1205d5e0e64cc0aab4f7e60cfb669e4b477bc4c")
            self.assertIn("c1205d5e0e64cc0aab4f7e60cfb669e4b477bc4c", item.magnet_uri.lower())
            self.assertNotEqual(item.info_hash, "5938472")

    async def test_torlock_resolves_real_info_hash_and_magnet(self):
        from providers.torrents.torlock import TorlockProvider

        provider = TorlockProvider()
        mock_list_html = """
        <table class="table-striped">
            <tr>
                <td><a href="/icon">ic</a><a href="/torrent/123456/sintel-4k.html">Sintel 4K 2160p</a></td>
                <td>today</td>
                <td>850 MB</td>
                <td>120</td>
                <td>12</td>
            </tr>
        </table>
        """
        mock_details_html = """
        <html>
            <body>
                <a href="magnet:?xt=urn:btih:08a80a2b0e64cc0aab4f7e60cfb669e4b477bc4c&dn=Sintel">Download Magnet</a>
            </body>
        </html>
        """

        with patch("core.client.http_client.get_text") as mock_get:
            async def side_effect(url, **kwargs):
                if "/torrent/123456/" in url:
                    return mock_details_html
                return mock_list_html
            mock_get.side_effect = side_effect

            items = await provider._do_search("Sintel", limit=10)
            self.assertEqual(len(items), 1)
            item = items[0]
            self.assertEqual(item.info_hash, "08a80a2b0e64cc0aab4f7e60cfb669e4b477bc4c")
            self.assertIn("08a80a2b0e64cc0aab4f7e60cfb669e4b477bc4c", item.magnet_uri.lower())
            self.assertNotEqual(item.info_hash, "123456")

    async def test_stream_resolver_retains_items_with_info_hash(self):
        from core.stream_resolver import resolve_streams
        from models.torrent import TorrentItem
        from core.title_parser import parse_release_title

        item1337 = TorrentItem(
            id="c1205d5e0e64cc0aab4f7e60cfb669e4b477bc4c",
            title="Inception 2010 1080p BluRay x264",
            info_hash="c1205d5e0e64cc0aab4f7e60cfb669e4b477bc4c",
            magnet_uri="magnet:?xt=urn:btih:c1205d5e0e64cc0aab4f7e60cfb669e4b477bc4c&dn=Inception",
            size_bytes=2147483648,
            size_formatted="2.0 GB",
            seeders=50,
            leechers=10,
            category="movies",
            provider="1337x",
            sources=["1337x"],
            details_url="https://1337x.to/torrent/123/inception",
            metadata=parse_release_title("Inception 2010 1080p BluRay x264"),
        )

        mock_prov = MagicMock()
        mock_prov.search = AsyncMock(return_value=[item1337])

        with patch("core.stream_resolver.TORRENT_PROVIDERS", {"1337x": mock_prov}), \
             patch("core.stream_resolver.fetch_torrentio_streams", return_value=[]):
            res = await resolve_streams(title="Inception", imdb_id="tt1375666", year="2010")
            self.assertGreaterEqual(len(res.streams), 1)
            found = any(s.info_hash == "c1205d5e0e64cc0aab4f7e60cfb669e4b477bc4c" for s in res.streams)
            self.assertTrue(found, "Stream resolver must retain valid 1337x/torlock stream with resolved infoHash")

    # --------------------------------------------------------------------------
    # CRIT-02: AllDebrid multi-value form submission without dict() collapsing
    # --------------------------------------------------------------------------
    async def test_alldebrid_cache_check_preserves_all_hashes(self):
        from core.debrid.alldebrid import AllDebridClient

        client = AllDebridClient(api_key="mock_key")
        hashes = [
            "1111111111111111111111111111111111111111",
            "2222222222222222222222222222222222222222",
            "3333333333333333333333333333333333333333",
        ]

        captured_data = None

        class MockResponse:
            status = 200
            async def json(self):
                return {
                    "status": "success",
                    "data": {
                        "magnets": [
                            {"hash": "1111111111111111111111111111111111111111", "instant": True},
                            {"hash": "2222222222222222222222222222222222222222", "instant": False},
                            {"hash": "3333333333333333333333333333333333333333", "instant": True},
                        ]
                    }
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
            def post(self, url, headers=None, data=None):
                nonlocal captured_data
                captured_data = data
                return MockResponse()

        with patch("aiohttp.ClientSession", MockSession):
            result = await client.check_cache(hashes)

        # Verify all 3 hashes were passed to data, not collapsed to 1 by dict()
        self.assertIsNotNone(captured_data)
        self.assertFalse(isinstance(captured_data, dict), "data should not be collapsed to a standard dict")
        # In a list of tuples, there should be 3 entries
        self.assertEqual(len(list(captured_data)), 3)
        self.assertEqual(result[hashes[0]], True)
        self.assertEqual(result[hashes[1]], False)
        self.assertEqual(result[hashes[2]], True)

    # --------------------------------------------------------------------------
    # CRIT-03: WebTorrent Node daemon timeout cleanup
    # --------------------------------------------------------------------------
    def test_torrent_engine_js_has_timeout_cleanup(self):
        engine_path = os.path.join(os.path.dirname(__file__), "..", "streamer", "torrent_engine.js")
        with open(engine_path, "r", encoding="utf-8") as f:
            content = f.read()

        # Check for client.remove inside the timeout callback
        self.assertIn("this.client.remove(torrent", content, "torrent_engine.js must call this.client.remove on timeout")
        self.assertIn("destroyStore: true", content, "torrent_engine.js must pass destroyStore: true on timeout removal")

    # --------------------------------------------------------------------------
    # CRIT-04: Virtual HLS MPEG-TS segment generator
    # --------------------------------------------------------------------------
    async def test_hls_ts_segment_generator_command(self):
        from core.transmuxer import stream_hls_ts_segment

        captured_cmd = None

        class MockProcess:
            def __init__(self):
                self.returncode = 0
                self.stdout = AsyncMock()
                self.stdout.read.side_effect = [b"MPEG-TS-TEST-PAYLOAD", b""]
            def terminate(self):
                pass
            async def wait(self):
                return 0

        async def mock_subprocess_exec(*cmd, **kwargs):
            nonlocal captured_cmd
            captured_cmd = list(cmd)
            return MockProcess()

        with patch("asyncio.create_subprocess_exec", side_effect=mock_subprocess_exec):
            chunks = []
            async for chunk in stream_hls_ts_segment("http://localhost:8000/source.mkv", start_seconds=12.0, duration_seconds=6.0):
                chunks.append(chunk)

            self.assertEqual(b"".join(chunks), b"MPEG-TS-TEST-PAYLOAD")
            self.assertIsNotNone(captured_cmd)
            # Verify proper format is mpegts
            self.assertIn("mpegts", captured_cmd)
            # Verify -ss and -t are passed for strict segment boundaries
            self.assertIn("-ss", captured_cmd)
            ss_idx = captured_cmd.index("-ss")
            self.assertEqual(captured_cmd[ss_idx + 1], "12.000")

            self.assertIn("-t", captured_cmd)
            t_idx = captured_cmd.index("-t")
            self.assertEqual(captured_cmd[t_idx + 1], "6.000")

            # Verify -output_ts_offset is passed for PTS continuity across segments
            self.assertIn("-output_ts_offset", captured_cmd)
            offset_idx = captured_cmd.index("-output_ts_offset")
            self.assertEqual(captured_cmd[offset_idx + 1], "12.000")

    # --------------------------------------------------------------------------
    # CRIT-05: Subtitle SSRF security validation
    # --------------------------------------------------------------------------
    def test_ssrf_validator_blocks_private_and_local_addresses(self):
        from core.security import validate_outbound_proxy_url

        # Disallowed schemes
        with self.assertRaises(HTTPException) as ctx:
            validate_outbound_proxy_url("file:///etc/passwd")
        self.assertEqual(ctx.exception.status_code, 400)

        with self.assertRaises(HTTPException) as ctx:
            validate_outbound_proxy_url("ftp://127.0.0.1/test")
        self.assertEqual(ctx.exception.status_code, 400)

        # Loopback / Localhost
        with self.assertRaises(HTTPException) as ctx:
            validate_outbound_proxy_url("http://127.0.0.1/secrets")
        self.assertEqual(ctx.exception.status_code, 403)

        with self.assertRaises(HTTPException) as ctx:
            validate_outbound_proxy_url("http://localhost:8000/api")
        self.assertEqual(ctx.exception.status_code, 403)

        # Link-local / Cloud metadata (169.254.169.254)
        with self.assertRaises(HTTPException) as ctx:
            validate_outbound_proxy_url("http://169.254.169.254/latest/meta-data/")
        self.assertEqual(ctx.exception.status_code, 403)

        # RFC1918 Private networks
        with self.assertRaises(HTTPException) as ctx:
            validate_outbound_proxy_url("http://192.168.1.100/admin")
        self.assertEqual(ctx.exception.status_code, 403)

        with self.assertRaises(HTTPException) as ctx:
            validate_outbound_proxy_url("http://10.0.0.5:8080/")
        self.assertEqual(ctx.exception.status_code, 403)

    def test_ssrf_validator_allows_valid_external_urls(self):
        from core.security import validate_outbound_proxy_url

        valid_url = "https://yifysubtitles.ch/subtitle/test.srt"
        # Mock socket.gethostbyname to return public IP
        with patch("socket.gethostbyname", return_value="104.21.49.201"):
            clean = validate_outbound_proxy_url(valid_url)
            self.assertEqual(clean, valid_url)

    # --------------------------------------------------------------------------
    # CRIT-06: VLC process launcher safety (no taskkill /F /IM vlc.exe)
    # --------------------------------------------------------------------------
    def test_vlc_launcher_does_not_execute_global_taskkill(self):
        from core.transmuxer import launch_vlc_process

        executed_commands = []

        def mock_subprocess_run(cmd, *args, **kwargs):
            executed_commands.append(cmd)
            mock_res = MagicMock()
            mock_res.returncode = 0
            return mock_res

        class MockPopen:
            pid = 99999

        with patch("core.transmuxer.find_vlc", return_value="C:\\Program Files\\VideoLAN\\VLC\\vlc.exe"), \
             patch("subprocess.run", side_effect=mock_subprocess_run), \
             patch("subprocess.Popen", return_value=MockPopen()), \
             patch("os.path.isfile", return_value=True):

            success = launch_vlc_process("http://localhost:8000/stream.mp4", "Test Stream")
            self.assertTrue(success)

            # Ensure NO global taskkill /IM vlc.exe was called
            for cmd in executed_commands:
                if isinstance(cmd, list):
                    joined = " ".join(cmd).lower()
                    self.assertNotIn("/im vlc.exe", joined, "Destructive taskkill /IM vlc.exe must not be executed")


if __name__ == "__main__":
    unittest.main()
