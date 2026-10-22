import asyncio
import hashlib
import json
import logging
import time
from enum import Enum
from typing import Any, Dict, List, Optional, Set

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519

from config import settings

logger = logging.getLogger("CometNet")


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
    """

    def __init__(self, node_name: str = "evo-node", private_key: Optional[ed25519.Ed25519PrivateKey] = None):
        self.node_name = node_name
        self._private_key = private_key or ed25519.Ed25519PrivateKey.generate()
        self._public_key = self._private_key.public_key()
        
        raw_pub = self._public_key.public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw
        )
        self.public_key_hex = raw_pub.hex()
        self.node_id = hashlib.sha256(raw_pub).hexdigest()

        # In-memory storage & deduplication
        self._seen_messages: Set[str] = set()
        self._seen_order: List[str] = []
        self._max_seen: int = 10000

        self.torrent_catalog: Dict[str, Dict[str, Any]] = {}
        self.debrid_cache: Dict[str, Set[str]] = {}
        self.connected_peers: Dict[str, Any] = {}

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
        Creates a signed torrent announcement for broadcast across the gossip network.
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
        return msg

    def announce_cache(self, info_hash: str, provider: str, cached: bool = True) -> Dict[str, Any]:
        """
        Creates a signed debrid cache status announcement.
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
        return msg

    def lookup_torrent(self, info_hash: str) -> Optional[Dict[str, Any]]:
        return self.torrent_catalog.get(info_hash.strip().lower())

    def lookup_cache(self, info_hash: str) -> Set[str]:
        return self.debrid_cache.get(info_hash.strip().lower(), set())


_cometnet_instance: Optional[CometNetNode] = None


def get_cometnet_node() -> CometNetNode:
    global _cometnet_instance
    if _cometnet_instance is None:
        _cometnet_instance = CometNetNode(node_name="EvoScrapper-CometNet")
    return _cometnet_instance
