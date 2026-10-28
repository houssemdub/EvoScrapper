import asyncio
import os
import re
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

TRANSMUXER_PY_PATH = os.path.join(os.path.dirname(__file__), "..", "core", "transmuxer.py")
STREAM_ROUTER_PY_PATH = os.path.join(os.path.dirname(__file__), "..", "routers", "stream.py")
STREMIO_ROUTER_PY_PATH = os.path.join(os.path.dirname(__file__), "..", "routers", "stremio.py")
APP_JS_PATH = os.path.join(os.path.dirname(__file__), "..", "static", "app.js")

VALID_VTT = "WEBVTT\n\n00:00:01.000 --> 00:00:03.000\nHello\n"


# ── 1. Disk cache for extracted embedded-subtitle VTT ─────────────────────────

def test_sub_vtt_cache_roundtrip_and_rejects_invalid(tmp_path, monkeypatch):
    """Contract: store_cached_sub_vtt persists only valid cue-bearing WebVTT; load returns None otherwise."""
    from core import transmuxer

    monkeypatch.setattr(transmuxer, "SUB_VTT_CACHE_DIR", str(tmp_path))

    assert transmuxer.store_cached_sub_vtt("k|1|0", VALID_VTT) is True
    assert transmuxer.load_cached_sub_vtt("k|1|0") == VALID_VTT

    # Note-only extraction results must never be cached
    assert transmuxer.store_cached_sub_vtt("k|2|0", "WEBVTT\n\nNOTE Empty\n") is False
    assert transmuxer.load_cached_sub_vtt("k|2|0") is None
    assert transmuxer.load_cached_sub_vtt("missing") is None


def test_background_extraction_caches_only_valid_cues(tmp_path, monkeypatch):
    """Contract: the background extraction job writes cache on success and cleans up the job registry."""
    from core import transmuxer

    monkeypatch.setattr(transmuxer, "SUB_VTT_CACHE_DIR", str(tmp_path))

    async def fake_extract(source_url, sub_index=0, timeout=8.0):
        return VALID_VTT

    async def fake_extract_bad(source_url, sub_index=0, timeout=8.0):
        return "WEBVTT\n\nNOTE Empty or unsupported embedded subtitle track\n"

    async def scenario():
        monkeypatch.setattr(transmuxer, "extract_embedded_subtitle_vtt", fake_extract)

        started = transmuxer.start_sub_vtt_extraction("job-ok", "http://source", 0)
        assert started is True
        assert transmuxer.sub_vtt_job_running("job-ok") is True

        # Single-flight: a second start for the same key must be a no-op
        assert transmuxer.start_sub_vtt_extraction("job-ok", "http://source", 0) is False

        while transmuxer.sub_vtt_job_running("job-ok"):
            await asyncio.sleep(0.01)
        assert transmuxer.load_cached_sub_vtt("job-ok") == VALID_VTT

        monkeypatch.setattr(transmuxer, "extract_embedded_subtitle_vtt", fake_extract_bad)
        transmuxer.start_sub_vtt_extraction("job-bad", "http://source", 0)
        while transmuxer.sub_vtt_job_running("job-bad"):
            await asyncio.sleep(0.01)
        assert transmuxer.load_cached_sub_vtt("job-bad") is None

    asyncio.run(scenario())


def test_extract_supports_configurable_timeout():
    """Contract: extract_embedded_subtitle_vtt must accept a timeout parameter (long budget for background jobs)."""
    import inspect
    from core.transmuxer import extract_embedded_subtitle_vtt

    sig = inspect.signature(extract_embedded_subtitle_vtt)
    assert "timeout" in sig.parameters, "extraction must support a configurable timeout"
    with open(TRANSMUXER_PY_PATH, "r", encoding="utf-8") as f:
        code = f.read()
    assert "EVO_SUB_EXTRACT_TIMEOUT" in code, "background extraction budget must be env-configurable"


# ── 2. /api/v1/stream/subtitles pending protocol ──────────────────────────────

def test_stream_subtitles_endpoint_pending_protocol():
    """Contract: the endpoint must serve cache hits immediately and return a pollable pending marker otherwise."""
    with open(STREAM_ROUTER_PY_PATH, "r", encoding="utf-8") as f:
        code = f.read()
    assert "load_cached_sub_vtt" in code, "endpoint must check the VTT disk cache first"
    assert "start_sub_vtt_extraction" in code, "endpoint must launch background extraction on cache miss"
    assert "X-Evo-Sub-Pending" in code, "pending responses must be marked so clients can poll"
    assert "no-store" in code, "pending responses must never be cached"


