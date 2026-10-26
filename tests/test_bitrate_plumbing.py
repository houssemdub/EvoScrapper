"""Executed tests for measured-bitrate plumbing: UI probe -> FastAPI -> daemon scheduler."""
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from main import app

client = TestClient(app)

HASH = "1" * 40
PROBE_OK = {
    "success": True,
    "duration": 2400.0,
    "size": 0,
    "bit_rate": 0,
    "video_codec": "hevc",
    "audio_codec": "eac3",
    "audio_tracks": [],
    "subtitle_tracks": [],
}


def test_warm_endpoint_forwards_duration_to_daemon_calls():
    """Both daemon calls issued by /warm must carry the measured duration."""
    captured = {}

    async def mock_warm_torrent(info_hash, file_idx=0, magnet=None, season=None, episode=None, duration=None, stage_seconds=None):
        captured["warm_torrent"] = {"file_idx": file_idx, "duration": duration, "stage_seconds": stage_seconds}
        return {"status": "warmed", "info_hash": info_hash}

    async def mock_warm_window(info_hash, file_idx=0, byte_offset=0, start_time=None, duration=None, buffer_mb=None, stage_seconds=None):
        captured["warm_window"] = {"byte_offset": byte_offset, "duration": duration, "buffer_mb": buffer_mb, "stage_seconds": stage_seconds}
        return True

    with patch("routers.stream.warm_torrent", side_effect=mock_warm_torrent), \
         patch("routers.stream.warm_window", side_effect=mock_warm_window):
        res = client.get(f"/api/v1/stream/warm?info_hash={HASH}&file_idx=3&duration=2400")

    assert res.status_code == 200, res.text
    assert captured["warm_torrent"]["duration"] == 2400
    assert captured["warm_torrent"]["file_idx"] == 3
    assert captured["warm_window"]["duration"] == 2400


def test_warm_endpoint_works_without_duration():
    """The duration parameter must stay optional (backward compatibility)."""
    captured = {}

    async def mock_warm_torrent(info_hash, file_idx=0, magnet=None, season=None, episode=None, duration=None, stage_seconds=None):
        captured["duration"] = duration
        return {"status": "warmed", "info_hash": info_hash}

    async def mock_warm_window(info_hash, file_idx=0, byte_offset=0, start_time=None, duration=None, buffer_mb=None, stage_seconds=None):
        return True

    with patch("routers.stream.warm_torrent", side_effect=mock_warm_torrent), \
         patch("routers.stream.warm_window", side_effect=mock_warm_window):
        res = client.get(f"/api/v1/stream/warm?info_hash={HASH}&file_idx=0")

    assert res.status_code == 200, res.text
    assert captured["duration"] is None


@pytest.mark.asyncio
async def test_probe_pushes_measured_duration_to_daemon():
    """A successful probe feeds its duration (and bitrate when known) into the daemon scheduler."""
    from routers.stream import probe_stream_metadata

    with patch("routers.stream.ensure_streaming_daemon", new=AsyncMock(return_value=True)), \
         patch("core.transmuxer.probe_media_stream", new=AsyncMock(return_value=dict(PROBE_OK))), \
         patch("core.torrent_streamer.push_stream_metadata", new=AsyncMock(return_value={"avg_bitrate_bps": 14316558})) as mock_push:
        result = await probe_stream_metadata(
            info_hash=HASH,
            file_idx=2,
            magnet=None,
            season=None,
            episode=None,
        )

    assert result["success"] is True
    mock_push.assert_awaited_once()
    args, kwargs = mock_push.await_args
    assert args[0] == HASH
    assert kwargs["file_idx"] == 2
    assert kwargs["duration"] == 2400.0
    # bit_rate was 0 in the probe: the daemon must derive bitrate from file length instead.
    assert kwargs["bitrate_bps"] is None


@pytest.mark.asyncio
async def test_probe_forwards_explicit_bitrate_when_measured():
    from routers.stream import probe_stream_metadata

    probe_payload = dict(PROBE_OK, bit_rate=21_000_000)
    with patch("routers.stream.ensure_streaming_daemon", new=AsyncMock(return_value=True)), \
         patch("core.transmuxer.probe_media_stream", new=AsyncMock(return_value=probe_payload)), \
         patch("core.torrent_streamer.push_stream_metadata", new=AsyncMock(return_value={})) as mock_push:
        await probe_stream_metadata(
            info_hash=HASH,
            file_idx=0,
            magnet=None,
            season=None,
            episode=None,
        )

    kwargs = mock_push.await_args.kwargs
    assert kwargs["duration"] == 2400.0
    assert kwargs["bitrate_bps"] == 21_000_000


@pytest.mark.asyncio
async def test_probe_skips_daemon_push_when_duration_unknown():
    from routers.stream import probe_stream_metadata

    probe_payload = dict(PROBE_OK, success=False, duration=0.0)
    with patch("routers.stream.ensure_streaming_daemon", new=AsyncMock(return_value=True)), \
         patch("core.transmuxer.probe_media_stream", new=AsyncMock(return_value=probe_payload)), \
         patch("core.torrent_streamer.push_stream_metadata", new=AsyncMock()) as mock_push:
        result = await probe_stream_metadata(
            info_hash=HASH,
            file_idx=0,
            magnet=None,
            season=None,
            episode=None,
        )

    assert result["success"] is False
    mock_push.assert_not_awaited()


def test_probe_endpoint_pushes_measured_duration_via_http():
    """End-to-end through the HTTP layer: /probe pushes duration into the daemon session."""
    with patch("routers.stream.ensure_streaming_daemon", new=AsyncMock(return_value=True)), \
         patch("core.transmuxer.probe_media_stream", new=AsyncMock(return_value=dict(PROBE_OK))), \
         patch("core.torrent_streamer.push_stream_metadata", new=AsyncMock(return_value={"avg_bitrate_bps": 14316558})):
        res = client.get(f"/api/v1/stream/probe?info_hash={HASH}&file_idx=0")

    assert res.status_code == 200, res.text
    assert res.json()["duration"] == 2400.0
