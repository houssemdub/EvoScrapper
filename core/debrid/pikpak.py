import asyncio
import os
import time
from typing import Any, Dict, List, Optional
import aiohttp

from core.debrid.base import DebridClient, DebridStreamResult


class PikPakClient(DebridClient):
    """
    PikPak Cloud Drive API Client.
    Supports high-speed cloud torrent caching and unthrottled streaming links.
    API Docs: https://api-drive.mypikpak.com
    """

    BASE_URL = "https://api-drive.mypikpak.com"
    AUTH_URL = "https://user.mypikpak.com/v1/auth"

    def __init__(
        self,
        api_key: Optional[str] = None,
        username: Optional[str] = None,
        password: Optional[str] = None,
    ):
        key = api_key or os.getenv("PIKPAK_API_KEY", "")
        super().__init__(api_key=key)
        self.username = username or os.getenv("PIKPAK_USER", "")
        self.password = password or os.getenv("PIKPAK_PASSWORD", "")
        self.provider_name = "PikPak"
        self._access_token: Optional[str] = self.api_key if self.api_key else None
        self._token_expires: float = 0.0

    @property
    def is_configured(self) -> bool:
        return bool(self.api_key or (self.username and self.password))

    async def _ensure_token(self, session: aiohttp.ClientSession) -> Optional[str]:
        if self._access_token and time.time() < self._token_expires:
            return self._access_token
        if self.api_key and not self.username:
            self._access_token = self.api_key
            self._token_expires = time.time() + 86400
            return self._access_token
        if not self.username or not self.password:
            return None

        try:
            url = f"{self.AUTH_URL}/signin"
            payload = {
                "client_id": "YNxT9w7GMdW5wX9q",
                "username": self.username,
                "password": self.password,
            }
            async with session.post(url, json=payload, timeout=6.0) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    self._access_token = data.get("access_token")
                    expires_in = data.get("expires_in", 7200)
                    self._token_expires = time.time() + float(expires_in) - 60
                    return self._access_token
        except Exception as e:
            print(f"[PikPak] Auth error: {e}")
        return None

    def _headers(self, token: str) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {token}",
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
            token = await self._ensure_token(session)
            if not token:
                return results

            try:
                # Check task batch availability
                for h in clean_hashes[:20]:
                    url = f"{self.BASE_URL}/drive/v1/task?type=offline"
                    # Query cloud records for cached hash
                    async with session.get(url, headers=self._headers(token)) as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            tasks = data.get("tasks", [])
                            for t in tasks:
                                if t.get("phase") == "PHASE_TYPE_COMPLETE":
                                    params = t.get("params", {})
                                    if h in params.get("url", "").lower():
                                        results[h] = True
            except Exception as e:
                print(f"[PikPak] Cache check warning: {e}")

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
            token = await self._ensure_token(session)
            if not token:
                return None

            try:
                # 1. Create offline magnet download task
                url = f"{self.BASE_URL}/drive/v1/files"
                body = {
                    "kind": "drive#file",
                    "folder_type": "DOWNLOAD",
                    "upload_type": "UPLOAD_TYPE_URL",
                    "url": {"url": mag},
                }
                async with session.post(url, headers=self._headers(token), json=body) as resp:
                    if resp.status not in (200, 201):
                        return None
                    data = await resp.json()
                    task_info = data.get("task", {})
                    file_info = data.get("file", {})
                    file_id = file_info.get("id") or task_info.get("file_id")

                    if not file_id:
                        # Poll task status briefly if file_id is pending
                        task_id = task_info.get("id")
                        if task_id:
                            for _ in range(3):
                                await asyncio.sleep(0.5)
                                t_url = f"{self.BASE_URL}/drive/v1/tasks/{task_id}"
                                async with session.get(t_url, headers=self._headers(token)) as t_resp:
                                    if t_resp.status == 200:
                                        t_data = await t_resp.json()
                                        file_id = t_data.get("file_id")
                                        if file_id:
                                            break

                if not file_id:
                    return None

                # 2. Get file details and direct stream link
                detail_url = f"{self.BASE_URL}/drive/v1/files/{file_id}"
                async with session.get(detail_url, headers=self._headers(token)) as resp:
                    if resp.status == 200:
                        f_data = await resp.json()
                        stream_url = f_data.get("web_content_link")
                        if not stream_url:
                            medias = f_data.get("medias", [])
                            if medias:
                                stream_url = medias[0].get("link", {}).get("url")

                        filename = f_data.get("name", "PikPakStream.mp4")
                        size = int(f_data.get("size") or 0)

                        if stream_url:
                            return DebridStreamResult(
                                url=stream_url,
                                filename=filename,
                                size=size,
                                provider="PikPak",
                                cached=True,
                            )
            except Exception as e:
                print(f"[PikPak] Resolve error: {e}")

        return None

    async def get_user_info(self) -> Dict[str, Any]:
        if not self.is_configured:
            return {"configured": False, "provider": self.provider_name}
        try:
            timeout = aiohttp.ClientTimeout(total=5.0)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                token = await self._ensure_token(session)
                if not token:
                    return {"configured": True, "provider": self.provider_name, "valid": False}
                url = f"{self.BASE_URL}/drive/v1/about"
                async with session.get(url, headers=self._headers(token)) as resp:
                    if resp.status == 200:
                        d = await resp.json()
                        return {
                            "configured": True,
                            "provider": self.provider_name,
                            "username": self.username or "PikPak User",
                            "quota": d.get("quota", {}),
                            "premium": True,
                        }
        except Exception:
            pass
        return {"configured": True, "provider": self.provider_name, "valid": False}