def test_stream_subtitles_endpoint_serves_cache_and_pending(tmp_path, monkeypatch):
    """Functional: cache hit returns VTT; miss returns pending response and starts a job."""
    import routers.stream as stream_router

    async def noop_daemon():
        return True

    monkeypatch.setattr(stream_router, "load_cached_sub_vtt", lambda key: None)
    monkeypatch.setattr(stream_router, "_find_cached_media_path", lambda **kw: None)
    monkeypatch.setattr(stream_router, "ensure_streaming_daemon", noop_daemon)
    started = {}
    monkeypatch.setattr(stream_router, "start_sub_vtt_extraction",
                        lambda key, src, idx: started.setdefault("args", (key, src, idx)) or True)
    monkeypatch.setattr(stream_router, "get_internal_stream_url",
                        lambda info_hash, file_idx, **kw: f"http://daemon/{info_hash}/{file_idx}")

    resp = asyncio.run(stream_router.get_embedded_subtitles(info_hash="abc123", file_idx=0, sub_index=0))
    assert resp.headers.get("X-Evo-Sub-Pending") == "1"
    assert "abc123" in started["args"][1]
    assert started["args"][2] == 0

    monkeypatch.setattr(stream_router, "load_cached_sub_vtt", lambda key: VALID_VTT)
    resp2 = asyncio.run(stream_router.get_embedded_subtitles(info_hash="abc123", file_idx=0, sub_index=0))
    assert resp2.headers.get("X-Evo-Sub-Pending") != "1"
    assert resp2.body.decode("utf-8") == VALID_VTT


def test_failed_extraction_is_retryable(monkeypatch):
    """Functional: a failed extraction must not be terminal — the endpoint relaunches the job (single-flight) so a later poll can succeed."""
    from routers import stream as stream_router

    async def noop_daemon():
        return None

    FAILED = "WEBVTT\n\nNOTE Extraction error: simulated timeout\n"
    monkeypatch.setattr(stream_router, "get_failed_sub_vtt", lambda key: FAILED)
    monkeypatch.setattr(stream_router, "load_cached_sub_vtt", lambda key: None)
    monkeypatch.setattr(stream_router, "_find_cached_media_path", lambda **kw: None)
    monkeypatch.setattr(stream_router, "ensure_streaming_daemon", noop_daemon)
    started = {}
    monkeypatch.setattr(stream_router, "start_sub_vtt_extraction",
                        lambda key, src, idx: started.setdefault("args", (key, src, idx)) or True)
    monkeypatch.setattr(stream_router, "get_internal_stream_url",
                        lambda info_hash, file_idx, **kw: f"http://daemon/{info_hash}/{file_idx}")

    resp = asyncio.run(stream_router.get_embedded_subtitles(info_hash="abc123", file_idx=0, sub_index=0))
    assert resp.body.decode("utf-8") == FAILED
    assert resp.headers.get("X-Evo-Sub-Pending") != "1"
    assert "args" in started, "failed marker must relaunch the extraction job"


# ── 3. Frontend polls pending extraction ──────────────────────────────────────

def test_app_js_polls_pending_embedded_extraction():
    """Contract: app.js must poll pending embedded-subtitle extraction instead of falling back instantly."""
    with open(APP_JS_PATH, "r", encoding="utf-8") as f:
        app_code = f.read()
    assert "X-Evo-Sub-Pending" in app_code, "app.js must detect the pending response header"
    assert "NOTE Extraction pending" in app_code or "X-Evo-Sub-Pending" in app_code


def test_app_js_poll_budget_covers_server_extraction_timeout():
    """Contract: the frontend poll budget must cover the server's EVO_SUB_EXTRACT_TIMEOUT (default 240s)."""
    with open(APP_JS_PATH, "r", encoding="utf-8") as f:
        app_code = f.read()
    m = re.search(r"EMBEDDED_SUB_POLL_BUDGET_MS\s*=\s*(\d+)", app_code)
    assert m, "app.js must define EMBEDDED_SUB_POLL_BUDGET_MS for the pending-extraction poll loop"
    budget_ms = int(m.group(1))
    with open(TRANSMUXER_PY_PATH, "r", encoding="utf-8") as f:
        tm_code = f.read()
    tm = re.search(r'EVO_SUB_EXTRACT_TIMEOUT",\s*"(\d+)"', tm_code)
    server_default_s = int(tm.group(1)) if tm else 240
    assert budget_ms >= server_default_s * 1000, (
        f"frontend poll budget {budget_ms}ms is shorter than server extraction timeout {server_default_s}s"
    )


