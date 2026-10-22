from typing import List, Optional
from fastapi import APIRouter, HTTPException, Query
from core.cache import cache
from core.discover import fetch_catalog, fetch_discover_detail, get_discover_suggestions, search_catalog
from models.discover import DiscoverCatalogResponse, DiscoverDetail, DiscoverItem

router = APIRouter(prefix="/api/v1/discover", tags=["Discover"])


@router.get("/catalog", response_model=DiscoverCatalogResponse)
async def get_discover_catalog(
    type: str = Query("movie", description="Media type: movie, series, or anime"),
    catalog: str = Query("top", description="Catalog feed: top, trending, new"),
    genre: Optional[str] = Query(None, description="Optional genre filter, e.g. Action, Sci-Fi"),
    page: int = Query(1, ge=1, le=20, description="Catalog page number (48 items per page)"),
):
    """
    Fetches visual catalog cards for Movies, Series, and Anime with posters,
    ratings, genres, and release years.
    """
    valid_types = ("movie", "series", "anime")
    if type.lower() not in valid_types:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid media type '{type}'. Allowed types: {', '.join(valid_types)}",
        )
    return await fetch_catalog(media_type=type.lower(), catalog=catalog, genre=genre, page=page)


@router.get("/meta/{type}/{imdb_id}", response_model=DiscoverDetail)
async def get_discover_detail(
    type: str,
    imdb_id: str,
    nocache: bool = Query(False, description="Bypass and refresh cache"),
):
    """
    Fetches full detail for a title including 4K backdrops, cast, director,
    plot, and the complete season and episode tree for series/anime.
    """
    if not (imdb_id.startswith("tt") or imdb_id.startswith("kitsu:")):
        raise HTTPException(status_code=400, detail="Invalid title ID format. Must start with 'tt' or 'kitsu:'.")

    detail = await fetch_discover_detail(media_type=type.lower(), imdb_id=imdb_id, bypass_cache=nocache)
    if not detail:
        raise HTTPException(status_code=404, detail=f"No metadata found for {imdb_id}")
    return detail


@router.post("/cache/clear")
async def clear_discover_cache():
    """Wipes the in-memory cache clean."""
    await cache.clear()
    return {"status": "success", "message": "Discover cache cleared successfully"}


@router.get("/search", response_model=List[DiscoverItem])
async def search_discover_items(
    query: str = Query(..., min_length=2, description="Search query string"),
    type: Optional[str] = Query(None, description="Optional media type filter"),
):
    """
    Searches the Discover catalog by title or keyword.
    """
    return await search_catalog(query=query, media_type=type.lower() if type else None)


@router.get("/suggestions", response_model=List[DiscoverItem])
async def get_discover_suggestions_route(
    q: str = Query(..., min_length=2, description="Search query string"),
    type: Optional[str] = Query(None, description="Optional media type: movie, series, anime"),
    limit: int = Query(8, ge=1, le=20, description="Max suggestions to return"),
):
    """
    Ultra-fast autocomplete search suggestions matching titles, years, and posters.
    """
    return await get_discover_suggestions(query=q, media_type=type.lower() if type else "all", limit=limit)
