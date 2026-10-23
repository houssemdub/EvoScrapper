import os
import re
import shutil
import subprocess
import sys
from unittest.mock import patch
import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from main import app
from core.torrent_streamer import is_direct_streamable


@pytest.fixture
def client():
    return TestClient(app)


def test_javascript_syntax_validity():
    """Validates that all frontend and streamer JavaScript files have zero syntax errors."""
    node_bin = shutil.which("node")
    if not node_bin:
        pytest.skip("Node.js binary not found on system")

    js_files = [
        os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "static", "app.js")),
        os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "static", "p2p-player.js")),
        os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "streamer", "server.js")),
        os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "streamer", "torrent_engine.js")),
    ]

    for f in js_files:
        assert os.path.isfile(f), f"File {f} must exist"
        proc = subprocess.run([node_bin, "-c", f], capture_output=True, text=True)
        assert proc.returncode == 0, f"Syntax error in {os.path.basename(f)}: {proc.stderr}"


def test_direct_stream_bypass_detection():
    """Verifies browser-native MP4/WebM formats bypass FFmpeg while HEVC/MKV/surround require transmuxing."""
    # Native direct streams (MP4/WebM with H.264/AAC/VP9/Opus)
    assert is_direct_streamable("Inception.2010.1080p.BluRay.x264.AAC-YTS.mp4") is True
    assert is_direct_streamable("Big.Buck.Bunny.1080p.h264.mp3.mp4") is True
    assert is_direct_streamable("Sintel.2010.720p.VP9.opus.webm") is True
    assert is_direct_streamable("Cosmos.Laundromat.av1.opus.webm") is True

    # Formats requiring transmuxing (MKV container, HEVC/x265, 10-bit, non-browser audio like AC3/DDP/DTS)
    assert is_direct_streamable("Oppenheimer.2023.2160p.UHD.BluRay.x265.DDP5.1.mkv") is False
    assert is_direct_streamable("Avatar.2009.1080p.Remux.AVC.DTS-HD.MA.5.1.mkv") is False
    assert is_direct_streamable("Interstellar.2014.1080p.BluRay.x265.10bit.mp4") is False
    assert is_direct_streamable("Dune.2021.1080p.TrueHD.Atmos.mkv") is False
    assert is_direct_streamable("Sample.Video.AC3.Surround.avi") is False


def test_default_trackers_tier_list():
    """Verifies that streamer/torrent_engine.js contains comprehensive public trackers (UDP, HTTP, WSS)."""
    engine_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "streamer", "torrent_engine.js"))
    assert os.path.isfile(engine_path), "torrent_engine.js must exist"

    with open(engine_path, "r", encoding="utf-8") as f:
        content = f.read()

    # Extract DEFAULT_TRACKERS
    m = re.search(r"const\s+DEFAULT_TRACKERS\s*=\s*\[(.*?)\];", content, re.DOTALL)
    assert m, "DEFAULT_TRACKERS array must be defined in torrent_engine.js"

    trackers_block = m.group(1)
    trackers = [t.strip().strip("'\"") for t in trackers_block.split(",") if t.strip().strip("'\"")]

    assert len(trackers) >= 18, f"Expected at least 18 top-tier trackers, found {len(trackers)}"

    # Check required tracker protocols
    has_udp = any(t.startswith("udp://") for t in trackers)
    has_http = any(t.startswith("http://") or t.startswith("https://") for t in trackers)
    has_wss = any(t.startswith("wss://") or t.startswith("ws://") for t in trackers)

    assert has_udp, "Must include UDP trackers"
    assert has_http, "Must include HTTP trackers"
    assert has_wss, "Must include WebTorrent WSS trackers for browser P2P mesh"

    # Check key reliable tracker domains
    assert any("opentrackr.org" in t for t in trackers)
    assert any("openbittorrent.com" in t for t in trackers)
    assert any("openwebtorrent.com" in t for t in trackers)


def test_torrent_engine_sliding_window_strategy():
    """Verifies torrent_engine.js implements aggressive 2-5% critical header, tail index, and sliding cursor priority."""
    engine_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "streamer", "torrent_engine.js"))
    with open(engine_path, "r", encoding="utf-8") as f:
        content = f.read()

    # Verify sliding window method signature and prioritization logic
    assert "applySlidingWindow(torrent, file, byteOffset" in content
    # Base priority 1 for all file pieces
    assert "file.select(1)" in content
    # Critical header calculation (2-5% or minimum pieces)
    assert "criticalCount" in content and "headerEnd" in content
    # Priority 3 for header
    assert "torrent.select(fileStartPiece, headerEnd, 3)" in content
    # Priority 3 for tail index
    assert "torrent.select(indexStart, fileEndPiece, 3)" in content
    # Sliding cursor priority 3 & buffer priority 2
    assert "immediateWindow" in content and "bufferPieces" in content


def test_stream_duration_headers(client):
    """Verifies that /api/v1/stream/transmux respects duration query and outputs X-Content-Duration."""
    async def mock_generator(*args, **kwargs):
        yield b"MP4-STREAM-TEST-DATA"

    with patch("routers.stream.ensure_streaming_daemon", return_value=True), \
         patch("routers.stream.stream_transmuxed_video", side_effect=mock_generator):

        res = client.get(
            "/api/v1/stream/transmux",
            params={
                "info_hash": "0123456789abcdef0123456789abcdef01234567",
                "file_idx": 0,
                "duration": 5432.5,
            },
            headers={"x-api-key": "dev-key"},
        )
        assert res.status_code == 200
        assert "X-Content-Duration" in res.headers
        assert res.headers["X-Content-Duration"] == "5432.5"
        assert res.headers["Content-Duration"] == "5432.5"


