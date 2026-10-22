import pytest
from core.transmuxer import generate_hls_manifest


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
