"""
Unit and contract tests verifying VLC-parity subtitle pipeline improvements (Tier 1, 2, and 3):
1. rAF-driven cue evaluation loop in static/app.js.
2. Anchor-relative program clock math for transmux/direct playback.
3. Drift-aware subtitle model persistence (linear + quadratic) in localStorage.
4. Background extraction initiation on fast preview requests in routers/stream.py.
5. X-TIMESTAMP-MAP preservation in sanitize_webvtt_content and proxy_subtitle_vtt.
6. Multi-window VAD anchoring for framerate drift detection in core/subtitle_sync/engine.py.
7. Native text track rendering mode and continuous seek micro-sync in static/app.js.
8. Watch party subtitle state broadcast & synchronization in core/watch_party.py & static/js/party.js.
9. ASS style markup preservation in routers/subtitles.py & static/app.js.
10. Automatic PGS bitmap routing to canvas overlay in core/transmuxer.py.
"""

import os
import re
import pytest
from core.transmuxer import sanitize_webvtt_content
from core.watch_party import WatchPartyRoom, WatchPartyManager
from routers.subtitles import srt_to_webvtt, ass_to_webvtt

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP_JS_PATH = os.path.join(ROOT_DIR, "static", "app.js")
PARTY_JS_PATH = os.path.join(ROOT_DIR, "static", "js", "party.js")
STREAM_PY_PATH = os.path.join(ROOT_DIR, "routers", "stream.py")
ENGINE_PY_PATH = os.path.join(ROOT_DIR, "core", "subtitle_sync", "engine.py")
TRANSMUXER_PY_PATH = os.path.join(ROOT_DIR, "core", "transmuxer.py")


def test_raf_driven_overlay_loop_contract():
    """Verify app.js defines rAF loop and handles play/pause/visibility state."""
    with open(APP_JS_PATH, "r", encoding="utf-8") as f:
        code = f.read()

    assert "function startSubtitleOverlayLoop" in code, "Must declare startSubtitleOverlayLoop"
    assert "function stopSubtitleOverlayLoop" in code, "Must declare stopSubtitleOverlayLoop"
    assert "requestAnimationFrame" in code, "Must use requestAnimationFrame for per-frame cue evaluations"
    assert "cancelAnimationFrame" in code, "Must cleanly cancel rAF on pause/stop"
    assert "visibilitychange" in code, "Must throttle/stop rAF loop when tab is hidden"


def test_anchor_relative_clock_contract():
    """Verify anchor-relative time math in app.js replaces naive playbackOffset addition."""
    with open(APP_JS_PATH, "r", encoding="utf-8") as f:
        code = f.read()

    assert "function getPlayerCurrentTime" in code, "Must provide centralized getPlayerCurrentTime"
    assert "anchorTime" in code, "Must track active.anchorTime"
    assert "anchorStreamStartTime" in code, "Must track active.anchorStreamStartTime"

    # Ensure updateSubtitleOverlay calls getPlayerCurrentTime
    idx = code.find("function updateSubtitleOverlay()")
    end_idx = code.find("function renderCuesToVideo(", idx)
    assert idx != -1 and end_idx != -1, "updateSubtitleOverlay must be defined"
    overlay_fn = code[idx:end_idx]
    assert "getPlayerCurrentTime()" in overlay_fn, "updateSubtitleOverlay must rely on getPlayerCurrentTime()"


def test_drift_model_persistence_contract():
    """Verify quadratic and linear drift models are saved and restored."""
    with open(APP_JS_PATH, "r", encoding="utf-8") as f:
        code = f.read()

    # saveCurrentSubtitleSync saves model & params
    m_save = re.search(r"function saveCurrentSubtitleSync\(\)\s*\{([\s\S]*?)\}", code)
    assert m_save, "saveCurrentSubtitleSync must be defined"
    save_code = m_save.group(1)
    assert "driftModel" in save_code, "Must persist driftModel object into localStorage"
    assert "params" in save_code, "Must serialize model params"

    # loadSavedSubtitleSync reads driftModel
    m_load = re.search(r"function loadSavedSubtitleSync\(track\)\s*\{([\s\S]*?)\}", code)
    assert m_load, "loadSavedSubtitleSync must be defined"
    load_code = m_load.group(1)
    assert "driftModel" in load_code, "Must parse and return driftModel"


def test_stream_fast_preview_launches_background_extraction():
    """Verify routers/stream.py triggers full background extraction even when fast preview is served."""
    with open(STREAM_PY_PATH, "r", encoding="utf-8") as f:
        code = f.read()

    fast_block = re.search(r"if fast is True:\s*([\s\S]*?)return Response", code)
    assert fast_block, "Fast preview block must exist in get_embedded_subtitles"
    block_text = fast_block.group(1)
    assert "start_sub_vtt_extraction" in block_text, (
        "Fast preview request must launch background extraction to build full cached VTT"
    )


