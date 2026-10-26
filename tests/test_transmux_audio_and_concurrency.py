import asyncio
import os
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from core.transmuxer import stream_transmuxed_video, get_ffmpeg_max_concurrency


@pytest.mark.asyncio
async def test_bs775_filter_generated_for_surround():
    """Verifies that ITU-R BS.775 downmix filter matrix is injected when audio channels > 2."""
    captured_cmd = None

    class MockProcess:
        def __init__(self):
            self.returncode = 0
            self.stdout = AsyncMock()
            self.stdout.read = AsyncMock(side_effect=[b"DATA", b""])
            self.stderr = AsyncMock()
            self.stderr.readline = AsyncMock(return_value=b"")
            self.terminate = MagicMock()
            self.wait = AsyncMock()

    async def mock_exec(*args, **kwargs):
        nonlocal captured_cmd
        captured_cmd = list(args)
        return MockProcess()

    with patch("asyncio.create_subprocess_exec", side_effect=mock_exec):
        # 1. Surround audio: channels=6
        gen = stream_transmuxed_video("http://127.0.0.1:8888/test", channels=6, audio_boost=1.2)
        async for _ in gen:
            break

        cmd_str = " ".join(captured_cmd)
        assert "pan=stereo|FL=0.5*c0+0.7071*c2+0.7071*c4|FR=0.5*c1+0.7071*c2+0.7071*c5" in cmd_str
        assert "volume=1.20" in cmd_str

        # 2. Stereo audio: channels=2
        gen2 = stream_transmuxed_video("http://127.0.0.1:8888/test", channels=2, audio_boost=1.0)
        async for _ in gen2:
            break

        cmd_str2 = " ".join(captured_cmd)
        assert "pan=stereo" not in cmd_str2


@pytest.mark.asyncio
async def test_ffmpeg_killed_fast_on_client_disconnect():
    """Verifies that if FFmpeg process hangs during terminate, SIGKILL is issued within 1.0s."""
    mock_proc = MagicMock()
    mock_proc.returncode = None
    mock_proc.stdout = AsyncMock()
    mock_proc.stdout.read = AsyncMock(return_value=b"FIRST_CHUNK")
    mock_proc.stderr = AsyncMock()
    mock_proc.stderr.readline = AsyncMock(return_value=b"")
    mock_proc.terminate = MagicMock()
    mock_proc.kill = MagicMock()

    # Make first wait() simulate a hang (timeout), second wait() complete after kill()
    wait_count = 0
    async def mock_wait():
        nonlocal wait_count
        wait_count += 1
        if wait_count == 1:
            await asyncio.sleep(2.0)
        return 0

    mock_proc.wait = mock_wait

    with patch("asyncio.create_subprocess_exec", AsyncMock(return_value=mock_proc)):
        gen = stream_transmuxed_video("http://127.0.0.1:8888/test")
        async for chunk in gen:
            assert chunk == b"FIRST_CHUNK"
            break  # Triggers client disconnect / GeneratorExit
        await gen.aclose()

        mock_proc.terminate.assert_called_once()
        mock_proc.kill.assert_called_once()


def test_semaphore_concurrency_bounded(monkeypatch):
    """Verifies that FFmpeg semaphore concurrency adapts to CPU count and EVO_MAX_CONCURRENT_FFMPEG."""
    monkeypatch.setenv("EVO_MAX_CONCURRENT_FFMPEG", "7")
    assert get_ffmpeg_max_concurrency() == 7

    monkeypatch.delenv("EVO_MAX_CONCURRENT_FFMPEG", raising=False)
    default_concurrency = get_ffmpeg_max_concurrency()
    assert 2 <= default_concurrency <= 8


def test_ui_pgs_client_canvas_default_and_seek_debounce():
    """Verifies static/app.js defaults PGS engine to client_canvas and debounces seekPlayer by 250ms."""
    app_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "static", "app.js"))
    with open(app_path, "r", encoding="utf-8") as f:
        app_js = f.read()

    assert "pgsEngine: (function() { try { return localStorage.getItem('evo_pgs_engine') || 'client_canvas'" in app_js
    assert "_seekDebounceTimer = setTimeout" in app_js
    assert "250" in app_js
