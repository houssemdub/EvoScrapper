import asyncio
import hashlib
import json
import logging
import time
from enum import Enum
from typing import Any, Dict, List, Optional, Set
import aiohttp
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519

from config import settings
from core.logger import cometnet_logger

logger = cometnet_logger


class CometMessageType(str, Enum):
    TORRENT_ANNOUNCE = "torrent_announce"
    CACHE_ANNOUNCE = "cache_announce"
    PING = "ping"
    PONG = "pong"
    QUERY = "query"


class CometNetNode:
    """
    Decentralized P2P Metadata Gossip Node inspired by CometNet.
    Enables peer-to-peer torrent discovery and decentralized multi-provider
    Debrid cache availability sharing without central indexing servers.
    Supports real-time WebSocket transport across peer mesh and configured relays.
    """

    def __init__(
        self,
        node_name: str = "evo-node",
        private_key: Optional[ed25519.Ed25519PrivateKey] = None,
        relays: Optional[List[str]] = None,
    ):
        self.node_name = node_name
        self._private_key = private_key or ed25519.Ed25519PrivateKey.generate()
        self._public_key = self._private_key.public_key()

        raw_pub = self._public_key.public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
        self.public_key_hex = raw_pub.hex()
        self.node_id = hashlib.sha256(raw_pub).hexdigest()

        # In-memory storage & deduplication
        self._seen_messages: Set[str] = set()
        self._seen_order: List[str] = []
        self._max_seen: int = 10000

        self.torrent_catalog: Dict[str, Dict[str, Any]] = {}
        self.debrid_cache: Dict[str, Set[str]] = {}

        # Networking & WebSocket Mesh State
        self.relays: List[str] = relays if relays is not None else list(getattr(settings, "COMETNET_RELAYS", []))
        self._running: bool = False
        self._background_tasks: List[asyncio.Task] = []
        self._session: Optional[aiohttp.ClientSession] = None
        self._outbound_websockets: Set[Any] = set()
        self._inbound_websockets: Set[Any] = set()

    def _canonicalize_payload(self, data: Dict[str, Any]) -> bytes:
        """
        Produces stable deterministic byte serialization for cryptographic signing.
        """
        return json.dumps(data, sort_keys=True, separators=(",", ":")).encode("utf-8")

    def create_signed_message(
        self,
        msg_type: CometMessageType,
        payload: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Constructs and cryptographically signs a gossip protocol message.
        """
        ts = time.time()
        type_str = msg_type.value if isinstance(msg_type, CometMessageType) else str(msg_type)

        signable = {
            "type": type_str,
            "sender_id": self.node_id,
            "sender_pubkey": self.public_key_hex,
            "timestamp": ts,
            "payload": payload,
        }
        signable_bytes = self._canonicalize_payload(signable)
        signature = self._private_key.sign(signable_bytes).hex()

        msg_id = hashlib.sha256(f"{self.node_id}:{ts}:{type_str}".encode("utf-8")).hexdigest()

        return {
            "id": msg_id,
            "type": type_str,
            "sender_id": self.node_id,
            "sender_pubkey": self.public_key_hex,
            "timestamp": ts,
            "payload": payload,
            "signature": signature,
        }

    def verify_message(self, msg: Dict[str, Any]) -> bool:
        """
        Verifies the Ed25519 digital signature of an incoming gossip message.
        """
        try:
            sender_pub_hex = msg.get("sender_pubkey")
            sig_hex = msg.get("signature")
            if not sender_pub_hex or not sig_hex:
                return False

            peer_pub = ed25519.Ed25519PublicKey.from_public_bytes(bytes.fromhex(sender_pub_hex))

            # Reconstruct signable structure exactly
            signable = {
                "type": msg["type"],
                "sender_id": msg["sender_id"],
                "sender_pubkey": msg["sender_pubkey"],
                "timestamp": msg["timestamp"],
                "payload": msg["payload"],
            }
            signable_bytes = self._canonicalize_payload(signable)
            peer_pub.verify(bytes.fromhex(sig_hex), signable_bytes)
            return True
        except (InvalidSignature, KeyError, ValueError, Exception):
            return False

    def ingest_message(self, msg: Dict[str, Any]) -> bool:
        """
        Validates, deduplicates, and ingests a peer message into the local cache.
        Returns True if newly accepted, False if duplicate or invalid.
        """
        if not self.verify_message(msg):
            return False

        msg_id = msg.get("id")
        if not msg_id or msg_id in self._seen_messages:
            return False

        # Register in bounded deduplication set
        self._seen_messages.add(msg_id)
        self._seen_order.append(msg_id)
        if len(self._seen_order) > self._max_seen:
            oldest = self._seen_order.pop(0)
            self._seen_messages.discard(oldest)

        msg_type = msg.get("type")
        payload = msg.get("payload", {})

        if msg_type == CometMessageType.TORRENT_ANNOUNCE.value:
            info_hash = payload.get("info_hash", "").strip().lower()
            if info_hash:
                self.torrent_catalog[info_hash] = {
                    "info_hash": info_hash,
                    "title": payload.get("title", ""),
                    "size": payload.get("size", 0),
                    "trackers": payload.get("trackers", []),
                    "updated_at": msg.get("timestamp", time.time()),
                }

        elif msg_type == CometMessageType.CACHE_ANNOUNCE.value:
            info_hash = payload.get("info_hash", "").strip().lower()
            provider = payload.get("provider", "").strip().lower()
            cached = payload.get("cached", False)
            if info_hash and provider:
                if info_hash not in self.debrid_cache:
                    self.debrid_cache[info_hash] = set()
                if cached:
                    self.debrid_cache[info_hash].add(provider)
                else:
                    self.debrid_cache[info_hash].discard(provider)

        return True

    def announce_torrent(
        self,
        info_hash: str,
        title: str,
        size: int,
        trackers: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """
        Creates a signed torrent announcement and fans it out across the gossip network.
        """
        msg = self.create_signed_message(
            msg_type=CometMessageType.TORRENT_ANNOUNCE,
            payload={
                "info_hash": info_hash.strip().lower(),
                "title": title,
                "size": size,
                "trackers": trackers or [],
            },
        )
        self.ingest_message(msg)
        self._trigger_async_broadcast(msg)
        return msg

    def announce_cache(self, info_hash: str, provider: str, cached: bool = True) -> Dict[str, Any]:
        """
        Creates a signed debrid cache status announcement and broadcasts to the mesh.
        """
        msg = self.create_signed_message(
            msg_type=CometMessageType.CACHE_ANNOUNCE,
            payload={
                "info_hash": info_hash.strip().lower(),
                "provider": provider.strip().lower(),
                "cached": cached,
            },
        )
        self.ingest_message(msg)
        self._trigger_async_broadcast(msg)
        return msg

    def _trigger_async_broadcast(self, msg: Dict[str, Any]):
        """Helper to fire broadcast in running event loop without blocking synchronous callers."""
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self.broadcast_signed_message(msg))
        except RuntimeError:
            pass

    async def broadcast_signed_message(self, msg: Dict[str, Any], exclude_ws: Optional[Any] = None):
        """
        Fans out a signed gossip message to all active inbound and outbound WebSocket peers.
        """
        raw_text = json.dumps(msg)

        # Broadcast to outbound relay connections
        dead_outbound = set()
        for ws in list(self._outbound_websockets):
            if ws is exclude_ws:
                continue
            try:
                if not ws.closed:
                    await ws.send_str(raw_text)
                else:
                    dead_outbound.add(ws)
            except Exception:
                dead_outbound.add(ws)
        self._outbound_websockets.difference_update(dead_outbound)

        # Broadcast to inbound client connections
        dead_inbound = set()
        for ws in list(self._inbound_websockets):
            if ws is exclude_ws:
                continue
            try:
                # Starlette / FastAPI WebSocket
                await ws.send_text(raw_text)
            except Exception:
                dead_inbound.add(ws)
        self._inbound_websockets.difference_update(dead_inbound)

    async def _relay_worker(self, relay_url: str):
        """
        Resilient background worker connecting to a remote CometNet relay.
        Features automatic reconnect, exponential backoff, and gossip exchange.
        """
        backoff = 5.0
        while self._running:
            try:
                if not self._session or self._session.closed:
                    self._session = aiohttp.ClientSession()

                timeout = aiohttp.ClientTimeout(total=None, connect=6.0)
                async with self._session.ws_connect(relay_url, timeout=timeout) as ws:
                    self._outbound_websockets.add(ws)
                    backoff = 5.0  # reset backoff upon successful connection
                    logger.info(f"[CometNet] Connected to relay: {relay_url}")

                    # Handshake ping
                    handshake = self.create_signed_message(
                        CometMessageType.PING,
                        {"node_name": self.node_name, "version": "3.0"},
                    )
                    await ws.send_str(json.dumps(handshake))

                    async for msg in ws:
                        if not self._running:
                            break
                        if msg.type == aiohttp.WSMsgType.TEXT:
                            try:
                                payload = json.loads(msg.data)
                                if isinstance(payload, dict):
                                    if self.ingest_message(payload):
                                        # Forward newly verified message to other connected peers
                                        await self.broadcast_signed_message(payload, exclude_ws=ws)
                            except Exception:
                                pass
                        elif msg.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR):
                            break
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.debug(f"[CometNet] Relay {relay_url} connection error: {e}")
            finally:
                pass

            if not self._running:
                break

            # Sleep with backoff before reconnect
            try:
                await asyncio.sleep(backoff)
                backoff = min(backoff * 1.5, 60.0)
            except asyncio.CancelledError:
                break

    async def handle_inbound_ws(self, websocket: Any):
        """
        Handles an incoming WebSocket peer connection from FastAPI.
        """
        await websocket.accept()
        self._inbound_websockets.add(websocket)
        try:
            # Send intro ping
            intro = self.create_signed_message(
                CometMessageType.PING,
                {"node_name": self.node_name, "version": "3.0"},
            )
            await websocket.send_text(json.dumps(intro))

            while True:
                data_text = await websocket.receive_text()
                try:
                    payload = json.loads(data_text)
                    if isinstance(payload, dict):
                        if self.ingest_message(payload):
                            await self.broadcast_signed_message(payload, exclude_ws=websocket)
                except Exception:
                    pass
        except Exception:
            pass
        finally:
            self._inbound_websockets.discard(websocket)

    async def start(self):
        """
        Starts the CometNet mesh networking subsystem and background relay connectors.
        """
        if self._running:
            return
        self._running = True

        if not self._session or self._session.closed:
            self._session = aiohttp.ClientSession()

        # Spawn relay workers
        for relay in self.relays:
            if relay.startswith("ws://") or relay.startswith("wss://"):
                task = asyncio.create_task(self._relay_worker(relay))
                self._background_tasks.append(task)

        logger.info(f"[CometNet] Node started ({self.node_id[:16]}...) with {len(self._background_tasks)} relay workers")

    async def stop(self):
        """
        Gracefully stops mesh networking and closes all active sockets.
        """
        if not self._running:
            return
        self._running = False

        # Cancel background relay workers
        for task in self._background_tasks:
            task.cancel()
        if self._background_tasks:
            await asyncio.gather(*self._background_tasks, return_exceptions=True)
        self._background_tasks.clear()

        # Close outbound websockets
        for ws in list(self._outbound_websockets):
            try:
                await ws.close()
            except Exception:
                pass
        self._outbound_websockets.clear()

        # Close inbound websockets
        for ws in list(self._inbound_websockets):
            try:
                await ws.close()
            except Exception:
                pass
        self._inbound_websockets.clear()

        # Close aiohttp session
        if self._session and not self._session.closed:
            await self._session.close()
            self._session = None

        logger.info("[CometNet] Node stopped cleanly")

    def lookup_torrent(self, info_hash: str) -> Optional[Dict[str, Any]]:
        return self.torrent_catalog.get(info_hash.strip().lower())

    def lookup_cache(self, info_hash: str) -> Set[str]:
        return self.debrid_cache.get(info_hash.strip().lower(), set())

    def get_stats(self) -> Dict[str, Any]:
        """Returns node telemetry and mesh diagnostics."""
        return {
            "node_id": self.node_id,
            "node_name": self.node_name,
            "public_key": self.public_key_hex,
            "running": self._running,
            "relays_configured": len(self.relays),
            "outbound_connections": len(self._outbound_websockets),
            "inbound_connections": len(self._inbound_websockets),
            "torrents_indexed": len(self.torrent_catalog),
            "debrid_cached_entries": len(self.debrid_cache),
            "seen_messages_count": len(self._seen_messages),
        }


_cometnet_instance: Optional[CometNetNode] = None


def get_cometnet_node() -> CometNetNode:
    global _cometnet_instance
    if _cometnet_instance is None:
        _cometnet_instance = CometNetNode(node_name="EvoScrapper-CometNet")
    return _cometnet_instance
