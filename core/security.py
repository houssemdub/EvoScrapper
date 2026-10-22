import hmac
import ipaddress
import socket
import urllib.parse
from typing import Optional
from fastapi import HTTPException, Security, status
from fastapi.security import APIKeyHeader
from config import settings

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


def validate_outbound_proxy_url(target_url: str) -> str:
    """
    SSRF safeguard: validates outbound proxy target URLs for subtitles and external proxies.
    Rejects disallowed schemes, unresolvable hosts, loopback, link-local,
    and private RFC1918 IP addresses.
    """
    if not target_url or not isinstance(target_url, str):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing or invalid target URL.",
        )

    parsed = urllib.parse.urlparse(target_url.strip())
    if parsed.scheme.lower() not in ("http", "https"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Disallowed URL scheme '{parsed.scheme}'. Only http and https are permitted.",
        )

    hostname = parsed.hostname
    if not hostname:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid host in target URL.",
        )

    # Check for direct IP address or resolve DNS
    try:
        try:
            ip_addr = ipaddress.ip_address(hostname)
        except ValueError:
            # Not an IP literal, resolve via DNS
            resolved_ip_str = socket.gethostbyname(hostname)
            ip_addr = ipaddress.ip_address(resolved_ip_str)

        if ip_addr.is_private or ip_addr.is_loopback or ip_addr.is_link_local or ip_addr.is_reserved or ip_addr.is_multicast:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access to private, loopback, or internal network addresses is forbidden.",
            )
    except socket.gaierror:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Could not resolve host '{hostname}'.",
        )

    return target_url


async def verify_api_key(x_api_key: Optional[str] = Security(api_key_header)):
    """
    Validates API key if configured in settings.
    If no API_KEY is set in settings, authentication is bypassed.
    """
    if settings.API_KEY:
        if not x_api_key or not hmac.compare_digest(x_api_key, settings.API_KEY):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access forbidden: Invalid or missing API key.",
            )
    return True
