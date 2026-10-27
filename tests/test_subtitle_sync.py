import pytest
from core.subtitle_sync import (
    parse_silencedetect_output,
    compute_optimal_offset,
    align_to_reference_cues,
)


def test_parse_silencedetect_output():
    mock_stderr = """
[silencedetect @ 000001] silence_start: 0.00
[silencedetect @ 000001] silence_end: 10.50 | silence_duration: 10.50
[silencedetect @ 000001] silence_start: 25.00
[silencedetect @ 000001] silence_end: 32.00 | silence_duration: 7.00
[silencedetect @ 000001] silence_start: 50.00
[silencedetect @ 000001] silence_end: 55.00 | silence_duration: 5.00
"""
    speech = parse_silencedetect_output(mock_stderr, total_duration=60.0)
    # Expected speech: (10.5, 25.0), (32.0, 50.0), (55.0, 60.0)
    assert len(speech) == 3
    assert speech[0] == (10.5, 25.0)
    assert speech[1] == (32.0, 50.0)
    assert speech[2] == (55.0, 60.0)


def test_compute_optimal_offset_shifted_cues():
    # Ground truth speech intervals
    speech = [
        (12.0, 16.0),
        (20.0, 25.0),
        (34.0, 40.0),
        (48.0, 55.0),
        (70.0, 78.0),
    ]

    # Subtitles are 4.5 seconds DELAYED (they start at 16.5 instead of 12.0)
    delay = 4.5
    cues = [(s + delay, e + delay) for s, e in speech]

    # Algorithm should calculate offset = -4.5 to shift them back
    offset, confidence = compute_optimal_offset(cues, speech, min_offset=-15.0, max_offset=15.0, step=0.1)
    assert abs(offset - (-4.5)) <= 0.15
    assert confidence > 0.8


def test_compute_optimal_offset_advanced_cues():
    speech = [
        (15.0, 20.0),
        (30.0, 36.0),
        (45.0, 52.0),
    ]

    # Subtitles are 3.0 seconds ADVANCED (they start too early at 12.0 instead of 15.0)
    delay = -3.0
    cues = [(s + delay, e + delay) for s, e in speech]

    # Algorithm should calculate offset = +3.0 to delay them to match
    offset, confidence = compute_optimal_offset(cues, speech, min_offset=-10.0, max_offset=10.0, step=0.1)
    assert abs(offset - 3.0) <= 0.15
    assert confidence > 0.8


def test_align_to_reference_cues():
    ref_cues = [
        (10.0, 14.0),
        (22.0, 26.0),
        (35.0, 41.0),
        (50.0, 55.0),
    ]

    # External Spanish subtitle is shifted by 2.4 seconds
    target_cues = [(s + 2.4, e + 2.4) for s, e in ref_cues]

    offset, confidence = align_to_reference_cues(target_cues, ref_cues)
    assert abs(offset - (-2.4)) <= 0.05
    assert confidence == 1.0


@pytest.mark.asyncio
async def test_auto_sync_endpoint_vad():
    from unittest.mock import patch, AsyncMock
    from httpx import AsyncClient, ASGITransport
    from main import app

    speech_mock = [(10.0, 15.0), (25.0, 30.0)]
    # Cues are shifted by +3.5s
    cues = [{"start": s + 3.5, "end": e + 3.5, "text": "Hello"} for s, e in speech_mock]

    with patch("core.subtitle_sync.extract_speech_intervals_from_stream", new=AsyncMock(return_value=speech_mock)), \
         patch("core.torrent_streamer.ensure_streaming_daemon", new=AsyncMock(return_value=True)):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            res = await client.post(
                "/api/v1/stream/subtitles/auto-sync",
                json={
                    "info_hash": "a" * 40,
                    "file_idx": 0,
                    "cues": cues,
                },
            )
            assert res.status_code == 200
            data = res.json()
            assert data["success"] is True
            assert data["method"] == "audio_vad"
            assert abs(data["offset"] - (-3.5)) <= 0.15


