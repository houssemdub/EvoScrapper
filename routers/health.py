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

    # Subsystem diagnostics
    subsystems = {}
    try:
        from core.debrid.manager import get_debrid_manager
        debrid_mgr = get_debrid_manager()
        subsystems["debrid"] = {
            "configured_providers": [p.provider_name for p in debrid_mgr.active_providers],
            "total_supported": len(debrid_mgr.providers),
        }
    except Exception:
        pass

    try:
        from core.cometnet import get_cometnet_node
        comet = get_cometnet_node()
        subsystems["cometnet"] = {
            "running": comet._running,
            "node_id": comet.node_id[:16],
            "peers_outbound": len(comet._outbound_websockets),
            "peers_inbound": len(comet._inbound_websockets),
            "catalog_size": len(comet.torrent_catalog),
        }
    except Exception:
        pass

    try:
        from core.cache import cache
        subsystems["cache"] = {
            "entries_count": len(cache._store),
        }
    except Exception:
        pass

    return HealthResponse(
        app="EvoScrapper",
        version="2.0.0",
        status="healthy" if healthy_count > 0 else "degraded",
        uptime_seconds=uptime,
        total_providers=len(provider_stats),
        healthy_providers=healthy_count,
        providers=provider_stats,
        subsystems=subsystems,
    )


@router.get("/ready")
@router.get("/api/v1/ready")
async def readiness_check():
    """Readiness probe for load balancers and container orchestrators."""
    from fastapi.responses import JSONResponse

    provider_stats = get_all_provider_health()
    healthy_count = sum(1 for p in provider_stats if p.status.value == "closed")
    is_ready = healthy_count > 0

    body = {
        "ready": is_ready,
        "healthy_providers": healthy_count,
        "total_providers": len(provider_stats),
        "timestamp": time.time(),
    }
    return JSONResponse(status_code=200 if is_ready else 503, content=body)


@router.get("/api/v1/providers/status", response_model=List[ProviderHealth])
async def list_providers_status():
    """Detailed circuit breaker state and average latency per provider."""
    return get_all_provider_health()
