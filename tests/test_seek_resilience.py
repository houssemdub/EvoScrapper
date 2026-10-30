import os
import shutil
import subprocess
import textwrap
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
            assert "X-Evo-Seek-Keyframe" not in resp.headers
    finally:
        from core.transmuxer import get_keyframes_cache_path
        p = get_keyframes_cache_path(test_hash, 0)
        if os.path.isfile(p):
            try:
                os.remove(p)
            except OSError:
                pass


def test_engine_sliding_window_critical_index_pieces():
    """Verifies that applySlidingWindow marks container index pieces at file end as critical."""
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js binary not found on system")

    script = textwrap.dedent(
        """
        import { makeEngine, makeTorrent, makeFile, installSession, check } from './tests/node/engine_harness.mjs';

        const engine = makeEngine();
        const { torrent, calls } = makeTorrent();
        const file = makeFile();
        installSession(engine, torrent);

        engine.applySlidingWindow(torrent, file, 0, { avgBitrateBps: 8000000 });

        const tail = calls.critical.find(call => call.end === 4095);
        check(tail, `missing critical tail range: ${JSON.stringify(calls.critical)}`);
        check(tail.start === 4094, `expected last two pieces critical: ${JSON.stringify(tail)}`);
        process.exit(0);
        """
    )
    result = subprocess.run(
        [node, "--input-type=module"],
        input=script,
        capture_output=True,
        text=True,
        timeout=20,
        cwd=os.path.abspath(os.path.join(os.path.dirname(__file__), "..")),
    )
    assert result.returncode == 0, f"{result.stdout}\n{result.stderr}"


def test_transmux_head_request_returns_keyframe():
    """Verifies that HEAD /transmux returns 200 with X-Evo-Seek-Keyframe without launching ffmpeg generator."""
    test_hash = "head123456789012345678901234567890123456"
    save_cached_keyframes(test_hash, 0, [0.0, 31.823, 37.246, 42.668])

    try:
        with patch("routers.stream.ensure_streaming_daemon", new=AsyncMock(return_value=True)), \
             patch("routers.stream.warm_window", new=AsyncMock(return_value=True)):
            resp = client.head(
                f"/api/v1/stream/transmux?info_hash={test_hash}&file_idx=0&start_time=37.0&duration=6000",
                headers=AUTH_HEADERS,
            )
            assert resp.status_code == 200
            assert resp.headers.get("X-Evo-Seek-Keyframe") == "31.823"
            assert "X-Evo-Seek-Keyframe" in resp.headers.get("Access-Control-Expose-Headers", "")
    finally:
        from core.transmuxer import get_keyframes_cache_path
        p = get_keyframes_cache_path(test_hash, 0)
        if os.path.isfile(p):
            try:
                os.remove(p)
            except OSError:
                pass


@pytest.mark.asyncio
async def test_probe_keyframes_near_read_intervals():
    """Verifies that probe_keyframes_near queries ffprobe with -read_intervals around target_time."""
    captured_cmd = None

    async def mock_subprocess_exec(*cmd, **kwargs):
        nonlocal captured_cmd
        captured_cmd = list(cmd)
        mock_proc = MagicMock()
        mock_proc.communicate = AsyncMock(return_value=(b"23.106000,K__\n31.989000,K__\n37.412000,K__\n", b""))
        mock_proc.returncode = 0
        return mock_proc

    from core.transmuxer import probe_keyframes_near, get_keyframes_cache_path
    test_hash = "near123456789012345678901234567890123456"
    p = get_keyframes_cache_path(test_hash, 0)
    if os.path.isfile(p):
        try:
            os.remove(p)
        except OSError:
            pass

    try:
        with patch("asyncio.create_subprocess_exec", side_effect=mock_subprocess_exec):
            kfs = await probe_keyframes_near(
                "http://127.0.0.1:8889/stream",
                test_hash,
                file_idx=0,
                target_time=37.0,
            )
        assert captured_cmd is not None
        assert "-read_intervals" in captured_cmd
        int_idx = captured_cmd.index("-read_intervals")
        # Target is 37.0, window should be [12.00%47.00]
        assert "12.00%47.00" in captured_cmd[int_idx + 1]
        assert 31.989 in kfs
    finally:
        if os.path.isfile(p):
            try:
                os.remove(p)
            except OSError:
                pass


