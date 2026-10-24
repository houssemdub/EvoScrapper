import asyncio
import os
from typing import Any, Dict, List, Optional
import aiohttp

from core.debrid.base import DebridClient, DebridStreamResult


class DebridLinkClient(DebridClient):
    """
    Debrid-Link API v2 Client.
    Supports instant seedbox cache probing and direct HTTPS uncurbed streaming.
    API Docs: https://debrid-link.com/api_doc/v2
    """

    BASE_URL = "https://debrid-link.com/api/v2"

    def __init__(self, api_key: Optional[str] = None):
        key = api_key or os.getenv("DEBRIDLINK_API_KEY", "")
        super().__init__(api_key=key)
        self.provider_name = "DebridLink"

    def _headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "User-Agent": "EvoScrapper/3.0",
        }

    async def check_cache(self, info_hashes: List[str]) -> Dict[str, bool]:
        if not self.is_configured or not info_hashes:
            return {h.lower(): False for h in info_hashes}

        clean_hashes = [h.strip().lower() for h in info_hashes if h and len(h.strip()) == 40]
        results: Dict[str, bool] = {h: False for h in clean_hashes}
        if not clean_hashes:
            return results

        timeout = aiohttp.ClientTimeout(total=6.0)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            try:
                # Debrid-Link accepts comma-separated hashes on /seedbox/cached
                hash_list = ",".join(clean_hashes[:50])
                url = f"{self.BASE_URL}/seedbox/cached?url={hash_list}"
                async with session.get(url, headers=self._headers()) as resp:
                    if resp.status == 200:
                        payload = await resp.json()
                        if payload.get("success"):
                            val = payload.get("value", {})
                            if isinstance(val, dict):
                                for h in clean_hashes:
                                    if h in val or h.upper() in val:
                                        results[h] = True
            except Exception as e:
                print(f"[DebridLink] Cache check warning: {e}")

        return results

    async def resolve_stream(
        self,
        info_hash: str,
        file_idx: int = 0,
        magnet: Optional[str] = None,
        season: Optional[int] = None,
        episode: Optional[int] = None,
    ) -> Optional[DebridStreamResult]:
        if not self.is_configured:
            return None

        clean_hash = info_hash.strip().lower()
        mag = magnet or f"magnet:?xt=urn:btih:{clean_hash}"

        timeout = aiohttp.ClientTimeout(total=20.0)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            try:
                # 1. Add torrent to seedbox (async=true for immediate cached resolution)
                add_url = f"{self.BASE_URL}/seedbox/add"
                payload = {"url": mag, "async": True}
                async with session.post(add_url, headers=self._headers(), json=payload) as resp:
                    if resp.status not in (200, 201):
                        return None
                    data = await resp.json()
                    if not data.get("success"):
                        return None

                    val = data.get("value", {})
                    files = val.get("files", [])
                    if not files:
                        # Poll once if files not yet attached
                        torrent_id = val.get("id")
                        if torrent_id:
                            await asyncio.sleep(0.5)
                            list_url = f"{self.BASE_URL}/seedbox/list?ids={torrent_id}"
                            async with session.get(list_url, headers=self._headers()) as l_resp:
                                if l_resp.status == 200:
                                    l_data = await l_resp.json()
                                    items = l_data.get("value", [])
                                    if items:
                                        files = items[0].get("files", [])

                if not files:
                    return None

                chosen_idx = file_idx
                if (season is not None or episode is not None) and files:
                    from core.file_matcher import select_target_file
                    chosen_idx = select_target_file(files, season=season, episode=episode, requested_idx=file_idx) or 0

                target_file = files[chosen_idx] if 0 <= chosen_idx < len(files) else files[0]
                dl_url = target_file.get("downloadUrl") or target_file.get("url")
                filename = target_file.get("name", "Stream.mp4")
                size = target_file.get("size", 0)

                if dl_url:
                    return DebridStreamResult(
                        url=dl_url,
                        filename=filename,
                        size=size,
                        provider="DebridLink",
                        cached=True,
                    )
            except Exception as e:
                print(f"[DebridLink] Resolve error: {e}")

        return None

    async def get_user_info(self) -> Dict[str, Any]:
        if not self.is_configured:
            return {"configured": False, "provider": self.provider_name}
        try:
            timeout = aiohttp.ClientTimeout(total=5.0)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                url = f"{self.BASE_URL}/account/infos"
                async with session.get(url, headers=self._headers()) as resp:
                    if resp.status == 200:
                        d = (await resp.json()).get("value", {})
                        return {
                            "configured": True,
                            "provider": self.provider_name,
                            "username": d.get("username"),
                            "premium": d.get("premium", False),
                            "expiration": d.get("premiumLeft"),
                        }
        except Exception:
            pass
        return {"configured": True, "provider": self.provider_name, "valid": False}
