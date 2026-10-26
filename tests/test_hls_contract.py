import math
import shutil
import struct
import subprocess

import pytest
from fastapi.testclient import TestClient

from core.transmuxer import (
    _hls_cache,
    generate_hls_manifest,
    stream_hls_fmp4_init,
    stream_hls_ts_segment,
)
from main import app
from routers import stream as stream_router


AUTH_HEADERS = {"X-API-Key": "test_key"}
INFO_HASH = "c1205d5e0e64cc0aab4f7e60cfb669e4b477bc4c"


def top_level_boxes(data):
    boxes = []
    offset = 0
    while offset + 8 <= len(data):
        size = struct.unpack(">I", data[offset:offset + 4])[0]
        box_type = data[offset + 4:offset + 8].decode("latin1")
        header = 8
        if size == 1:
            size = struct.unpack(">Q", data[offset + 8:offset + 16])[0]
            header = 16
        if size < header or offset + size > len(data):
            break
        boxes.append((box_type, offset, size, header))
        offset += size
    assert offset == len(data), f"unparsed trailing bytes at {offset}/{len(data)}"
    return boxes


def child_boxes(data, start, end):
    offset = start
    while offset + 8 <= end:
        size = struct.unpack(">I", data[offset:offset + 4])[0]
        box_type = data[offset + 4:offset + 8].decode("latin1")
        header = 8
        if size == 1:
            size = struct.unpack(">Q", data[offset + 8:offset + 16])[0]
            header = 16
        if size < header or offset + size > end:
            break
        yield box_type, offset, size, header
        offset += size


def track_timescales(init_bytes):
    result = {}
    for box_type, offset, size, header in top_level_boxes(init_bytes):
        if box_type != "moov":
            continue
        for trak_type, trak_offset, trak_size, trak_header in child_boxes(
            init_bytes, offset + header, offset + size
        ):
            if trak_type != "trak":
                continue
            track_id = None
            timescale = None
            for child_type, child_offset, child_size, child_header in child_boxes(
                init_bytes, trak_offset + trak_header, trak_offset + trak_size
            ):
                payload = child_offset + child_header
                if child_type == "tkhd":
                    version = init_bytes[payload]
                    track_id = struct.unpack(
                        ">I", init_bytes[payload + (12 if version == 0 else 20):][:4]
                    )[0]
                elif child_type == "mdia":
                    for mdia_type, mdia_offset, mdia_size, mdia_header in child_boxes(
                        init_bytes, child_offset + child_header, child_offset + child_size
                    ):
                        if mdia_type != "mdhd":
                            continue
                        mdhd_payload = mdia_offset + mdia_header
                        version = init_bytes[mdhd_payload]
                        ts_offset = mdhd_payload + (12 if version == 0 else 20)
                        timescale = struct.unpack(">I", init_bytes[ts_offset:ts_offset + 4])[0]
            if track_id is not None and timescale:
                result[track_id] = timescale
    return result


def moof_tfdt_pairs(data):
    pairs = []
    for box_type, offset, size, header in top_level_boxes(data):
        if box_type != "moof":
            continue
        for traf_type, traf_offset, traf_size, traf_header in child_boxes(
            data, offset + header, offset + size
        ):
            if traf_type != "traf":
                continue
            track_id = None
            for child_type, child_offset, child_size, child_header in child_boxes(
                data, traf_offset + traf_header, traf_offset + traf_size
            ):
                payload = child_offset + child_header
                if child_type == "tfhd":
                    track_id = struct.unpack(">I", data[payload + 4:payload + 8])[0]
                elif child_type == "tfdt" and track_id is not None:
                    version = data[payload]
                    if version == 1:
                        value = struct.unpack(">Q", data[payload + 4:payload + 12])[0]
                    else:
                        value = struct.unpack(">I", data[payload + 4:payload + 8])[0]
                    pairs.append((track_id, value))
    return pairs


@pytest.fixture(scope="module")
def local_video(tmp_path_factory):
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        pytest.skip("ffmpeg is required for HLS byte-contract tests")
    target = tmp_path_factory.mktemp("hls_contract") / "fixture.mp4"
    subprocess.run(
        [
            ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-i", "testsrc2=size=160x120:rate=25",
            "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000",
            "-t", "4", "-c:v", "libx264", "-preset", "ultrafast",
            "-g", "25", "-keyint_min", "25", "-sc_threshold", "0",
            "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "64k",
            str(target),
        ],
        check=True,
        capture_output=True,
    )
    return str(target)


def test_manifest_includes_trailing_partial_segment():
    manifest = generate_hls_manifest(
        info_hash=INFO_HASH,
        total_duration_sec=13.0,
        segment_duration_sec=6.0,
        file_idx=0,
        keyframes=[],
    )

    assert "#EXTINF:6.0," in manifest
    assert "#EXTINF:1.0," in manifest
    assert "start=12.00" in manifest
    assert manifest.count("#EXTINF:") == 3


