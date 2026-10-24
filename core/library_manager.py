import asyncio
import json
import os
import tempfile
import time
from typing import Dict, List, Optional
from models.library import LibraryItem, LibraryResponse


class LibraryManager:
    """
    Manages user bookmarks and watchlist items with status tracking:
    - watching (In Progress)
    - plan_to_watch (Planned)
    - completed (Finished)
    - on_hold (Paused)
    - dropped (Discontinued)
    Backed by local persistent JSON storage.
    """

    VALID_STATUSES = {"watching", "plan_to_watch", "completed", "on_hold", "dropped"}

    def __init__(self, storage_path: str = "data/library.json"):
        self.storage_path = storage_path
        self._lock = asyncio.Lock()
        self._items: Dict[str, LibraryItem] = {}
        self._loaded = False

    def _ensure_dir(self):
        folder = os.path.dirname(self.storage_path)
        if folder and not os.path.exists(folder):
            os.makedirs(folder, exist_ok=True)

    async def _load_if_needed(self):
        if self._loaded:
            return
        self._ensure_dir()
        if os.path.exists(self.storage_path):
            try:
                with open(self.storage_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    for k, v in data.items():
                        self._items[k] = LibraryItem(**v)
            except Exception as e:
                print(f"[LibraryManager] Failed to load library: {e}")
        self._loaded = True

    async def _save(self):
        self._ensure_dir()
        try:
            raw = {k: v.model_dump() for k, v in self._items.items()}
            content = json.dumps(raw, indent=2, ensure_ascii=False)

            def _sync_atomic_write():
                dir_name = os.path.dirname(self.storage_path) or "."
                with tempfile.NamedTemporaryFile("w", dir=dir_name, delete=False, encoding="utf-8") as tf:
                    tf.write(content)
                    tf.flush()
                    os.fsync(tf.fileno())
                    temp_name = tf.name
                os.replace(temp_name, self.storage_path)

            await asyncio.to_thread(_sync_atomic_write)
        except Exception as e:
            print(f"[LibraryManager] Failed to save library atomically: {e}")

    async def get_items(self, status: Optional[str] = None) -> LibraryResponse:
        async with self._lock:
            await self._load_if_needed()
            counts = {s: 0 for s in self.VALID_STATUSES}
            counts["all"] = len(self._items)

            for item in self._items.values():
                if item.status in counts:
                    counts[item.status] += 1

            if status and status.lower() != "all":
                filtered = [it for it in self._items.values() if it.status == status.lower()]
            else:
                filtered = list(self._items.values())

            # Sort by most recently updated
            filtered.sort(key=lambda x: x.updated_at, reverse=True)

            return LibraryResponse(
                items=filtered,
                total=len(filtered),
                counts=counts,
            )

    async def get_item(self, item_id: str) -> Optional[LibraryItem]:
        async with self._lock:
            await self._load_if_needed()
            return self._items.get(item_id)

    async def upsert_item(self, item: LibraryItem) -> LibraryItem:
        async with self._lock:
            await self._load_if_needed()
            now = time.time()
            existing = self._items.get(item.id)

            if existing:
                item.created_at = existing.created_at
                item.updated_at = now
            else:
                item.created_at = now
                item.updated_at = now

            if item.status not in self.VALID_STATUSES:
                item.status = "plan_to_watch"

            self._items[item.id] = item
            await self._save()
            return item

    async def bulk_upsert_items(self, items: List[LibraryItem]) -> int:
        async with self._lock:
            await self._load_if_needed()
            now = time.time()
            count = 0
            for item in items:
                if not item or not item.id or not item.title:
                    continue
                existing = self._items.get(item.id)
                if existing:
                    item.created_at = existing.created_at
                    item.updated_at = now
                else:
                    item.created_at = now
                    item.updated_at = now

                if item.status not in self.VALID_STATUSES:
                    item.status = "plan_to_watch"

                self._items[item.id] = item
                count += 1

            if count > 0:
                await self._save()
            return count

    async def update_status(self, item_id: str, status: str) -> Optional[LibraryItem]:
        async with self._lock:
            await self._load_if_needed()
            item = self._items.get(item_id)
            if not item:
                return None

            st = status.lower().strip()
            if st in self.VALID_STATUSES:
                item.status = st
                item.updated_at = time.time()
                await self._save()
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
            await self._load_if_needed()
            item = self._items.get(item_id)
            if not item:
                return None

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

            # Track granular per-episode progress for series/anime
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
                # Auto-transition to watching if still in plan_to_watch
                item.status = "watching"

            item.updated_at = time.time()
            await self._save()
            return item

    async def remove_item(self, item_id: str) -> bool:
        async with self._lock:
            await self._load_if_needed()
            if item_id in self._items:
                del self._items[item_id]
                await self._save()
                return True
            return False


library_manager = LibraryManager()
