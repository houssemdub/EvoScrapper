import pytest
import os
from httpx import AsyncClient, ASGITransport
from main import app
from core.transmuxer import detect_hw_encoders, get_video_encoder


def test_detect_hw_encoders():
    """Verify hardware encoder detection runs without error and returns dictionary of capabilities."""
    encoders = detect_hw_encoders()
    assert isinstance(encoders, dict)
    assert "nvenc" in encoders
    assert "qsv" in encoders
    assert "amf" in encoders
    assert "vaapi" in encoders
    assert "software" in encoders
    assert encoders["software"] is True  # libx264 is always available


def test_get_video_encoder():
    """Verify encoder selection falls back to libx264 when hw is disabled or unavailable."""
    codec, extra_args = get_video_encoder(hw_accel=False)
    assert codec == "libx264"
    assert isinstance(extra_args, list)


def test_frontend_player_enhancement_elements():
    """Verify index.html contains PiP, speed selector, night mode, resume prompt, and binge auto-play elements."""
    html_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "static", "index.html"))
    with open(html_path, "r", encoding="utf-8") as f:
        html = f.read()

    # Section 1.4: Native Picture-in-Picture
    assert 'id="btn-player-pip"' in html

    # Section 1.5: Variable Playback Speed Controls
    assert 'id="player-speed-select"' in html

    # Section 1.6: Night Mode Audio Dialogue Compression
    assert 'id="btn-player-night-mode"' in html

    # Section 1.3: Next Episode Auto-play / Binge Watch Mode
    assert 'id="player-next-episode-card"' in html

    # Section 1.2: Continue Watching / Resume Timestamp Prompt
    assert 'id="player-resume-prompt"' in html


def test_frontend_player_enhancement_scripts():
    """Verify app.js contains functions for PiP, speed, night mode, resume, and next episode binge auto-play."""
    js_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "static", "app.js"))
    with open(js_path, "r", encoding="utf-8") as f:
        js = f.read()

    # Section 1.4
    assert "togglePictureInPicture" in js

    # Section 1.5
    assert "setPlaybackSpeed" in js

    # Section 1.6
    assert "toggleNightModeAudio" in js

    # Section 1.3
    assert "checkNextEpisodeTrigger" in js or "triggerNextEpisodeCountdown" in js

    # Section 1.2
    assert "promptResumePlayback" in js or "checkPlaybackResume" in js
