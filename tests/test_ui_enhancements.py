import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from httpx import AsyncClient, ASGITransport
from main import app
from core.library_manager import library_manager


@pytest.mark.asyncio
async def test_bulk_library_upsert_and_export():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        # 1. Test Bulk Import
        bulk_items = [
            {
                "id": "tt15239678",
                "title": "Dune: Part Two",
                "type": "movie",
                "year": "2024",
                "rating": "8.6",
                "status": "completed",
                "progress_percent": 100
            },
            {
                "id": "tt2788316",
                "title": "Shōgun",
                "type": "series",
                "year": "2024",
                "rating": "8.7",
                "status": "watching",
                "current_season": 1,
                "current_episode": 5,
                "progress_percent": 50
            }
        ]
        resp = await ac.post("/api/v1/library/bulk", json={"items": bulk_items})
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data.get("imported") == 2

        # Verify items exist in library
        resp = await ac.get("/api/v1/library")
        assert resp.status_code == 200
        lib_data = resp.json()
        items = lib_data.get("items", [])
        titles = [it["title"] for it in items]
        assert "Dune: Part Two" in titles
        assert "Shōgun" in titles

        # Clean up
        await ac.delete("/api/v1/library/tt15239678")
        await ac.delete("/api/v1/library/tt2788316")


@pytest.mark.asyncio
async def test_discover_suggestions():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        # Test general suggestions for "dune"
        resp = await ac.get("/api/v1/discover/suggestions?q=dune&type=all&limit=5")
        assert resp.status_code == 200, resp.text
        suggestions = resp.json()
        assert isinstance(suggestions, list)
        assert len(suggestions) > 0
        assert any("dune" in (s.get("title") or "").lower() for s in suggestions)

        # Test anime suggestions
        resp = await ac.get("/api/v1/discover/suggestions?q=naruto&type=anime&limit=5")
        assert resp.status_code == 200, resp.text
        anime_suggestions = resp.json()
        assert isinstance(anime_suggestions, list)
        assert len(anime_suggestions) > 0
        assert any("naruto" in (s.get("title") or "").lower() for s in anime_suggestions)