# ── 4. Stremio addon advertises embedded tracks ───────────────────────────────

def test_stremio_addon_advertises_embedded_tracks():
    """Contract: the addon must record resolved torrents per item and expose embedded text tracks as WebVTT URLs."""
    with open(STREMIO_ROUTER_PY_PATH, "r", encoding="utf-8") as f:
        code = f.read()
    assert "_RECENT_ITEM_STREAMS" in code, "streams endpoint must remember torrent candidates per item"
    assert "subtitle_tracks" in code, "subtitles resource must probe embedded tracks"
    assert "evo-embedded" in code, "embedded entries must be namespaced"
    assert "/api/v1/stream/subtitles" in code, "embedded entries must point at the VTT extraction endpoint"


def test_stremio_subtitles_merge_embedded_tracks(monkeypatch):
    """Functional: embedded text tracks from the most recent torrent are merged into the subtitles response."""
    import routers.stremio as stremio_router

    stremio_router._RECENT_ITEM_STREAMS.clear()
    stremio_router._EMBEDDED_PROBE_CACHE.clear()
    stremio_router._RECENT_ITEM_STREAMS["movie:tt123:None:None"] = (
        __import__("time").time(),
        [("hash1", 0), ("hash2", 1)],
    )

    async def fake_search(**kwargs):
        class R:
            data = []
        return R()

    import routers.subtitles as subs_router
    monkeypatch.setattr(subs_router, "search_subtitles", fake_search)

    async def fake_probe(info_hash, file_idx):
        if info_hash == "hash1":
            return [
                {"sub_idx": 0, "codec": "subrip", "is_bitmap": False, "language": "eng", "title": "English"},
                {"sub_idx": 1, "codec": "hdmv_pgs_subtitle", "is_bitmap": True, "language": "fre", "title": "French PGS"},
            ]
        return []

    monkeypatch.setattr(stremio_router, "_probe_embedded_tracks", fake_probe)

    class FakeRequest:
        base_url = "http://127.0.0.1:8000/"

    result = asyncio.run(stremio_router.get_stremio_subtitles(
        stype="movie", item_id="tt123.json", request=FakeRequest(),
    ))

    subs = result["subtitles"]
    embedded = [s for s in subs if s["id"].startswith("evo-embedded:")]
    assert len(embedded) == 1, "only non-bitmap embedded tracks must be advertised"
    assert embedded[0]["url"] == "http://127.0.0.1:8000/api/v1/stream/subtitles?info_hash=hash1&file_idx=0&sub_index=0"
    assert embedded[0]["lang"] == "eng"

    stremio_router._RECENT_ITEM_STREAMS.clear()
    stremio_router._EMBEDDED_PROBE_CACHE.clear()


def test_stremio_subtitles_without_recent_streams_returns_providers_only(monkeypatch):
    """Functional: with no recently resolved torrent for the item, only provider subs are returned."""
    import time

    import routers.stremio as stremio_router

    stremio_router._RECENT_ITEM_STREAMS.clear()
    stremio_router._EMBEDDED_PROBE_CACHE.clear()

    async def fake_search(**kwargs):
        class Sub:
            id = "os:1"
            url = "https://opensubtitles.test/dl.srt"
            download_url = "https://opensubtitles.test/dl.srt"
            language_code = "eng"
        class R:
            data = [Sub()]
        return R()

    import routers.subtitles as subs_router
    monkeypatch.setattr(subs_router, "search_subtitles", fake_search)

    called = {"probe": False}

    async def fail_probe(info_hash, file_idx):
        called["probe"] = True
        return []

    monkeypatch.setattr(stremio_router, "_probe_embedded_tracks", fail_probe)

    class FakeRequest:
        base_url = "http://127.0.0.1:8000/"

    result = asyncio.run(stremio_router.get_stremio_subtitles(
        stype="movie", item_id="tt999.json", request=FakeRequest(),
    ))
    assert [s["id"] for s in result["subtitles"]] == ["os:1"]
    assert called["probe"] is False, "must not probe when no torrent was recently resolved for the item"

    stremio_router._RECENT_ITEM_STREAMS.clear()
    stremio_router._EMBEDDED_PROBE_CACHE.clear()
