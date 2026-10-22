import asyncio
import time
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from core.aggregator import deduplicate_torrents, filter_torrents
from core.cache import cache
from core.media_meta import fetch_media_details
from core.security import verify_api_key
from models.common import UnifiedMediaBundle
from models.media import MediaDetails
from providers.subtitles import SUBTITLE_PROVIDERS
from providers.torrents import TORRENT_PROVIDERS
from routers.subtitles import resolve_imdb_id

router = APIRouter(prefix="/api/v1/media", tags=["Media Bundle"], dependencies=[Depends(verify_api_key)])


@router.get("/meta", response_model=MediaDetails)
async def get_media_metadata(
    query: Optional[str] = Query(None, description="Movie/series title or raw release name"),
    year: Optional[int] = Query(None, description="Release year"),
    imdb_id: Optional[str] = Query(None, description="IMDb ID (tt1234567)"),
):
    """
    Scrapes and retrieves rich movie/series metadata:
    - IMDb ID & clickable link
    - High-res poster jacket image
    - 4K backdrop wallpaper image
    - IMDb rating, runtime, director, cast, genres, plot synopsis
    - Official YouTube trailer embed URL
    """
    if not query and not imdb_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Either 'query' or 'imdb_id' must be provided.",
        )
    meta = await fetch_media_details(query=query, year=year, imdb_id=imdb_id)
    if not meta:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Media metadata could not be resolved.",
        )
    return meta



@router.get("/lookup", response_model=UnifiedMediaBundle)
async def unified_media_lookup(
    query: Optional[str] = Query(None, description="Movie or series name"),
    imdb_id: Optional[str] = Query(None, description="IMDb ID (tt0816692)"),
    season: Optional[int] = Query(None, description="Season number for TV shows"),
    episode: Optional[int] = Query(None, description="Episode number for TV shows"),
    language: str = Query("en", description="Subtitle language code"),
    resolution: Optional[str] = Query(None, description="Torrent resolution filter"),
    limit: int = Query(50, ge=1, le=100),
):
    """
    Unified Media Bundle Lookup:
    Simultaneously queries both torrent indexers and subtitle providers,
    returning a consolidated payload with deduplicated torrent magnets
    and synchronized subtitles.
    """
    if not imdb_id and query:
        is_ser = bool(season or episode)
        imdb_id = await resolve_imdb_id(query, is_series=is_ser)

    search_term = query or imdb_id
    if not search_term:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Either 'query' or 'imdb_id' must be provided.",
        )

    cache_key = f"media_bundle:{search_term}:{season}:{episode}:{language}:{resolution}:{limit}"
    cached = await cache.get(cache_key)
    if cached:
        return cached

    start = time.time()

    # 1. Dispatch torrent searches
    torrent_tasks = [
        p.search(search_term, limit=limit)
        for p in TORRENT_PROVIDERS.values()
    ]

    # 2. Dispatch subtitle searches
    sub_tasks = [
        p.search(
            query=query or "",
            imdb_id=imdb_id,
            season=season,
            episode=episode,
            language=language,
            limit=limit,
        )
        for p in SUBTITLE_PROVIDERS.values()
    ]

    # Run everything in parallel
    all_tasks = asyncio.gather(
        asyncio.gather(*torrent_tasks, return_exceptions=True),
        asyncio.gather(*sub_tasks, return_exceptions=True),
    )
    raw_torrents_batches, raw_subs_batches = await all_tasks

    # Process Torrents
    all_torrents = []
    for batch in raw_torrents_batches:
        if isinstance(batch, list):
            all_torrents.extend(batch)
    deduped_torrents = deduplicate_torrents(all_torrents)
    final_torrents = filter_torrents(deduped_torrents, resolution=resolution, query=search_term)[:limit]

    # Process Subtitles
    all_subs = []
    for batch in raw_subs_batches:
        if isinstance(batch, list):
            all_subs.extend(batch)
    final_subs = all_subs[:limit]

    elapsed = round(time.time() - start, 3)
    bundle = UnifiedMediaBundle(
        query=query,
        imdb_id=imdb_id,
        total_torrents=len(final_torrents),
        total_subtitles=len(final_subs),
        torrents=final_torrents,
        subtitles=final_subs,
        execution_time_seconds=elapsed,
    )
    await cache.set(cache_key, bundle, ttl=900)
    return bundle
