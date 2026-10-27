import asyncio
import json
import time
from typing import Dict, List, Optional

from core.database import Database, get_database, migrate_legacy_json_library
from models.library import LibraryItem, LibraryResponse


def _row_to_item(row: Dict) -> LibraryItem:
    try:
        ep_progress = json.loads(row.get("episode_progress") or "{}")
        if not isinstance(ep_progress, dict):
            ep_progress = {}
    except (TypeError, ValueError):
        ep_progress = {}
    return LibraryItem(
        id=row["id"],
        title=row["title"],
        type=row.get("type") or "movie",
        poster=row.get("poster"),
        backdrop=row.get("backdrop"),
        year=row.get("year"),
        rating=row.get("rating"),
        status=row.get("status") or "plan_to_watch",
        current_season=row.get("current_season"),
        current_episode=row.get("current_episode"),
        total_episodes=row.get("total_episodes") or 0,
        progress_percent=row.get("progress_percent") or 0,
        playback_seconds=row.get("playback_seconds") or 0.0,
        duration_seconds=row.get("duration_seconds") or 0.0,
        episode_progress=ep_progress,
        created_at=row.get("created_at") or 0.0,
        updated_at=row.get("updated_at") or 0.0,
    )


class LibraryManager:
    """
    T4.1: manages user bookmarks and watchlist items backed by embedded SQLite
    (data/evoscrapper.db) instead of a rewritten-per-write JSON file. Status
    tracking and semantics are unchanged:
    - watching / plan_to_watch / completed / on_hold / dropped
    The legacy data/library.json is imported once and archived as *.migrated.
    """

    VALID_STATUSES = {"watching", "plan_to_watch", "completed", "on_hold", "dropped"}

    def __init__(self, db_path: Optional[str] = None, storage_path: str = "data/library.json"):
        # A custom db_path gets a dedicated Database (tests, tooling); the
        # default shares the process-wide singleton.
        self.db = Database(db_path) if db_path else get_database()
        self.legacy_json_path = storage_path
        self._lock = asyncio.Lock()
        self._ready = False

    async def _ensure_ready(self):
        if self._ready:
            return
        await self.db.connect()
        await migrate_legacy_json_library(self.db, self.legacy_json_path)
        self._ready = True

    @staticmethod
    def _heal_poster(item: LibraryItem) -> None:
        if not item.poster and item.id and item.id.startswith("tt"):
            item.poster = f"https://images.metahub.space/poster/medium/{item.id}/img"

    def _merge_into_existing(self, item: LibraryItem, existing: LibraryItem) -> None:
        item.created_at = existing.created_at
        if not item.poster and existing.poster:
            item.poster = existing.poster
        if not item.backdrop and existing.backdrop:
            item.backdrop = existing.backdrop
        if not item.year and existing.year:
            item.year = existing.year
        if not item.rating and existing.rating:
            item.rating = existing.rating

    async def get_items(self, status: Optional[str] = None) -> LibraryResponse:
        async with self._lock:
            await self._ensure_ready()
            rows = await self.db.fetch_all(
                "SELECT * FROM library_items ORDER BY updated_at DESC"
            )
            items = [_row_to_item(r) for r in rows]

        counts = {s: 0 for s in self.VALID_STATUSES}
        counts["all"] = len(items)
        for item in items:
            self._heal_poster(item)
            if item.status in counts:
                counts[item.status] += 1

        if status and status.lower() != "all":
            filtered = [it for it in items if it.status == status.lower()]
        else:
            filtered = items
        return LibraryResponse(items=filtered, total=len(filtered), counts=counts)

    async def get_item(self, item_id: str) -> Optional[LibraryItem]:
        async with self._lock:
            await self._ensure_ready()
            row = await self.db.fetch_one("SELECT * FROM library_items WHERE id = ?", (item_id,))
        if not row:
            return None
        item = _row_to_item(row)
        self._heal_poster(item)
        return item

    async def upsert_item(self, item: LibraryItem) -> LibraryItem:
        async with self._lock:
            await self._ensure_ready()
            now = time.time()
            row = await self.db.fetch_one("SELECT * FROM library_items WHERE id = ?", (item.id,))
            if row:
                self._merge_into_existing(item, _row_to_item(row))
            else:
                item.created_at = now
            item.updated_at = now
            self._heal_poster(item)
            if item.status not in self.VALID_STATUSES:
                item.status = "plan_to_watch"
            await self._write_item(item)
            return item

    async def bulk_upsert_items(self, items: List[LibraryItem]) -> int:
        async with self._lock:
            await self._ensure_ready()
            now = time.time()
            count = 0
            for item in items:
                if not item or not item.id or not item.title:
                    continue
                row = await self.db.fetch_one("SELECT * FROM library_items WHERE id = ?", (item.id,))
                if row:
                    self._merge_into_existing(item, _row_to_item(row))
                else:
                    item.created_at = now
                item.updated_at = now
                self._heal_poster(item)
                if item.status not in self.VALID_STATUSES:
                    item.status = "plan_to_watch"
                await self._write_item(item)
                count += 1
            return count

    async def _write_item(self, item: LibraryItem) -> None:
        await self.db.execute(
            """INSERT INTO library_items
               (id, title, type, poster, backdrop, year, rating, status,
                current_season, current_episode, total_episodes, progress_percent,
                playback_seconds, duration_seconds, episode_progress, created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(id) DO UPDATE SET
                 title=excluded.title, type=excluded.type, poster=excluded.poster,
                 backdrop=excluded.backdrop, year=excluded.year, rating=excluded.rating,
                 status=excluded.status, current_season=excluded.current_season,
                 current_episode=excluded.current_episode, total_episodes=excluded.total_episodes,
                 progress_percent=excluded.progress_percent, playback_seconds=excluded.playback_seconds,
                 duration_seconds=excluded.duration_seconds, episode_progress=excluded.episode_progress,
                 created_at=excluded.created_at, updated_at=excluded.updated_at""",
            (
                item.id, item.title, item.type, item.poster, item.backdrop,
                item.year, item.rating, item.status,
                item.current_season, item.current_episode, item.total_episodes,
                item.progress_percent, item.playback_seconds, item.duration_seconds,
                json.dumps(item.episode_progress or {}),
                item.created_at, item.updated_at,
            ),
        )

    async def update_status(self, item_id: str, status: str) -> Optional[LibraryItem]:
        async with self._lock:
            await self._ensure_ready()
            row = await self.db.fetch_one("SELECT * FROM library_items WHERE id = ?", (item_id,))
            if not row:
                return None
            item = _row_to_item(row)
            st = status.lower().strip()
            if st in self.VALID_STATUSES:
                item.status = st
                item.updated_at = time.time()
                await self._write_item(item)
            return item

    async def update_progress(
        self,
        item_id: str,
        season: Optional[int] = None,
        episode: Optional[int] = None,
        progress_percent: Optional[int] = None,
        playback_seconds: Optional[float] = None,
        duration_seconds: Optional[float] = None,
        status: Optional[str] = None,
    ) -> Optional[LibraryItem]:
        async with self._lock:
            await self._ensure_ready()
            row = await self.db.fetch_one("SELECT * FROM library_items WHERE id = ?", (item_id,))
            if not row:
                return None
            item = _row_to_item(row)

            if season is not None:
                item.current_season = season
            if episode is not None:
                item.current_episode = episode
            if progress_percent is not None:
                item.progress_percent = progress_percent
            if playback_seconds is not None:
                item.playback_seconds = playback_seconds
            if duration_seconds is not None:
                item.duration_seconds = duration_seconds

            # Granular per-episode progress for series/anime
            if season is not None or episode is not None:
                ep_key = f"s{season or 1}e{episode or 1}"
                if item.episode_progress is None:
                    item.episode_progress = {}
                item.episode_progress[ep_key] = {
                    "season": season,
                    "episode": episode,
                    "progress_percent": progress_percent,
                    "playback_seconds": playback_seconds,
                    "duration_seconds": duration_seconds,
                    "updated_at": time.time(),
                }

            if status and status.lower().strip() in self.VALID_STATUSES:
                item.status = status.lower().strip()
            elif progress_percent is not None and progress_percent >= 90 and item.type == "movie":
                item.status = "completed"
            elif item.status == "plan_to_watch":
                item.status = "watching"

            item.updated_at = time.time()
            await self._write_item(item)
            return item

    async def remove_item(self, item_id: str) -> bool:
        async with self._lock:
            await self._ensure_ready()
            row = await self.db.fetch_one("SELECT id FROM library_items WHERE id = ?", (item_id,))
            if not row:
                return False
            await self.db.execute("DELETE FROM library_items WHERE id = ?", (item_id,))
            return True


library_manager = LibraryManager()
