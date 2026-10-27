"""T4.1 SQLite storage: JSON migration, merge semantics, concurrency, router flow."""
import asyncio
import json
import sys
import os

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from core.library_manager import LibraryManager
from models.library import LibraryItem


@pytest.fixture
def manager(tmp_path):
    return LibraryManager(
        db_path=str(tmp_path / "library.db"),
        storage_path=str(tmp_path / "library.json"),
    )


def _item(item_id: str, **kwargs) -> LibraryItem:
    return LibraryItem(id=item_id, title=kwargs.pop("title", f"Title {item_id}"), **kwargs)


class TestCrudAndSemantics:
    @pytest.mark.asyncio
    async def test_upsert_get_roundtrip_preserves_all_fields(self, manager):
        saved = await manager.upsert_item(_item("tt111", type="series", year="2009", total_episodes=340))
        assert saved.created_at > 0 and saved.updated_at > 0

        fetched = await manager.get_item("tt111")
        assert fetched is not None
        assert fetched.type == "series"
        assert fetched.total_episodes == 340
        assert fetched.created_at == saved.created_at

        # Re-upsert keeps created_at stable, bumps updated_at
        again = await manager.upsert_item(_item("tt111", type="series"))
        assert again.created_at == saved.created_at
        assert again.updated_at >= saved.updated_at

    @pytest.mark.asyncio
    async def test_merge_fills_empty_fields_from_existing(self, manager):
        await manager.upsert_item(_item("tt222", poster="https://x/p.jpg", backdrop="https://x/b.jpg", rating="8.5", year="2010"))
        merged = await manager.upsert_item(_item("tt222"))
        assert merged.poster == "https://x/p.jpg"
        assert merged.backdrop == "https://x/b.jpg"
        assert merged.rating == "8.5"
        assert merged.year == "2010"

    @pytest.mark.asyncio
    async def test_invalid_status_falls_back_to_plan_to_watch(self, manager):
        saved = await manager.upsert_item(_item("tt333", status="bogus"))
        assert saved.status == "plan_to_watch"

    @pytest.mark.asyncio
    async def test_movie_auto_completes_at_90_percent(self, manager):
        await manager.upsert_item(_item("tt444", type="movie", status="watching"))
        done = await manager.update_progress("tt444", progress_percent=92)
        assert done.status == "completed"

    @pytest.mark.asyncio
    async def test_series_episode_progress_roundtrip(self, manager):
        await manager.upsert_item(_item("tt555", type="anime"))
        await manager.update_progress("tt555", season=2, episode=7, progress_percent=60, playback_seconds=300.0)
        item = await manager.get_item("tt555")
        ep = item.episode_progress["s2e7"]
        assert ep["episode"] == 7
        assert ep["playback_seconds"] == 300.0

        # Second update overwrites the same key
        await manager.update_progress("tt555", season=2, episode=7, progress_percent=95)
        item2 = await manager.get_item("tt555")
        assert item2.episode_progress["s2e7"]["progress_percent"] == 95

    @pytest.mark.asyncio
    async def test_counts_and_status_filter(self, manager):
        await manager.upsert_item(_item("a", status="watching"))
        await manager.upsert_item(_item("b", status="completed"))
        await manager.upsert_item(_item("c", status="watching"))
        res = await manager.get_items()
        assert res.counts["watching"] == 2
        assert res.counts["completed"] == 1
        assert res.counts["all"] == 3
        filtered = await manager.get_items(status="watching")
        assert filtered.total == 2 and {i.id for i in filtered.items} == {"a", "c"}

    @pytest.mark.asyncio
    async def test_remove(self, manager):
        await manager.upsert_item(_item("gone"))
        assert await manager.remove_item("gone") is True
        assert await manager.remove_item("gone") is False
        assert await manager.get_item("gone") is None

    @pytest.mark.asyncio
    async def test_bulk_upsert_skips_invalid(self, manager):
        count = await manager.bulk_upsert_items([
            _item("ok1"), _item("ok2"),
            _item(""),  # no id
            LibraryItem(id="no_title", title=""),  # empty title
        ])
        assert count == 2