@pytest.mark.asyncio
async def test_probe_keyframes_normalizes_container_start():
    """R1: Verifies probe_keyframes normalizes raw PTS by subtracting container start_time."""
    from core.transmuxer import probe_keyframes, get_keyframes_cache_path, load_cached_keyframes
    test_hash = "r1norm1234567890123456789012345678901234"
    p = get_keyframes_cache_path(test_hash, 0)
    if os.path.isfile(p):
        try:
            os.remove(p)
        except OSError:
            pass

    async def mock_subprocess_exec(*cmd, **kwargs):
        mock_proc = MagicMock()
        cmd_str = " ".join(cmd)
        if "format=start_time" in cmd_str:
            mock_proc.communicate = AsyncMock(return_value=(b'{"format": {"start_time": "1.400000"}}', b""))
        else:
            # Raw packets: keyframes at 2.8, 6.4, 11.4
            mock_proc.communicate = AsyncMock(return_value=(b"2.800000,K__\n6.400000,K__\n11.400000,K__\n", b""))
        mock_proc.returncode = 0
        return mock_proc

    try:
        with patch("asyncio.create_subprocess_exec", side_effect=mock_subprocess_exec):
            kfs = await probe_keyframes("http://127.0.0.1:8889/stream", test_hash, file_idx=0)

        # Content time: 2.8 - 1.4 = 1.4; 6.4 - 1.4 = 5.0; 11.4 - 1.4 = 10.0
        # First cached keyframe after 0.0 is raw pts - 1.4 = 1.4
        cached = load_cached_keyframes(test_hash, 0)
        assert cached is not None
        non_zero = [k for k in cached if k > 0]
        assert non_zero[0] == round(2.8 - 1.4, 3)
        assert cached == [0.0, 1.4, 5.0, 10.0]
    finally:
        if os.path.isfile(p):
            try:
                os.remove(p)
            except OSError:
                pass


@pytest.mark.asyncio
async def test_probe_keyframes_timeout_not_cached():
    """R2: Verifies that probe timeout does not poison the persistent keyframe cache."""
    from core.transmuxer import probe_keyframes, get_keyframes_cache_path, load_cached_keyframes
    test_hash = "r2timeout1234567890123456789012345678901"
    p = get_keyframes_cache_path(test_hash, 0)
    if os.path.isfile(p):
        try:
            os.remove(p)
        except OSError:
            pass

    async def mock_subprocess_exec(*cmd, **kwargs):
        mock_proc = MagicMock()
        async def slow_communicate():
            await asyncio.sleep(5.0)
            return (b"0.000000,K__\n5.000000,K__\n", b"")
        mock_proc.communicate = slow_communicate
        mock_proc.kill = MagicMock()
        mock_proc.returncode = None
        return mock_proc

    try:
        with patch("asyncio.create_subprocess_exec", side_effect=mock_subprocess_exec):
            await probe_keyframes("http://127.0.0.1:8889/stream", test_hash, file_idx=0, timeout=0.05)

        # Cache must NOT have been saved
        assert load_cached_keyframes(test_hash, 0) is None
    finally:
        if os.path.isfile(p):
            try:
                os.remove(p)
            except OSError:
                pass


def test_transmux_route_header_honesty_on_snap():
    """R3: Verifies X-Evo-Seek-Keyframe is present when keyframe <= 15s found, absent otherwise."""
    test_hash = "r3snap1234567890123456789012345678901234"
    from core.transmuxer import save_cached_keyframes, get_keyframes_cache_path
    save_cached_keyframes(test_hash, 0, [0.0, 50.0, 100.0])
    p = get_keyframes_cache_path(test_hash, 0)

    try:
        with patch("routers.stream.ensure_streaming_daemon", new=AsyncMock(return_value=True)), \
             patch("routers.stream.warm_window", new=AsyncMock(return_value=True)):
            # Case A: seek to 58.0 -> keyframe at 50.0 is within 8.0s (<= 15s)
            resp_found = client.head(
                f"/api/v1/stream/transmux?info_hash={test_hash}&file_idx=0&start_time=58.0",
                headers=AUTH_HEADERS,
            )
            assert resp_found.status_code == 200
            assert resp_found.headers.get("X-Evo-Seek-Keyframe") == "50.0"

            # Case B: seek to 80.0 -> preceding keyframe is 50.0, gap is 30s (> 15s), probe finds nothing
            with patch("core.transmuxer.probe_keyframes_near", new=AsyncMock(return_value=[])):
                resp_none = client.head(
                    f"/api/v1/stream/transmux?info_hash={test_hash}&file_idx=0&start_time=80.0",
                    headers=AUTH_HEADERS,
                )
                assert resp_none.status_code == 200
                assert "X-Evo-Seek-Keyframe" not in resp_none.headers
    finally:
        if os.path.isfile(p):
            try:
                os.remove(p)
            except OSError:
                pass


