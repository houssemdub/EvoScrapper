"""
P8: Watch-Together rooms over CometNet.

A room is identified by a short unguessable code. Members post playback
events (play/pause/seek) that are sequenced per room and fanned out over the
CometNet mesh as signed PARTY_EVENT messages, so instances of EvoScrapper on
different machines can share a room. Each viewer keeps their own media source;
only the transport controls are synchronized.
"""
import secrets
import time
from typing import Any, Dict, List, Optional

from core.logger import cometnet_logger

PARTY_EVENT_MAX_AGE_SECONDS = 300.0
ROOM_MAX_EVENTS = 500
ROOM_MAX_MEMBERS = 12
ROOM_TTL_SECONDS = 6 * 3600


class WatchPartyError(Exception):
    pass


class WatchPartyRoom:
    def __init__(self, code: str, info_hash: str, host_peer_id: str):
        self.code = code
        self.info_hash = info_hash
        self.host_peer_id = host_peer_id
        self.created_at = time.time()
        self.last_active = self.created_at
        self.members: Dict[str, float] = {host_peer_id: self.created_at}
        self.events: List[Dict[str, Any]] = []
        self._seq = 0
        self.latest_subtitle_state: Optional[Dict[str, Any]] = None

    def add_member(self, peer_id: str) -> int:
        if peer_id not in self.members and len(self.members) >= ROOM_MAX_MEMBERS:
            raise WatchPartyError("room is full")
        self.members[peer_id] = time.time()
        self.last_active = time.time()
        return len(self.events)

    def is_member(self, peer_id: str) -> bool:
        return peer_id in self.members

    def post_event(
        self,
        peer_id: str,
        action: str,
        position: float,
        subtitle_state: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        if not self.is_member(peer_id):
            raise WatchPartyError("peer has not joined this room")
        allowed = {"play", "pause", "seek", "sync", "sub_sync"}
        if action not in allowed:
            raise WatchPartyError(f"unsupported action: {action}")
        self._seq += 1
        event = {
            "seq": self._seq,
            "peer_id": peer_id,
            "action": action,
            "position": round(float(position), 3),
            "ts": time.time(),
        }
        if subtitle_state:
            event["subtitle_state"] = subtitle_state
            self.latest_subtitle_state = subtitle_state
        self.events.append(event)
        if len(self.events) > ROOM_MAX_EVENTS:
            self.events = self.events[-ROOM_MAX_EVENTS:]
        self.last_active = event["ts"]
        return event

    def events_since(self, seq: int) -> List[Dict[str, Any]]:
        return [e for e in self.events if e["seq"] > seq]

    def snapshot(self) -> Dict[str, Any]:
        latest = self.events[-1] if self.events else None
        return {
            "code": self.code,
            "info_hash": self.info_hash,
            "host": self.host_peer_id,
            "members": sorted(self.members.keys()),
            "member_count": len(self.members),
            "latest_seq": self._seq,
            "latest_event": latest,
            "latest_subtitle_state": self.latest_subtitle_state,
        }


class WatchPartyManager:
    def __init__(self):
        self.rooms: Dict[str, WatchPartyRoom] = {}

    def create_room(self, info_hash: str, host_peer_id: str) -> WatchPartyRoom:
        h = (info_hash or "").strip().lower()
        if not h or len(h) != 40:
            raise WatchPartyError("invalid info hash")
        host = (host_peer_id or "").strip()
        if not host:
            raise WatchPartyError("invalid host id")
        self._sweep()
        code = secrets.token_hex(3)
        while code in self.rooms:
            code = secrets.token_hex(3)
        room = WatchPartyRoom(code, h, host)
        self.rooms[code] = room
        return room

    def get_room(self, code: str) -> Optional[WatchPartyRoom]:
        return self.rooms.get((code or "").strip().lower())

    def join_room(self, code: str, peer_id: str) -> WatchPartyRoom:
        room = self.get_room(code)
        if not room:
            raise WatchPartyError("room not found")
        room.add_member((peer_id or "").strip())
        return room

    def post_event(
        self,
        code: str,
        peer_id: str,
        action: str,
        position: float,
        subtitle_state: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        room = self.get_room(code)
        if not room:
            raise WatchPartyError("room not found")
        return room.post_event(peer_id, action, position, subtitle_state=subtitle_state)

    def apply_gossip_event(
        self,
        code: str,
        peer_id: str,
        action: str,
        position: float,
        ts: float,
        subtitle_state: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """Ingests a PARTY_EVENT gossiped from a remote instance, if the room exists here."""
        room = self.get_room(code)
        if not room:
            return False
        if abs(time.time() - ts) > PARTY_EVENT_MAX_AGE_SECONDS:
            return False
        if peer_id and peer_id not in room.members:
            room.members[peer_id] = ts
        room.post_event(peer_id, action, position, subtitle_state=subtitle_state)
        return True

    def _sweep(self) -> None:
        now = time.time()
        stale = [code for code, room in self.rooms.items() if now - room.last_active > ROOM_TTL_SECONDS]
        for code in stale:
            self.rooms.pop(code, None)

    def stats(self) -> Dict[str, Any]:
        self._sweep()
        return {"rooms": len(self.rooms), "members": sum(len(r.members) for r in self.rooms.values())}


_manager: Optional[WatchPartyManager] = None


def get_watch_party_manager() -> WatchPartyManager:
    global _manager
    if _manager is None:
        _manager = WatchPartyManager()
    return _manager
