"""Regression seal for the 2026-10-26 18:41 `division by zero` crash on
/hls/playlist.m3u8: generate_hls_manifest must build a valid playlist for
every pathological keyframe shape and duration combination, and the route must
never return 500 for positive inputs."""
import sys
import os

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from core.transmuxer import generate_hls_manifest

HASH = "ab" * 20

PATHOLOGICAL_KEYFRAME_SETS = [
    [],                                  # no keyframes at all
    [0.0],                               # single keyframe
    [0.0, 0.0, 0.0],                     # duplicates at origin
    [0.0] + [float(i) for i in range(1, 200)],  # dense 1s keyframes
    [0.0, 7200.0],                       # keyframes only at both ends
    [5000.0, 8000.0, 12000.0],           # all keyframes beyond the duration
    [0.0, 0.5, 0.6, 0.7],                # micro-GOP cluster near origin
    [-10.0, 0.0, 30.0],                  # negative keyframe filtered out
    [float("nan"), float("inf"), 0.0, 30.0],  # non-finite entries
]

DURATIONS = [0.5, 6.0, 30.0, 123.456, 3600.0, 7200.0, 8699.607]


@pytest.mark.parametrize("keyframes", PATHOLOGICAL_KEYFRAME_SETS, ids=lambda kf: f"n={len(kf)}")
@pytest.mark.parametrize("duration", DURATIONS)
def test_manifest_never_raises_on_pathological_keyframe_shapes(keyframes, duration):
    manifest = generate_hls_manifest(
        info_hash=HASH,
        total_duration_sec=duration,
        segment_duration_sec=6.0,
        file_idx=0,
        keyframes=keyframes,
    )
    assert manifest.startswith("#EXTM3U")
    assert manifest.rstrip().endswith("#EXT-X-ENDLIST")
    # Every segment must carry a positive duration.
    for line in manifest.splitlines():
        if line.startswith("#EXTINF:"):
            assert float(line[len("#EXTINF:"):].rstrip(",")) > 0


def test_manifest_with_real_cached_keyframes_across_durations():
    """Mirrors the original crash reproduction: real probe data x mismatched durations."""
    import json
    from pathlib import Path

    keyframe_files = sorted(Path("data", "keyframes").glob("*.json"))
    if not keyframe_files:
        pytest.skip("no cached keyframes on this machine")
    for kf_file in keyframe_files:
        h, idx = kf_file.stem.rsplit("_", 1)
        kfs = json.loads(kf_file.read_text())
        for dur in (30.0, 600.0, 3600.0, max(kfs), max(kfs) * 0.5):
            manifest = generate_hls_manifest(
                info_hash=h, total_duration_sec=float(dur),
                segment_duration_sec=6.0, file_idx=int(idx), keyframes=kfs,
            )
            assert "#EXT-X-ENDLIST" in manifest


def test_playlist_route_serves_cached_keyframe_hash():
    """Route-level: the exact endpoint that crashed must 200 with playlist content."""
    from fastapi.testclient import TestClient
    from main import app

    client = TestClient(app)
    res = client.get(f"/api/v1/stream/hls/playlist.m3u8?info_hash={HASH}&duration=3600")
    assert res.status_code == 200
    assert res.text.startswith("#EXTM3U")


def test_playlist_route_rejects_invalid_durations():
    from fastapi.testclient import TestClient
    from main import app

    client = TestClient(app)
    for bad in ("0", "-5", "nan", "inf"):
        res = client.get(f"/api/v1/stream/hls/playlist.m3u8?info_hash={HASH}&duration={bad}")
        assert res.status_code in (400, 422), f"duration={bad} returned {res.status_code}"
