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


def test_player_unmute_overlay_conditional_guard():
    """Contract: player-unmute-overlay MUST only show when video is actually muted and auto-dismiss when unmuted."""
    with open(APP_PATH, "r", encoding="utf-8") as f:
        js = f.read()

    with open(HTML_PATH, "r", encoding="utf-8") as f:
        html = f.read()

    # 1. Overlay is hidden by default in HTML
    assert 'id="player-unmute-overlay" class="player-unmute-overlay hidden"' in html

    # 2. In app.js, catch block must NOT unconditionally call unmuteOverlay.classList.remove('hidden')
    assert "if (unmuteOverlay) unmuteOverlay.classList.remove('hidden');\n    hidePlayerBufferingHUD();" not in js, \
        "video.play().catch must NOT unconditionally unhide player-unmute-overlay when not muted"

    # 3. checkMuteState or onplaying verifies unmuted state to hide overlay
    assert "video.onplaying" in js
    assert "unmuteAndBoostVideo" in js


def test_subtitle_autosync_off_by_default():
    """Contract: automatic subtitle timing changes (saved-offset restore at load,
    post-seek micro-sync) MUST be opt-in via the subs_autosync setting, default OFF."""
    with open(APP_PATH, "r", encoding="utf-8") as f:
        js = f.read()
    with open(HTML_PATH, "r", encoding="utf-8") as f:
        html = f.read()

    # 1. Settings toggle exists in HTML and is NOT pre-checked (default OFF).
    # Match a standalone `checked` attribute only (not `this.checked` in onchange).
    assert 'id="settings-toggle-subs-autosync"' in html
    toggle_idx = html.index('id="settings-toggle-subs-autosync"')
    tag_start = html.rindex("<input", 0, toggle_idx)
    tag_end = html.index(">", toggle_idx)
    assert not re.search(r"\schecked(?=[\s>])", html[tag_start:tag_end]), \
        "subs-autosync toggle must not be pre-checked"

    # 2. Gate helper reads the setting with strict-on semantics (absent = OFF)
    assert "function isSubtitleAutoSyncEnabled" in js
    assert "s.subs_autosync === true" in js

    # 3. Saved-offset restore in applySubtitle is gated on the helper
    restore_idx = js.index("const savedSync = loadSavedSubtitleSync(subItem);")
    gate_idx = js.index("isSubtitleAutoSyncEnabled()", restore_idx)
    apply_idx = js.index("restoredOffset = savedSync.offset;", restore_idx)
    assert gate_idx < apply_idx, "saved offset must only be applied when isSubtitleAutoSyncEnabled() passes"

    # 4. Post-seek micro-sync is gated on the helper
    micro_idx = js.index("function triggerSeekMicroSync")
    assert "isSubtitleAutoSyncEnabled()" in js[micro_idx:micro_idx + 400]
