import asyncio
import os
from typing import Any, Dict, List, Optional
import aiohttp

from core.debrid.base import DebridClient, DebridStreamResult


class AllDebridClient(DebridClient):
    """
    AllDebrid API v4 Client.
    Supports instant cache probing and direct HTTPS unthrottled streaming.
    """

    BASE_URL = "https://api.alldebrid.com/v4"

    def __init__(self, api_key: Optional[str] = None):
        key = api_key or os.getenv("ALLDEBRID_API_KEY", "")
        super().__init__(api_key=key)
        self.provider_name = "AllDebrid"

    def _headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "User-Agent": "EvoScrapper/2.0",
        }

    async def check_cache(self, info_hashes: List[str]) -> Dict[str, bool]:
        if not self.is_configured or not info_hashes:
            return {h.lower(): False for h in info_hashes}

        clean_hashes = [h.strip().lower() for h in info_hashes if h and len(h.strip()) == 40]
        results: Dict[str, bool] = {h: False for h in clean_hashes}

        timeout = aiohttp.ClientTimeout(total=6.0)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            try:
                # AllDebrid magnet/instant endpoint accepts repeated magnets[] parameter
                # Pass list of tuples directly so aiohttp encodes repeated keys without dict key collapsing
                form_payload = [("magnets[]", h) for h in clean_hashes[:40]]
                url = f"{self.BASE_URL}/magnet/instant?agent=evoscrapper"
                async with session.post(url, headers=self._headers(), data=form_payload) as resp:
                    if resp.status == 200:
                        payload = await resp.json()
                        data = payload.get("data", {})
                        magnets = data.get("magnets", [])
                        for item in magnets:
                            h = item.get("hash", "").lower()
                            if h and item.get("instant", False):
                                results[h] = True
            except Exception as e:
                print(f"[AllDebrid] Cache check warning: {e}")

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
                # 1. Upload magnet
                upload_url = f"{self.BASE_URL}/magnet/upload?agent=evoscrapper"
                async with session.post(upload_url, headers=self._headers(), data={"magnets[]": mag}) as resp:
                    if resp.status != 200:
                        return None
                    payload = await resp.json()
                    magnets = payload.get("data", {}).get("magnets", [])
                    if not magnets:
                        return None
                    mag_info = magnets[0]
                    torrent_id = mag_info.get("id")

                # 2. Check status and get unlocked links
                status_url = f"{self.BASE_URL}/magnet/status?agent=evoscrapper&id={torrent_id}"
                async with session.get(status_url, headers=self._headers()) as resp:
                    if resp.status != 200:
                        return None
                    st_data = await resp.json()
                    mag_obj = st_data.get("data", {}).get("magnets", {})
                    links = mag_obj.get("links", [])
                    if not links:
                        return None

                chosen_idx = file_idx
                if (season is not None or episode is not None) and links:
                    from core.file_matcher import select_target_file
                    chosen_idx = select_target_file(links, season=season, episode=episode, requested_idx=file_idx) or 0

                target_item = links[chosen_idx] if 0 <= chosen_idx < len(links) else links[0]
                link_url = target_item.get("link")
                filename = target_item.get("filename", "Stream.mp4")
                size = target_item.get("size", 0)

                # 3. Unlock link
                unlock_url = f"{self.BASE_URL}/link/unlock?agent=evoscrapper"
                async with session.post(unlock_url, headers=self._headers(), data={"link": link_url}) as resp:
                    if resp.status == 200:
                        unres = await resp.json()
                        stream_link = unres.get("data", {}).get("link")
                        if stream_link:
                            return DebridStreamResult(
                                url=stream_link,
                                filename=filename,
                                size=size,
                                provider="AllDebrid",
                                cached=True,
                            )
            except Exception as e:
                print(f"[AllDebrid] Resolve error: {e}")

        return None

    async def get_user_info(self) -> Dict[str, Any]:
        if not self.is_configured:
            return {"configured": False, "provider": self.provider_name}
        try:
            timeout = aiohttp.ClientTimeout(total=5.0)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                url = f"{self.BASE_URL}/user?agent=evoscrapper"
                async with session.get(url, headers=self._headers()) as resp:
                    if resp.status == 200:
                        d = (await resp.json()).get("data", {}).get("user", {})
                        return {
                            "configured": True,
                            "provider": self.provider_name,
                            "username": d.get("username"),
                            "premium": d.get("isPremium", False),
                            "expiration": d.get("premiumUntil"),
                        }
        except Exception:
            pass
        return {"configured": True, "provider": self.provider_name, "valid": False}
