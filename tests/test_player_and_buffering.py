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
