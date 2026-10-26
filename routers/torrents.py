import asyncio
import json
import time
from typing import List, Optional
from fastapi import APIRouter, Depends, Query, status
from fastapi.responses import StreamingResponse
from config import settings
from core.torrent_streamer import get_torrent_files
from core.aggregator import deduplicate_torrents, filter_torrents, gate_by_swarm_health
from core.cache import cache
from core.security import verify_api_key
from models.torrent import TorrentItem, TorrentSearchResponse
from providers.torrents import TORRENT_PROVIDERS
from core.logger import scrapers_logger

router = APIRouter(prefix="/api/v1/torrents", tags=["Torrents"], dependencies=[Depends(verify_api_key)])

_prewarm_tasks: set = set()

# T0.4: empty results are cached briefly (negative-result TTL) so a newly
# seeded torrent is discoverable quickly, while full results keep the long TTL.
FULL_RESULT_TTL = 900
EMPTY_RESULT_TTL = 120


def search_result_ttl(items: List[TorrentItem]) -> int:
    return FULL_RESULT_TTL if items else EMPTY_RESULT_TTL


def _prewarm_top_swarms(items: List[TorrentItem]) -> None:
    """
    Opt-in (PREWARM_SWARMS): resolve the top results' metadata and peer
    connections in the background right after a search so click-to-play skips
    the metadata wait. The daemon deselects every piece, so nothing downloads
    until a reader actually appears.
    """
    if not settings.PREWARM_SWARMS:
        return

    candidates = []
    for item in items:
        info_hash = (item.info_hash or "").strip().lower()
        if info_hash and not info_hash.startswith("cdn_"):
            candidates.append((info_hash, item.magnet_uri or None))
        if len(candidates) >= 2:
            break

    async def _warm(info_hash: str, magnet: Optional[str]) -> None:
        try:
            await get_torrent_files(info_hash, magnet)
        except Exception:
            pass

    for info_hash, magnet in candidates:
        task = asyncio.create_task(_warm(info_hash, magnet))
        _prewarm_tasks.add(task)
        task.add_done_callback(_prewarm_tasks.discard)


@router.get("/search", response_model=TorrentSearchResponse)
async def search_torrents(
    query: str = Query(..., description="Search query or IMDb ID (tt...)"),
    provider: str = Query("all", description="Target provider or 'all'"),
    category: Optional[str] = Query(None, description="Category filter (movies, tv, anime)"),
    resolution: Optional[str] = Query(None, description="Resolution filter (2160p, 1080p, 720p)"),
    min_seeders: int = Query(0, description="Minimum seeders count"),
    limit: int = Query(50, ge=1, le=200, description="Max results to return"),
):
    """
    Search torrents across a single provider or all healthy providers in parallel.
    Features automatic deduplication and quality enrichment.
    """
    cache_key = f"torrent_search:{provider}:{query}:{category}:{resolution}:{min_seeders}:{limit}"
    cached = await cache.get(cache_key)
    if cached:
        scrapers_logger.info(f"Cache hit for query='{query}' provider='{provider}'")
        return cached

    scrapers_logger.info(f"Searching torrents for query='{query}' provider='{provider}' category={category}")

    start = time.time()
    query_str = query.strip()

    if provider.lower() != "all":
        p = TORRENT_PROVIDERS.get(provider.lower())
        if not p:
            return TorrentSearchResponse(
                query=query_str,
                provider=provider,
                total=0,
                time_taken=round(time.time() - start, 3),
                data=[],
            )
        results = await p.search(query_str, limit=limit)
    else:
        # Fan out across capable active providers concurrently with bounded concurrency
        from core.stream_resolver import PROVIDER_MEDIA_CAPABILITIES

        target_cat = (category or "").lower().strip()
        cat_key = "movie" if target_cat in ("movie", "movies") else (
            "series" if target_cat in ("tv", "series", "shows") else (
                "anime" if target_cat in ("anime", "animation") else None
            )
        )
        capable_names = PROVIDER_MEDIA_CAPABILITIES.get(cat_key) if cat_key else None
        active_providers = [
            p for name, p in TORRENT_PROVIDERS.items()
            if capable_names is None or name in capable_names
        ]

        sem = asyncio.Semaphore(10)

        async def _bounded_search(prov):
            async with sem:
                try:
                    return await prov.search(query_str, limit=limit)
                except Exception:
                    return []

        tasks = [_bounded_search(p) for p in active_providers]
        gathered = await asyncio.gather(*tasks, return_exceptions=True)
        results = []
        for r in gathered:
            if isinstance(r, list):
                results.extend(r)

    # De-duplicate across providers
    deduped = deduplicate_torrents(results)
    final_items = filter_torrents(
        deduped, resolution=resolution, min_seeders=min_seeders, category=category, query=query_str
    )[:limit]

    # T0.2: hide dead torrents behind a healthy swarm (skipped with debrid).
    try:
        from core.debrid.manager import get_debrid_manager
        debrid_configured = bool(get_debrid_manager().active_providers)
    except Exception:
        debrid_configured = False
    final_items = gate_by_swarm_health(final_items, debrid_configured=debrid_configured)

    elapsed = round(time.time() - start, 3)
    _prewarm_top_swarms(final_items)
    response = TorrentSearchResponse(
        query=query_str,
        provider=provider,
        total=len(final_items),
        time_taken=elapsed,
        data=final_items,
    )
    await cache.set(cache_key, response, ttl=search_result_ttl(final_items))
    return response