@pytest.mark.parametrize("duration", [0.0, -1.0, math.nan, math.inf])
@pytest.mark.parametrize("field", ["total_duration_sec", "segment_duration_sec"])
def test_manifest_rejects_invalid_durations(field, duration):
    kwargs = {"total_duration_sec": 13.0, "segment_duration_sec": 6.0, field: duration}
    with pytest.raises(ValueError):
        generate_hls_manifest(info_hash=INFO_HASH, file_idx=0, keyframes=[], **kwargs)


@pytest.mark.parametrize("field", ["duration", "segment_duration"])
@pytest.mark.parametrize("value", ["0", "-1", "nan", "inf"])
def test_playlist_route_rejects_invalid_durations(field, value):
    response = TestClient(app).get(
        "/api/v1/stream/hls/playlist.m3u8",
        params={"info_hash": INFO_HASH, field: value},
        headers=AUTH_HEADERS,
    )
    assert response.status_code == 422


async def test_fmp4_init_contains_only_initialization_boxes(local_video, tmp_path, monkeypatch):
    monkeypatch.setattr(_hls_cache, "cache_dir", str(tmp_path))
    data = b"".join([chunk async for chunk in stream_hls_fmp4_init(local_video)])
    types = [box_type for box_type, _, _, _ in top_level_boxes(data)]

    assert types == ["ftyp", "moov"]
    assert track_timescales(data)


async def test_fmp4_media_segment_excludes_init_and_offsets_tfdt(local_video, tmp_path, monkeypatch):
    monkeypatch.setattr(_hls_cache, "cache_dir", str(tmp_path))
    init = b"".join([chunk async for chunk in stream_hls_fmp4_init(local_video)])
    timescales = track_timescales(init)

    start = 2.0
    media = b"".join([
        chunk async for chunk in stream_hls_ts_segment(
            local_video,
            start_seconds=start,
            duration_seconds=1.0,
            segment_format="fmp4",
            prefetch=False,
        )
    ])
    types = [box_type for box_type, _, _, _ in top_level_boxes(media)]

    assert "ftyp" not in types and "moov" not in types and "mfra" not in types
    assert "moof" in types and "mdat" in types

    first_tfdt = {}
    for track_id, decode_time in moof_tfdt_pairs(media):
        first_tfdt.setdefault(track_id, decode_time)
    assert first_tfdt
    for track_id, decode_time in first_tfdt.items():
        assert decode_time == round(start * timescales[track_id])


async def test_ts_and_fmp4_cache_entries_do_not_collide(local_video, tmp_path, monkeypatch):
    monkeypatch.setattr(_hls_cache, "cache_dir", str(tmp_path))
    kwargs = dict(start_seconds=0.0, duration_seconds=1.0, prefetch=False)

    ts = b"".join([chunk async for chunk in stream_hls_ts_segment(local_video, **kwargs)])
    fmp4 = b"".join([
        chunk async for chunk in stream_hls_ts_segment(
            local_video, segment_format="fmp4", **kwargs
        )
    ])

    assert ts[:1] == b"\x47"
    assert [box_type for box_type, _, _, _ in top_level_boxes(fmp4) if box_type == "moof"]
    assert ts != fmp4


def test_segment_route_serves_advertised_format(monkeypatch):
    calls = []

    async def fake_segment(source, start_seconds=0.0, duration_seconds=6.0, segment_format="ts", **kwargs):
        calls.append(segment_format)
        yield b"segment"

    async def fake_init(source):
        yield b"init"

    monkeypatch.setattr(stream_router, "stream_hls_ts_segment", fake_segment)
    monkeypatch.setattr(stream_router, "stream_hls_fmp4_init", fake_init)
    client = TestClient(app)

    ts_response = client.get(
        "/api/v1/stream/hls/segment",
        params={"info_hash": INFO_HASH, "format": "ts"},
        headers=AUTH_HEADERS,
    )
    fmp4_response = client.get(
        "/api/v1/stream/hls/segment",
        params={"info_hash": INFO_HASH, "format": "fmp4"},
        headers=AUTH_HEADERS,
    )
    init_response = client.get(
        "/api/v1/stream/hls/init.mp4",
        params={"info_hash": INFO_HASH},
        headers=AUTH_HEADERS,
    )

    assert ts_response.headers["content-type"].startswith("video/mp2t")
    assert fmp4_response.headers["content-type"].startswith("video/mp4")
    assert init_response.headers["content-type"].startswith("video/mp4")
    assert calls == ["ts", "fmp4"]