class TestLegacyJsonMigration:
    @pytest.mark.asyncio
    async def test_json_library_imported_and_archived(self, tmp_path):
        legacy = {
            "tt999": {
                "id": "tt999", "title": "Legacy Movie", "type": "movie",
                "status": "watching", "progress_percent": 40,
                "created_at": 100.0, "updated_at": 200.0,
            }
        }
        json_path = tmp_path / "library.json"
        json_path.write_text(json.dumps(legacy), encoding="utf-8")
        db_path = tmp_path / "library.db"

        mgr = LibraryManager(db_path=str(db_path), storage_path=str(json_path))
        item = await mgr.get_item("tt999")
        assert item is not None
        assert item.title == "Legacy Movie"
        assert item.created_at == 100.0

        # Archived so a later re-import cannot duplicate
        assert not json_path.exists()
        assert (tmp_path / "library.json.migrated").exists()
        res = await mgr.get_items()
        assert res.total == 1

    @pytest.mark.asyncio
    async def test_no_reimport_when_db_already_populated(self, tmp_path):
        db_path = tmp_path / "library.db"
        json_path = tmp_path / "library.json"

        # Seed the DB first, then plant a legacy JSON afterwards.
        first = LibraryManager(db_path=str(db_path), storage_path=str(json_path))
        await first.upsert_item(_item("tt2", title="B"))
        json_path.write_text(json.dumps({"tt1": {"id": "tt1", "title": "A"}}), encoding="utf-8")

        # A fresh manager (new process simulation) must skip migration
        # because the table is not empty.
        second = LibraryManager(db_path=str(db_path), storage_path=str(json_path))
        res = await second.get_items()
        assert res.total == 1 and res.items[0].id == "tt2"
        assert json_path.exists()  # never consumed

    @pytest.mark.asyncio
    async def test_corrupt_json_is_ignored(self, tmp_path):
        json_path = tmp_path / "library.json"
        json_path.write_text("{not valid json", encoding="utf-8")
        mgr = LibraryManager(db_path=str(tmp_path / "library.db"), storage_path=str(json_path))
        res = await mgr.get_items()
        assert res.total == 0


class TestConcurrency:
    @pytest.mark.asyncio
    async def test_parallel_upserts_all_persist(self, manager):
        async def upsert(i: int):
            return await manager.upsert_item(_item(f"cc{i:03d}", status="watching"))

        await asyncio.gather(*(upsert(i) for i in range(25)))
        res = await manager.get_items()
        assert res.total == 25

    @pytest.mark.asyncio
    async def test_parallel_progress_updates_last_write_wins_consistently(self, manager):
        await manager.upsert_item(_item("race", type="movie", status="watching"))

        async def bump(p: int):
            return await manager.update_progress("race", progress_percent=p)

        await asyncio.gather(*(bump(p) for p in range(10, 60, 5)))
        item = await manager.get_item("race")
        assert item.progress_percent in range(10, 60, 5)
        # Row must be internally consistent (no torn JSON)
        assert isinstance(item.episode_progress, dict)


class TestRouterFlow:
    @pytest.mark.asyncio
    async def test_library_endpoints_end_to_end(self, tmp_path, monkeypatch):
        from fastapi.testclient import TestClient
        from main import app
        import routers.library as rl
        from core.library_manager import LibraryManager

        isolated = LibraryManager(
            db_path=str(tmp_path / "library.db"),
            storage_path=str(tmp_path / "library.json"),
        )
        monkeypatch.setattr(rl, "library_manager", isolated)
        client = TestClient(app)

        res = client.post("/api/v1/library", json={
            "id": "tt1375666", "title": "Inception", "type": "movie", "year": "2010",
        })
        assert res.status_code == 200, res.text

        listed = client.get("/api/v1/library")
        assert listed.status_code == 200
        body = listed.json()
        assert body["total"] == 1
        assert body["items"][0]["poster"] and "metahub" in body["items"][0]["poster"]

        prog = client.patch("/api/v1/library/tt1375666/progress", json={
            "progress_percent": 95,
        })
        assert prog.status_code == 200
        assert prog.json()["status"] == "completed"

        removed = client.delete("/api/v1/library/tt1375666")
        assert removed.status_code == 200
        assert client.get("/api/v1/library/").json()["total"] == 0
