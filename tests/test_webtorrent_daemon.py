import pytest
from core.torrent_streamer import (
    canonical_hash,
    get_internal_stream_url,
    is_daemon_healthy,
    get_daemon_status,
    STREAM_PORT,
    DAEMON_URL,
)


def test_canonical_hash_parsing():
    # Test raw 40-char SHA1 hex
    raw_hash = "c1205d5e0e64cc0aab4f7e60cfb669e4b477bc4c"
    assert canonical_hash(raw_hash) == raw_hash.lower()

    # Test standard magnet link
    magnet = f"magnet:?xt=urn:btih:{raw_hash}&dn=Ubuntu+ISO"
    assert canonical_hash(magnet) == raw_hash.lower()

    # Test base32 magnet link
    b32_magnet = "magnet:?xt=urn:btih:4EQF2XQOMTHQUK2PQ5QM7NTEE22HO7CM"
    b32_hash = canonical_hash(b32_magnet)
    assert len(b32_hash) == 40
    assert b32_hash.isalnum()


def test_internal_stream_url_formatting():
    info_hash = "c1205d5e0e64cc0aab4f7e60cfb669e4b477bc4c"
    url = get_internal_stream_url(
        info_hash=info_hash,
        file_idx=2,
        magnet=f"magnet:?xt=urn:btih:{info_hash}",
        season=1,
        episode=5,
    )
    assert f"info_hash={info_hash}" in url
    assert "file_idx=2" in url
    assert "season=1" in url
    assert "episode=5" in url
    assert url.startswith(DAEMON_URL)


@pytest.mark.asyncio
async def test_daemon_status_contract():
    # If daemon is offline, returns standard offline dictionary structure
    status = await get_daemon_status()
    assert isinstance(status, dict)
    assert "status" in status
    assert "active_torrents" in status
    assert "sessions" in status
