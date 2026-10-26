"""
P4 completion: streaming with automatic cross-source failover.

Serves a video stream from an ordered list of candidate sources (e.g. Debrid
CDN first, P2P swarm as warm backup). If the active source stalls or dies
mid-stream, the generator resumes from the exact byte offset on the next
candidate — the player never sees an error, just a brief pause.
"""
import asyncio
from typing import AsyncGenerator, Dict, List, Optional, Tuple

import aiohttp

from core.logger import streaming_logger

FAILOVER_CHUNK_SIZE = 256 * 1024


def _range_start(range_header: Optional[str]) -> int:
    if not range_header:
        return 0
    try:
        start = range_header.split("=")[1].split("-")[0]
        return max(0, int(start))
    except (IndexError, ValueError):
        return 0


def _resume_range(original_range: Optional[str], served: int, total: Optional[int]) -> Optional[str]:
    """Builds the Range header that continues the stream at the byte offset."""
    start = _range_start(original_range) + served
    if total is not None and start >= total:
        return None
    return f"bytes={start}-"


async def _open_source(
    session: aiohttp.ClientSession,
    url: str,
    range_header: Optional[str],
    api_key: Optional[str],
    connect_timeout: float,
) -> Optional[Tuple[aiohttp.ClientResponse, Optional[int]]]:
    headers = {}
    if range_header:
        headers["Range"] = range_header
    if api_key:
        headers["X-API-Key"] = api_key
    try:
        resp = await session.get(
            url,
            headers=headers,
            timeout=aiohttp.ClientTimeout(total=None, sock_connect=connect_timeout, sock_read=45.0),
        )
    except Exception:
        return None
    if resp.status not in (200, 206):
        resp.close()
        return None
    total: Optional[int] = None
    content_range = resp.headers.get("Content-Range", "")
    if "/" in content_range:
        try:
            total = int(content_range.rsplit("/", 1)[1])
        except (IndexError, ValueError):
            total = None
    if total is None:
        length = resp.headers.get("Content-Length")
        if length and resp.status == 200:
            try:
                total = int(length)
            except ValueError:
                total = None
    return resp, total


async def stream_with_failover(
    session: aiohttp.ClientSession,
    candidate_urls: List[str],
    original_range: Optional[str] = None,
    api_key: Optional[str] = None,
    connect_timeout: float = 4.0,
) -> AsyncGenerator[bytes, None]:
    """
    Streams from the first healthy candidate; on mid-stream failure resumes at
    the exact byte offset on the next candidate. Yields nothing when every
    source fails (the client's own reconnect logic takes over).
    """
    for index, url in enumerate(candidate_urls):
        if not url:
            continue
        served = 0
        # index 0 uses the client's original Range; later hops use the
        # accumulated resume range computed after each failover.
        range_header = original_range
        opened = await _open_source(session, url, range_header, api_key, connect_timeout)
        if not opened:
            streaming_logger.info(f"[FailoverStream] candidate {index} unavailable: {url[:80]}")
            continue
        resp, total = opened
        try:
            async for chunk in resp.content.iter_chunked(FAILOVER_CHUNK_SIZE):
                served += len(chunk)
                yield chunk
            # Clean EOF on this source: done entirely.
            if total is None or _range_start(original_range or "") + served >= total:
                return
            # Source ended early but claims more bytes: fail over.
            streaming_logger.info(f"[FailoverStream] candidate {index} ended early at {served} bytes")
        except (asyncio.CancelledError, GeneratorExit):
            resp.close()
            raise
        except Exception as e:
            streaming_logger.info(f"[FailoverStream] candidate {index} failed mid-stream: {e}")
        finally:
            if not resp.closed:
                resp.close()

        # Fail over from the exact byte offset.
        original_range = _resume_range(original_range, served, total)
        if original_range is None:
            return
    return
