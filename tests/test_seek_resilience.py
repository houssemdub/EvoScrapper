import os
import subprocess
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from fastapi.testclient import TestClient
from main import app
from core.transmuxer import stream_transmuxed_video, save_cached_keyframes


client = TestClient(app)
AUTH_HEADERS = {"X-API-Key": "test_key"}


@pytest.mark.asyncio
async def test_transmux_seek_av_alignment_flags():
    """Verifies that transmux seeking sets -noaccurate_seek in copy mode and avoids asetpts PTS gap/copyts desync."""
    captured_cmd = None

    async def mock_subprocess_exec(*cmd, **kwargs):
        nonlocal captured_cmd
        captured_cmd = list(cmd)
        mock_proc = MagicMock()
        mock_proc.stdout = AsyncMock()
        mock_proc.stdout.read = AsyncMock(side_effect=[b"fMP4data", b""])
        mock_proc.returncode = 0
        mock_proc.wait = AsyncMock(return_value=0)
        return mock_proc

    with patch("asyncio.create_subprocess_exec", side_effect=mock_subprocess_exec):
        gen = stream_transmuxed_video(
            source_url_or_path="http://127.0.0.1:8889/stream?info_hash=abc",
            start_seconds=360.0,
            transcode_video=False,
            burn_sub_idx=None,
        )
        async for chunk in gen:
            break

    assert captured_cmd is not None
    assert "-copyts" not in captured_cmd
    assert "-avoid_negative_ts" in captured_cmd
    assert "-noaccurate_seek" in captured_cmd
    # -noaccurate_seek must come before -i
    noacc_idx = captured_cmd.index("-noaccurate_seek")
    i_idx = captured_cmd.index("-i")
    assert noacc_idx < i_idx
    # asetpts=PTS-STARTPTS must NOT be present as it injects gaps before packet 1
    af_idx = captured_cmd.index("-af")
    assert "asetpts=PTS-STARTPTS" not in captured_cmd[af_idx + 1]
    assert "aresample=async=1" in captured_cmd[af_idx + 1]


@pytest.mark.asyncio
async def test_probe_keyframes_packet_based():
    """Verifies that probe_keyframes uses packet-level parsing without full video decoding."""
    captured_cmd = None

    async def mock_subprocess_exec(*cmd, **kwargs):
        nonlocal captured_cmd
        captured_cmd = list(cmd)
        mock_proc = MagicMock()
        mock_proc.communicate = AsyncMock(return_value=(b"0.000000,K__\n5.000000,K__\n10.000000,K__\n", b""))
        mock_proc.returncode = 0
        return mock_proc

    from core.transmuxer import probe_keyframes, get_keyframes_cache_path
    test_hash = "abcdefabcdefabcdefabcdefabcdefabcdefabcd"
    p = get_keyframes_cache_path(test_hash, 99)
    if os.path.isfile(p):
        try:
            os.remove(p)
        except OSError:
            pass

    try:
        with patch("asyncio.create_subprocess_exec", side_effect=mock_subprocess_exec):
            kfs = await probe_keyframes("http://127.0.0.1:8889/stream", test_hash, file_idx=99)

        assert captured_cmd is not None
        assert "-show_packets" in captured_cmd
        assert "-show_frames" not in captured_cmd
        assert kfs == [0.0, 5.0, 10.0]
    finally:
        if os.path.isfile(p):
            try:
                os.remove(p)
            except OSError:
                pass


def test_keyframe_snapping_on_transmux_seek():
    """Verifies that /transmux snaps start_time to nearest preceding keyframe."""
    test_hash = "1234567890123456789012345678901234567890"
    save_cached_keyframes(test_hash, 0, [0.0, 60.0, 120.0, 180.0, 240.0, 300.0, 354.2, 420.0])

    async def mock_gen(*args, **kwargs):
        yield b"chunk"

    try:
        with patch("routers.stream.ensure_streaming_daemon", new=AsyncMock(return_value=True)), \
             patch("routers.stream.warm_window", new=AsyncMock(return_value=True)), \
             patch("routers.stream.stream_transmuxed_video", side_effect=mock_gen):
            resp = client.get(
                f"/api/v1/stream/transmux?info_hash={test_hash}&file_idx=0&start_time=360.0&duration=6000",
                headers=AUTH_HEADERS,
            )
            assert resp.status_code == 200
            assert resp.headers.get("X-Evo-Seek-Keyframe") == "354.2"
    finally:
        from core.transmuxer import get_keyframes_cache_path
        p = get_keyframes_cache_path(test_hash, 0)
        if os.path.isfile(p):
            try:
                os.remove(p)
            except OSError:
                pass


def test_keyframe_snapping_does_not_snap_to_zero_when_sparse():
    """Verifies that /transmux does NOT snap seek to 0.0 when keyframes list is empty, sparse, or distant (> 15s)."""
    test_hash = "9876543210987654321098765432109876543210"
    save_cached_keyframes(test_hash, 0, [0.0])
    captured_start_seconds = None

    async def mock_gen(*args, **kwargs):
        nonlocal captured_start_seconds
        captured_start_seconds = kwargs.get("start_seconds")
        yield b"chunk"

    try:
        with patch("routers.stream.ensure_streaming_daemon", new=AsyncMock(return_value=True)), \
             patch("routers.stream.warm_window", new=AsyncMock(return_value=True)), \
             patch("routers.stream.stream_transmuxed_video", side_effect=mock_gen):
            resp = client.get(
                f"/api/v1/stream/transmux?info_hash={test_hash}&file_idx=0&start_time=360.0&duration=6000",
                headers=AUTH_HEADERS,
            )
            assert resp.status_code == 200
            # Must NOT snap to 0.0! Must preserve user's seek position 360.0
            assert captured_start_seconds == 360.0
            assert resp.headers.get("X-Evo-Seek-Keyframe") == "360.0"
    finally:
        from core.transmuxer import get_keyframes_cache_path
        p = get_keyframes_cache_path(test_hash, 0)
        if os.path.isfile(p):
            try:
                os.remove(p)
            except OSError:
                pass


def test_engine_sliding_window_critical_index_pieces():
    """Verifies that applySlidingWindow calls critical() on container index pieces at file end."""
    engine_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "streamer", "torrent_engine.js"))
    with open(engine_path, "r", encoding="utf-8") as f:
        content = f.read()

    assert "torrent.critical(indexStart, fileEndPiece)" in content
