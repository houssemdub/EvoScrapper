"""
T4.1: Embedded SQLite storage layer (asyncio-native via aiosqlite).

Replaces file-based JSON persistence for the library and watch history,
eliminating whole-file rewrite concurrency and enabling indexed queries.
WAL mode keeps readers and the single writer concurrent-safe.

Design note: a thin async DAL instead of SQLAlchemy/SQLModel — the models are
already pydantic, the schema is small, and this keeps the dependency surface
and query behavior explicit.
"""
import json
import os
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

import aiosqlite

from core.logger import app_logger

DEFAULT_DB_PATH = os.path.join("data", "evoscrapper.db")

_SCHEMA_VERSION = 2
_SCHEMA = """
CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS library_items (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    type TEXT NOT NULL DEFAULT 'movie',
    poster TEXT,
    backdrop TEXT,
    year TEXT,
    rating TEXT,
    status TEXT NOT NULL DEFAULT 'plan_to_watch',
    current_season INTEGER,
    current_episode INTEGER,
    total_episodes INTEGER DEFAULT 0,
    progress_percent INTEGER DEFAULT 0,
    playback_seconds REAL DEFAULT 0.0,
    duration_seconds REAL DEFAULT 0.0,
    episode_progress TEXT NOT NULL DEFAULT '{}',
    created_at REAL NOT NULL DEFAULT 0.0,
    updated_at REAL NOT NULL DEFAULT 0.0
);

CREATE INDEX IF NOT EXISTS idx_library_status ON library_items(status);
CREATE INDEX IF NOT EXISTS idx_library_updated ON library_items(updated_at DESC);

CREATE TABLE IF NOT EXISTS seek_heatmaps (
    info_hash TEXT NOT NULL,
    bucket INTEGER NOT NULL,
    weight REAL NOT NULL,
    updated_at REAL NOT NULL,
    PRIMARY KEY (info_hash, bucket)
);

CREATE INDEX IF NOT EXISTS idx_seek_hash ON seek_heatmaps(info_hash);

CREATE TABLE IF NOT EXISTS debrid_coverage (
    info_hash TEXT NOT NULL,
    provider TEXT NOT NULL,
    hits REAL NOT NULL DEFAULT 1.0,
    last_seen REAL NOT NULL,
    PRIMARY KEY (info_hash, provider)
);

CREATE INDEX IF NOT EXISTS idx_coverage_hash ON debrid_coverage(info_hash);
CREATE INDEX IF NOT EXISTS idx_coverage_last_seen ON debrid_coverage(last_seen DESC);

CREATE TABLE IF NOT EXISTS profiles (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    avatar TEXT NOT NULL DEFAULT 'default',
    pin_hash TEXT,
    salt TEXT,
    is_kids INTEGER NOT NULL DEFAULT 0,
    created_at REAL NOT NULL DEFAULT 0.0,
    updated_at REAL NOT NULL DEFAULT 0.0
);
"""


class Database:
    """Singleton async SQLite connection with schema management and helpers."""

    def __init__(self, db_path: str = DEFAULT_DB_PATH):
        self.db_path = db_path
        self._conn: Optional[aiosqlite.Connection] = None
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)

    async def connect(self) -> None:
        if self._conn is not None:
            return
        conn = await aiosqlite.connect(self.db_path)
        conn.row_factory = aiosqlite.Row
        await conn.execute("PRAGMA journal_mode=WAL")
        await conn.execute("PRAGMA foreign_keys=ON")
        await conn.executescript(_SCHEMA)
        row = await (await conn.execute("SELECT version FROM schema_version")).fetchone()
        if row is None:
            await conn.execute("INSERT INTO schema_version (version) VALUES (?)", (_SCHEMA_VERSION,))
        elif row["version"] < _SCHEMA_VERSION:
            await conn.execute("UPDATE schema_version SET version = ?", (_SCHEMA_VERSION,))
        await conn.commit()
        self._conn = conn
        app_logger.info(f"[Database] SQLite ready at {self.db_path} (schema v{_SCHEMA_VERSION})")

    def _require(self) -> aiosqlite.Connection:
        if self._conn is None:
            raise RuntimeError("Database.connect() must be awaited first")
        return self._conn

    async def execute(self, sql: str, params: Iterable[Any] = ()) -> None:
        conn = self._require()
        await conn.execute(sql, tuple(params))
        await conn.commit()

    async def fetch_all(self, sql: str, params: Iterable[Any] = ()) -> List[Dict[str, Any]]:
        conn = self._require()
        async with conn.execute(sql, tuple(params)) as cursor:
            rows = await cursor.fetchall()
            return [dict(r) for r in rows]

    async def fetch_one(self, sql: str, params: Iterable[Any] = ()) -> Optional[Dict[str, Any]]:
        conn = self._require()
        async with conn.execute(sql, tuple(params)) as cursor:
            row = await cursor.fetchone()
            return dict(row) if row is not None else None

    async def close(self) -> None:
        if self._conn is not None:
            try:
                await self._conn.close()
            except Exception:
                pass
            self._conn = None


