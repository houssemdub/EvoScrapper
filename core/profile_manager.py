"""
T4.4: Household multi-user profiles and PIN verification manager.
Backed by embedded SQLite (profiles table in data/evoscrapper.db).
"""
import hashlib
import os
import secrets
import time
from typing import Any, Dict, List, Optional
from uuid import uuid4

from core.database import Database, get_database


def _hash_pin(pin: str, salt: str) -> str:
    return hashlib.sha256((salt + pin).encode("utf-8")).hexdigest()


class ProfileManager:
    """
    Manages household user profiles, kids mode restriction, and PIN lock verification.
    """

    def __init__(self, db: Optional[Database] = None):
        self.db = db or get_database()
        self._ready = False

    async def _ensure_ready(self) -> None:
        if self._ready:
            return
        await self.db.connect()
        self._ready = True

        # Ensure default profile exists if database has 0 profiles
        count_row = await self.db.fetch_one("SELECT COUNT(*) AS n FROM profiles")
        if count_row and count_row["n"] == 0:
            now = time.time()
            await self.db.execute(
                """INSERT INTO profiles (id, name, avatar, pin_hash, salt, is_kids, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                ("default", "Default Profile", "avatar_1", None, None, 0, now, now),
            )

    async def list_profiles(self) -> List[Dict[str, Any]]:
        await self._ensure_ready()
        rows = await self.db.fetch_all("SELECT id, name, avatar, (pin_hash IS NOT NULL) AS has_pin, is_kids, created_at, updated_at FROM profiles ORDER BY created_at ASC")
        return [
            {
                "id": r["id"],
                "name": r["name"],
                "avatar": r["avatar"],
                "has_pin": bool(r["has_pin"]),
                "is_kids": bool(r["is_kids"]),
                "created_at": r["created_at"],
                "updated_at": r["updated_at"],
            }
            for r in rows
        ]

    async def get_profile(self, profile_id: str) -> Optional[Dict[str, Any]]:
        await self._ensure_ready()
        r = await self.db.fetch_one("SELECT id, name, avatar, (pin_hash IS NOT NULL) AS has_pin, is_kids, created_at, updated_at FROM profiles WHERE id = ?", (profile_id,))
        if not r:
            return None
        return {
            "id": r["id"],
            "name": r["name"],
            "avatar": r["avatar"],
            "has_pin": bool(r["has_pin"]),
            "is_kids": bool(r["is_kids"]),
            "created_at": r["created_at"],
            "updated_at": r["updated_at"],
        }

    async def create_profile(
        self,
        name: str,
        avatar: str = "avatar_1",
        pin: Optional[str] = None,
        is_kids: bool = False,
    ) -> Dict[str, Any]:
        await self._ensure_ready()
        profile_id = f"prof_{uuid4().hex[:8]}"
        now = time.time()

        pin_hash = None
        salt = None
        if pin and pin.strip():
            salt = secrets.token_hex(8)
            pin_hash = _hash_pin(pin.strip(), salt)

        await self.db.execute(
            """INSERT INTO profiles (id, name, avatar, pin_hash, salt, is_kids, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (profile_id, name.strip(), avatar.strip() or "avatar_1", pin_hash, salt, 1 if is_kids else 0, now, now),
        )

        return {
            "id": profile_id,
            "name": name.strip(),
            "avatar": avatar.strip() or "avatar_1",
            "has_pin": bool(pin_hash),
            "is_kids": is_kids,
            "created_at": now,
            "updated_at": now,
        }

    async def verify_pin(self, profile_id: str, pin: str) -> bool:
        await self._ensure_ready()
        r = await self.db.fetch_one("SELECT pin_hash, salt FROM profiles WHERE id = ?", (profile_id,))
        if not r:
            return False
        if not r["pin_hash"]:
            return True  # No PIN required
        if not pin:
            return False
        expected_hash = _hash_pin(pin.strip(), r["salt"] or "")
        import hmac
        return hmac.compare_digest(expected_hash, r["pin_hash"])

    async def delete_profile(self, profile_id: str) -> bool:
        await self._ensure_ready()
        count_row = await self.db.fetch_one("SELECT COUNT(*) AS n FROM profiles")
        if count_row and count_row["n"] <= 1:
            return False  # Cannot delete the only remaining profile

        await self.db.execute("DELETE FROM profiles WHERE id = ?", (profile_id,))
        return True


_profile_manager: Optional[ProfileManager] = None


def get_profile_manager() -> ProfileManager:
    global _profile_manager
    if _profile_manager is None:
        _profile_manager = ProfileManager()
    return _profile_manager
