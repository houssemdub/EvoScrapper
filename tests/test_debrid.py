import os
import sys
import asyncio
import unittest
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from core.debrid.base import DebridStreamResult
from core.debrid.manager import get_debrid_manager
from core.debrid.realdebrid import RealDebridClient
from core.debrid.alldebrid import AllDebridClient
from core.debrid.torbox import TorboxClient
from core.debrid.debridlink import DebridLinkClient
from core.debrid.premiumize import PremiumizeClient
from core.debrid.pikpak import PikPakClient


class TestDebridEngine(unittest.TestCase):

    def test_clients_instantiation(self):
        rd = RealDebridClient(api_key="mock_rd_key")
        self.assertEqual(rd.provider_name, "RealDebrid")
        self.assertTrue(rd.is_configured)

        ad = AllDebridClient(api_key="mock_ad_key")
        self.assertEqual(ad.provider_name, "AllDebrid")
        self.assertTrue(ad.is_configured)

        tb = TorboxClient(api_key="mock_tb_key")
        self.assertEqual(tb.provider_name, "TorBox")
        self.assertTrue(tb.is_configured)

        dl = DebridLinkClient(api_key="mock_dl_key")
        self.assertEqual(dl.provider_name, "DebridLink")
        self.assertTrue(dl.is_configured)

        pm = PremiumizeClient(api_key="mock_pm_key")
        self.assertEqual(pm.provider_name, "Premiumize")
        self.assertTrue(pm.is_configured)

        pk = PikPakClient(username="test@pikpak.com", password="password123")
        self.assertEqual(pk.provider_name, "PikPak")
        self.assertTrue(pk.is_configured)

    def test_all_six_providers_in_manager(self):
        mgr = get_debrid_manager()
        expected = {"realdebrid", "alldebrid", "torbox", "debridlink", "premiumize", "pikpak"}
        self.assertTrue(expected.issubset(set(mgr.providers.keys())))

    def test_unconfigured_clients(self):
        rd = RealDebridClient(api_key="")
        self.assertFalse(rd.is_configured)

    def test_debrid_manager_singleton(self):
        mgr1 = get_debrid_manager()
        mgr2 = get_debrid_manager()
        self.assertIs(mgr1, mgr2)

    def test_empty_cache_check(self):
        mgr = get_debrid_manager()
        res = asyncio.run(mgr.check_cache([]))
        self.assertEqual(res, {})

    def test_debridlink_cache_check_mock(self):
        from unittest.mock import patch, MagicMock

        dl = DebridLinkClient(api_key="test_key")
        test_hash = "4a1d4d3d8a6fc5b7507eb23521d8b13d6a4c2810"

        class MockResponse:
            def __init__(self, data, status=200):
                self._data = data
                self.status = status

            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc_val, exc_tb):
                pass

            async def json(self):
                return self._data

        class MockSession:
            def __init__(self, *args, **kwargs):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc_val, exc_tb):
                pass

            def get(self, url, headers=None):
                return MockResponse({"success": True, "value": {test_hash: {"name": "Test"}}})

        with patch("aiohttp.ClientSession", MockSession):
            res = asyncio.run(dl.check_cache([test_hash]))
            self.assertTrue(res.get(test_hash))

    def test_premiumize_cache_check_mock(self):
        from unittest.mock import patch

        pm = PremiumizeClient(api_key="test_key")
        test_hash = "4a1d4d3d8a6fc5b7507eb23521d8b13d6a4c2810"

        class MockResponse:
            def __init__(self, data, status=200):
                self._data = data
                self.status = status

            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc_val, exc_tb):
                pass

            async def json(self):
                return self._data

        class MockSession:
            def __init__(self, *args, **kwargs):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc_val, exc_tb):
                pass

            def post(self, url, headers=None, data=None):
                return MockResponse({"status": "success", "response": [True]})

        with patch("aiohttp.ClientSession", MockSession):
            res = asyncio.run(pm.check_cache([test_hash]))
            self.assertTrue(res.get(test_hash))

    def test_pikpak_cache_check_mock(self):
        from unittest.mock import patch

        pk = PikPakClient(api_key="mock_access_token")
        test_hash = "4a1d4d3d8a6fc5b7507eb23521d8b13d6a4c2810"

        class MockResponse:
            def __init__(self, data, status=200):
                self._data = data
                self.status = status

            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc_val, exc_tb):
                pass

            async def json(self):
                return self._data

        class MockSession:
            def __init__(self, *args, **kwargs):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc_val, exc_tb):
                pass

            def get(self, url, headers=None):
                return MockResponse({
                    "tasks": [
                        {"phase": "PHASE_TYPE_COMPLETE", "params": {"url": f"magnet:?xt=urn:btih:{test_hash}"}}
                    ]
                })

        with patch("aiohttp.ClientSession", MockSession):
            res = asyncio.run(pk.check_cache([test_hash]))
            self.assertTrue(res.get(test_hash))


if __name__ == "__main__":
    unittest.main()