def test_ui_subtitle_drawer_layout_and_telemetry():
    """Verifies style.css and index.html have proper layout constraints, wider width, and live P2P telemetry badge."""
    css_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "static", "style.css"))
    with open(css_path, "r", encoding="utf-8") as f:
        css = f.read()

    # Subtitle drawer layout & scrolling: wider 520px layout with z-index 65
    assert "width: 520px;" in css
    assert "z-index: 65;" in css
    assert "overscroll-behavior: contain;" in css
    assert "sub-drawer-nav" in css
    assert "sub-nav-tab" in css

    html_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "static", "index.html"))
    with open(html_path, "r", encoding="utf-8") as f:
        html = f.read()

    # Live P2P telemetry badge in controls HUD
    assert 'id="player-hud-p2p-badge"' in html
    assert 'id="player-hud-p2p-text"' in html

    # Segmented navigation tabs inside redesigned drawer
    assert 'id="sub-tab-tracks"' in html
    assert 'id="sub-tab-sync"' in html
    assert 'id="sub-tab-style"' in html
    assert 'id="sub-panel-tracks"' in html

    app_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "static", "app.js"))
    with open(app_path, "r", encoding="utf-8") as f:
        js = f.read()

    # Video duration fallback unfreezing
    assert "video.onloadedmetadata" in js
    assert "video.ondurationchange" in js
    assert "isDirectStream" in js
    assert "player-hud-p2p-text" in js


def test_subtitle_pause_on_open_and_resume_on_select():
    """Verifies app.js pauses playback when opening the subtitle drawer and auto-resumes after selecting a subtitle."""
    app_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "static", "app.js"))
    with open(app_path, "r", encoding="utf-8") as f:
        js = f.read()

    # switchSubDrawerTab function exists
    assert "function switchSubDrawerTab" in js

    # toggleSubtitleDrawer pauses video on open and records state
    assert "wasPlayingBeforeDrawer" in js
    assert "video.pause()" in js

    # selectSubtitleByIndex auto-hides drawer and resumes playback
    assert "toggleSubtitleDrawer(false)" in js
    assert "video.play()" in js


def test_fullscreen_controls_auto_hide_behavior():
    """Verifies controls bar only hides in fullscreen mode and stays visible in normal mode with a 3-second activity timer."""
    css_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "static", "style.css"))
    with open(css_path, "r", encoding="utf-8") as f:
        css = f.read()

    # CSS explicitly restricts user-idle hiding to fullscreen selectors
    assert ":fullscreen.user-idle" in css
    assert ".player-video-wrap .player-bottom-controls" in css

    app_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "static", "app.js"))
    with open(app_path, "r", encoding="utf-8") as f:
        js = f.read()

    # JS verifies isFs before setting idle timer
    assert "handlePlayerActivity" in js
    assert "document.fullscreenElement" in js
    # 3-second timer (3000ms)
    assert "3000" in js


def test_uiverse_neon_svg_loader_assets():
    """Verifies that the Uiverse.io animated SVG loader (E-v-o paths) is implemented with theme styles and CSS animations."""
    css_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "static", "style.css"))
    with open(css_path, "r", encoding="utf-8") as f:
        css = f.read()

    # CSS classes and animations
    assert ".loader" in css or ".evo-loader" in css
    assert "@keyframes dashArray" in css
    assert "@keyframes spinDashArray" in css
    assert "@keyframes dashOffset" in css
    assert "@keyframes evoSpin" in css
    assert "stroke-dashoffset" in css
    assert "transform: rotate" in css

    html_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "static", "index.html"))
    with open(html_path, "r", encoding="utf-8") as f:
        html = f.read()

    # SVG Defs & Gradient definitions with theme colors
    assert 'id="b"' in html or 'id="evo-grad-b"' in html
    assert 'id="c"' in html or 'id="evo-grad-c"' in html
    assert 'id="d"' in html or 'id="evo-grad-d"' in html
    assert "#00e5ff" in html  # Cyan accent
    assert "#00ff88" in html  # Neon green accent
    assert "gradientTransform" in html
    assert 'id="player-buffering-spinner"' in html

    app_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "static", "app.js"))
    with open(app_path, "r", encoding="utf-8") as f:
        js = f.read()

    # Site-wide helper and usage
    assert "getEvoLoaderHtml" in js
    assert "evo-loader" in js
    assert "evo-loader-container" in js


def test_direct_stream_default_and_duration_unfreezing():
    """Verifies that EvoScrapper defaults to direct /play streaming and guarantees duration display."""
    app_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "static", "app.js"))
    with open(app_path, "r", encoding="utf-8") as f:
        js = f.read()

    # Default to direct stream (/api/v1/stream/play)
    assert "/api/v1/stream/play?" in js
    assert "useTransmux = false;" in js or "const useTransmux = false;" in js
    assert "toggleStreamPipelineMode" in js

    # Automatic fallback on video error
    assert "video.onerror" in js
    assert "/api/v1/stream/transmux" in js

    # Immediate total-time display initialization
    assert "player-total-time" in js
    assert "formatPlayerDuration" in js
    assert "player-hud-mode-label" in js

