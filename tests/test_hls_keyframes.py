import os
import pytest
from core.transmuxer import (
    generate_hls_manifest,
    load_cached_keyframes,
    save_cached_keyframes,
    get_keyframes_cache_path,
)


def test_manifest_snaps_to_keyframes():
    """Verifies that generate_hls_manifest snaps EXTINF boundaries to nearest keyframes."""
    info_hash = "abcdef0123456789abcdef0123456789abcdef01"
    # Target 6.0s segments: keyframes at 0, 5.8, 11.9, 17.8, 24.0
    keyframes = [0.0, 5.8, 11.9, 17.8, 24.0]

    manifest = generate_hls_manifest(
        info_hash=info_hash,
        total_duration_sec=24.0,
        segment_duration_sec=6.0,
        file_idx=0,
        keyframes=keyframes,
    )

    # Segments should snap to keyframes:
    # Seg 0: 0.0 -> 5.8 (duration 5.8)
    # Seg 1: 5.8 -> 11.9 (duration 6.1)
    # Seg 2: 11.9 -> 17.8 (duration 5.9)
    # Seg 3: 17.8 -> 24.0 (duration 6.2)
    assert "#EXTINF:5.8," in manifest
    assert "#EXTINF:6.1," in manifest
    assert "#EXTINF:5.9," in manifest
    assert "#EXTINF:6.2," in manifest
    assert "start=0.00" in manifest
    assert "start=5.80" in manifest
    assert "start=11.90" in manifest
    assert "start=17.80" in manifest


def test_manifest_fallback_when_no_keyframes():
    """Verifies that generate_hls_manifest cleanly falls back to fixed 6.0s intervals when keyframes are absent."""
    info_hash = "0000000000000000000000000000000000000000"
    manifest = generate_hls_manifest(
        info_hash=info_hash,
        total_duration_sec=18.0,
        segment_duration_sec=6.0,
        file_idx=0,
        keyframes=None,
    )

    assert "#EXT-X-VERSION:3" in manifest
    assert "#EXTINF:6.0," in manifest
    assert "start=0.00" in manifest
    assert "start=6.00" in manifest
    assert "start=12.00" in manifest


def test_keyframe_cache_persistence(tmp_path, monkeypatch):
    """Verifies that save_cached_keyframes persists to disk and load_cached_keyframes retrieves it."""
    test_dir = str(tmp_path / "keyframes")
    import core.transmuxer as tx
    monkeypatch.setattr(tx, "KEYFRAMES_DIR", test_dir)

    info_hash = "fedcba9876543210fedcba9876543210fedcba98"
    file_idx = 1
    sample_kf = [0.0, 4.85, 9.72, 14.58]

    # Initially not present
    assert load_cached_keyframes(info_hash, file_idx) is None

    # Save and reload
    save_cached_keyframes(info_hash, file_idx, sample_kf)
    loaded = load_cached_keyframes(info_hash, file_idx)
    assert loaded == sample_kf


def test_manifest_prefer_fmp4():
    """Verifies that prefer_fmp4 includes #EXT-X-MAP:URI and version 7."""
    info_hash = "1234567890123456789012345678901234567890"
    manifest = generate_hls_manifest(
        info_hash=info_hash,
        total_duration_sec=12.0,
        segment_duration_sec=6.0,
        file_idx=0,
        prefer_fmp4=True,
    )

    assert "#EXT-X-VERSION:7" in manifest
    assert '#EXT-X-MAP:URI="/api/v1/stream/hls/init.mp4' in manifest
    assert "format=fmp4" in manifest
