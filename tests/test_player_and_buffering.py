import re
import subprocess
import os
import pytest

CSS_PATH = os.path.join(os.path.dirname(__file__), "..", "static", "style.css")
ENGINE_PATH = os.path.join(os.path.dirname(__file__), "..", "streamer", "torrent_engine.js")


def test_player_hud_idle_hiding_css_rules():
    """Contract: style.css MUST define complete auto-hide rules for header, controls, footer, and cursor."""
    with open(CSS_PATH, "r", encoding="utf-8") as f:
        css = f.read()

    # Verify user-idle cursor hiding
    assert re.search(r"\.player-video-wrap[^{]*\.user-idle[^{]*\{[^}]*cursor:\s*none", css) or \
           re.search(r"\.user-idle[^{]*\{[^}]*cursor:\s*none", css), "Missing cursor: none rule for user-idle"

    # Verify user-idle header hiding
    assert re.search(r"\.user-idle\s+\.player-hud-header", css), "Missing .user-idle .player-hud-header rule"

    # Verify user-idle footer / controls hiding
    assert re.search(r"\.user-idle\s+\.player-bottom-controls", css), "Missing .user-idle .player-bottom-controls rule"


def test_multi_tier_buffering_in_engine():
    """Contract: torrent_engine.js MUST implement multi-tier concurrent buffering (immediate, multi-peer horizon, and deep reservoir)."""
    with open(ENGINE_PATH, "r", encoding="utf-8") as f:
        code = f.read()

    # The scheduler builds one urgent (priority 3), one horizon (priority 2),
    # and one retention (priority 1) range per reader. Execution-level coverage
    # lives in tests/test_engine_scheduler.py.
    assert "_buildReaderIntervals" in code, "Missing tiered reader scheduler"
    assert "urgentPieces" in code and "priority: 3" in code, "Missing immediate window definition"
    assert "bufferPieces" in code and "priority: 2" in code, "Missing multi-peer horizon definition"
    assert "RETENTION_PIECES" in code and "priority: 1" in code, "Missing deep background reservoir definition"


def test_player_prebuffering_contract_in_app_js():
    """Contract: app.js playerBufferingInterval MUST declare bufferAheadSec and elapsedPrebuffer,
    and seekTransmuxOffset MUST attach canplay/loadeddata lifecycle listeners so seeking cannot freeze."""
    app_js_path = os.path.join(os.path.dirname(__file__), "..", "static", "app.js")
    with open(app_js_path, "r", encoding="utf-8") as f:
        app_js = f.read()

    # 1. Check variable declarations in playerBufferingInterval
    assert "const bufferAheadSec = getPlayerBufferAheadSec();" in app_js, "bufferAheadSec must be declared"
    assert "const elapsedPrebuffer = _prebufferStartTime > 0" in app_js, "elapsedPrebuffer must be declared"

    # 2. Check seek release listeners
    assert "onSeekCanPlay" in app_js, "seekTransmuxOffset must define onSeekCanPlay listener"
    assert "video.addEventListener('canplay', onSeekCanPlay" in app_js, "must listen to canplay on seek"
    assert "video.addEventListener('loadeddata', onSeekCanPlay" in app_js, "must listen to loadeddata on seek"

    # 3. Check initial start canplay listeners
    assert "onInitialCanPlay" in app_js, "playStreamInBrowser must define onInitialCanPlay listener"
    assert "video.addEventListener('canplay', onInitialCanPlay" in app_js, "must listen to canplay on initial start"
