import asyncio
import hashlib
import hmac
import ipaddress
import socket
import time
import urllib.parse
from typing import Dict, Optional
import httpx
from fastapi import HTTPException, Request, Security, status
from fastapi.security import APIKeyHeader
from config import settings

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)

SESSION_COOKIE_NAME = "evo_session"
SESSION_TTL_SECONDS = 12 * 60 * 60


def _session_signing_key() -> bytes:
    """Derives the session signing key from the configured API key."""
    return hashlib.sha256(
        f"evo-session:{settings.API_KEY or ''}".encode("utf-8")
    ).digest()


def create_session_token(ttl: int = SESSION_TTL_SECONDS) -> str:
    """Creates an expiry-bound session token for HttpOnly cookie auth."""
    expires = int(time.time()) + int(ttl)
    signature = hmac.new(
        _session_signing_key(), str(expires).encode("utf-8"), hashlib.sha256
    ).hexdigest()
    return f"{expires}.{signature}"


def verify_session_token(token: Optional[str]) -> bool:
    """Validates a session token and its expiry with constant-time comparison."""
    if not token or not settings.API_KEY:
        return False
    try:
        expires_raw, signature = token.split(".", 1)
        expires = int(expires_raw)
    except (TypeError, ValueError):
        return False
    if expires < int(time.time()):
        return False
    expected = hmac.new(
        _session_signing_key(), str(expires).encode("utf-8"), hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, signature)


def validate_outbound_proxy_url(target_url: str) -> str:
    """
    Reject malformed URLs and hosts with any non-public IPv4/IPv6 address.
    This checks DNS results, not the eventual connection's resolved address.
    """
    if not target_url or not isinstance(target_url, str):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing or invalid target URL.",
        )

    target_url = target_url.strip()
    if any(ord(char) < 32 or ord(char) == 127 for char in target_url):
        raise HTTPException(status_code=400, detail="Control characters are not allowed in target URLs.")
    try:
        parsed = urllib.parse.urlparse(target_url)
        hostname = parsed.hostname
        port = parsed.port
    except ValueError:
        raise HTTPException(status_code=400, detail="Malformed host or port in target URL.")
    if parsed.scheme.lower() not in ("http", "https"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Disallowed URL scheme '{parsed.scheme}'. Only http and https are permitted.",
        )

    if not hostname or port == 0 or parsed.username is not None or parsed.password is not None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid host, port, or URL credentials in target URL.",
        )

    try:
        try:
            addresses = [ipaddress.ip_address(hostname)]
        except ValueError:
            resolved = socket.getaddrinfo(
                hostname, port or (443 if parsed.scheme.lower() == "https" else 80),
                type=socket.SOCK_STREAM,
            )
            addresses = [ipaddress.ip_address(item[4][0]) for item in resolved]
            if not addresses:
                raise socket.gaierror("No addresses returned")

        for address in addresses:
            address = getattr(address, "ipv4_mapped", None) or address
            if not address.is_global or address.is_reserved or address.is_multicast:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Access to private, loopback, or internal network addresses is forbidden.",
                )
    except (socket.gaierror, ValueError):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Could not resolve host '{hostname}'.",
        )

    return target_url


async def fetch_public_url(
    client: httpx.AsyncClient,
    target_url: str,
    *,
    headers: Optional[Dict[str, str]] = None,
    timeout: Optional[float] = None,
    stream: bool = False,
) -> httpx.Response:
    """GET a public URL, validating every hop and closing unread redirects."""
    request_headers = httpx.Headers(headers or {})
    request_headers.pop("host", None)
    strip_credentials = False
    timeout_args = {"timeout": timeout} if timeout is not None else {}

    for hop in range(6):
        target_url = await asyncio.to_thread(validate_outbound_proxy_url, target_url)
        try:
            request = client.build_request("GET", target_url, headers=request_headers, **timeout_args)
            if strip_credentials:
                for name in ("authorization", "cookie", "proxy-authorization"):
                    request.headers.pop(name, None)
            response = await client.send(request, stream=True, follow_redirects=False, auth=None)
        except (httpx.InvalidURL, ValueError):
            raise HTTPException(status_code=400, detail="Malformed outbound URL or redirect.")

        location = response.headers.get("location")
        if response.status_code in (301, 302, 303, 307, 308) and location:
            await response.aclose()
            if hop == 5:
                raise HTTPException(status_code=400, detail="Too many outbound redirects.")
            try:
                redirect_url = urllib.parse.urljoin(target_url, location)
                next_url = httpx.URL(redirect_url)
            except (httpx.InvalidURL, ValueError):
                raise HTTPException(status_code=400, detail="Malformed outbound redirect.")
            if (next_url.scheme, next_url.host, next_url.port) != (request.url.scheme, request.url.host, request.url.port):
                strip_credentials = True
            target_url = redirect_url
            continue

        if not stream:
            try:
                await response.aread()
            finally:
                await response.aclose()
        return response


async def verify_api_key(
    request: Request,
    x_api_key: Optional[str] = Security(api_key_header),
):
    """
    Validates the configured API key from an X-API-Key header or the signed
    HttpOnly session cookie. The cookie path lets fetch, EventSource, and
    <video>/HLS media requests authenticate without exposing the long-lived
    key in playback URLs.

    If no API_KEY is set in settings, authentication is bypassed.
    """
    if settings.API_KEY:
        header_ok = bool(x_api_key) and hmac.compare_digest(x_api_key, settings.API_KEY)
        if not header_ok and not verify_session_token(
            request.cookies.get(SESSION_COOKIE_NAME)
        ):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access forbidden: Invalid or missing API key.",
            )
    return True
