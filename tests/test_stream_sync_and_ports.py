import inspect
import os
import re
import sys
import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

CONFIG_PATH = os.path.join(os.path.dirname(__file__), "..", "config.py")
STREAMER_PY_PATH = os.path.join(os.path.dirname(__file__), "..", "core", "torrent_streamer.py")
TRANSMUXER_PY_PATH = os.path.join(os.path.dirname(__file__), "..", "core", "transmuxer.py")
ENGINE_JS_PATH = os.path.join(os.path.dirname(__file__), "..", "streamer", "torrent_engine.js")
SERVER_JS_PATH = os.path.join(os.path.dirname(__file__), "..", "streamer", "server.js")
APP_JS_PATH = os.path.join(os.path.dirname(__file__), "..", "static", "app.js")
DOCKER_COMPOSE_PATH = os.path.join(os.path.dirname(__file__), "..", "docker-compose.yml")


def test_ports_50000_and_50001_configured_and_enforced():
    """Contract: Ports 50000 (torrent wire) and 50001 (DHT) must be declared in config, killed if stale, and passed to node."""
    from config import settings
    assert getattr(settings, "TORRENT_PORT", None) == 50000, "settings.TORRENT_PORT must default to 50000"
    assert getattr(settings, "DHT_PORT", None) == 50001, "settings.DHT_PORT must default to 50001"

    with open(STREAMER_PY_PATH, "r", encoding="utf-8") as f:
        streamer_code = f.read()
    assert "50000" in streamer_code and "50001" in streamer_code, "kill_stale_daemon or startup must check ports 50000 and 50001"

    with open(ENGINE_JS_PATH, "r", encoding="utf-8") as f:
        engine_code = f.read()
    assert "50000" in engine_code and "50001" in engine_code, "torrent_engine.js must configure torrentPort 50000 and dhtPort 50001"


def test_buffering_engine_sliding_window_and_critical():
    """Contract: applySlidingWindow must manage critical pieces and priority overrides to prevent playback starvation."""
    with open(ENGINE_JS_PATH, "r", encoding="utf-8") as f:
        engine_code = f.read()

    assert "torrent._critical" in engine_code or "critical(" in engine_code, "torrent_engine.js must manage critical pieces"
    assert "urgentPieces" in engine_code and "bufferPieces" in engine_code, "torrent_engine.js must prioritize playback cursor pieces"
    assert "bufferStart = urgentEnd + 2" in engine_code, "priority tiers must stay separated so WebTorrent cannot collapse them"
    assert "applySlidingWindow" in engine_code, "torrent_engine.js must implement applySlidingWindow"


def test_transmuxer_av_sync_flags():
    """Contract: stream_transmuxed_video must configure aresample first_pts=0, negative_cts_offsets, and genpts to eliminate A/V desync."""
    with open(TRANSMUXER_PY_PATH, "r", encoding="utf-8") as f:
        transmuxer_code = f.read()

    assert "first_pts=0" in transmuxer_code, "aresample filter must include first_pts=0 to prevent initial audio timestamp drift"
    assert "negative_cts_offsets" in transmuxer_code, "movflags must include negative_cts_offsets to avoid CTS video delays"
    assert "genpts" in transmuxer_code, "ffmpeg flags must include genpts to regenerate timestamps from stream packets"


def test_app_js_prefers_embedded_subtitles_for_perfect_sync():
    """Contract: app.js must auto-apply embedded text subtitles when available because they are 100% in sync with the video."""
    with open(APP_JS_PATH, "r", encoding="utf-8") as f:
        app_code = f.read()

    assert "textEmbedded" in app_code, "app.js must detect embedded text subtitles"
    # Ensure jump to cue handles transmux mode with playbackOffset
    assert "jumpToNextCue" in app_code
    assert "jumpToPrevCue" in app_code
