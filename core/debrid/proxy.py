import base64
import hashlib
import hmac
import json
import time
from typing import Any, AsyncGenerator, Dict, Optional, Tuple
import httpx

from config import settings
from core.security import validate_outbound_proxy_url


class DebridStreamProxy:
    """
    Debrid Multi-IP Stream Proxy Gateway.
    Allows multiple household devices/clients to stream from unchained Debrid
    links through the EvoScrapper server IP without triggering Real-Debrid /
    AllDebrid simultaneous multi-IP access bans.
    """

    def __init__(self, secret_key: Optional[str] = None):
        self.secret_key = (secret_key or getattr(settings, "DEBRID_PROXY_SECRET", "evoscrapper-debrid-proxy-secret-key")).encode("utf-8")

    def generate_token(self, upstream_url: str, filename: Optional[str] = None, expires_in: int = 86400) -> str:
        """
        Generates an HMAC-SHA256 signed tamper-proof proxy token.
        """
        payload = {
            "url": upstream_url,
            "filename": filename or "",
            "exp": int(time.time()) + expires_in,
        }
        raw_json = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        b64_payload = base64.urlsafe_b64encode(raw_json).decode("ascii").rstrip("=")
        sig = hmac.new(self.secret_key, b64_payload.encode("ascii"), hashlib.sha256).hexdigest()
        return f"{b64_payload}.{sig}"

    def verify_token(self, token: str) -> Optional[Dict[str, Any]]:
        """
        Verifies and extracts payload from signed token. Returns None if invalid or expired.
        """
        if not token or "." not in token:
            return None
        parts = token.split(".")
        if len(parts) != 2:
            return None

        b64_payload, sig = parts
        expected_sig = hmac.new(self.secret_key, b64_payload.encode("ascii"), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(sig, expected_sig):
            return None

        try:
            # Add back base64 padding
            rem = len(b64_payload) % 4
            padded = b64_payload + ("=" * (4 - rem) if rem else "")
            raw_json = base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8")
            payload = json.loads(raw_json)

            exp = payload.get("exp", 0)
            if time.time() > exp:
                return None
            return payload
        except Exception:
            return None

    def get_proxy_url(
        self,
        upstream_url: str,
        filename: Optional[str] = None,
        base_path: str = "/api/v1/stream/debrid/proxy",
    ) -> str:
        """
        Constructs the client-facing proxy URL with embedded token.
        """
        token = self.generate_token(upstream_url, filename=filename)
        fn_param = f"&filename={filename}" if filename else ""
        return f"{base_path}?token={token}{fn_param}"

    async def create_upstream_stream(
        self,
        upstream_url: str,
        incoming_headers: Optional[Dict[str, str]] = None,
    ) -> Tuple[AsyncGenerator[bytes, None], int, Dict[str, str]]:
        """
        Initiates a streaming connection to the upstream Debrid CDN.
        Passes through HTTP Range headers and returns an async generator for bytes.
        Validates target URL against SSRF before connecting.
        """
        validate_outbound_proxy_url(upstream_url)

        headers_to_send: Dict[str, str] = {
            "User-Agent": (incoming_headers or {}).get("user-agent", "EvoScrapper/2.0 (Video Stream Proxy)")
        }

        if incoming_headers:
            range_val = incoming_headers.get("range") or incoming_headers.get("Range")
            if range_val:
                headers_to_send["Range"] = range_val

        client = httpx.AsyncClient(
            follow_redirects=True,
            timeout=httpx.Timeout(connect=15.0, read=None, write=30.0, pool=None),
        )

        req = client.build_request("GET", upstream_url, headers=headers_to_send)
        resp = await client.send(req, stream=True)

        status_code = resp.status_code
        out_headers: Dict[str, str] = {}

        for k in ["content-range", "content-length", "content-type", "accept-ranges", "content-disposition"]:
            val = resp.headers.get(k)
            if val:
                header_name = "-".join([part.capitalize() for part in k.split("-")])
                out_headers[header_name] = val

        if "Accept-Ranges" not in out_headers:
            out_headers["Accept-Ranges"] = "bytes"

        async def stream_generator() -> AsyncGenerator[bytes, None]:
            try:
                async for chunk in resp.aiter_bytes(chunk_size=128 * 1024):
                    yield chunk
            finally:
                await resp.aclose()
                await client.aclose()

        return stream_generator(), status_code, out_headers


_proxy_instance: Optional[DebridStreamProxy] = None


def get_debrid_proxy() -> DebridStreamProxy:
    global _proxy_instance
    if _proxy_instance is None:
        _proxy_instance = DebridStreamProxy()
    return _proxy_instance
