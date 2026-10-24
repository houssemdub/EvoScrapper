import asyncio
from typing import Any, Dict, Optional
import httpx
from curl_cffi.requests import AsyncSession as CurlAsyncSession
from config import settings


DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "DNT": "1",
    "Upgrade-Insecure-Requests": "1",
}

JSON_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
}


class HttpClient:
    """
    Unified async HTTP client.
    Features:
    - Standard high-concurrency requests via HTTPX with connection pooling.
    - Cloudflare / TLS fingerprint evasion via curl_cffi when requested.
    """

    def __init__(self):
        self._httpx_client: Optional[httpx.AsyncClient] = None
        self._client_loop: Optional[asyncio.AbstractEventLoop] = None
        self._curl_session: Optional[CurlAsyncSession] = None
        self._curl_loop: Optional[asyncio.AbstractEventLoop] = None
        self._lock: Optional[asyncio.Lock] = None
        self._lock_loop: Optional[asyncio.AbstractEventLoop] = None

    def _get_lock(self) -> asyncio.Lock:
        current_loop = asyncio.get_running_loop()
        if self._lock is None or self._lock_loop != current_loop:
            self._lock = asyncio.Lock()
            self._lock_loop = current_loop
        return self._lock

    async def get_httpx_client(self) -> httpx.AsyncClient:
        current_loop = asyncio.get_running_loop()
        lock = self._get_lock()
        async with lock:
            if (
                self._httpx_client is None
                or self._httpx_client.is_closed
                or self._client_loop != current_loop
            ):
                proxies = settings.HTTP_PROXY if settings.HTTP_PROXY else None
                self._httpx_client = httpx.AsyncClient(
                    proxy=proxies,
                    timeout=httpx.Timeout(settings.DEFAULT_TIMEOUT, connect=3.0),
                    headers=DEFAULT_HEADERS,
                    follow_redirects=True,
                    http2=True,
                )
                self._client_loop = current_loop
            return self._httpx_client

    async def get_curl_session(self) -> CurlAsyncSession:
        current_loop = asyncio.get_running_loop()
        lock = self._get_lock()
        async with lock:
            if self._curl_session is None or self._curl_loop != current_loop:
                proxy = settings.HTTP_PROXY if settings.HTTP_PROXY else None
                self._curl_session = CurlAsyncSession(
                    impersonate="chrome120",
                    proxy=proxy,
                    timeout=settings.DEFAULT_TIMEOUT,
                )
                self._curl_loop = current_loop
            return self._curl_session

    async def get_text(
        self,
        url: str,
        params: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
        timeout: Optional[float] = None,
        use_stealth: bool = False,
    ) -> str:
        """Fetches text/HTML from a URL."""
        req_headers = {**DEFAULT_HEADERS, **(headers or {})}
        t = timeout or settings.DEFAULT_TIMEOUT

        if use_stealth:
            curl = await self.get_curl_session()
            resp = await curl.get(url, params=params, headers=req_headers, timeout=t)
            if resp.status_code >= 400:
                raise RuntimeError(f"HTTP error {resp.status_code} while fetching {url}")
            return resp.text

        client = await self.get_httpx_client()
        resp = await client.get(url, params=params, headers=req_headers, timeout=t)
        resp.raise_for_status()
        return resp.text

    async def get_json(
        self,
        url: str,
        params: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
        timeout: Optional[float] = None,
        use_stealth: bool = False,
    ) -> Any:
        """Fetches and parses JSON from a URL."""
        req_headers = {**JSON_HEADERS, **(headers or {})}
        t = timeout or settings.DEFAULT_TIMEOUT

        if use_stealth:
            curl = await self.get_curl_session()
            resp = await curl.get(url, params=params, headers=req_headers, timeout=t)
            if resp.status_code >= 400:
                raise RuntimeError(f"HTTP error {resp.status_code} while fetching {url}")
            return resp.json()

        client = await self.get_httpx_client()
        resp = await client.get(url, params=params, headers=req_headers, timeout=t)
        resp.raise_for_status()
        return resp.json()

    async def post_json(
        self,
        url: str,
        json_data: Any = None,
        params: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
        timeout: Optional[float] = None,
    ) -> Any:
        """Performs an async POST request with a JSON payload."""
        req_headers = {**JSON_HEADERS, **(headers or {})}
        client = await self.get_httpx_client()
        t = timeout or settings.DEFAULT_TIMEOUT
        resp = await client.post(url, json=json_data, params=params, headers=req_headers, timeout=t)
        resp.raise_for_status()
        return resp.json()

    async def close(self):
        """Clean shutdown of underlying connection pools."""
        if self._httpx_client and not self._httpx_client.is_closed:
            await self._httpx_client.aclose()
            self._httpx_client = None
        if self._curl_session:
            # curl_cffi session close
            try:
                await self._curl_session.close()
            except Exception:
                pass
            self._curl_session = None


http_client = HttpClient()
