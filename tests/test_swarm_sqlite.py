import os
import tempfile
import pytest
import json
import time

from core.database import Database, migrate_legacy_json_swarm
from core.swarm_intelligence import SeekHeatmapStore, DebridCoverageIndex


@pytest.mark.asyncio
async def test_swarm_sqlite_tables_created():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test_swarm.db")
        db = Database(db_path)
        await db.connect()

        # Check schema version
        row = await db.fetch_one("SELECT version FROM schema_version")
        assert row is not None
        assert row["version"] >= 2

        # Verify tables exist
        heat_rows = await db.fetch_all("SELECT * FROM seek_heatmaps")
        assert heat_rows == []
        cov_rows = await db.fetch_all("SELECT * FROM debrid_coverage")
        assert cov_rows == []

        await db.close()


@pytest.mark.asyncio
async def test_seek_heatmap_sqlite_roundtrip():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test_swarm.db")
        json_path = os.path.join(tmpdir, "seek.json")
        db = Database(db_path)
        await db.connect()

        store = SeekHeatmapStore(path=json_path)
        store.record("0123456789abcdef0123456789abcdef01234567", 90.0, weight=2.5)
        store.record("0123456789abcdef0123456789abcdef01234567", 120.0, weight=1.0)

        # Sync to DB
        count = await store.sync_to_db(db)
        assert count == 2

        # Verify rows in DB
        rows = await db.fetch_all("SELECT * FROM seek_heatmaps WHERE info_hash = ?", ("0123456789abcdef0123456789abcdef01234567",))
        assert len(rows) == 2

        # Create fresh store and load from DB
        fresh_store = SeekHeatmapStore(path=os.path.join(tmpdir, "empty.json"))
        assert fresh_store.bucket_count("0123456789abcdef0123456789abcdef01234567") == 0
        loaded = await fresh_store.load_from_db(db)
        assert loaded == 2
        assert fresh_store.bucket_count("0123456789abcdef0123456789abcdef01234567") == 2
        targets = fresh_store.top_seek_targets("0123456789abcdef0123456789abcdef01234567", k=2)
        assert len(targets) == 2
        assert targets[0]["bucket"] == 3  # 90.0 // 30 = 3

        await db.close()


@pytest.mark.asyncio
async def test_debrid_coverage_sqlite_roundtrip():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test_swarm.db")
        json_path = os.path.join(tmpdir, "cov.json")
        db = Database(db_path)
        await db.connect()

        index = DebridCoverageIndex(path=json_path)
        index.record("aabbccddeeff00112233445566778899aabbccdd", "realdebrid", corroborated=True)
        index.record("aabbccddeeff00112233445566778899aabbccdd", "alldebrid", corroborated=False)

        count = await index.sync_to_db(db)
        assert count == 2

        rows = await db.fetch_all("SELECT * FROM debrid_coverage WHERE info_hash = ?", ("aabbccddeeff00112233445566778899aabbccdd",))
        assert len(rows) == 2

        fresh_index = DebridCoverageIndex(path=os.path.join(tmpdir, "empty.json"))
        loaded = await fresh_index.load_from_db(db)
        assert loaded == 2
        providers = fresh_index.providers_for("aabbccddeeff00112233445566778899aabbccdd")
        assert len(providers) == 2
        assert providers[0]["provider"] == "realdebrid"  # higher confidence

        await db.close()


@pytest.mark.asyncio
async def test_migrate_legacy_json_swarm():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test_swarm.db")
        heat_json = os.path.join(tmpdir, "legacy_heat.json")
        cov_json = os.path.join(tmpdir, "legacy_cov.json")

        with open(heat_json, "w") as f:
            json.dump({"hash1": {"1": 1.5, "2": 3.0}}, f)

        with open(cov_json, "w") as f:
            json.dump({"hash1": {"torbox": {"ts": time.time(), "hits": 2.0}}}, f)

        db = Database(db_path)
        await db.connect()

        h_count, c_count = await migrate_legacy_json_swarm(db, heat_json, cov_json)
        assert h_count == 2
        assert c_count == 1

        # Idempotency check
        h2, c2 = await migrate_legacy_json_swarm(db, heat_json, cov_json)
        assert h2 == 0
        assert c2 == 0

        await db.close()
