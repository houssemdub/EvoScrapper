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


if __name__ == "__main__":
    unittest.main()
