import asyncio
import os
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from core.database import Database
from core.transmuxer import (
    _LazySemaphore,
    _FFMPEG_SEMAPHORE,
    _HLS_SEMAPHORE,
    get_ffmpeg_max_concurrency,
)
from core.stream_resolver import resolve_streams, StreamItem
from core.subtitle_sync.engine import SubtitleSyncEngine, SyncCandidate


@pytest.mark.asyncio
async def test_database_serialized_concurrency_lock(tmp_path):
    """Verifies that Database._lock serializes concurrent executions and commits without SQLite collision."""
    db_file = str(tmp_path / "test_concurrency.db")
    db = Database(db_file)
    await db.connect()

    # Launch 20 concurrent coroutines attempting to write to the database simultaneously
    async def worker(idx: int):
        await db.execute(
            """INSERT OR REPLACE INTO library_items (id, title, status, created_at, updated_at)
               VALUES (?, ?, 'completed', ?, ?)""",
            (f"item_{idx}", f"Test Movie {idx}", float(idx), float(idx)),
        )

    await asyncio.gather(*(worker(i) for i in range(20)))

    rows = await db.fetch_all("SELECT COUNT(*) as n FROM library_items")
    assert rows[0]["n"] == 20

    # Test execute_many
    batch = [(f"item_batch_{i}", f"Batch Movie {i}", "plan_to_watch", float(i), float(i)) for i in range(10)]
    await db.execute_many(
        """INSERT OR REPLACE INTO library_items (id, title, status, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?)""",
        batch,
    )
    rows_after = await db.fetch_all("SELECT COUNT(*) as n FROM library_items")
    assert rows_after[0]["n"] == 30

    await db.close()


@pytest.mark.asyncio
async def test_lazy_semaphore_event_loop_attachment():
    """Verifies that _LazySemaphore does not attach to a loop until requested and exposes _value."""
    lazy = _LazySemaphore(lambda: asyncio.Semaphore(5))
    assert lazy._value == 5

    async with lazy:
        assert lazy._value == 4
    assert lazy._value == 5

    # Check that module-level semaphores work as expected
    assert _FFMPEG_SEMAPHORE._value >= 2
    assert _HLS_SEMAPHORE._value >= 1


@pytest.mark.asyncio
async def test_stream_resolver_fast_path_torrentio():
    """Verifies that stream_resolver harvests Torrentio first and uses a fast bounded timeout for local scrapers."""
    mock_torrentio = [
        StreamItem(
            name="Torrentio [4K]",
            title="Inception.2010.2160p.UHD.Remux.mkv",
            info_hash="1111222233334444555566667777888899990000",
            file_idx=0,
            tracker="torrentio",
            seeds=50,
            peers=10,
            resolution="4K",
            is_direct=True,
        )
    ]

    async def slow_local_scraper(*args, **kwargs):
        await asyncio.sleep(10.0)  # Slow hanging local scraper
        return []

    mock_prov = MagicMock()
    mock_prov.search = slow_local_scraper

    with patch("core.stream_resolver.fetch_torrentio_streams", new=AsyncMock(return_value=mock_torrentio)), \
         patch("core.stream_resolver.get_capable_providers", return_value=[mock_prov]):
        
        # Should finish quickly via bounded gather without waiting 10s for the slow provider
        start = asyncio.get_event_loop().time()
        res = await resolve_streams(title="Inception", imdb_id="tt1375666")
        elapsed = asyncio.get_event_loop().time() - start

        assert res is not None
        assert len(res.streams) >= 1
        assert res.streams[0].info_hash == "1111222233334444555566667777888899990000"
        # Bounded timeout for local scrapers must ensure fast turnaround
        assert elapsed < 5.0


@pytest.mark.asyncio
async def test_subtitle_sync_vad_stream_duration_bounding():
    """Verifies that audio VAD duration is bounded on HTTP streams to prevent swarm bandwidth starvation."""
    engine = SubtitleSyncEngine()

    dummy_cues = [
        (10.0, 14.0, "Hello world"),
        (16.0, 20.0, "Second cue line"),
        (40.0, 45.0, "Third cue line"),
    ]

    captured_duration = None

    async def mock_extract(source_url, duration=90.0, **kwargs):
        nonlocal captured_duration
        captured_duration = duration
        return [(10.5, 14.5), (16.2, 20.2), (40.1, 45.1)]

    with patch("core.subtitle_sync.engine.extract_speech_intervals_from_stream", side_effect=mock_extract):
        res = await engine.sync(
            video_source="http://localhost:8889/stream?info_hash=abc",
            subtitle_cues=dummy_cues,
            vad_duration=90.0,
        )
        assert res.success is True
        # For HTTP stream, duration must be bounded to 45.0s to protect swarm playback
        assert captured_duration == 45.0


def test_js_code_hardening_contracts():
    """Verifies frontend and streaming engine contracts for debouncing and smooth playback gating."""
    with open("streamer/torrent_engine.js", "r", encoding="utf-8") as f:
        engine_code = f.read()

    # Wire listener must debounce rapid handshake storms
    assert "wireDebounceTimer" in engine_code, "torrent_engine.js must debounce rapid peer wire handshakes"

    with open("static/app.js", "r", encoding="utf-8") as f:
        app_code = f.read()

    # Probe handler must not mutate video.src if already playing or readyState >= 3
    assert "readyState >= 3" in app_code, "app.js must protect active playback from probe video.src reload"


