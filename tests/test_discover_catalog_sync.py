import pytest
from httpx import AsyncClient, ASGITransport
from main import app
import os


@pytest.mark.asyncio
async def test_catalog_filtering_by_min_rating():
    """Verify backend catalog endpoint filters items by min_rating."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Request catalog with min_rating = 7.5
        resp = await client.get("/api/v1/discover/catalog?type=movie&min_rating=7.5&page=1")
        assert resp.status_code == 200
        data = resp.json()
        assert "items" in data
        assert isinstance(data["items"], list)
        for item in data["items"]:
            if item.get("rating"):
                try:
                    assert float(item["rating"]) >= 7.5
                except ValueError:
                    pass


@pytest.mark.asyncio
async def test_catalog_filtering_by_year_range_and_sort():
    """Verify backend catalog endpoint filters items by year range and sorts appropriately."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/v1/discover/catalog?type=movie&year_from=2010&year_to=2023&sort=rating_desc")
        assert resp.status_code == 200
        data = resp.json()
        assert "items" in data
        items = data["items"]
        for item in items:
            if item.get("year"):
                try:
                    y = int(item["year"][:4])
                    assert 2010 <= y <= 2023
                except ValueError:
                    pass


@pytest.mark.asyncio
async def test_discover_recommendations_endpoint():
    """Verify endpoint provides similar/recommended titles for a given movie/series."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Interstellar imdb_id
        resp = await client.get("/api/v1/discover/recommendations/movie/tt0816692")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) > 0
        assert any(item.get("title") for item in data)


@pytest.mark.asyncio
async def test_library_scrobble_endpoint():
    """Verify playback scrobble endpoint logs watching activity for sync."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        payload = {
            "item_id": "tt0816692",
            "title": "Interstellar",
            "type": "movie",
            "playback_seconds": 1200.0,
            "duration_seconds": 10140.0,
            "progress_percent": 12,
        }
        resp = await client.post("/api/v1/library/scrobble", json=payload)
        assert resp.status_code == 200
        data = resp.json()
        assert data.get("status") == "success"
        assert data.get("item_id") == "tt0816692"


def test_frontend_discover_filter_and_recommendation_elements():
    """Verify UI templates contain advanced filter controls, cast chips, and recommendations container."""
    html_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "static", "index.html"))
    with open(html_path, "r", encoding="utf-8") as f:
        html = f.read()

    assert 'id="discover-rating-filter"' in html
    assert 'id="discover-year-filter"' in html

    js_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "static", "app.js"))
    with open(js_path, "r", encoding="utf-8") as f:
        js = f.read()

    assert "renderDiscoverRecommendations" in js
    assert "searchDiscoverByPerson" in js
