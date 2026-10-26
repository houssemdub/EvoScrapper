import asyncio
import os
import sys
from unittest.mock import AsyncMock, patch, MagicMock
import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from core.transmuxer import generate_hls_manifest, stream_hls_ts_segment, _HLS_SEMAPHORE, _hls_cache


def test_generate_hls_manifest_structure():
    info_hash = "c1205d5e0e64cc0aab4f7e60cfb669e4b477bc4c"
    manifest = generate_hls_manifest(
        info_hash=info_hash,
        total_duration_sec=120.0,
        segment_duration_sec=6.0,
        file_idx=0,
    )
    assert manifest.startswith("#EXTM3U")
    assert "#EXT-X-VERSION:3" in manifest
    assert "#EXT-X-TARGETDURATION:6" in manifest
    assert "#EXTINF:6.0," in manifest
    assert f"info_hash={info_hash}" in manifest
    assert "segment_idx=0" in manifest
    assert "#EXT-X-ENDLIST" in manifest


@pytest.mark.asyncio
async def test_hls_segment_cache_zero_spawns_on_second_request(tmp_path):
    """[STRM-HIGH-04] Asserts second request for the same HLS segment serves from cache with 0 FFmpeg spawns."""
    spawn_count = 0

    async def mock_subprocess_exec(*cmd, **kwargs):
        nonlocal spawn_count
        spawn_count += 1
        mock_proc = MagicMock()
        mock_proc.stdout = AsyncMock()
        mock_proc.stdout.read = AsyncMock(side_effect=[b"TS_CHUNK_MOCK", b""])
        mock_proc.returncode = 0
        mock_proc.wait = AsyncMock(return_value=0)
        return mock_proc

    # Point cache to temp directory for clean isolated test
    test_cache = str(tmp_path / "hls_cache")
    _hls_cache.cache_dir = test_cache
    os.makedirs(test_cache, exist_ok=True)

    source_url = "http://127.0.0.1:8889/stream?info_hash=aabbccddeeff00112233445566778899aabbccdd&file_idx=0"

    with patch("asyncio.create_subprocess_exec", side_effect=mock_subprocess_exec):
        # 1. First request: cache miss, spawns FFmpeg
        chunks1 = []
        async for c in stream_hls_ts_segment(source_url, start_seconds=12.0, duration_seconds=6.0, prefetch=False):
            chunks1.append(c)
        assert b"".join(chunks1) == b"TS_CHUNK_MOCK"
        assert spawn_count == 1, "First request must spawn 1 FFmpeg process on cache miss"

        # 2. Second request: cache hit, MUST serve from disk with ZERO spawns
        chunks2 = []
        async for c in stream_hls_ts_segment(source_url, start_seconds=12.0, duration_seconds=6.0, prefetch=False):
            chunks2.append(c)
        assert b"".join(chunks2) == b"TS_CHUNK_MOCK"
        assert spawn_count == 1, "Second request MUST be served from cache with ZERO new FFmpeg spawns"


@pytest.mark.asyncio
async def test_hls_prefetch_muxes_lookahead_segments_concurrently(tmp_path, monkeypatch):
    """The 1-3 lookahead segments must mux concurrently so a post-seek buffer
    refills in a fraction of the sequential time."""
    import core.transmuxer as tm
    from core.transmuxer import HlsSegmentCache

    monkeypatch.setattr(tm, "_hls_cache", HlsSegmentCache(cache_dir=str(tmp_path / "hls_cache")))

    events = {"active": 0, "max_active": 0, "starts": []}

    async def fake_segment_chunks(source_url_or_path, start_seconds, duration_seconds, chunk_size, segment_format):
        events["active"] += 1
        events["max_active"] = max(events["max_active"], events["active"])
        events["starts"].append(start_seconds)
        await asyncio.sleep(0.02)
        events["active"] -= 1
        yield b"segment-data"

    monkeypatch.setattr(tm, "_segment_chunks", fake_segment_chunks)

    unique_source = f"http://127.0.0.1:8889/stream?info_hash={'d' * 40}&file_idx=0"
    tm._trigger_hls_prefetch(unique_source, 0.0, 6.0, "ts")

    tasks = list(tm._PREFETCH_TASKS)
    assert tasks, "prefetch did not schedule any background work"
    await asyncio.gather(*tasks)

    assert sorted(events["starts"]) == [6.0, 12.0, 18.0], f"wrong lookahead starts: {events['starts']}"
    assert events["max_active"] >= 2, (
        f"lookahead segments muxed sequentially (max concurrent = {events['max_active']})"
    )


@pytest.mark.asyncio
async def test_hls_muxer_concurrency_bounded_to_semaphore(tmp_path):
    """[STRM-HIGH-04] Asserts 15 concurrent HLS segment requests never exceed bounded concurrency."""
    current_active = 0
    max_active = 0

    async def mock_subprocess_exec(*cmd, **kwargs):
        nonlocal current_active, max_active
        current_active += 1
        if current_active > max_active:
            max_active = current_active
        await asyncio.sleep(0.05)
        current_active -= 1

        mock_proc = MagicMock()
        mock_proc.stdout = AsyncMock()
        mock_proc.stdout.read = AsyncMock(side_effect=[b"TS_DATA", b""])
        mock_proc.returncode = 0
        mock_proc.wait = AsyncMock(return_value=0)
        return mock_proc

    test_cache = str(tmp_path / "hls_cache_stress")
    _hls_cache.cache_dir = test_cache
    os.makedirs(test_cache, exist_ok=True)

    with patch("asyncio.create_subprocess_exec", side_effect=mock_subprocess_exec):
        tasks = []
        for i in range(15):
            url = f"http://127.0.0.1:8889/stream?info_hash=11223344556677889900aabbccddeeff00112233&file_idx={i}"
            async def consume(u, s):
                async for _ in stream_hls_ts_segment(u, start_seconds=s, duration_seconds=6.0):
                    pass
            tasks.append(consume(url, float(i * 6)))

        await asyncio.gather(*tasks)

    # Must be bounded by _HLS_SEMAPHORE._value (default 3)
    assert max_active <= 3, f"Peak concurrent FFmpeg instances was {max_active}, must be <= 3"
