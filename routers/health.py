import time
from typing import List
from fastapi import APIRouter
from models.common import HealthResponse, ProviderHealth
from providers.subtitles import SUBTITLE_PROVIDERS
from providers.torrents import TORRENT_PROVIDERS

router = APIRouter(tags=["Health & Diagnostics"])

START_TIME = time.time()


def get_all_provider_health() -> List[ProviderHealth]:
    stats: List[ProviderHealth] = []
    for p in TORRENT_PROVIDERS.values():
        stats.append(p.get_health())
    for s in SUBTITLE_PROVIDERS.values():
        stats.append(s.get_health())
    return stats


@router.get("/health", response_model=HealthResponse)
@router.get("/api/v1/health", response_model=HealthResponse)
async def health_check():
    """System health check and live provider operational metrics."""
    uptime = round(time.time() - START_TIME, 2)
    provider_stats = get_all_provider_health()
    healthy_count = sum(1 for p in provider_stats if p.status.value == "closed")

    return HealthResponse(
        app="EvoScrapper",
        version="2.0.0",
        status="healthy" if healthy_count > 0 else "degraded",
        uptime_seconds=uptime,
        total_providers=len(provider_stats),
        healthy_providers=healthy_count,
        providers=provider_stats,
    )


@router.get("/api/v1/providers/status", response_model=List[ProviderHealth])
async def list_providers_status():
    """Detailed circuit breaker state and average latency per provider."""
    return get_all_provider_health()
