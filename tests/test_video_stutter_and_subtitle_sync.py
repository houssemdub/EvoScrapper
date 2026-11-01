"""
tests/test_video_stutter_and_subtitle_sync.py
Automated verification tests for Initial Video Stutter & Subtitle/Audio Desync fixes.
Covers:
- Phase 2: FFmpeg A/V clock alignment, B-frame DTS/PTS, 10MB head/2MB tail piece prioritization, startup buffer gate.
- Phase 3: Embedded/hash bypass, speech bandpass VAD filter, watermark/credit cue filtering, offset clamping > 8.0s,
  consistent embedded subtitle extraction timestamps, and text track cue alignment.
"""
import inspect
import os
import re
import pytest
from unittest.mock import AsyncMock, patch

from core.subtitle_sync.consensus import ConsensusSync, SyncCandidate
from core.subtitle_sync.engine import SubtitleSyncEngine
from core.subtitle_sync.forced_subs import detect_forced_subtitles, filter_for_sync
from core.transmuxer import (
    _build_hls_ffmpeg_cmd,
    extract_embedded_subtitle_vtt,
    stream_transmuxed_video,
)


# ---------------------------------------------------------------------------
# Phase 2: Initial Video Stutter & A/V Clock Alignment
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_transmuxer_flags_and_audio_clock_alignment():
    """Task 2.1: Verify FFmpeg command builder for transmuxing includes exact input flags, probing, and zero-delay flags."""
    captured_cmd = None

    async def mock_subprocess_exec(*cmd, **kwargs):
        nonlocal captured_cmd
        captured_cmd = list(cmd)
        mock_proc = AsyncMock()
        mock_proc.returncode = 0
        mock_proc.stdout.read = AsyncMock(side_effect=[b"fake_mp4_bytes", b""])
        mock_proc.stderr.readline = AsyncMock(return_value=b"")
        mock_proc.wait = AsyncMock(return_value=0)
        return mock_proc

    with patch("asyncio.create_subprocess_exec", side_effect=mock_subprocess_exec):
        gen = stream_transmuxed_video("http://127.0.0.1:8889/stream/test.mkv", start_seconds=12.5)
        async for _ in gen:
            break

    assert captured_cmd is not None
    cmd_str = " ".join(captured_cmd)

    # 1. Input flags and probing
    assert "+genpts+discardcorrupt+igndts" in cmd_str
    assert "-analyzeduration 5000000" in cmd_str
    assert "-probesize 5000000" in cmd_str

    # 2. Seeking (-ss before -i)
    ss_idx = captured_cmd.index("-ss")
    i_idx = captured_cmd.index("-i")
    assert ss_idx < i_idx

    # 3. Audio clock alignment
    af_idx = captured_cmd.index("-af")
    af_val = captured_cmd[af_idx + 1]
    assert "aresample=async=1000:first_pts=0" in af_val

    # 4. Zero-delay muxing and timestamp normalization
    assert "-avoid_negative_ts" in captured_cmd
    assert "-max_interleave_delta" in captured_cmd
    assert "-muxpreload" in captured_cmd
    assert "-muxdelay" in captured_cmd
    assert "-max_muxing_queue_size" in captured_cmd
    assert "4096" in captured_cmd

    # 5. movflags
    movflags_idx = captured_cmd.index("-movflags")
    movflags = captured_cmd[movflags_idx + 1]
    assert "frag_keyframe" in movflags
    assert "empty_moov" in movflags
    assert "default_base_moof" in movflags
    assert "omit_tfhd_offset" in movflags


def test_hls_command_builder_flags():
    """Task 2.1: Verify HLS FFmpeg command builder includes zero-delay muxing and proper probing."""
    cmd = _build_hls_ffmpeg_cmd("http://127.0.0.1:8889/stream/test.mkv", 0.0, 6.0, "fmp4")
    cmd_str = " ".join(cmd)
    assert "+genpts+discardcorrupt+igndts" in cmd_str
    assert "-analyzeduration 5000000" in cmd_str
    assert "-probesize 5000000" in cmd_str
    assert "aresample=async=1000:first_pts=0" in cmd_str
    assert "omit_tfhd_offset" in cmd_str
    assert "-max_interleave_delta 0" in cmd_str


def test_torrent_engine_piece_prioritization_window():
    """Task 2.2: Verify startup head priority covers at least 10MB and tail covers 2MB."""
    engine_path = os.path.join(os.path.dirname(__file__), "..", "streamer", "torrent_engine.js")
    with open(engine_path, "r", encoding="utf-8") as f:
        src = f.read()

    # Verify 10MB head calculation
    assert "10 * 1024 * 1024" in src
    assert "2 * 1024 * 1024" in src
    assert "headTenMbPieces" in src or "minTenMbPieces" in src
    assert "tailTwoMbPieces" in src or "twoMbPieces" in src


def test_startup_video_buffer_gate_in_js():
    """Task 2.3: Verify startup video buffer gate in p2p-player.js and app.js."""
    p2p_player_path = os.path.join(os.path.dirname(__file__), "..", "static", "p2p-player.js")
    with open(p2p_player_path, "r", encoding="utf-8") as f:
        p2p_src = f.read()

    assert "safePlayWithBufferGate" in p2p_src
    assert "3.0" in p2p_src or ">= 3" in p2p_src
    assert "readyState >= 4" in p2p_src
    assert "4000" in p2p_src
    assert "videoEl.currentTime = videoEl.currentTime" in p2p_src

    app_path = os.path.join(os.path.dirname(__file__), "..", "static", "app.js")
    with open(app_path, "r", encoding="utf-8") as f:
        app_src = f.read()

    assert "safePlayWithBufferGate" in app_src
    assert "video.currentTime = video.currentTime" in app_src


