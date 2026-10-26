"""
routers/stremio.py — Stremio Addon Ecosystem & Native Addon Server
Provides full compliance with the Stremio Addon Protocol v3:
- /manifest.json (and /stremio/manifest.json)
- /stream/{type}/{item_id}.json (and /stremio/stream/{type}/{item_id}.json)
Also allows querying external community Stremio addons via /api/v1/addons/*.
"""

from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query

from core.media_meta import fetch_media_details
from core.security import verify_api_key
from core.stream_resolver import resolve_streams
from core.stremio_addon import fetch_addon_manifest, fetch_addon_streams

router = APIRouter(tags=["Stremio Addon Engine"])


# ==============================================================================
# Native Stremio Addon V3 Server Endpoints
# ==============================================================================

@router.get("/manifest.json")
@router.get("/stremio/manifest.json")
async def get_stremio_manifest() -> Dict[str, Any]:
    """
    Official Stremio Addon v3 Manifest.
    Allows EvoScrapper to be installed directly into official Stremio apps on
    Android TV, FireStick, Desktop, and Web as a custom streaming addon.
    """
    return {
        "id": "org.evoscrapper.addon",
        "version": "3.0.0",
        "name": "EvoScrapper Streams",
        "description": "Decentralized Multi-Indexer Torrent & 6-Provider Multi-Debrid Streaming Gateway",
        "resources": ["stream", "subtitles"],
        "types": ["movie", "series", "anime"],
        "catalogs": [],
        "idPrefixes": ["tt", "kitsu:"],
        "background": "https://images.metahub.space/background/medium/tt1375666/img",
        "logo": "/static/favicon.ico",
    }


@router.get("/stream/{type}/{item_id}.json")
@router.get("/stremio/stream/{type}/{item_id}.json")
async def get_stremio_stream(type: str, item_id: str) -> Dict[str, List[Dict[str, Any]]]:
    """
    Stremio Stream Resolver endpoint compliant with Stremio Addon v3 specs.
    Handles movies ('tt1375666'), TV series ('tt1528406:1:8'), and anime ('kitsu:1234:1:8').
    """
    # 1. Parse item_id and season/episode
    clean_id = item_id.replace(".json", "")
    season: Optional[int] = None
    episode: Optional[int] = None
    imdb_id: str = clean_id

    if clean_id.startswith("kitsu:"):
        parts = clean_id.split(":")
        if len(parts) >= 4:
            imdb_id = f"{parts[0]}:{parts[1]}"
            try:
                season = int(parts[2])
                episode = int(parts[3])
            except ValueError:
                pass
    elif ":" in clean_id:
        parts = clean_id.split(":")
        imdb_id = parts[0]
        if len(parts) >= 3:
            try:
                season = int(parts[1])
                episode = int(parts[2])
            except ValueError:
                pass

    # 2. Resolve title metadata
    title: Optional[str] = None
    year: Optional[str] = None
    try:
        meta = await fetch_media_details(imdb_id)
        if meta:
            title = meta.title
            year = meta.year
    except Exception:
        pass

    if not title:
        title = imdb_id

    # 3. Resolve streams across all indexers and debrid caches
    media_type = type.lower()
    if media_type not in ("movie", "series", "anime"):
        media_type = "movie"

    res = await resolve_streams(
        title=title,
        imdb_id=imdb_id,
        year=year,
        season=season,
        episode=episode,
        media_type=media_type,
        include_cdn=False,
    )

    # 4. Format into Stremio stream items
    stremio_streams: List[Dict[str, Any]] = []
    for s in res.streams:
        stream_entry: Dict[str, Any] = {
            "name": f"EvoScrapper\n{s.name}",
            "title": f"{s.title}\n💾 {s.size} 👥 {s.seeds} seeds | {s.tracker}",
        }
        if s.stream_url:
            stream_entry["url"] = s.stream_url
        else:
            stream_entry["infoHash"] = s.info_hash
            stream_entry["fileIdx"] = s.file_idx

        stremio_streams.append(stream_entry)

    return {"streams": stremio_streams}


# ==============================================================================
# External Addon Client Endpoints
# ==============================================================================

@router.get("/subtitles/{stype}/{item_id}.json")
@router.get("/stremio/subtitles/{stype}/{item_id}.json")
async def get_stremio_subtitles(
    stype: str,
    item_id: str,
    season: Optional[int] = None,
    episode: Optional[int] = None,
    language: Optional[str] = None,
) -> Dict[str, Any]:
    """
    T4.6 Stremio v3 subtitles resource: serves EvoScrapper's aggregated
    subtitle providers (OpenSubtitles, Gestdown, SubDL, SubSource, YIFY) to
    official Stremio apps.
    """
    clean_id = item_id.split(".")[0]
    import re as _re
    if not _re.match(r"^tt\d+$", clean_id, _re.I):
        return {"subtitles": []}

    from routers.subtitles import search_subtitles
    try:
        response = await search_subtitles(
            query=None,
            imdb_id=clean_id,
            season=season,
            episode=episode,
            language=language,
            info_hash=None,
            provider="all",
            limit=20,
        )
    except Exception:
        return {"subtitles": []}

    subtitles = []
    for sub in getattr(response, "data", []) or []:
        url = getattr(sub, "url", None) or getattr(sub, "download_url", None)
        if not url:
            continue
        subtitles.append({
            "id": str(getattr(sub, "id", "")) or f"evo:{len(subtitles)}",
            "url": url,
            "lang": str(getattr(sub, "language_code", "") or getattr(sub, "language", "") or "eng"),
        })
    return {"subtitles": subtitles}


@router.get("/api/v1/addons/manifest", dependencies=[Depends(verify_api_key)])
async def get_external_addon_manifest(
    url: str = Query(..., description="Stremio addon manifest URL or base URL"),
):
    """
    Fetches and parses a Stremio addon manifest from an external URL.
    """
    try:
        manifest = await fetch_addon_manifest(url)
        return {"success": True, "manifest": manifest}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/api/v1/addons/streams", dependencies=[Depends(verify_api_key)])
async def get_external_addon_streams(
    url: str = Query(..., description="Stremio addon base URL"),
    media_type: str = Query("movie", description="Media type: movie, series, or anime"),
    item_id: str = Query(..., description="IMDb ID e.g. tt15239678 or Kitsu ID"),
    season: Optional[int] = Query(None, description="Season number"),
    episode: Optional[int] = Query(None, description="Episode number"),
):
    """
    Fetches available streams for a movie or TV episode directly from an external Stremio addon.
    """
    streams = await fetch_addon_streams(
        addon_url=url,
        media_type=media_type,
        item_id=item_id,
        season=season,
        episode=episode,
    )
    return {
        "success": True,
        "addon_url": url,
        "total": len(streams),
        "streams": streams,
    }
