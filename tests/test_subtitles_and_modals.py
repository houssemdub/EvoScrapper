import pytest
from core.transmuxer import sanitize_webvtt_content
import os


def test_sanitize_webvtt_content_filters_vector_drawings():
    raw_vtt = """WEBVTT

00:00.000 --> 00:05.000
m -5 0 l -51 0 l -5 1 l -9 4 l -4 3 l -26 25

00:05.100 --> 00:08.500
The Kingdom of Fiore...

00:08.600 --> 00:10.000
m 0 0 l 10 10

00:10.100 --> 00:12.500
A world of magic.
"""
    sanitized = sanitize_webvtt_content(raw_vtt)
    assert "The Kingdom of Fiore..." in sanitized
    assert "A world of magic." in sanitized
    assert "m -5 0 l -51 0" not in sanitized
    assert "m 0 0 l 10 10" not in sanitized


def test_css_modal_z_index_hierarchy():
    css_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "static", "style.css"))
    with open(css_path, "r", encoding="utf-8") as f:
        content = f.read()

    assert "z-index: 10000000 !important;" in content  # .modal-overlay
    assert "z-index: 10500000 !important;" in content  # #player-modal
    assert "z-index: 11000000 !important;" in content  # child modals
    assert "z-index: 20000000 !important;" in content  # #toast-container
    assert "z-index: 999999 !important;" in content    # discover search suggestions


def test_app_js_subtitle_and_title_helpers():
    js_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "static", "app.js"))
    with open(js_path, "r", encoding="utf-8") as f:
        content = f.read()

    assert "extractCleanMediaInfo" in content
    assert "LANG_ALIAS_TO_FAMILY" in content
    assert "isVectorDrawingCue" in content
    assert "Blu-ray PGS" in content


def test_fullscreen_exit_and_modal_portal_handling():
    """Verify that closing the player exits browser fullscreen, and child modals portal into fullscreen."""
    js_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "static", "app.js"))
    with open(js_path, "r", encoding="utf-8") as f:
        js_content = f.read()

    css_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "static", "style.css"))
    with open(css_path, "r", encoding="utf-8") as f:
        css_content = f.read()

    # 1. closePlayerModal exits fullscreen if active
    close_idx = js_content.find("function closePlayerModal()")
    assert close_idx != -1
    close_chunk = js_content[close_idx:close_idx + 600]
    assert "document.fullscreenElement" in close_chunk
    assert "exitFullscreen" in close_chunk

    # 2. syncFullscreenPortal and handleFullscreenChangePortals exist
    assert "function syncFullscreenPortal" in js_content
    assert "function handleFullscreenChangePortals" in js_content
    assert "syncFullscreenPortal(modal, shouldOpen)" in js_content or "syncFullscreenPortal(modal, true)" in js_content

    # 3. CSS rules support .modal-overlay and #toast-container inside fullscreen element
    assert "#player-video-wrap:fullscreen .modal-overlay" in css_content
    assert "z-index: 10000000 !important;" in css_content
    assert "#player-video-wrap:fullscreen #toast-container" in css_content

    # 4. Verify global mousemove listeners and fullscreen active controls rules
    assert "document.addEventListener('mousemove', handleGlobalPlayerActivity" in js_content
    assert "#player-video-wrap:fullscreen:not(.user-idle) .player-bottom-controls" in css_content
    assert "#player-video-wrap:fullscreen.user-idle .player-bottom-controls" in css_content
