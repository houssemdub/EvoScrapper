import asyncio
import re
from typing import Any, Dict, List, Optional
import aiohttp


class WebCdnScraper:
    """
    Direct Web CDN Scraper.
    Adapted from stremio-cdn-videos-master.
    Fetches direct web embed & CDN streaming mirrors (VidSrc, SuperEmbed, 2Embed)
    for instant 0-peer streaming fallback when torrent swarms are slow or unavailable.
    """

    VIDSRC_BASE = "https://vidsrc.me"
    TWOEMBED_BASE = "https://www.2embed.cc"

    async def get_streams(
        self,
        imdb_id: str,
        media_type: str = "movie",
        season: Optional[int] = None,
        episode: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        if not imdb_id or not imdb_id.startswith("tt"):
            return []

        results = []
        is_series = (media_type.lower() in ("series", "tv", "anime")) and season and episode

        # 1. VidSrc Provider Entry
        if is_series:
            vidsrc_embed = f"{self.VIDSRC_BASE}/embed/{imdb_id}/{season}-{episode}/"
            twoembed_url = f"{self.TWOEMBED_BASE}/embedtv/{imdb_id}&s={season}&e={episode}"
            title_prefix = f"S{season:02d}E{episode:02d}"
        else:
            vidsrc_embed = f"{self.VIDSRC_BASE}/embed/{imdb_id}/"
            twoembed_url = f"{self.TWOEMBED_BASE}/embed/{imdb_id}"
            title_prefix = "Movie"

        # Web CDN Stream 1: VidSrc Cloud
        results.append({
            "name": "🌐 WEB-CDN (INSTANT)",
            "title": f"VidSrc Cloud Stream ({title_prefix}) [No Peers Needed]",
            "info_hash": f"cdn_vidsrc_{imdb_id}_{season or 0}_{episode or 0}",
            "file_idx": 0,
            "tracker": "VidSrc.me Cloud CDN",
            "size_str": "Cloud Stream",
            "seeds": 20,
            "peers": 0,
            "score": 50.0,
            "quality": {
                "resolution": "1080p",
                "source": "WEB-CDN",
                "codec": "H.264",
                "audio": "Stereo",
                "hdr": [],
                "group": "VidSrc",
            },
            "is_cdn": True,
            "cdn_url": vidsrc_embed,
            "embed_url": vidsrc_embed,
        })

        # Web CDN Stream 2: 2Embed Mirror
        results.append({
            "name": "🌐 WEB-CDN (MIRROR 2)",
            "title": f"2Embed Alternative Multi-Server ({title_prefix}) [No Peers Needed]",
            "info_hash": f"cdn_2embed_{imdb_id}_{season or 0}_{episode or 0}",
            "file_idx": 0,
            "tracker": "2Embed Cloud Mirror",
            "size_str": "Cloud Stream",
            "seeds": 15,
            "peers": 0,
            "score": 45.0,
            "quality": {
                "resolution": "1080p",
                "source": "WEB-CDN",
                "codec": "H.264",
                "audio": "Stereo",
                "hdr": [],
                "group": "2Embed",
            },
            "is_cdn": True,
            "cdn_url": twoembed_url,
            "embed_url": twoembed_url,
        })

        return results


_cdn_scraper_instance: Optional[WebCdnScraper] = None


def get_web_cdn_scraper() -> WebCdnScraper:
    global _cdn_scraper_instance
    if _cdn_scraper_instance is None:
        _cdn_scraper_instance = WebCdnScraper()
    return _cdn_scraper_instance
