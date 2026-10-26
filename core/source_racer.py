"""P4 dual-source racing and P5 quality ladder candidate selection."""
import asyncio
import sys
import os
import time
from typing import Any, Dict, List, Optional, Tuple

import aiohttp

from config import settings
from core.logger import streaming_logger


async def _fetch_probe(url: str, api_key: Optional[str], timeout: float = 3.0) -> bool:
    """Downloads the first 256KB of a candidate source. Returns True on success."""
    headers = {"Range": "bytes=0-262143"}
    if api_key:
        headers["X-API-Key"] = api_key
    try:
        session = await get_shared_session()
        async with session.get(
            url,
            headers=headers,
            timeout=aiohttp.ClientTimeout(total=timeout, sock_connect=2.0),
        ) as resp:
            if resp.status not in (200, 206):
                return False
            # Consume a chunk to prove real bytes flow, not just headers.
            chunk = await resp.content.read(65536)
            return bool(chunk)
    except Exception:
        return False


_session: Optional[aiohttp.ClientSession] = None


async def get_shared_session() -> aiohttp.ClientSession:
    global _session
    if _session is None or _session.closed:
        _session = aiohttp.ClientSession()
    return _session


async def close_shared_session() -> None:
    global _session
    if _session and not _session.closed:
        await _session.close()
    _session = None


async def race_stream_sources(
    p2p_url: Optional[str],
    debrid_url: Optional[str],
    api_key: Optional[str] = None,
    race_window_seconds: float = 3.0,
) -> Dict[str, Any]:
    """
    P4: races a P2P swarm URL against a Debrid CDN URL for the first 256KB.
    The winner serves; the loser is reported as a warm backup. If only one
    candidate exists it wins by default. Never races when a candidate is None.
    """
    candidates: Dict[str, str] = {}
    if p2p_url:
        candidates["p2p"] = p2p_url
    if debrid_url:
        candidates["debrid"] = debrid_url

    if not candidates:
        return {"winner": None, "winner_url": None, "backup": None, "backup_url": None, "raced": False}

    if len(candidates) == 1:
        kind, url = next(iter(candidates.items()))
        return {
            "winner": kind,
            "winner_url": url,
            "backup": None,
            "backup_url": None,
            "raced": False,
        }

    probes = {kind: asyncio.create_task(_fetch_probe(url, api_key)) for kind, url in candidates.items()}

    # Keep waiting through failed completions: a fast failure must not end the
    # race before a slower healthy candidate gets its chance.
    loop = asyncio.get_running_loop()
    deadline = loop.time() + race_window_seconds
    remaining = set(probes.values())
    winner: Optional[str] = None
    while remaining and winner is None:
        timeout = max(0.0, deadline - loop.time())
        done, remaining = await asyncio.wait(remaining, timeout=timeout, return_when=asyncio.FIRST_COMPLETED)
        for kind, task in probes.items():
            if task in done:
                try:
                    succeeded = bool(task.result())
                except Exception:
                    succeeded = False
                if succeeded:
                    winner = kind
                    break
        if winner is None and (not done or loop.time() >= deadline):
            break  # window expired with no healthy candidate
    for task in remaining:
        task.cancel()

    if winner is None:
        # Neither responded inside the window: fall back to debrid when
        # present (unthrottled CDN beats a cold swarm), else p2p.
        winner = "debrid" if "debrid" in candidates else "p2p"

    loser = "debrid" if winner == "p2p" else "p2p"
    return {
        "winner": winner,
        "winner_url": candidates[winner],
        "backup": loser if loser in candidates else None,
        "backup_url": candidates.get(loser),
        "raced": True,
        "race_window_seconds": race_window_seconds,
    }
