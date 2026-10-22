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
