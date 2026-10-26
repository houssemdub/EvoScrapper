import asyncio
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, HTTPException, Query, Depends
from pydantic import BaseModel, Field

from core.cometnet import get_cometnet_node, CometMessageType
from core.security import verify_api_key
from core.swarm_intelligence import get_seek_heatmap, get_coverage_index, derive_scene_boundaries
from core.watch_party import get_watch_party_manager, WatchPartyError

router = APIRouter(prefix="/api/v1/cometnet", tags=["CometNet Mesh"])


class AnnounceTorrentRequest(BaseModel):
    info_hash: str = Field(..., min_length=40, max_length=40, description="40-char hex info hash")
    title: str = Field(..., min_length=1, description="Torrent title")
    size: int = Field(0, ge=0, description="Size in bytes")
    trackers: List[str] = Field(default_factory=list, description="List of tracker URLs")


class AnnounceCacheRequest(BaseModel):
    info_hash: str = Field(..., min_length=40, max_length=40, description="40-char hex info hash")
    provider: str = Field(..., min_length=2, description="Debrid provider name (e.g. realdebrid, alldebrid, torbox)")
    cached: bool = Field(True, description="Cache availability status")


@router.websocket("/ws")
async def cometnet_websocket_endpoint(websocket: WebSocket):
    """
    WebSocket endpoint for bidirectional peer mesh gossip synchronization.
    Peers exchange cryptographically signed Ed25519 announcements for instant
    torrent catalog discovery and multi-provider debrid cache availability.
    """
    node = get_cometnet_node()
    await node.handle_inbound_ws(websocket)


@router.get("/stats")
async def get_cometnet_stats() -> Dict[str, Any]:
    """
    Returns real-time node telemetry, peer mesh connectivity, and indexed catalog counts.
    """
    node = get_cometnet_node()
    return node.get_stats()


@router.get("/lookup/{info_hash}")
async def lookup_cometnet_item(info_hash: str) -> Dict[str, Any]:
    """
    Queries local decentralized mesh knowledge for a specific torrent info_hash.
    Returns metadata and debrid providers known to have cached this torrent.
    """
    node = get_cometnet_node()
    clean_hash = info_hash.strip().lower()
    torrent = node.lookup_torrent(clean_hash)
    cached_providers = list(node.lookup_cache(clean_hash))

    return {
        "info_hash": clean_hash,
        "found": bool(torrent or cached_providers),
        "torrent": torrent,
        "cached_providers": cached_providers,
    }


@router.post("/announce/torrent", dependencies=[Depends(verify_api_key)])
async def announce_torrent_endpoint(req: AnnounceTorrentRequest) -> Dict[str, Any]:
    """
    Announces a torrent to the decentralized CometNet mesh.
    Signs the payload with the node's Ed25519 private key and gossips to all peers.
    """
    node = get_cometnet_node()
    signed_msg = node.announce_torrent(
        info_hash=req.info_hash,
        title=req.title,
        size=req.size,
        trackers=req.trackers,
    )
    return {
        "status": "announced",
        "message_id": signed_msg.get("id"),
        "sender_id": signed_msg.get("sender_id"),
    }


@router.post("/announce/cache", dependencies=[Depends(verify_api_key)])
async def announce_cache_endpoint(req: AnnounceCacheRequest) -> Dict[str, Any]:
    """
    Announces instant debrid cache availability for a torrent to the CometNet mesh.
    """
    node = get_cometnet_node()
    signed_msg = node.announce_cache(
        info_hash=req.info_hash,
        provider=req.provider,
        cached=req.cached,
    )
    return {
        "status": "announced",
        "message_id": signed_msg.get("id"),
        "sender_id": signed_msg.get("sender_id"),
    }


class AnnounceSeekRequest(BaseModel):
    info_hash: str = Field(..., min_length=40, max_length=40, description="40-char hex info hash")
    position: float = Field(..., ge=0, description="Seek landing position in seconds")


@router.post("/seek", dependencies=[Depends(verify_api_key)])
async def announce_seek_event(req: AnnounceSeekRequest) -> Dict[str, Any]:
    """P1: records a local seek into the collective heatmap and gossips an
    anonymous 30-second-bucket event to the mesh."""
    get_seek_heatmap().record(req.info_hash, req.position)
    node = get_cometnet_node()
    node.announce_seek(req.info_hash, req.position)
    return {"status": "ok", "heatmap_buckets": get_seek_heatmap().bucket_count(req.info_hash)}


