"""
core/stremio_addon.py — Stremio V3 Addon Engine
Handles Stremio community addon manifest parsing (Torrentio, CyberFlix, etc.)
and queries stream endpoints.
"""

from typing import Any, Dict, List, Optional
import urllib.parse
import aiohttp
from core.client import http_client


def build_magnet_uri(info_hash: str, title: str) -> str:
    """
    Builds a properly encoded magnet URI ensuring dn= is URL-encoded
    and stripping problematic newlines, control chars, or trailing whitespace.
    """
    clean_hash = (info_hash or "").lower().strip()
    clean_title = (title or "Torrent").split("\n")[0].strip()
    encoded_dn = urllib.parse.quote_plus(clean_title)
    return f"magnet:?xt=urn:btih:{clean_hash}&dn={encoded_dn}"


def normalize_addon_url(url: str) -> str:
    """Normalizes stremio:// scheme and ensures clean base URL without trailing slash or /manifest.json."""
    clean = (url or "").strip()
    if clean.startswith("stremio://"):
        clean = "https://" + clean[10:]
    clean = clean.rstrip("/")
    if clean.endswith("/manifest.json"):
        clean = clean[:-14]
    return clean.rstrip("/")


async def fetch_addon_manifest(addon_url: str) -> Dict[str, Any]:
    """Fetches and parses a Stremio V3 addon manifest."""
    base_url = normalize_addon_url(addon_url)
    manifest_url = f"{base_url}/manifest.json"

    try:
        data = await http_client.get_json(manifest_url, timeout=10.0)
        if isinstance(data, dict) and "id" in data and "name" in data:
            data["_base_url"] = base_url
            data["_manifest_url"] = manifest_url
            return data
        raise ValueError("Invalid Stremio manifest format (missing id or name)")
    except Exception as e:
        raise ValueError(f"Failed to fetch Stremio manifest from {manifest_url}: {e}")


async def fetch_addon_streams(
    addon_url: str,
    media_type: str,
    item_id: str,
    season: Optional[int] = None,
    episode: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """
    Queries a Stremio addon for streams matching movie or series episode.
    URL pattern: {base_url}/stream/{type}/{id}.json
    For series/anime: {id} is formatted as {imdb_id}:{season}:{episode}
    """
    base_url = normalize_addon_url(addon_url)
    media_type = (media_type or "movie").lower()
    if media_type == "anime":
        media_type = "series"

    if season is not None and episode is not None:
        target_id = f"{item_id}:{season}:{episode}"
    else:
        target_id = item_id

    stream_endpoint = f"{base_url}/stream/{media_type}/{target_id}.json"

    try:
        data = await http_client.get_json(stream_endpoint, timeout=12.0)
        if not isinstance(data, dict):
            return []

        raw_streams = data.get("streams", [])
        results = []
        for s in raw_streams:
            if not isinstance(s, dict):
                continue

            info_hash = s.get("infoHash")
            title = s.get("title") or s.get("name") or "Stremio Stream"
            file_idx = s.get("fileIdx", 0)
            stream_url = s.get("url")

            magnet = None
            if info_hash:
                magnet = build_magnet_uri(info_hash, title)

            results.append({
                "name": s.get("name", "Stremio Addon"),
                "title": title,
                "info_hash": info_hash,
                "file_idx": file_idx,
                "stream_url": stream_url,
                "magnet": magnet,
                "behaviorHints": s.get("behaviorHints", {}),
            })
        return results
    except Exception as e:
        print(f"[StremioEngine] Addon stream fetch error from {stream_endpoint}: {e}")
        return []
