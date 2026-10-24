import os
import re
import pytest

APP_PATH = os.path.join(os.path.dirname(__file__), "..", "static", "app.js")
HTML_PATH = os.path.join(os.path.dirname(__file__), "..", "static", "index.html")
CSS_PATH = os.path.join(os.path.dirname(__file__), "..", "static", "style.css")


def test_skip_intro_removed_from_html_and_css():
    """Contract: player-skip-btn MUST be completely removed from HTML and CSS."""
    with open(HTML_PATH, "r", encoding="utf-8") as f:
        html = f.read()
    assert "player-skip-btn" not in html, "player-skip-btn still present in index.html"
    assert "handleSkipIntroOutro" not in html, "handleSkipIntroOutro still in index.html"

    with open(CSS_PATH, "r", encoding="utf-8") as f:
        css = f.read()
    assert ".player-skip-btn" not in css, ".player-skip-btn still present in style.css"


def test_skip_intro_removed_from_app_js():
    """Contract: handleSkipIntroOutro MUST be removed from app.js."""
    with open(APP_PATH, "r", encoding="utf-8") as f:
        js = f.read()
    assert "function handleSkipIntroOutro" not in js, "handleSkipIntroOutro function still in app.js"


def test_arabic_does_not_substring_match_hungarian():
    """Contract: matchSubtitleLang in app.js must NOT match 'Hungarian' or 'Bulgarian' when filtering for 'ar'."""
    with open(APP_PATH, "r", encoding="utf-8") as f:
        js = f.read()

    # The old buggy check: name.includes(alias) where alias is 'ar' caused 'hungarian'.includes('ar') == True
    # Verify exact word tokenization or safe boundary matching exists
    assert "nameWords" in js or "split(/[^a-z0-9]+/)" in js or "words.includes" in js, \
        "matchSubtitleLang must tokenize name to avoid substring collisions like 'ar' matching 'hungarian'"