# ---------------------------------------------------------------------------
# Phase 3: Subtitle-to-Audio Desync Fixes
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_bypass_auto_sync_for_embedded_and_hash():
    """Task 3.1: Embedded and exact-hash matched subtitles must bypass VAD/Alass auto-sync."""
    engine = SubtitleSyncEngine()
    cues = [(10.0, 14.0, "Hello world"), (15.0, 18.0, "How are you?")]

    # 1. Embedded source bypass
    res_embedded = await engine.sync(
        video_source="http://fake-source",
        subtitle_cues=cues,
        source="embedded",
        manual=False,
    )
    assert res_embedded.success is True
    assert res_embedded.offset == 0.0
    assert res_embedded.confidence == 1.0
    assert res_embedded.method == "bypass_exact_match"

    # 2. Exact-hash match bypass
    res_hash = await engine.sync(
        video_source="http://fake-source",
        subtitle_cues=cues,
        hash_match=True,
        manual=False,
    )
    assert res_hash.success is True
    assert res_hash.offset == 0.0
    assert res_hash.confidence == 1.0
    assert res_hash.method == "bypass_exact_match"

    # 3. Manual trigger overrides bypass
    with patch("core.subtitle_sync.engine.extract_speech_intervals_from_stream", new=AsyncMock(return_value=[(10.5, 14.5)])):
        res_manual = await engine.sync(
            video_source="http://fake-source",
            subtitle_cues=cues,
            source="embedded",
            manual=True,
        )
        assert res_manual.method != "bypass_exact_match"


def test_vad_audio_extraction_filter():
    """Task 3.2: Verify FFmpeg VAD extraction uses speech bandpass and afftdn filter."""
    vad_path = os.path.join(os.path.dirname(__file__), "..", "core", "subtitle_sync", "vad.py")
    with open(vad_path, "r", encoding="utf-8") as f:
        vad_src = f.read()

    assert "highpass=f=300" in vad_src
    assert "lowpass=f=3000" in vad_src
    assert "afftdn=nf=-25" in vad_src
    assert "+genpts+discardcorrupt+igndts" in vad_src


def test_strip_credit_and_watermark_cues():
    """Task 3.2: Filter out watermark/credit cues before computing sync."""
    cues = [
        (1.0, 4.0, "Synced and corrected by HoneyBunny"),
        (4.5, 7.0, "Subtitles by OpenSubtitles.org"),
        (8.0, 10.0, "www.mysubtitles.com"),
        (12.0, 16.0, "I thought you were never coming back."),
        (18.0, 21.0, "Of course I came back."),
    ]
    mask = detect_forced_subtitles(cues)
    clean = filter_for_sync(cues, mask)

    # First three credit/watermark cues must be stripped
    clean_texts = [c[2] for c in clean]
    assert "Synced and corrected by HoneyBunny" not in clean_texts
    assert "Subtitles by OpenSubtitles.org" not in clean_texts
    assert "www.mysubtitles.com" not in clean_texts
    # Legitimate dialogue cues must remain
    assert "I thought you were never coming back." in clean_texts
    assert "Of course I came back." in clean_texts


def test_consensus_clamps_unreliable_large_offsets():
    """Task 3.2: Clamps offsets > 8.0s when confidence is low."""
    # Single candidate with offset > 8.0s and low confidence
    cs1 = ConsensusSync()
    cs1.add_candidate(SyncCandidate(offset=25.0, confidence=0.45, method="audio_vad"))
    res1 = cs1.compute_consensus()
    assert res1.offset == 0.0
    assert res1.method == "rejected_large_offset"

    # Conflicting candidates without consensus where max conf has low confidence and >8s offset
    cs2 = ConsensusSync(min_consensus=2)
    cs2.add_candidate(SyncCandidate(offset=15.0, confidence=0.55, method="audio_vad"))
    cs2.add_candidate(SyncCandidate(offset=-12.0, confidence=0.40, method="external_ref"))
    res2 = cs2.compute_consensus()
    assert res2.offset == 0.0
    assert res2.method == "rejected_large_offset"


@pytest.mark.asyncio
async def test_embedded_subtitle_extraction_timestamp_normalization():
    """Task 3.3: Verify embedded subtitle extraction includes consistent normalization flags."""
    captured_cmd = None

    async def mock_subprocess_exec(*cmd, **kwargs):
        nonlocal captured_cmd
        captured_cmd = list(cmd)
        mock_proc = AsyncMock()
        mock_proc.communicate = AsyncMock(return_value=(b"WEBVTT\n\n00:00:01.000 --> 00:00:03.000\nHello", b""))
        return mock_proc

    with patch("asyncio.create_subprocess_exec", side_effect=mock_subprocess_exec), \
         patch("core.transmuxer.find_ffmpeg", return_value="ffmpeg"):
        vtt = await extract_embedded_subtitle_vtt("http://fake-source/video.mkv", sub_stream_index=0)

    assert captured_cmd is not None
    cmd_str = " ".join(captured_cmd)
    assert "+genpts+discardcorrupt+igndts" in cmd_str
    assert "-copyts" in captured_cmd
    assert "-start_at_zero" in captured_cmd
    assert "-avoid_negative_ts" in captured_cmd
    assert "make_zero" in captured_cmd


def test_app_js_vtt_timestamp_map_and_align_text_tracks():
    """Task 3.4: Verify X-TIMESTAMP-MAP parsing and text track alignment in app.js."""
    app_path = os.path.join(os.path.dirname(__file__), "..", "static", "app.js")
    with open(app_path, "r", encoding="utf-8") as f:
        app_src = f.read()

    assert "X-TIMESTAMP-MAP=MPEGTS:" in app_src
    assert "90000" in app_src
    assert "alignTextTracks" in app_src
    assert "syncNativeTextTracks" in app_src
