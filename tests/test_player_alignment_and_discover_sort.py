import os
import re
import pytest

CSS_PATH = os.path.join(os.path.dirname(__file__), "..", "static", "style.css")
APP_PATH = os.path.join(os.path.dirname(__file__), "..", "static", "app.js")


def test_player_controls_bar_css_alignment():
    """Contract: player controls row and volume elements MUST be flex-aligned on the same center line."""
    with open(CSS_PATH, "r", encoding="utf-8") as f:
        css = f.read()

    # Must define player-volume-wrap with align-items: center
    assert re.search(r"\.player-volume-wrap\s*\{[^}]*align-items:\s*center", css), \
        "Missing .player-volume-wrap with align-items: center"

    # Must define player-volume-slider-wrap with align-items: center
    assert re.search(r"\.player-volume-slider-wrap\s*\{[^}]*align-items:\s*center", css), \
        "Missing .player-volume-slider-wrap with align-items: center"


def test_player_controls_air_gap():
    """Contract: player controls row MUST add generous air between left/right elements (>= 0.75rem or 12px)."""
    with open(CSS_PATH, "r", encoding="utf-8") as f:
        css = f.read()

    # Verify gap for controls left and right is increased
    match_left = re.search(r"\.player-controls-left[^{]*\{[^}]*gap:\s*([^;]+);", css)
    assert match_left, "Missing gap definition for .player-controls-left"
    gap_val = match_left.group(1).strip()
    assert "2xs" not in gap_val and "3xs" not in gap_val, f"Gap '{gap_val}' is too cramped"


def test_discover_default_stream_sort_to_seeds():
    """Contract: app.js MUST set streamFilter sort default to 'seeds_desc'."""
    with open(APP_PATH, "r", encoding="utf-8") as f:
        js = f.read()

    # Discover state initialization must default to seeds_desc
    assert re.search(r"streamFilter:\s*\{[^}]*sort:\s*['\"]seeds_desc['\"]", js), \
        "state.discover.streamFilter.sort must default to 'seeds_desc'"

    # On resolve selection, it must reset to seeds_desc
    assert "sort: 'seeds_desc'" in js, "Missing reset to 'seeds_desc' in resolveStreamsForCurrentSelection"
