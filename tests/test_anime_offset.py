import os
import sys
import unittest
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from core.anime_offset import AnimeOffsetEngine
from scrappers.nyaa import NyaaScraper


class TestAnimeOffset(unittest.TestCase):

    def test_continuous_series_queries(self):
        queries = AnimeOffsetEngine.get_search_queries("One Piece", season=21, episode=1071)
        self.assertTrue(any("1071" in q for q in queries))
        self.assertTrue(any("S21E1071" in q for q in queries))

    def test_seasonal_offset_queries(self):
        # Attack on Titan Season 2 Ep 1 is Absolute Ep 26
        queries = AnimeOffsetEngine.get_search_queries("Attack on Titan", season=2, episode=1)
        self.assertTrue(any("26" in q for q in queries))
        self.assertTrue(any("S02E01" in q for q in queries))

    def test_nyaa_instantiation(self):
        scraper = NyaaScraper()
        self.assertEqual(scraper.BASE_URL, "https://nyaa.si")
        self.assertIn("subsplease", scraper.TRUSTED_GROUPS)


if __name__ == "__main__":
    unittest.main()
