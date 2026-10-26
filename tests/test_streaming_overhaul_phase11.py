import pytest
from fastapi.testclient import TestClient
from main import app
from core.transmuxer import HlsSegmentCache, _hls_cache
from routers.stream import _WATCHDOG_HISTORY


client = TestClient(app)
AUTH_HEADERS = {"X-API-Key": "test_key"}


def test_hls_cache_stats_and_telemetry():
    cache = HlsSegmentCache()
    stats = cache.get_stats()
    assert "hits" in stats
    assert "misses" in stats
    assert "hit_ratio" in stats
    assert "avg_first_byte_latency_sec" in stats
    assert stats["hits"] == 0
    assert stats["misses"] == 0
    assert stats["hit_ratio"] == 1.0

    cache.hits = 3
    cache.misses = 1
    cache.record_latency(0.025)
    cache.record_latency(0.015)
    updated = cache.get_stats()
    assert updated["hits"] == 3
    assert updated["misses"] == 1
    assert updated["hit_ratio"] == 0.75
    assert updated["avg_first_byte_latency_sec"] == 0.02


def test_diagnostics_extended_telemetry():
    resp = client.get("/api/v1/stream/diagnostics", headers=AUTH_HEADERS)
    assert resp.status_code == 200
    data = resp.json()

    assert "hls_cache" in data
    assert "transmux" in data
    assert "debrid_proxy" in data
    assert "watchdog_history" in data
    assert "mesh" in data

    assert "max_concurrency" in data["transmux"]
    assert "active_permits" in data["transmux"]
    assert "shared_client_active" in data["debrid_proxy"]
    assert data["mesh"]["engine"] == "p2p-media-loader"


def test_keyframes_endpoint():
    resp = client.get(
        "/api/v1/stream/keyframes?info_hash=1111111111111111111111111111111111111111&file_idx=0",
        headers=AUTH_HEADERS,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "info_hash" in data
    assert "file_idx" in data
    assert "keyframes" in data
    assert isinstance(data["keyframes"], list)
