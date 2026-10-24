import asyncio
import os
from typing import Any, Dict, List, Optional
import aiohttp

from core.debrid.base import DebridClient, DebridStreamResult


class PremiumizeClient(DebridClient):
    """
    Premiumize.me API Client.
    Supports instant batch cache probing and direct 1-step directdl stream resolution.
    API Docs: https://www.premiumize.me/api
    """

    BASE_URL = "https://www.premiumize.me/api"

    def __init__(self, api_key: Optional[str] = None):
        key = api_key or os.getenv("PREMIUMIZE_API_KEY", "")
        super().__init__(api_key=key)
        self.provider_name = "Premiumize"

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
                # Premiumize cache/check accepts items[]=hash1&items[]=hash2
                params = [("items[]", h) for h in clean_hashes[:50]]
                url = f"{self.BASE_URL}/cache/check?apikey={self.api_key}"
                async with session.post(url, headers=self._headers(), data=params) as resp:
                    if resp.status == 200:
                        payload = await resp.json()
                        if payload.get("status") == "success":
                            cached_flags = payload.get("response", [])
                            for idx, is_cached in enumerate(cached_flags):
                                if idx < len(clean_hashes) and is_cached:
                                    results[clean_hashes[idx]] = True
            except Exception as e:
                print(f"[Premiumize] Cache check warning: {e}")

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
                # Premiumize /transfer/directdl immediately returns direct links for cached torrents
                url = f"{self.BASE_URL}/transfer/directdl"
                data = {"src": mag, "apikey": self.api_key}
                async with session.post(url, headers=self._headers(), data=data) as resp:
                    if resp.status != 200:
                        return None
                    payload = await resp.json()
                    if payload.get("status") != "success":
                        return None

                    content = payload.get("content", [])
                    if not content:
                        return None

                    chosen_idx = file_idx
                    if (season is not None or episode is not None) and content:
                        from core.file_matcher import select_target_file
                        chosen_idx = select_target_file(content, season=season, episode=episode, requested_idx=file_idx) or 0

                    target = content[chosen_idx] if 0 <= chosen_idx < len(content) else content[0]
                    stream_url = target.get("link") or target.get("stream_link")
                    filename = target.get("path", "Stream.mp4").split("/")[-1]
                    size = target.get("size", 0)

                    if stream_url:
                        return DebridStreamResult(
                            url=stream_url,
                            filename=filename,
                            size=size,
                            provider="Premiumize",
                            cached=True,
                        )
            except Exception as e:
                print(f"[Premiumize] Resolve error: {e}")

        return None

    async def get_user_info(self) -> Dict[str, Any]:
        if not self.is_configured:
            return {"configured": False, "provider": self.provider_name}
        try:
            timeout = aiohttp.ClientTimeout(total=5.0)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                url = f"{self.BASE_URL}/account/info?apikey={self.api_key}"
                async with session.get(url, headers=self._headers()) as resp:
                    if resp.status == 200:
                        d = await resp.json()
                        if d.get("status") == "success":
                            prem_until = d.get("premium_until")
                            return {
                                "configured": True,
                                "provider": self.provider_name,
                                "customer_id": d.get("customer_id"),
                                "premium": bool(prem_until and prem_until > 0),
                                "expiration": prem_until,
                            }
        except Exception:
            pass
        return {"configured": True, "provider": self.provider_name, "valid": False}