def test_sanitize_webvtt_preserves_timestamp_map():
    """Verify sanitize_webvtt_content retains X-TIMESTAMP-MAP header."""
    raw = "WEBVTT\nX-TIMESTAMP-MAP=MPEGTS:900000,LOCAL:00:00:00.000\n\n00:00:10.000 --> 00:00:15.000\nHello world\n"
    sanitized = sanitize_webvtt_content(raw)
    assert "X-TIMESTAMP-MAP=MPEGTS:900000,LOCAL:00:00:00.000" in sanitized


def test_srt_to_webvtt_emits_timestamp_map_and_handles_negative_shift():
    """Verify srt_to_webvtt emits X-TIMESTAMP-MAP and drops cues before 0 instead of collapsing."""
    srt = (
        "1\n00:00:01,000 --> 00:00:02,000\nEarly line\n\n"
        "2\n00:00:05,000 --> 00:00:08,000\nLater line\n"
    )
    # Negative shift of -3s drops cue 1 (ends at -1s), shifts cue 2 to 00:00:02.000 --> 00:00:05.000
    vtt = srt_to_webvtt(
        srt,
        offset_seconds=-3.0,
        timestamp_map="X-TIMESTAMP-MAP=MPEGTS:180000,LOCAL:00:00:00.000",
    )
    assert "X-TIMESTAMP-MAP=MPEGTS:180000,LOCAL:00:00:00.000" in vtt
    assert "Early line" not in vtt
    assert "00:00:02.000 --> 00:00:05.000" in vtt
    assert "Later line" in vtt


def test_multi_window_vad_in_engine():
    """Verify engine.py implements multi-window VAD sampling for drift detection without embedded ref."""
    with open(ENGINE_PY_PATH, "r", encoding="utf-8") as f:
        code = f.read()

    assert "multi_window" in code
    assert "asyncio.gather" in code
    assert "vad_drift_model" in code
    assert "audio_vad_drift" in code


def test_native_track_and_seek_micro_sync_contract():
    """Verify app.js includes native text track rendering & seek micro-sync functionality."""
    with open(APP_JS_PATH, "r", encoding="utf-8") as f:
        code = f.read()

    assert "_nativeSubTrack" in code, "Must manage video._nativeSubTrack"
    assert "addTextTrack" in code, "Must support native HTML5 text track"
    assert "VTTCue" in code, "Must construct VTTCue items"
    assert "triggerSeekMicroSync" in code, "Must declare triggerSeekMicroSync"
    assert "continuousSync" in code, "Must support continuousSync option"


def test_watch_party_subtitle_state_sync():
    """Verify watch party supports subtitle state broadcasting & snapshots."""
    room = WatchPartyRoom("test1", "a" * 40, "host_1")
    sub_state = {"offset": 1.25, "drift_model": {"model": "linear", "params": [0.001, 0]}, "active_track_id": "sub_1"}
    evt = room.post_event("host_1", "sub_sync", 120.0, subtitle_state=sub_state)
    assert evt["action"] == "sub_sync"
    assert evt["subtitle_state"] == sub_state
    snap = room.snapshot()
    assert snap["latest_subtitle_state"] == sub_state

    # Verify party.js handles subtitle_state
    with open(PARTY_JS_PATH, "r", encoding="utf-8") as f:
        party_code = f.read()
    assert "evt.subtitle_state" in party_code
    assert "setSubtitleSync" in party_code


def test_ass_to_webvtt_styling_preservation():
    """Verify ass_to_webvtt translates ASS formatting tags into HTML/VTT tags."""
    ass_text = (
        "[Events]\n"
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
        "Dialogue: 0,0:00:01.00,0:00:03.00,Default,,0,0,0,,{\\b1}Bold{\\b0} and {\\i1}Italic{\\i0}\n"
    )
    vtt = ass_to_webvtt(ass_text)
    assert "<b>Bold</b> and <i>Italic</i>" in vtt


def test_pgs_bitmap_auto_canvas_routing():
    """Verify transmuxer emits NOTE Codec: hdmv_pgs on bitmap stream detection so client routes to canvas."""
    with open(TRANSMUXER_PY_PATH, "r", encoding="utf-8") as f:
        code = f.read()

    assert "NOTE Codec: hdmv_pgs" in code, "Must emit hdmv_pgs marker to trigger client Canvas decoder"