@router.get("/combo", response_model=TorrentSearchResponse)
async def search_combo(
    query: str = Query(..., description="Search query or IMDb ID"),
    resolution: Optional[str] = Query(None, description="Resolution filter"),
    min_seeders: int = Query(0, description="Minimum seeders"),
    limit: int = Query(50, ge=1, le=200),
):
    """High-level multi-indexer search route with global deduplication."""
    return await search_torrents(
        query=query,
        provider="all",
        category=None,
        resolution=resolution,
        min_seeders=min_seeders,
        limit=limit,
    )


@router.get("/stream")
async def stream_search(
    query: str = Query(..., description="Search query"),
    limit: int = Query(25, ge=1, le=100),
):
    """
    Real-Time Server-Sent Events (SSE) search.
    Streams torrent batches as each provider finishes without waiting for slower indexers.
    """
    query_str = query.strip()

    async def event_generator():
        sse_sem = asyncio.Semaphore(8)

        async def _run_search(provider):
            async with sse_sem:
                try:
                    results = await provider.search(query_str, limit=limit)
                    return provider.name, results
                except Exception:
                    return provider.name, []

        tasks = [asyncio.create_task(_run_search(p)) for p in TORRENT_PROVIDERS.values()]
        for completed_coro in asyncio.as_completed(tasks):
            try:
                provider_name, items = await completed_coro
                if items:
                    payload = {
                        "provider": provider_name,
                        "count": len(items),
                        "items": [item.model_dump() for item in items],
                    }
                    yield f"data: {json.dumps(payload)}\n\n"
            except Exception:
                pass
        yield "data: [DONE]\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@router.get("/trending", response_model=TorrentSearchResponse)
async def get_trending(limit: int = Query(50, ge=1, le=100)):
    """Returns aggregated trending media from active providers."""
    cache_key = f"torrent_trending:{limit}"
    cached = await cache.get(cache_key)
    if cached:
        return cached

    start = time.time()
    # YTS, ThePirateBay, and Nyaa provide curated top/trending
    trending_tasks = [
        TORRENT_PROVIDERS["yts"].trending(limit=limit),
        TORRENT_PROVIDERS["thepiratebay"].trending(limit=limit),
        TORRENT_PROVIDERS["nyaa"].trending(limit=limit),
    ]
    results = await asyncio.gather(*trending_tasks, return_exceptions=True)
    all_items: List[TorrentItem] = []
    for r in results:
        if isinstance(r, list):
            all_items.extend(r)

    deduped = deduplicate_torrents(all_items)[:limit]
    response = TorrentSearchResponse(
        query="trending",
        provider="all",
        total=len(deduped),
        time_taken=round(time.time() - start, 3),
        data=deduped,
    )
    await cache.set(cache_key, response, ttl=3600)
    return response
