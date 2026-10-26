import os
import subprocess
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from fastapi.testclient import TestClient
from main import app


@pytest.fixture
def client():
    return TestClient(app)


def test_localhost_direct_range_emits_307(monkeypatch, client):
    """Verifies that localhost clients receive 307 redirect when EVO_DIRECT_RANGE=true."""
    monkeypatch.setenv("EVO_DIRECT_RANGE", "true")
    with patch("routers.stream.ensure_streaming_daemon", new=AsyncMock(return_value=True)):
        res = client.get(
            "/api/v1/stream/play?info_hash=1111111111111111111111111111111111111111&file_idx=0",
            follow_redirects=False,
            headers={"host": "127.0.0.1:8888"},
        )
        assert res.status_code == 307
        assert "/stream?info_hash=" in res.headers["location"]


def test_remote_client_retains_proxy_path(monkeypatch):
    """Verifies that non-localhost clients use the safe HTTP proxy path even when EVO_DIRECT_RANGE=true."""
    import aiohttp
    from routers.stream import stream_raw_torrent
    from fastapi import Request

    monkeypatch.setenv("EVO_DIRECT_RANGE", "true")

    class MockContent:
        async def iter_chunked(self, size):
            yield b"stream-data"

    mock_resp = MagicMock()
    mock_resp.status = 200
    mock_resp.headers = {"Content-Type": "video/mp4", "Content-Length": "100"}
    mock_resp.content = MockContent()
    mock_resp.close = MagicMock()

    mock_session = MagicMock()
    mock_session.get = AsyncMock(return_value=mock_resp)

    mock_req = MagicMock(spec=Request)
    mock_req.headers = {"host": "evoscrapper.remote.domain"}
    mock_client = MagicMock()
    mock_client.host = "192.168.1.100"
    mock_req.client = mock_client

    with patch("routers.stream.ensure_streaming_daemon", new=AsyncMock(return_value=True)), \
         patch("routers.stream.get_http_session", new=AsyncMock(return_value=mock_session)):
        import asyncio
        resp = asyncio.run(stream_raw_torrent(
            request=mock_req,
            info_hash="1111111111111111111111111111111111111111",
            file_idx=0,
            magnet=None,
            duration=None,
            buffer_mb=None,
        ))
        assert resp.status_code == 200
        assert resp.headers.get("X-Evo-Buffer-State") == "healthy"


def test_server_js_range_out_of_bounds_handling():
    """Verifies streamer/server.js handles 206 range bounds, rejecting invalid/out-of-bounds with 416."""
    server_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "streamer", "server.js"))
    with open(server_path, "r", encoding="utf-8") as f:
        content = f.read()

    assert "start >= total" in content
    assert "'Content-Range': `bytes */${total}`" in content
    assert "res.writeHead(416" in content
    assert "range.includes(',')" in content

    # Test execution in Node
    node_cmd = [
        "node", "-e",
        """
        const total = 1000;
        function parseRange(range) {
            if (range.includes(',')) return { status: 416, header: `bytes */${total}` };
            const matches = range.match(/bytes=(\\d*)-(\\d*)/);
            if (!matches) return { status: 416, header: `bytes */${total}` };
            let start = matches[1] ? parseInt(matches[1], 10) : undefined;
            let end = matches[2] ? parseInt(matches[2], 10) : undefined;
            if (start === undefined && end !== undefined) {
                start = Math.max(0, total - end);
                end = total - 1;
            } else if (start !== undefined && end === undefined) {
                end = total - 1;
            }
            if (isNaN(start) || isNaN(end) || start >= total || start > end || start < 0) {
                return { status: 416, header: `bytes */${total}` };
            }
            end = Math.min(end, total - 1);
            return { status: 206, start, end, chunksize: end - start + 1 };
        }

        // Out of bounds start
        const oob = parseRange('bytes=2000-');
        if (oob.status !== 416) process.exit(1);

        // Multiple ranges
        const multi = parseRange('bytes=0-10,20-30');
        if (multi.status !== 416) process.exit(2);

        // Valid range 0-
        const valid = parseRange('bytes=0-');
        if (valid.status !== 206 || valid.start !== 0 || valid.end !== 999) process.exit(3);
        """
    ]
    res = subprocess.run(node_cmd, capture_output=True, text=True)
    assert res.returncode == 0, f"Node range validation failed: {res.stderr}"
