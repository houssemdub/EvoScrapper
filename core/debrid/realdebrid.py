import asyncio
import os
from typing import Any, Dict, List, Optional
import aiohttp

from core.debrid.base import DebridClient, DebridStreamResult


class RealDebridClient(DebridClient):
    """
    Real-Debrid API v2 Client.
    Supports instant cache probing and unthrottled 1Gbps direct HTTPS cloud streaming.
    """

    BASE_URL = "https://api.real-debrid.com/rest/1.0"

    def __init__(self, api_key: Optional[str] = None):
        key = api_key or os.getenv("REALDEBRID_API_KEY", "")
        super().__init__(api_key=key)
        self.provider_name = "RealDebrid"

    def _headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "User-Agent": "EvoScrapper/2.0",
        }

    async def check_cache(self, info_hashes: List[str]) -> Dict[str, bool]:
        if not self.is_configured or not info_hashes:
            return {h.lower(): False for h in info_hashes}

        clean_hashes = [h.strip().lower() for h in info_hashes if h and len(h.strip()) == 40]
        if not clean_hashes:
            return {}

        results: Dict[str, bool] = {h: False for h in clean_hashes}
        
        # Real-Debrid allows up to 50 hashes per check
        chunk_size = 40
        chunks = [clean_hashes[i:i + chunk_size] for i in range(0, len(clean_hashes), chunk_size)]

        timeout = aiohttp.ClientTimeout(total=6.0)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            for chunk in chunks:
                url = f"{self.BASE_URL}/torrents/instantAvailability/{'/'.join(chunk)}"
                try:
                    async with session.get(url, headers=self._headers()) as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            if isinstance(data, dict):
                                for h, info in data.items():
                                    hash_lower = h.lower()
                                    if isinstance(info, dict) and "rd" in info and len(info["rd"]) > 0:
                                        results[hash_lower] = True
                        elif resp.status in (401, 403):
                            # Invalid API key
                            break
                except Exception as e:
                    print(f"[RealDebrid] Cache check warning: {e}")

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
                # 1. Add Magnet to Real-Debrid
                add_url = f"{self.BASE_URL}/torrents/addMagnet"
                async with session.post(add_url, headers=self._headers(), data={"magnet": mag}) as resp:
                    if resp.status not in (200, 201):
                        return None
                    add_data = await resp.json()
                    torrent_id = add_data.get("id")
                    if not torrent_id:
                        return None

                # 2. Select All Files
                select_url = f"{self.BASE_URL}/torrents/selectFiles/{torrent_id}"
                async with session.post(select_url, headers=self._headers(), data={"files": "all"}):
                    pass

                # 3. Poll Torrent Info for Generated Links (up to 3 attempts)
                info_url = f"{self.BASE_URL}/torrents/info/{torrent_id}"
                links: List[str] = []
                filename = "Stream"
                filesize = 0
                for _ in range(3):
                    await asyncio.sleep(0.3)
                    async with session.get(info_url, headers=self._headers()) as resp:
                        if resp.status == 200:
                            info_data = await resp.json()
                            status = info_data.get("status")
                            links = info_data.get("links", [])
                            filename = info_data.get("filename", filename)
                            filesize = info_data.get("bytes", 0)
                            if links:
                                break

                if not links:
                    return None

                # Pick link corresponding to matched episode or file_idx
                files_list = info_data.get("files", [])
                chosen_link_idx = file_idx
                if (season is not None or episode is not None) and files_list:
                    from core.file_matcher import select_target_file
                    matched_file_idx = select_target_file(files_list, season=season, episode=episode, requested_idx=file_idx)
                    selected_files = [f for f in files_list if f.get("selected") == 1]
                    if not selected_files:
                        selected_files = files_list
                    try:
                        chosen_link_idx = next(idx for idx, f in enumerate(selected_files) if f.get("id") == files_list[matched_file_idx].get("id"))
                    except Exception:
                        chosen_link_idx = 0

                target_link = links[chosen_link_idx] if 0 <= chosen_link_idx < len(links) else links[0]

                # 4. Unrestrict link for direct 1Gbps HTTPS CDN access
                unrestrict_url = f"{self.BASE_URL}/unrestrict/link"
                async with session.post(unrestrict_url, headers=self._headers(), data={"link": target_link}) as resp:
                    if resp.status == 200:
                        unres_data = await resp.json()
                        download_url = unres_data.get("download")
                        if download_url:
                            return DebridStreamResult(
                                url=download_url,
                                filename=unres_data.get("filename", filename),
                                size=unres_data.get("filesize", filesize),
                                provider="RealDebrid",
                                cached=True,
                                mime_type=unres_data.get("mimeType", "video/mp4"),
                            )

            except Exception as e:
                print(f"[RealDebrid] Resolve error: {e}")

        return None

    async def get_user_info(self) -> Dict[str, Any]:
        if not self.is_configured:
            return {"configured": False, "provider": self.provider_name}

        timeout = aiohttp.ClientTimeout(total=5.0)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            try:
                url = f"{self.BASE_URL}/user"
                async with session.get(url, headers=self._headers()) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        return {
                            "configured": True,
                            "provider": self.provider_name,
                            "username": data.get("username"),
                            "premium": data.get("type") == "premium",
                            "expiration": data.get("expiration"),
                        }
            except Exception:
                pass

        return {"configured": True, "provider": self.provider_name, "valid": False}
