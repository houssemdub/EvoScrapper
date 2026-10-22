import asyncio
import os
from typing import Any, Dict, List, Optional
import aiohttp

from core.debrid.base import DebridClient, DebridStreamResult


class TorboxClient(DebridClient):
    """
    TorBox API Client.
    Next-gen debrid provider with fast instant availability probing and high-speed streaming.
    """

    BASE_URL = "https://api.torbox.app/v1/api"

    def __init__(self, api_key: Optional[str] = None):
        key = api_key or os.getenv("TORBOX_API_KEY", "")
        super().__init__(api_key=key)
        self.provider_name = "TorBox"

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

        timeout = aiohttp.ClientTimeout(total=5.0)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            try:
                # Torbox allows comma separated hashes
                hash_list = ",".join(clean_hashes[:50])
                url = f"{self.BASE_URL}/torrents/checkcached?hash={hash_list}&format=object"
                async with session.get(url, headers=self._headers()) as resp:
                    if resp.status == 200:
                        payload = await resp.json()
                        data = payload.get("data", {})
                        if isinstance(data, dict):
                            for h, val in data.items():
                                hash_lower = h.lower()
                                if val:
                                    results[hash_lower] = True
            except Exception as e:
                print(f"[TorBox] Cache check warning: {e}")

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

        timeout = aiohttp.ClientTimeout(total=15.0)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            try:
                # 1. Create torrent entry in TorBox
                url = f"{self.BASE_URL}/torrents/createtorrent"
                async with session.post(url, headers=self._headers(), data={"magnet": mag}) as resp:
                    if resp.status not in (200, 201):
                        return None
                    payload = await resp.json()
                    data_obj = payload.get("data", {})
                    torrent_id = data_obj.get("torrent_id")
                    if not torrent_id:
                        return None

                    files = data_obj.get("files", [])
                    chosen_file_id = file_idx
                    if (season is not None or episode is not None) and files:
                        from core.file_matcher import select_target_file
                        matched_idx = select_target_file(files, season=season, episode=episode, requested_idx=file_idx) or 0
                        chosen_file_id = files[matched_idx].get("id", file_idx)

                # 2. Request download link
                req_url = f"{self.BASE_URL}/torrents/requestdl?token={self.api_key}&torrent_id={torrent_id}&file_id={chosen_file_id}&zip=false"
                async with session.get(req_url, headers=self._headers()) as resp:
                    if resp.status == 200:
                        dl_data = await resp.json()
                        dl_url = dl_data.get("data")
                        if dl_url and isinstance(dl_url, str):
                            return DebridStreamResult(
                                url=dl_url,
                                filename="TorboxStream.mp4",
                                size=0,
                                provider="TorBox",
                                cached=True,
                            )
            except Exception as e:
                print(f"[TorBox] Resolve error: {e}")

        return None

    async def get_user_info(self) -> Dict[str, Any]:
        if not self.is_configured:
            return {"configured": False, "provider": self.provider_name}
        try:
            timeout = aiohttp.ClientTimeout(total=5.0)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                url = f"{self.BASE_URL}/user/me"
                async with session.get(url, headers=self._headers()) as resp:
                    if resp.status == 200:
                        d = (await resp.json()).get("data", {})
                        return {
                            "configured": True,
                            "provider": self.provider_name,
                            "email": d.get("email"),
                            "premium": d.get("plan", 0) > 0,
                        }
        except Exception:
            pass
        return {"configured": True, "provider": self.provider_name, "valid": False}
