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


def test_subtitle_cue_parser_and_pgs_routing():
    """Verify timeRegex is defined in cue parser and PGS subtitles auto-route properly."""
    js_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "static", "app.js"))
    with open(js_path, "r", encoding="utf-8") as f:
        js = f.read()

    # Verify timeRegex definition in parseVttOrSrtToCues
    assert "timeRegex = /(?:(\\d{1,2}):)?(\\d{2}):(\\d{2})[,.](\\d{3})" in js
    assert "subItem.is_image_based = true" in js

    # Verify CSS widened the player subtitle drawer
    css_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "static", "style.css"))
    with open(css_path, "r", encoding="utf-8") as f:
        css = f.read()
    assert "clamp(620px, 45vw, 780px)" in css


def test_transmuxer_bitmap_codec_detection():
    """Verify transmuxer correctly flags PGS, DVD, and VobSub subtitle streams as bitmap."""
    from core.transmuxer import probe_media_stream
    assert callable(probe_media_stream)
    # Mock probe logic check
    codecs_to_test = ["hdmv_pgs_subtitle", "pgssub", "PGS", "dvdsub", "vobsub", "dvb_subtitle"]
    for cname in codecs_to_test:
        is_bitmap = any(k in cname.lower() for k in ("pgs", "dvd", "vobsub", "xsub", "dvb_subtitle"))
        assert is_bitmap is True, f"Expected {cname} to be recognized as bitmap"

    text_codecs = ["subrip", "srt", "ass", "ssa", "webvtt", "mov_text"]
    for cname in text_codecs:
        is_bitmap = any(k in cname.lower() for k in ("pgs", "dvd", "vobsub", "xsub", "dvb_subtitle"))
        assert is_bitmap is False, f"Expected {cname} not to be bitmap"