@pytest.mark.asyncio
async def test_auto_sync_endpoint_reference():
    from unittest.mock import patch, AsyncMock
    from httpx import AsyncClient, ASGITransport
    from main import app

    ref_vtt = """WEBVTT

00:00:10.000 --> 00:00:15.000
Original English

00:00:25.000 --> 00:00:30.000
Second English line
"""
    cues = [{"start": 12.0, "end": 17.0, "text": "Hola"}, {"start": 27.0, "end": 32.0, "text": "Segunda linea"}]

    with patch("routers.stream.extract_embedded_subtitle_vtt", new=AsyncMock(return_value=ref_vtt)), \
         patch("core.torrent_streamer.ensure_streaming_daemon", new=AsyncMock(return_value=True)):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            res = await client.post(
                "/api/v1/stream/subtitles/auto-sync",
                json={
                    "info_hash": "a" * 40,
                    "file_idx": 0,
                    "reference_sub_idx": 0,
                    "cues": cues,
                },
            )
            assert res.status_code == 200
            data = res.json()
            assert data["success"] is True
            assert data["method"] == "embedded_reference"
            assert abs(data["offset"] - (-2.0)) <= 0.1


@pytest.mark.asyncio
async def test_auto_sync_endpoint_short_timestamp_vtt():
    """Verify auto-sync parses standard 2-component mm:ss.ttt WebVTT timestamps from FFmpeg."""
    from unittest.mock import patch, AsyncMock
    from httpx import AsyncClient, ASGITransport
    from main import app

    ref_vtt = """WEBVTT

01:10.000 --> 01:15.000
Original English

01:25.000 --> 01:30.000
Second English line
"""
    # 70.0s and 85.0s
    cues = [{"start": 72.0, "end": 77.0, "text": "Hola"}, {"start": 87.0, "end": 92.0, "text": "Segunda linea"}]

    with patch("routers.stream.extract_embedded_subtitle_vtt", new=AsyncMock(return_value=ref_vtt)), \
         patch("core.torrent_streamer.ensure_streaming_daemon", new=AsyncMock(return_value=True)):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            res = await client.post(
                "/api/v1/stream/subtitles/auto-sync",
                json={
                    "info_hash": "b" * 40,
                    "file_idx": 0,
                    "reference_sub_idx": 0,
                    "cues": cues,
                },
            )
            assert res.status_code == 200
            data = res.json()
            assert data["success"] is True
            assert data["method"] == "embedded_reference"
            assert abs(data["offset"] - (-2.0)) <= 0.1


def test_frontend_subtitle_sync_ui_elements():
    """Verify index.html contains auto-sync button, status indicator, voice anchor, and framerate presets."""
    import os
    html_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "static", "index.html"))
    with open(html_path, "r", encoding="utf-8") as f:
        html = f.read()

    assert 'id="btn-sub-autosync"' in html
    assert 'id="sub-autosync-status"' in html
    assert "syncSubtitleToCurrentTime" in html
    assert "rescaleSubtitleFramerate" in html
    assert "23.976 -> 25 fps" in html or "23.976 &rarr; 25 fps" in html


def test_frontend_subtitle_sync_scripts():
    """Verify app.js implements triggerAutoSyncSubtitles, voice sync, framerate retiming, and keyframe snapping."""
    import os
    js_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "static", "app.js"))
    with open(js_path, "r", encoding="utf-8") as f:
        js = f.read()

    assert "async function triggerAutoSyncSubtitles" in js
    assert "function syncSubtitleToCurrentTime" in js
    assert "function rescaleSubtitleFramerate" in js
    assert "Container Synced" in js
    # Verify keyframe snapping in seekTransmuxOffset
    assert "active.keyframes" in js
    # Verify hotkey handling
    assert "triggerAutoSyncSubtitles" in js
    assert "syncSubtitleToCurrentTime" in js

