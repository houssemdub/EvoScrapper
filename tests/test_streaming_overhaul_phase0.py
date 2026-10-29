import asyncio
import os
import sys
from unittest.mock import AsyncMock, patch, MagicMock
import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from main import app
from core.transmuxer import stream_transmuxed_video

@pytest.fixture
def client():
    return TestClient(app)

@pytest.mark.asyncio
async def test_stream_raw_torrent_timeout_total_is_none():
    """[STRM-CRIT-01] Verifies /play does not impose a cumulative total timeout on the live stream."""
    import aiohttp
    from routers.stream import stream_raw_torrent
    from fastapi import Request

    captured_timeout = None

    class MockContent:
        async def iter_chunked(self, size):
            yield b"data"

    mock_resp = MagicMock()
    mock_resp.status = 200
    mock_resp.headers = {"Content-Type": "video/mp4", "Content-Length": "100"}
    mock_resp.content = MockContent()
    mock_resp.close = MagicMock()

    async def mock_get(url, headers=None, timeout=None):
        nonlocal captured_timeout
        captured_timeout = timeout
        return mock_resp

    mock_session = MagicMock()
    mock_session.get = mock_get

    mock_req = MagicMock(spec=Request)
    mock_req.headers = {}

    with patch("routers.stream.ensure_streaming_daemon", new=AsyncMock(return_value=True)), \
         patch("routers.stream.get_http_session", new=AsyncMock(return_value=mock_session)):
        resp = await stream_raw_torrent(
            request=mock_req,
            info_hash="0123456789abcdef0123456789abcdef01234567",
            file_idx=0,
            magnet=None,
            duration=None,
        )

    assert captured_timeout is not None
    assert captured_timeout.total is None, "Streaming total timeout MUST be None to prevent 45s hard socket kill"
    assert captured_timeout.sock_connect == 10.0
    assert captured_timeout.sock_read == 45.0


def test_destructive_multi_session_eviction_eliminated():
    """[STRM-CRIT-02] Verifies server.js does NOT call cleanupOtherSessions on /stream and engine protects active streams."""
    server_js_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "streamer", "server.js"))
    with open(server_js_path, "r", encoding="utf-8") as f:
        content = f.read()

    # /stream route MUST NOT call cleanupOtherSessions
    stream_route_idx = content.find("pathname === '/stream'")
    assert stream_route_idx != -1
    stream_route_chunk = content[stream_route_idx:stream_route_idx + 1200]
    assert "cleanupOtherSessions" not in stream_route_chunk, "cleanupOtherSessions MUST NOT be called in /stream route"

    engine_js_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "streamer", "torrent_engine.js"))
    with open(engine_js_path, "r", encoding="utf-8") as f:
        engine_content = f.read()

    assert "activeReaders" in engine_content
    assert "enforceSessionCapacity" in engine_content
    assert "destroyStore: false" in engine_content


def test_critical_bitfield_preserves_unverified_pieces():
    """[STRM-CRIT-03] Verifies applySlidingWindow in torrent_engine.js does not blanket-fill(false) unverified critical bits."""
    engine_js_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "streamer", "torrent_engine.js"))
    with open(engine_js_path, "r", encoding="utf-8") as f:
        content = f.read()

    # Must NOT blanket fill(false) on _critical array
    assert "torrent._critical.fill(false)" not in content, "Must not blanket-reset _critical to false"
    assert "torrent.bitfield.get(i)" in content, "Must only clear critical bits for verified pieces"


@pytest.mark.asyncio
async def test_transmux_copy_seek_flags_avoid_desync():
    """[STRM-CRIT-04] Verifies copy-mode seeking omits -noaccurate_seek and includes -copyts & -avoid_negative_ts."""
    captured_cmd = None

    async def mock_subprocess_exec(*cmd, **kwargs):
        nonlocal captured_cmd
        captured_cmd = list(cmd)
        mock_proc = MagicMock()
        mock_proc.stdout = AsyncMock()
        mock_proc.stdout.read = AsyncMock(side_effect=[b"fMP4data", b""])
        mock_proc.returncode = 0
        mock_proc.wait = AsyncMock(return_value=0)
        return mock_proc

    with patch("asyncio.create_subprocess_exec", side_effect=mock_subprocess_exec):
        gen = stream_transmuxed_video(
            source_url_or_path="http://127.0.0.1:8889/stream?info_hash=abc",
            start_seconds=42.5,
            transcode_video=False,
            burn_sub_idx=None,
        )
        async for chunk in gen:
            break

    assert captured_cmd is not None
    assert "-copyts" not in captured_cmd, "-copyts MUST be omitted to prevent A/V PTS gap with aac audio"
    assert "-avoid_negative_ts" in captured_cmd
    assert "-noaccurate_seek" in captured_cmd
    af_idx = captured_cmd.index("-af")
    assert "aresample=async=1" in captured_cmd[af_idx + 1]
    assert "asetpts=PTS-STARTPTS" not in captured_cmd[af_idx + 1]


def test_debrid_status_no_name_error(client):
    """[STRM-CRIT-05] Verifies GET /api/v1/stream/debrid/status does not crash with NameError."""
    with patch("core.debrid.manager.DebridManager.get_all_statuses", new=AsyncMock(return_value=[])):
        resp = client.get("/api/v1/stream/debrid/status")
        assert resp.status_code == 200
        data = resp.json()
        assert "providers" in data
