import asyncio
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from core.file_matcher import select_target_file
from core.stream_resolver import compute_stream_score, is_same_show_title, matches_target_episode, resolve_streams
from core.torrent_streamer import is_daemon_healthy
from core.transmuxer import find_ffmpeg, find_vlc


def test_episode_matching():
    # Exact episode
    assert matches_target_episode("Breaking.Bad.S01E01.720p.BluRay.x264", 1, 1) is True
    assert matches_target_episode("Breaking.Bad.S01E01.720p.BluRay.x264", 1, 2) is False

    # Season pack
    assert matches_target_episode("Breaking.Bad.Season.1.Complete.1080p", 1, 1) is True
    assert matches_target_episode("Breaking.Bad.Season.2.Complete.1080p", 1, 1) is False

    # Anime absolute numbering
    assert matches_target_episode("[SubsPlease] Jujutsu Kaisen - 05 (1080p) [x264].mkv", 1, 5) is True

    # Title match boundary verification
    assert is_same_show_title("Fairy Tail", "FAIRY TAIL 100 YEARS QUEST S01E08") is False
    assert is_same_show_title("Fairy Tail", "[One Fansub] Fairy Tail: 100-nen Quest - S01") is False
    assert is_same_show_title("Fairy Tail", "Fairy Tail S01E08 1080p") is True
    assert is_same_show_title("Fairy Tail", "Fairy Tail 2009 2018 Season 1 8 Dual Audio") is True

    print("[+] Episode regex and title matching tests passed!")


def test_torrent_episode_file_matcher():
    """Verifies that complete series packs with movies, OVAs, OPs, and multiple seasons correctly auto-select the chosen episode."""
    test_files = [
        {"idx": 0, "path": "Fairy Tail Complete Series/Movies/Movie 02 - The Phoenix Priestess.mkv", "bytes": 2800000000},
        {"idx": 1, "path": "Fairy Tail Complete Series/OP and ED/OP 001 Snow fairy.mkv", "bytes": 50000000},
        {"idx": 2, "path": "Fairy Tail Complete Series/OP and ED/ED 001 Kanpeki.mkv", "bytes": 50000000},
        {"idx": 3, "path": "Fairy Tail Complete Series/Fairy Tail OVA/Fairy Tail - OVA 1.mkv", "bytes": 450000000},
        {"idx": 4, "path": "Fairy Tail Complete Series/Season 01/Fairy Tail - 001 - The Fairy Tail.mkv", "bytes": 700000000},
        {"idx": 5, "path": "Fairy Tail Complete Series/Season 01/Fairy Tail - 002 - Fire Dragon.mkv", "bytes": 700000000},
        {"idx": 6, "path": "Fairy Tail Complete Series/Season 02/Fairy Tail - 049 - Day of Encounter.mkv", "bytes": 700000000},
        {"idx": 7, "path": "Fairy Tail Complete Series/Season 02/Fairy Tail - 050 - Special Request.mkv", "bytes": 700000000},
    ]

    # S01E01 must select file 4 (not Movie 02 or OP 001)
    s1e1 = select_target_file(test_files, season=1, episode=1)
    assert s1e1 == 4, f"Expected idx 4, got {s1e1}"

    # S01E02 must select file 5
    s1e2 = select_target_file(test_files, season=1, episode=2)
    assert s1e2 == 5, f"Expected idx 5, got {s1e2}"

    # S02E01 must select file 6 (Episode 49)
    s2e1 = select_target_file(test_files, season=2, episode=1)
    assert s2e1 == 6, f"Expected idx 6, got {s2e1}"

    # S02E02 must select file 7 (Episode 50)
    s2e2 = select_target_file(test_files, season=2, episode=2)
    assert s2e2 == 7, f"Expected idx 7, got {s2e2}"

    # S00E01 (Specials/OVAs) must select file 3 (OVA 1)
    s0e1 = select_target_file(test_files, season=0, episode=1)
    assert s0e1 == 3, f"Expected idx 3, got {s0e1}"

    # Standard TV Series formatting
    tv_files = [
        {"idx": 0, "path": "Breaking Bad Season 1/Sample.mkv", "bytes": 10000000},
        {"idx": 1, "path": "Breaking Bad Season 1/Breaking.Bad.S01E01.Pilot.mkv", "bytes": 600000000},
        {"idx": 2, "path": "Breaking Bad Season 1/Breaking.Bad.S01E02.Cat.mkv", "bytes": 600000000},
        {"idx": 3, "path": "Breaking Bad Season 2/Breaking.Bad.S02E01.Seven.mkv", "bytes": 600000000},
    ]
    assert select_target_file(tv_files, season=1, episode=1) == 1
    assert select_target_file(tv_files, season=1, episode=2) == 2
    assert select_target_file(tv_files, season=2, episode=1) == 3

    print("[+] Torrent episode file matcher tests passed!")


