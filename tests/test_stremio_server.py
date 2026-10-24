import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch, AsyncMock
from main import app
from models.stream import StreamResolveResponse, StreamItem


@pytest.fixture
def client():
    return TestClient(app)


def test_stremio_manifest_endpoint(client):
    res = client.get("/manifest.json")
    assert res.status_code == 200
    data = res.json()
    assert data["id"] == "org.evoscrapper.addon"
    assert data["version"] == "3.0.0"
    assert "stream" in data["resources"]
    assert "movie" in data["types"]
    assert "series" in data["types"]
    assert "anime" in data["types"]

    # Also test /stremio/manifest.json alias
    alias_res = client.get("/stremio/manifest.json")
    assert alias_res.status_code == 200
    assert alias_res.json()["id"] == "org.evoscrapper.addon"


def test_stremio_stream_endpoint(client):
    mock_item = StreamItem(
        name="[RD+ 4K]",
        title="Inception (2010) [2160p Remux]",
        info_hash="c1205d5e0e64cc0aab4f7e60cfb669e4b477bc4c",
        file_idx=0,
        quality="4K",
        resolution="2160p",
        codec="HEVC",
        audio="TrueHD 7.1",
        hdr="DV",
        seeds=120,
        peers=15,
        size="42.5 GB",
        size_bytes=45634027520,
        tracker="YTS",
        magnet="magnet:?xt=urn:btih:c1205d5e0e64cc0aab4f7e60cfb669e4b477bc4c",
        stream_url="https://proxy.evoscrapper.local/stream/video.mp4",
        score=280.0,
        cached=True,
    )
    mock_response = StreamResolveResponse(
        streams=[mock_item],
        total=1,
        imdb_id="tt1375666",
        title="Inception",
        resolved_time_ms=150.0,
    )

    with patch("routers.stremio.resolve_streams", new=AsyncMock(return_value=mock_response)):
        res = client.get("/stream/movie/tt1375666.json")
        assert res.status_code == 200
        data = res.json()
        assert "streams" in data
        assert len(data["streams"]) == 1
        s = data["streams"][0]
        assert "EvoScrapper" in s["name"]
        assert s["url"] == "https://proxy.evoscrapper.local/stream/video.mp4"
        assert "42.5 GB" in s["title"]