_database: Optional[Database] = None


def get_database(db_path: str = DEFAULT_DB_PATH) -> Database:
    global _database
    if _database is None:
        _database = Database(db_path)
    return _database


async def migrate_legacy_json_library(db: Database, json_path: str) -> int:
    """
    One-time import of the legacy data/library.json watchlist. Runs only when
    the target table is empty and the file exists; archives the file after a
    successful import so a later re-import can never duplicate rows.
    """
    if not os.path.isfile(json_path):
        return 0
    existing = await db.fetch_one("SELECT COUNT(*) AS n FROM library_items")
    if existing and existing["n"] > 0:
        return 0
    try:
        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return 0
    except Exception as e:
        app_logger.warning(f"[Database] legacy library import failed to read {json_path}: {e}")
        return 0

    now = time.time()
    count = 0
    for item_id, raw in data.items():
        if not isinstance(raw, dict) or not item_id or not raw.get("title"):
            continue
        await db.execute(
            """INSERT OR REPLACE INTO library_items
               (id, title, type, poster, backdrop, year, rating, status,
                current_season, current_episode, total_episodes, progress_percent,
                playback_seconds, duration_seconds, episode_progress, created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                item_id,
                raw.get("title", "Unknown"),
                raw.get("type", "movie"),
                raw.get("poster"),
                raw.get("backdrop"),
                raw.get("year"),
                raw.get("rating"),
                raw.get("status", "plan_to_watch"),
                raw.get("current_season"),
                raw.get("current_episode"),
                raw.get("total_episodes", 0),
                raw.get("progress_percent", 0),
                raw.get("playback_seconds", 0.0),
                raw.get("duration_seconds", 0.0),
                json.dumps(raw.get("episode_progress") or {}),
                raw.get("created_at", now),
                raw.get("updated_at", now),
            ),
        )
        count += 1

    try:
        os.replace(json_path, json_path + ".migrated")
    except OSError:
        pass
    app_logger.info(f"[Database] migrated {count} library items from {json_path}")
    return count


async def migrate_legacy_json_swarm(db: Database, heatmap_path: str = "data/cometnet/seek_heatmap.json", coverage_path: str = "data/cometnet/debrid_coverage.json") -> Tuple[int, int]:
    """
    Imports legacy JSON seek heatmaps and debrid coverage into SQLite if tables are empty.
    """
    migrated_heat = 0
    migrated_cov = 0
    now = time.time()

    # 1. Heatmaps
    if os.path.isfile(heatmap_path):
        existing = await db.fetch_one("SELECT COUNT(*) AS n FROM seek_heatmaps")
        if existing and existing["n"] == 0:
            try:
                with open(heatmap_path, "r", encoding="utf-8") as f:
                    heat_data = json.load(f)
                if isinstance(heat_data, dict):
                    for h, buckets in heat_data.items():
                        if not isinstance(buckets, dict):
                            continue
                        for b, w in buckets.items():
                            try:
                                await db.execute(
                                    "INSERT OR REPLACE INTO seek_heatmaps (info_hash, bucket, weight, updated_at) VALUES (?, ?, ?, ?)",
                                    (str(h).strip().lower(), int(b), float(w), now),
                                )
                                migrated_heat += 1
                            except Exception:
                                pass
            except Exception as e:
                app_logger.warning(f"[Database] heatmap migration error: {e}")

    # 2. Coverage
    if os.path.isfile(coverage_path):
        existing = await db.fetch_one("SELECT COUNT(*) AS n FROM debrid_coverage")
        if existing and existing["n"] == 0:
            try:
                with open(coverage_path, "r", encoding="utf-8") as f:
                    cov_data = json.load(f)
                if isinstance(cov_data, dict):
                    for h, providers in cov_data.items():
                        if not isinstance(providers, dict):
                            continue
                        for p, v in providers.items():
                            if not isinstance(v, dict):
                                continue
                            try:
                                await db.execute(
                                    "INSERT OR REPLACE INTO debrid_coverage (info_hash, provider, hits, last_seen) VALUES (?, ?, ?, ?)",
                                    (str(h).strip().lower(), str(p).strip().lower(), float(v.get("hits", 1.0)), float(v.get("ts", now))),
                                )
                                migrated_cov += 1
                            except Exception:
                                pass
            except Exception as e:
                app_logger.warning(f"[Database] coverage migration error: {e}")

    return migrated_heat, migrated_cov