def test_codec_tools_detection():
    vlc = find_vlc()
    assert vlc is not None, "VLC executable should be found"
    assert os.path.isfile(vlc), f"VLC path does not exist: {vlc}"
    print(f"[+] VLC detection passed: {vlc}")

    ffmpeg = find_ffmpeg()
    assert ffmpeg is not None, "FFmpeg executable should be found"
    assert os.path.isfile(ffmpeg), f"FFmpeg path does not exist: {ffmpeg}"
    print(f"[+] FFmpeg detection passed: {ffmpeg}")


async def test_stream_resolver_async():
    # Test resolving streams for a popular title
    res = await resolve_streams(
        title="Inception",
        imdb_id="tt1375666",
        year="2010",
        media_type="movie",
    )
    assert res is not None
    assert res.title == "Inception"
    assert len(res.streams) > 0, "Should resolve streams for Inception"
    top = res.streams[0]
    assert top.info_hash, "Stream item must have info_hash"
    assert top.name, "Stream item must have badge name"
    assert top.score > 0, "Stream item must have positive quality score"
    safe_name = top.name.encode('ascii', errors='backslashreplace').decode('ascii')
    print(f"[+] Stream resolver passed: {len(res.streams)} streams found for Inception in {res.resolved_time_ms}ms. Top: {safe_name} - {top.title} (Score: {top.score})")

    # Test Fairy Tail S01E08 stream resolution (confirming 100 Years Quest is filtered out)
    ft_res = await resolve_streams(
        title="Fairy Tail",
        imdb_id="tt1528406",
        season=1,
        episode=8,
        media_type="anime",
    )
    assert ft_res is not None
    # None of the streams should contain "100 Years Quest" or "100-nen Quest"
    for s in ft_res.streams:
        s_title_lower = s.title.lower()
        assert "100 years quest" not in s_title_lower and "100-nen" not in s_title_lower, f"Conflicting sequel found in Fairy Tail streams: {s.title}"
    print(f"[+] Fairy Tail S01E08 resolver passed: {len(ft_res.streams)} valid streams resolved without sequel conflicts!")

    # Test daemon health
    healthy = await is_daemon_healthy()
    print(f"[+] P2P Streaming Engine Daemon healthy: {healthy}")


def test_pgs_burn_in_and_sup_pipeline():
    """Verifies that the transmuxer and stream router support PGS burn-in and raw SUP streaming."""
    from core.transmuxer import extract_embedded_sup_stream, stream_transmuxed_video
    import inspect

    # Verify signature accepts burn_sub_idx
    sig = inspect.signature(stream_transmuxed_video)
    assert "burn_sub_idx" in sig.parameters

    # Verify extract_embedded_sup_stream exists and is an async generator function
    assert inspect.isasyncgenfunction(extract_embedded_sup_stream)

    # Verify route exists in router
    from routers.stream import router
    assert any(route.path.endswith("/subtitles/sup") for route in router.routes)
    assert any(route.path.endswith("/transmux") for route in router.routes)


if __name__ == "__main__":
    test_episode_matching()
    test_codec_tools_detection()
    asyncio.run(test_stream_resolver_async())
    print("[+] All streaming & playback backend tests passed!")
