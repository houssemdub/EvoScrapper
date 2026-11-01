import pytest
import asyncio
from unittest.mock import MagicMock
from fastapi.testclient import TestClient
from main import app
from core.engine_manager import get_engine_manager, EngineType
from core.torrent_streamer import get_internal_stream_url, DAEMON_URL


@pytest.mark.asyncio
async def test_multi_engine_health_and_dynamic_urls():
    mgr = get_engine_manager()

    # 1. Switch to Node
    res_node = await mgr.switch_engine("node")
    assert res_node["status"] == "switched"
    assert res_node["active_engine"] == "node"
    assert "8889" in str(DAEMON_URL)

    node_url = get_internal_stream_url("0123456789abcdef0123456789abcdef01234567", 0)
    assert "http://127.0.0.1:8889/stream" in node_url

    # 2. Switch to Rust
    res_rust = await mgr.switch_engine("rust")
    assert res_rust["status"] == "switched"
    assert res_rust["active_engine"] == "rust"
    assert "8891" in str(DAEMON_URL)

    rust_url = get_internal_stream_url("0123456789abcdef0123456789abcdef01234567", 0)
    assert "http://127.0.0.1:8891/stream" in rust_url

    # Cleanup
    for eng in mgr.engines.values():
        eng.stop()


def test_transmux_head_request_fast_return():
    client = TestClient(app)
    # HEAD request to /api/v1/stream/transmux should return 200 without blocking ffprobe
    resp = client.head(
        "/api/v1/stream/transmux?info_hash=0123456789abcdef0123456789abcdef01234567&file_idx=0&start_time=12.5"
    )
    assert resp.status_code == 200
    assert resp.headers.get("content-type") == "video/mp4"
    assert resp.headers.get("accept-ranges") == "none"
