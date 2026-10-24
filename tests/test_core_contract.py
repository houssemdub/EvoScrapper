import pytest
from core.torrent_streamer import canonical_hash, is_direct_streamable, get_internal_stream_url
from core.transmuxer import probe_media_stream, find_ffmpeg, find_ffprobe


def test_canonical_hash_normalization():
    """Test Case 1: Verifies normalization of 40-char hex, Base32, and invalid inputs."""
    # 40-char hex uppercase
    raw_hex = "4A5B6C7D8E9F0123456789ABCDEF0123456789AB"
    assert canonical_hash(raw_hex) == raw_hex.lower()

    # Magnet URI with 40-char hex BTIH
    magnet_hex = f"magnet:?xt=urn:btih:{raw_hex}&dn=Test"
    assert canonical_hash(magnet_hex) == raw_hex.lower()

    # Magnet URI with 32-char Base32 BTIH
    base32_hash = "JJVHE3S3GNEU6UKONM43R5V7V747T34K"
    magnet_b32 = f"magnet:?xt=urn:btih:{base32_hash}&dn=Test"
    expected_hex = "4a6a726e5b33494f514e6b39b8f6bfaff9f9ef8a"
    assert canonical_hash(magnet_b32) == expected_hex

    # Raw 32-char Base32 hash (without magnet prefix)
    assert canonical_hash(base32_hash) == expected_hex

    # Invalid and corrupt inputs must return None
    assert canonical_hash("invalid-hash-123") is None
    assert canonical_hash("") is None
    assert canonical_hash(None) is None


def test_is_direct_streamable_codec_and_container_rules():
    """Test Case 2: Deterministically classifies browser-native formats vs remux-required."""
    # Pure native MP4 / WebM
    assert is_direct_streamable("Movie.2024.1080p.WEBRip.x264.AAC.mp4") is True
    assert is_direct_streamable("BigBuckBunny.720p.webm") is True

    # Containers requiring remux
    assert is_direct_streamable("Movie.1080p.mkv") is False
    assert is_direct_streamable("OldRelease.avi") is False
    assert is_direct_streamable("Broadcast.ts") is False

    # Codecs requiring transcode/remux
    assert is_direct_streamable("Anime.Ep01.1080p.x265.10bit.mp4") is False
    assert is_direct_streamable("Movie.2160p.HEVC.mp4") is False

    # Multi-channel or unsupported audio requiring remux
    assert is_direct_streamable("Film.720p.BluRay.DTS.5.1.mp4") is False
    assert is_direct_streamable("Concert.TrueHD.Atmos.mp4") is False

    # Empty and None inputs
    assert is_direct_streamable("") is False
    assert is_direct_streamable(None) is False


def test_get_internal_stream_url_encoding():
    """Test Case 3: URL generation formatting and parameter safety."""
    url = get_internal_stream_url(
        info_hash="aabbccdd11223344",
        file_idx=2,
        magnet="magnet:?xt=urn:btih:aabbccdd11223344&dn=Title with spaces & symbols!",
        season=1,
        episode=5,
    )
    assert url.startswith("http://127.0.0.1:8889/stream?")
    assert "info_hash=aabbccdd11223344" in url
    assert "file_idx=2" in url
    assert "season=1" in url
    assert "episode=5" in url
    assert "Title%20with%20spaces%20%26%20symbols%21" in url


@pytest.mark.asyncio
async def test_probe_media_stream_error_containment():
    """Test Case 4: probe_media_stream guarantees complete dictionary contract on errors."""
    result = await probe_media_stream("http://127.0.0.1:99999/nonexistent.mkv")
    assert isinstance(result, dict)
    assert result["success"] is False
    assert result["duration"] == 0.0
    # Must guarantee the full contract schema even on failure
    for key in ("size", "bit_rate", "video_codec", "audio_codec", "audio_tracks", "subtitle_tracks", "error"):
        assert key in result, f"Missing required key '{key}' in failure response"


def test_transmuxer_binary_discovery():
    """Test Case 5: Binary resolution runs safely without throwing exceptions."""
    ffmpeg_res = find_ffmpeg()
    assert ffmpeg_res is None or isinstance(ffmpeg_res, str)
    ffprobe_res = find_ffprobe()
    assert ffprobe_res is None or isinstance(ffprobe_res, str)