def test_cache_version_invalidates_legacy_caches(tmp_path, monkeypatch):
    """R1: Verifies new cache version invalidates legacy unversioned/raw list caches."""
    import json
    import core.transmuxer as tx
    monkeypatch.setattr(tx, "KEYFRAMES_DIR", str(tmp_path / "keyframes"))
    os.makedirs(str(tmp_path / "keyframes"), exist_ok=True)

    info_hash = "legacy1234567890123456789012345678901234"
    file_idx = 0
    legacy_path = tx.get_keyframes_cache_path(info_hash, file_idx)

    # Write legacy format (raw JSON list of floats)
    with open(legacy_path, "w", encoding="utf-8") as f:
        json.dump([0.0, 10.0, 20.0], f)

    # Must be discarded
    assert tx.load_cached_keyframes(info_hash, file_idx) is None

    # Save with v2 format
    tx.save_cached_keyframes(info_hash, file_idx, [0.0, 8.6, 18.6], container_start=1.4)
    loaded = tx.load_cached_keyframes(info_hash, file_idx)
    assert loaded == [0.0, 8.6, 18.6]

    data = tx.load_cached_keyframes_data(info_hash, file_idx)
    assert data is not None
    assert data["version"] == 2
    assert data["container_start"] == 1.4



def test_shift_vtt_timestamps_normalizes_to_content_time():
    """Contract: shift_vtt_timestamps subtracts container_start, clamps to 0.0, and preserves cue settings."""
    from core.transmuxer import shift_vtt_timestamps

    raw_vtt = """WEBVTT

00:00:11.400 --> 00:00:13.400
Hello World

00:01:05.50 --> 00:01:08.50 line:90% position:50%
Second line
"""
    shifted = shift_vtt_timestamps(raw_vtt, 1.4)
    assert "00:10.000 --> 00:12.000" in shifted or "00:00:10.000 --> 00:00:12.000" in shifted
    assert "Hello World" in shifted
    assert "line:90% position:50%" in shifted
    # Check clamping to 0.0 when start < offset
    early_vtt = "WEBVTT\n\n00:00:00.500 --> 00:00:02.000\nEarly cue\n"
    shifted_early = shift_vtt_timestamps(early_vtt, 1.4)
    assert "00:00.000 --> 00:00.600" in shifted_early or "00:00:00.000 --> 00:00:00.600" in shifted_early


def test_extract_embedded_subtitles_subtracts_container_start(monkeypatch):
    """Contract: extract_embedded_subtitle_vtt normalizes raw container timestamps by subtracting container_start."""
    import asyncio
    from core import transmuxer as tx

    raw_ffmpeg_vtt = b"""WEBVTT

00:00:11.400 --> 00:00:13.400
Dialogue at PTS 11.4
"""

    async def fake_subprocess_exec(*args, **kwargs):
        class FakeProc:
            returncode = 0
            async def communicate(self):
                return raw_ffmpeg_vtt, b""
            def kill(self):
                pass
        return FakeProc()

    async def fake_probe_container_start(url, timeout=3.0):
        return 1.4

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_subprocess_exec)
    monkeypatch.setattr(tx, "probe_container_start", fake_probe_container_start)

    result = asyncio.run(tx.extract_embedded_subtitle_vtt("http://fake/stream", sub_stream_index=0))
    # 11.4 - 1.4 = 10.0
    assert "00:10.000 --> 00:12.000" in result or "00:00:10.000 --> 00:00:12.000" in result
    assert "Dialogue at PTS 11.4" in result