@router.get("/heatmap/{info_hash}")
async def get_seek_heatmap_endpoint(info_hash: str, k: int = Query(3, ge=1, le=4)) -> Dict[str, Any]:
    """P1: top crowd-sourced seek hotspots for a torrent."""
    return {"info_hash": info_hash, "targets": get_seek_heatmap().top_seek_targets(info_hash, k=k)}


@router.get("/coverage/{info_hash}")
async def get_coverage_endpoint(info_hash: str) -> Dict[str, Any]:
    """P2: mesh-reported debrid coverage for a hash, ordered by confidence."""
    return {"info_hash": info_hash, "providers": get_coverage_index().providers_for(info_hash)}


@router.get("/scenes")
async def get_scene_boundaries(info_hash: str = Query(...), duration: float = Query(..., gt=0)) -> Dict[str, Any]:
    """P3: behavioral scene boundaries (intro/credits/scene hotspots) derived
    from the collective seek heatmap."""
    targets = get_seek_heatmap().top_seek_targets(info_hash, k=6, min_weight=0.0)
    return {
        "info_hash": info_hash,
        "duration": duration,
        "scenes": derive_scene_boundaries(targets, duration),
    }


class CreatePartyRequest(BaseModel):
    info_hash: str = Field(..., min_length=40, max_length=40)
    host_peer_id: str = Field(..., min_length=3, max_length=64)


class JoinPartyRequest(BaseModel):
    peer_id: str = Field(..., min_length=3, max_length=64)


class PartyEventRequest(BaseModel):
    peer_id: str = Field(..., min_length=3, max_length=64)
    action: str = Field(..., description="play | pause | seek | sync")
    position: float = Field(..., ge=0)


@router.post("/party/create", dependencies=[Depends(verify_api_key)])
async def create_party_room(req: CreatePartyRequest) -> Dict[str, Any]:
    """P8: opens a watch-together room for a torrent."""
    room = get_watch_party_manager().create_room(req.info_hash, req.host_peer_id)
    return {"success": True, **room.snapshot()}


@router.post("/party/{code}/join")
async def join_party_room(code: str, req: JoinPartyRequest) -> Dict[str, Any]:
    try:
        room = get_watch_party_manager().join_room(code, req.peer_id)
    except WatchPartyError as e:
        raise HTTPException(status_code=409, detail=str(e))
    return {"success": True, **room.snapshot()}


@router.post("/party/{code}/event")
async def post_party_event(code: str, req: PartyEventRequest) -> Dict[str, Any]:
    manager = get_watch_party_manager()
    try:
        event = manager.post_event(code, req.peer_id, req.action, req.position)
    except WatchPartyError as e:
        raise HTTPException(status_code=409, detail=str(e))
    # Fan the transport event out to remote instances over the mesh.
    try:
        get_cometnet_node().announce_party_event(code.lower(), req.peer_id, req.action, req.position)
    except Exception:
        pass
    return {"success": True, "event": event}


@router.get("/party/{code}/events")
async def get_party_events(code: str, since: int = Query(0, ge=0)) -> Dict[str, Any]:
    room = get_watch_party_manager().get_room(code)
    if not room:
        raise HTTPException(status_code=404, detail="room not found")
    return {"success": True, "events": room.events_since(since), "snapshot": room.snapshot()}


@router.get("/party/stats")
async def get_party_stats() -> Dict[str, Any]:
    return get_watch_party_manager().stats()


@router.get("/impact")
async def get_mesh_impact() -> Dict[str, Any]:
    """
    Plan metric #4: proves the swarm-intelligence layer is paying off —
    hint hit-rate from live daemon sessions, mesh coverage index size, and
    heatmap volume.
    """
    totals = {"seeks": 0, "hits": 0}
    sessions_tracked = 0
    try:
        from core.torrent_streamer import get_daemon_status
        status = await get_daemon_status()
        for sess in status.get("sessions", []):
            hs = sess.get("hint_stats")
            if hs:
                sessions_tracked += 1
                totals["seeks"] += hs.get("seeks") or 0
                totals["hits"] += hs.get("hits") or 0
    except Exception:
        pass

    heatmap = get_seek_heatmap()
    coverage = get_coverage_index()
    return {
        "hint_hit_rate_pct": round(totals["hits"] / totals["seeks"] * 100, 1) if totals["seeks"] else None,
        "hint_seeks": totals["seeks"],
        "hint_hits": totals["hits"],
        "sessions_tracked": sessions_tracked,
        "heatmap_hashes_tracked": len(heatmap._heat),
        "coverage": coverage.stats(),
    }