def test_debrid_proxy_dynamic_secret():
    """Verifies that FLAW-08 generates a cryptographically secure random secret when placeholder is used."""
    import core.debrid.proxy as proxy_mod
    from config import settings

    orig_setting = getattr(settings, "DEBRID_PROXY_SECRET", "")
    orig_runtime = proxy_mod._RUNTIME_PROXY_SECRET
    try:
        # Default placeholder -> should generate random hex string
        proxy_mod._RUNTIME_PROXY_SECRET = None
        settings.DEBRID_PROXY_SECRET = "evoscrapper-debrid-proxy-secret-key"
        sec1 = proxy_mod.get_debrid_proxy_secret()
        assert len(sec1) == 64
        assert sec1 != "evoscrapper-debrid-proxy-secret-key"
        # Subsequent call returns same runtime token
        assert proxy_mod.get_debrid_proxy_secret() == sec1

        # Explicit custom secret configured
        proxy_mod._RUNTIME_PROXY_SECRET = None
        settings.DEBRID_PROXY_SECRET = "super-secret-custom-token-xyz"
        assert proxy_mod.get_debrid_proxy_secret() == "super-secret-custom-token-xyz"
    finally:
        settings.DEBRID_PROXY_SECRET = orig_setting
        proxy_mod._RUNTIME_PROXY_SECRET = orig_runtime


@pytest.mark.asyncio
async def test_sprite_sheet_devnull_subprocess(tmp_path):
    """Verifies that FLAW-09 uses DEVNULL for stderr to prevent memory leaks during sprite sheet generation."""
    from core.transmuxer import generate_sprite_sheet

    mock_proc = AsyncMock()
    mock_proc.wait = AsyncMock(return_value=0)
    mock_proc.kill = MagicMock()

    call_count = 0
    def mock_isfile(p):
        nonlocal call_count
        if "test_sprite_hash" in str(p):
            call_count += 1
            return call_count > 1  # False on pre-check, True after ffmpeg runs
        return False

    with patch("core.transmuxer.find_ffmpeg", return_value="ffmpeg"), \
         patch("asyncio.create_subprocess_exec", return_value=mock_proc) as mock_exec, \
         patch("os.path.isfile", side_effect=mock_isfile), \
         patch("os.path.getsize", return_value=12345):

        res = await generate_sprite_sheet("http://fake/video.mp4", "test_sprite_hash_1234567890abcdef1234567890", 0)
        assert res is not None
        mock_exec.assert_called_once()
        _, kwargs = mock_exec.call_args
        assert kwargs.get("stderr") == asyncio.subprocess.DEVNULL
        assert kwargs.get("stdout") == asyncio.subprocess.DEVNULL


@pytest.mark.asyncio
async def test_direct_range_lan_redirect():
    """Verifies that FLAW-11 allows 307 direct redirect on LAN/Docker IPs when EVO_DIRECT_RANGE_LAN=true."""
    from routers.stream import stream_raw_torrent
    from starlette.requests import Request
    from fastapi.responses import RedirectResponse, StreamingResponse

    scope_lan = {
        "type": "http",
        "method": "GET",
        "path": "/stream/fakehash/0",
        "headers": [(b"host", b"192.168.1.100:8889")],
        "client": ("192.168.1.50", 54321),
    }
    req_lan = Request(scope_lan)

    with patch.dict(os.environ, {"EVO_DIRECT_RANGE": "true", "EVO_DIRECT_RANGE_LAN": "true"}), \
         patch("routers.stream.ensure_streaming_daemon", new=AsyncMock()), \
         patch("routers.stream.get_internal_stream_url", return_value="http://127.0.0.1:50000/stream?info_hash=fakehash"):
        
        resp = await stream_raw_torrent(req_lan, info_hash="fakehash", file_idx=0)
        assert isinstance(resp, RedirectResponse)
        assert resp.status_code == 307
        assert "192.168.1.100" in resp.headers["location"]
        assert "127.0.0.1" not in resp.headers["location"]

    # Public IP should NOT redirect even if EVO_DIRECT_RANGE_LAN=true
    scope_public = {
        "type": "http",
        "method": "GET",
        "path": "/stream/fakehash/0",
        "headers": [(b"host", b"example.com:8889")],
        "client": ("8.8.8.8", 54321),
    }
    req_public = Request(scope_public)

    mock_resp = AsyncMock()
    mock_resp.status = 200
    mock_resp.headers = {"Content-Type": "video/mp4", "Content-Length": "1000"}
    mock_resp.content.iter_chunked = AsyncMock(return_value=AsyncMock(__aiter__=lambda self: iter([b"data"])))

    mock_session = AsyncMock()
    mock_session.get = AsyncMock(return_value=mock_resp)

    with patch.dict(os.environ, {"EVO_DIRECT_RANGE": "true", "EVO_DIRECT_RANGE_LAN": "true"}), \
         patch("routers.stream.ensure_streaming_daemon", new=AsyncMock()), \
         patch("routers.stream.get_internal_stream_url", return_value="http://127.0.0.1:50000/stream?info_hash=fakehash"), \
         patch("routers.stream.get_http_session", return_value=mock_session):

        resp_pub = await stream_raw_torrent(req_public, info_hash="fakehash", file_idx=0)
        assert not isinstance(resp_pub, RedirectResponse)
        assert isinstance(resp_pub, StreamingResponse)


def test_frontend_dom_cache_and_timer_manager():
    """Verifies that FLAW-12 DOM caching and player TimerManager lifecycle cleanup are implemented."""
    with open("static/app.js", "r", encoding="utf-8") as f:
        js_code = f.read()

    assert "_domCache = new Map()" in js_code, "app.js must define _domCache Map"
    assert "function getCachedElement(id)" in js_code, "app.js must define getCachedElement"
    assert "TimerManager = {" in js_code, "app.js must define TimerManager"
    assert "clearAll()" in js_code, "TimerManager must support clearAll()"
    assert "TimerManager.clearAll()" in js_code, "closePlayerModal must invoke TimerManager.clearAll()"

