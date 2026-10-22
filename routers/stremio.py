"""
routers/stremio.py — Stremio Addon Ecosystem Endpoints
Allows registering and querying community Stremio addons.
"""

from typing import Optional
from fastapi import APIRouter, HTTPException, Query
from core.stremio_addon import fetch_addon_manifest, fetch_addon_streams

router = APIRouter(prefix="/api/v1/addons", tags=["Stremio Addons"])


@router.get("/manifest")
async def get_addon_manifest(
    url: str = Query(..., description="Stremio addon manifest URL or base URL"),
):
    """
    Fetches and parses a Stremio addon manifest from an external URL.
    """
    try:
        manifest = await fetch_addon_manifest(url)
        return {"success": True, "manifest": manifest}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/streams")
async def get_addon_streams(
    url: str = Query(..., description="Stremio addon base URL"),
    media_type: str = Query("movie", description="Media type: movie, series, or anime"),
    item_id: str = Query(..., description="IMDb ID e.g. tt15239678 or Kitsu ID"),
    season: Optional[int] = Query(None, description="Season number"),
    episode: Optional[int] = Query(None, description="Episode number"),
):
    """
    Fetches available streams for a movie or TV episode directly from a Stremio addon.
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
