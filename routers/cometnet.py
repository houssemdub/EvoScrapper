import asyncio
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, HTTPException, Query
from pydantic import BaseModel, Field

from core.cometnet import get_cometnet_node, CometMessageType

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


@router.post("/announce/torrent")
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


@router.post("/announce/cache")
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
