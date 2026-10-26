import pytest
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from httpx import AsyncClient, ASGITransport
from main import app
from core.discover import fetch_person_filmography, search_catalog


@pytest.mark.asyncio
async def test_fetch_person_filmography():
    """Verify that fetch_person_filmography retrieves actual movies/series for an actor/director."""
    results = await fetch_person_filmography("Cillian Murphy", limit=15)
    assert isinstance(results, list)
    assert len(results) > 0, "Filmography should return titles for Cillian Murphy"

    # Verify attributes on items
    first = results[0]
    assert hasattr(first, "id")
    assert hasattr(first, "title")
    assert hasattr(first, "type")

    # Titles should include his acclaimed works like Oppenheimer, Peaky Blinders, or Dunkirk
    all_titles = [it.title.lower() for it in results]
    assert any("oppenheimer" in t or "peaky blinders" in t or "dunkirk" in t for t in all_titles), f"Expected major titles in {all_titles}"


@pytest.mark.asyncio
async def test_filmography_api_endpoint():
    """Verify GET /api/v1/discover/filmography returns HTTP 200 and list of filmography items."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        res = await client.get("/api/v1/discover/filmography?name=Zendaya&limit=10")
        assert res.status_code == 200
        data = res.json()
        assert isinstance(data, list)
        assert len(data) > 0
        titles = [item["title"].lower() for item in data]
        assert any("dune" in t or "spider-man" in t or "challengers" in t or "euphoria" in t for t in titles)


@pytest.mark.asyncio
async def test_search_catalog_person_augmentation():
    """Verify search_catalog incorporates filmography when searching an actor."""
    from core.cache import cache
    await cache.clear()
    results = await search_catalog("Brad Pitt")
    assert isinstance(results, list)
    assert len(results) > 0
    # Must contain acclaimed films starring Brad Pitt rather than just documentaries about him
    titles = [it.title.lower() for it in results]
    assert any("12 monkeys" in t or "12 years a slave" in t or "fight club" in t or "bullet train" in t or "inglourious basterds" in t or "once upon a time" in t or "river runs through it" in t or "babylon" in t for t in titles), f"Expected real films in {titles}"


def test_frontend_filmography_integration():
    """Verify static/app.js contains filmography endpoint fetching and multi-director pill splitting."""
    app_js_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "static", "app.js"))
    with open(app_js_path, "r", encoding="utf-8") as f:
        js = f.read()

    assert "/api/v1/discover/filmography" in js
    assert "searchDiscoverByPerson" in js
    assert "directorList" in js

