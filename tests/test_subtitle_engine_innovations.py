import pytest
import os


def test_subtitle_studio_font_family_and_shadow_controls():
    """Verify subtitle drawer contains font family selector and shadow/outline controls."""
    html_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "static", "index.html"))
    with open(html_path, "r", encoding="utf-8") as f:
        html = f.read()

    # Section 2.3: Font Family Selector
    assert 'id="sub-style-font-family"' in html
    assert 'value="Inter"' in html or 'value="Roboto"' in html

    # Section 2.3: Text Shadow / Outline Selector
    assert 'id="sub-style-shadow"' in html


def test_subtitle_engine_scripts_and_ass_renderer():
    """Verify app.js contains EvoAssRenderer for client-side ASS/SSA parsing and rendering, and style functions."""
    js_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "static", "app.js"))
    with open(js_path, "r", encoding="utf-8") as f:
        js = f.read()

    # Section 2.1: Client-Side ASS/SSA Subtitle Rendering
    assert "EvoAssRenderer" in js or "parseAssSubtitles" in js

    # Section 2.2: Subtitle Offset Calibration
    assert "adjustSubtitleSyncMs" in js
    assert "setSubtitleSync" in js

    # Section 2.3: Subtitle Font Family & Shadow application
    assert "setSubtitleFontFamily" in js or "sub-style-font-family" in js
    assert "setSubtitleShadow" in js or "sub-style-shadow" in js
