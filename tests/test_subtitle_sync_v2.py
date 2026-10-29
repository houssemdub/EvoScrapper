import pytest
from core.subtitle_sync.forced_subs import detect_forced_subtitles, filter_for_sync


def test_detect_forced_subtitles():
    cues = [
        (10.0, 14.0, "Hello, how are you today?"),
        (20.0, 22.0, "[Sign: Central Hospital]"),
        (30.0, 35.0, "We need to get inside quickly."),
        (40.0, 42.0, "Sign: Police Station"),
        (50.0, 52.0, "(Theme music playing)"),
        (60.0, 62.0, "CREDITS: TRANSLATED BY ANONYMOUS"),
        (70.0, 71.0, "12:00"),
        (80.0, 85.0, "I didn't expect you to arrive so early."),
    ]

    mask = detect_forced_subtitles(cues)
    assert mask[0] is False  # Normal speech
    assert mask[1] is True   # [Sign: ...]
    assert mask[2] is False  # Normal speech
    assert mask[3] is True   # Sign: ...
    assert mask[4] is True   # (Theme music...)
    assert mask[5] is True   # CREDITS: ...
    assert mask[6] is True   # Timecode
    assert mask[7] is False  # Normal speech

    filtered = filter_for_sync(cues, mask)
    assert len(filtered) == 3
    assert filtered[0][2] == "Hello, how are you today?"
    assert filtered[1][2] == "We need to get inside quickly."
    assert filtered[2][2] == "I didn't expect you to arrive so early."


def test_drift_model_linear_pal_speedup():
    from core.subtitle_sync.drift import DriftModel

    # 24fps vs 25fps drift: ref runs ~4.167% faster, or an offset of +2.5s every 60s
    # y = offset = 0.04167 * t + 1.5
    cue_times = [60.0, 120.0, 300.0, 600.0, 1200.0, 1800.0]
    true_a = 0.04167
    true_b = 1.5
    ref_times = [t + (true_a * t + true_b) for t in cue_times]

    drift = DriftModel.fit_drift(cue_times, ref_times)
    assert drift["model"] == "linear"
    assert abs(drift["params"][0] - true_a) < 1e-4
    assert abs(drift["params"][1] - true_b) < 1e-3
    assert drift["rmse"] < 0.01

    # Test applying drift
    test_cues = [100.0, 500.0]
    adjusted = DriftModel.apply_drift(test_cues, drift)
    expected_0 = 100.0 + (true_a * 100.0 + true_b)
    expected_1 = 500.0 + (true_a * 500.0 + true_b)
    assert abs(adjusted[0] - expected_0) < 0.05
    assert abs(adjusted[1] - expected_1) < 0.05


def test_drift_model_degenerate_zero_variance():
    from core.subtitle_sync.drift import DriftModel

    # All points identical timestamp - must not divide by zero
    cue_times = [10.0, 10.0, 10.0]
    ref_times = [12.0, 12.0, 12.0]

    drift = DriftModel.fit_drift(cue_times, ref_times)
    assert drift["model"] == "linear"
    assert drift["params"][0] == 0.0
    assert drift["params"][1] == 2.0
    assert drift["rmse"] == 0.0


def test_consensus_sync_clustering_and_outlier_rejection():
    from core.subtitle_sync.consensus import ConsensusSync, SyncCandidate

    cs = ConsensusSync(min_consensus=2, max_outlier_sec=1.5)
    # 3 candidates agree around +2.5s, 1 outlier at -12.0s
    cs.add_candidate(SyncCandidate(offset=2.4, confidence=0.85, method="opensubtitles", metadata={}))
    cs.add_candidate(SyncCandidate(offset=2.6, confidence=0.80, method="subdl", metadata={}))
    cs.add_candidate(SyncCandidate(offset=2.5, confidence=0.90, method="audio_vad", metadata={}))
    cs.add_candidate(SyncCandidate(offset=-12.0, confidence=0.60, method="corrupted_track", metadata={}))

    result = cs.compute_consensus()
    assert result is not None
    assert result.method == "consensus"
    # Weighted average should be very close to 2.5
    assert abs(result.offset - 2.5) <= 0.1
    # Multi-signal agreement boost
    assert result.confidence >= 0.88
    assert "audio_vad" in result.metadata["methods"]
    assert "corrupted_track" not in result.metadata["methods"]
    assert result.metadata["cluster_size"] == 3


def test_consensus_sync_single_candidate():
    from core.subtitle_sync.consensus import ConsensusSync, SyncCandidate

    cs = ConsensusSync(min_consensus=2, max_outlier_sec=1.5)
    cs.add_candidate(SyncCandidate(offset=-1.8, confidence=0.95, method="embedded_ref", metadata={}))

    result = cs.compute_consensus()
    assert result is not None
    assert result.offset == -1.8
    assert result.confidence == 0.95
    assert result.method == "embedded_ref"


@pytest.mark.asyncio
async def test_adaptive_sync_controller_convergence():
    from core.subtitle_sync.adaptive import AdaptiveSyncController

    ctrl = AdaptiveSyncController(initial_offset=1.0)
    assert ctrl.get_offset(position_sec=60.0) == 1.0

    # User at position 60s presses delay +50ms (delaying subs by +0.05s)
    await ctrl.apply_user_correction(position_sec=60.0, delta_ms=50)
    # Then presses delay +50ms again at 65s
    await ctrl.apply_user_correction(position_sec=65.0, delta_ms=50)

    # Offset should now be approx 1.10s
    current_off = ctrl.get_offset(position_sec=62.0)
    assert abs(current_off - 1.10) < 0.01

    # Confidence should increase as corrections stabilize
    conf = ctrl.get_confidence()
    assert conf > 0.70


@pytest.mark.asyncio
async def test_adaptive_sync_controller_temporal_weighting():
    from core.subtitle_sync.adaptive import AdaptiveSyncController

    ctrl = AdaptiveSyncController(initial_offset=0.0)
    # Correction at beginning (10s): +1.0s
    await ctrl.apply_user_correction(position_sec=10.0, delta_ms=1000)
    # Correction much later (1800s): +2.5s (due to gradual drift later in movie)
    await ctrl.apply_user_correction(position_sec=1800.0, delta_ms=1500)

    # Near 10s, offset should be closer to 1.0s
    early_off = ctrl.get_offset(position_sec=15.0)
    # Near 1800s, offset should be closer to 2.5s
    late_off = ctrl.get_offset(position_sec=1805.0)

    assert abs(early_off - 1.0) < 0.2
    assert abs(late_off - 2.5) < 0.2


@pytest.mark.asyncio
async def test_subtitle_sync_engine_fusion():
    from unittest.mock import patch, AsyncMock
    from core.subtitle_sync.engine import SubtitleSyncEngine, SyncResult

    engine = SubtitleSyncEngine()

    # Ground truth dialogue starts at 10.0, 25.0, 40.0
    # Our target subtitles are DELAYED by +3.0s (starting at 13.0, 28.0, 43.0)
    target_cues = [
        (13.0, 17.0, "Welcome to the future."),
        (20.0, 21.0, "[Sign: Metro Station]"),  # forced sub
        (28.0, 33.0, "We don't have much time left."),
        (43.0, 48.0, "Let's move out immediately."),
    ]

    # Reference cues from embedded container (accurate at 10.0, 25.0, 40.0)
    embedded_cues = [
        (10.0, 14.0, "Welcome to the future."),
        (25.0, 30.0, "We don't have much time left."),
        (40.0, 45.0, "Let's move out immediately."),
    ]

    # External source #1 from SubDL (shifted by +3.0s as well)
    external_cues = [
        (10.0, 14.0, "Welcome"),
        (25.0, 30.0, "We don't have time"),
        (40.0, 45.0, "Move out"),
    ]

    # Audio VAD speech intervals (10.0 to 14.0, 25.0 to 30.0, 40.0 to 45.0)
    speech_intervals = [(10.0, 14.0), (25.0, 30.0), (40.0, 45.0)]

    with patch("core.subtitle_sync.engine.extract_speech_intervals_from_stream", new=AsyncMock(return_value=speech_intervals)):
        result = await engine.sync(
            video_source="http://mock-stream",
            subtitle_cues=target_cues,
            reference_cues=embedded_cues,
            external_cues_list=[external_cues],
        )

        assert isinstance(result, SyncResult)
        assert result.success is True
        # Target was delayed by 3.0s, so correction offset must be -3.0s
        assert abs(result.offset - (-3.0)) <= 0.15
        assert result.confidence >= 0.85
        assert "audio_vad" in result.signals_used or "consensus" in result.method
        assert result.adaptive_controller is not None
        assert abs(result.adaptive_controller.get_offset(15.0) - (-3.0)) <= 0.15


@pytest.mark.asyncio
async def test_auto_sync_v2_and_adjust_endpoints():
    from unittest.mock import patch, AsyncMock
    from httpx import AsyncClient, ASGITransport
    from main import app

    speech_mock = [(10.0, 15.0), (25.0, 30.0), (45.0, 50.0)]
    # Cues are shifted by +2.0s
    cues = [
        {"start": s + 2.0, "end": e + 2.0, "text": f"Line {idx}"}
        for idx, (s, e) in enumerate(speech_mock)
    ]

    with patch("core.subtitle_sync.engine.extract_speech_intervals_from_stream", new=AsyncMock(return_value=speech_mock)), \
         patch("core.torrent_streamer.ensure_streaming_daemon", new=AsyncMock(return_value=True)):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            # 1. Test auto-sync-v2
            res = await client.post(
                "/api/v1/stream/subtitles/auto-sync-v2",
                json={
                    "info_hash": "b" * 40,
                    "file_idx": 0,
                    "cues": cues,
                },
            )
            assert res.status_code == 200
            data = res.json()
            assert data["success"] is True
            assert abs(data["offset"] - (-2.0)) <= 0.15
            assert data["confidence"] > 0.6
            session_id = data["session_id"]
            assert session_id == f"{'b' * 40}:0:0"

            # 2. Test interactive user adjustment via /subtitles/adjust
            adj_res = await client.post(
                "/api/v1/stream/subtitles/adjust",
                json={
                    "session_id": session_id,
                    "position_sec": 12.0,
                    "delta_ms": 100,  # user delayed by +100ms
                },
            )
            assert adj_res.status_code == 200
            adj_data = adj_res.json()
            assert adj_data["success"] is True
            # New offset shifted by +0.1s
            assert abs(adj_data["offset"] - (data["offset"] + 0.1)) <= 0.05
            assert adj_data["confidence"] > 0.6


@pytest.mark.asyncio
async def test_auto_sync_with_reference_cues():
    from unittest.mock import patch, AsyncMock
    from httpx import AsyncClient, ASGITransport
    from main import app

    ref_cues = [
        {"start": 10.0, "end": 15.0, "text": "Original Dialogue"},
        {"start": 25.0, "end": 30.0, "text": "Second Dialogue"},
    ]
    # Target subtitles are 2.5 seconds early (advanced by -2.5s)
    target_cues = [
        {"start": 7.5, "end": 12.5, "text": "Spanish Dialogue"},
        {"start": 22.5, "end": 27.5, "text": "Second Spanish"},
    ]

    with patch("core.torrent_streamer.ensure_streaming_daemon", new=AsyncMock(return_value=True)):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            res = await client.post(
                "/api/v1/stream/subtitles/auto-sync",
                json={
                    "info_hash": "c" * 40,
                    "file_idx": 0,
                    "cues": target_cues,
                    "reference_cues": ref_cues,
                },
            )
            assert res.status_code == 200
            data = res.json()
            assert data["success"] is True
            assert data["method"] == "embedded_reference"
            # Since target was -2.5s early, offset needed is +2.5s
            assert abs(data["offset"] - 2.5) <= 0.1
            assert data["confidence"] >= 0.9


def test_failed_sub_vtt_prevents_infinite_polling(tmp_path, monkeypatch):
    """Verify failed/empty extraction is recorded and returned without X-Evo-Sub-Pending."""
    import asyncio
    from core import transmuxer

    monkeypatch.setattr(transmuxer, "SUB_VTT_CACHE_DIR", str(tmp_path))

    async def fake_extract_empty(source_url, sub_index=0, timeout=8.0):
        return "WEBVTT\n\nNOTE Empty or unsupported embedded subtitle track\n"

    async def scenario():
        monkeypatch.setattr(transmuxer, "extract_embedded_subtitle_vtt", fake_extract_empty)
        key = "job-empty-test"
        transmuxer.start_sub_vtt_extraction(key, "http://source", 0)
        while transmuxer.sub_vtt_job_running(key):
            await asyncio.sleep(0.01)

        # Must not be in disk cache (per contract)
        assert transmuxer.load_cached_sub_vtt(key) is None
        # But MUST be in failed registry so router serves terminal response rather than infinite pending
        failed_res = transmuxer.get_failed_sub_vtt(key)
        assert failed_res is not None
        assert "NOTE Empty" in failed_res

    asyncio.run(scenario())


def test_reference_alignment_regular_spacing_no_alias():
    """Regularly spaced cues must not alias to a neighbouring line (±one cue)."""
    from core.subtitle_sync import align_to_reference_cues

    ref = [(4.0 + i * 3.0, 6.0 + i * 3.0) for i in range(500)]
    target = [(s + 7.0, e + 7.0) for s, e in ref]

    offset, confidence = align_to_reference_cues(target, ref)
    assert abs(offset + 7.0) <= 0.05
    assert confidence >= 0.9


def test_reference_alignment_dense_regular_track_is_not_overconfident():
    """A 2s-spaced regular track matches almost any offset; confidence must say so."""
    from core.subtitle_sync import align_to_reference_cues

    ref = [(4.0 + i * 2.0, 5.5 + i * 2.0) for i in range(1500)]
    target = [(s + 7.0, e + 7.0) for s, e in ref[:600]]

    offset, confidence = align_to_reference_cues(target, ref)
    assert abs(offset + 7.0) <= 0.1
    # Multiple offsets explain this track equally well; never report 100%.
    assert confidence < 0.35


def test_reference_alignment_recovers_large_shift_with_dense_cues():
    """A >1 minute shift must not be lost to the dense candidate-window cap."""
    from core.subtitle_sync import align_to_reference_cues

    ref = [(4.0 + i * 3.0, 6.0 + i * 3.0) for i in range(500)]
    target = [(s + 115.0, e + 115.0) for s, e in ref]

    offset, confidence = align_to_reference_cues(target, ref)
    assert abs(offset + 115.0) <= 0.1
    assert confidence >= 0.9


def test_reference_alignment_detects_framerate_drift():
    """PAL 23.976 -> 25 fps drift is modelled instead of returning a rigid 0s."""
    import random
    from core.subtitle_sync import align_to_reference_cues_ex

    random.seed(11)
    starts = []
    t = 4.0
    for _ in range(600):
        starts.append(round(t, 3))
        t += random.uniform(1.2, 9.5)
    ref = [(s, s + random.uniform(1.0, 4.0)) for s in starts]

    scale = 0.95904
    offset = 2.5
    target = [(s / scale + offset, e / scale + offset) for s, e in ref]

    result = align_to_reference_cues_ex(target, ref)
    assert result["drift_model"] is not None
    assert abs(result["drift_model"]["params"][0] + 0.04096) < 1e-4
    # corrected(t) = ref = (t - 2.5) * scale  ->  b = -2.5 * scale
    assert abs(result["offset"] + 2.5 * scale) <= 0.1
    assert result["confidence"] >= 0.9


def test_vad_detects_large_constant_offset():
    """A subtitle file offset by >1 minute must still be recovered."""
    import random
    from core.subtitle_sync import compute_optimal_offset

    random.seed(3)
    speech = []
    t = 1.0
    while t < 118.0:
        t += random.uniform(0.8, 3.0)
        length = random.uniform(1.0, 4.0)
        if t + length > 120.0:
            break
        speech.append((round(t, 2), round(t + length, 2)))
        t += length

    target = [(s + 95.0, e + 95.0) for s, e in speech]
    offset, confidence = compute_optimal_offset(target, speech)
    assert abs(offset + 95.0) <= 0.6
    assert confidence >= 0.4


@pytest.mark.asyncio
async def test_v2_self_reference_is_ignored_and_vad_used():
    """Passing the active embedded track as its own reference must not fake 0s/100%."""
    from unittest.mock import patch, AsyncMock
    from httpx import AsyncClient, ASGITransport
    from main import app

    cues = [
        {"start": 10.0 + i * 8.0, "end": 14.0 + i * 8.0, "text": "Dialogue line"}
        for i in range(12)
    ]
    speech = [(c["start"], c["end"]) for c in cues]

    with patch("core.subtitle_sync.engine.extract_speech_intervals_from_stream", new=AsyncMock(return_value=speech)), \
         patch("core.torrent_streamer.ensure_streaming_daemon", new=AsyncMock(return_value=True)):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            res = await client.post(
                "/api/v1/stream/subtitles/auto-sync-v2",
                json={
                    "info_hash": "d" * 40,
                    "file_idx": 0,
                    "cues": cues,
                    "reference_cues": cues,
                },
            )
            assert res.status_code == 200
            data = res.json()
            assert data["success"] is True
            assert data["method"] == "audio_vad"
            assert abs(data["offset"]) <= 0.5


@pytest.mark.asyncio
async def test_engine_anchors_drift_offset_to_reference_constant():
    """Framerate drift fits must anchor the constant term, not a mid-window VAD blend."""
    import random
    from core.subtitle_sync.engine import SubtitleSyncEngine

    random.seed(17)
    starts = []
    t = 4.0
    for _ in range(240):
        starts.append(round(t, 3))
        t += random.uniform(2.0, 9.0)
    ref = [(s, s + random.uniform(1.0, 4.0), "Dialogue line") for s in starts]

    scale = 0.95904
    shift = 2.5
    target = [((s / scale) + shift, (e / scale) + shift, txt) for s, e, txt in ref]

    engine = SubtitleSyncEngine()
    result = await engine.sync(subtitle_cues=target, reference_cues=ref)

    assert result.success is True
    assert result.drift_model is not None
    assert abs(result.drift_model["params"][0] + 0.04096) < 1e-4
    # corrected(t) = ref = (t - shift) * scale  ->  constant b = -shift * scale
    assert abs(result.offset + shift * scale) <= 0.1
    assert result.method == "embedded_ref_drift"
    assert result.confidence >= 0.8


@pytest.mark.asyncio
async def test_engine_skips_vad_when_reference_is_authoritative():
    """A confident embedded reference must answer instantly instead of decoding audio."""
    from unittest.mock import patch, AsyncMock
    from core.subtitle_sync.engine import SubtitleSyncEngine

    ref = [(10.0 + i * 10.0, 14.0 + i * 10.0, "Dialogue line") for i in range(20)]
    target = [(s + 3.0, e + 3.0, txt) for s, e, txt in ref]

    vad = AsyncMock(return_value=[(10.0, 14.0)])
    with patch("core.subtitle_sync.engine.extract_speech_intervals_from_stream", new=vad):
        result = await SubtitleSyncEngine().sync(
            video_source="http://mock-stream",
            subtitle_cues=target,
            reference_cues=ref,
        )

    assert result.success is True
    assert abs(result.offset + 3.0) <= 0.1
    vad.assert_not_called()


def test_score_offsets_asymmetric_stage2():
    """Stage 2 fine search uses an asymmetric offset window and must peak at the exact shift."""
    from core.subtitle_sync.vad import _score_offsets

    speech = [(50.0, 55.0), (70.0, 75.0), (90.0, 95.0)]
    # Cues are advanced by 5.0s (starting at 45.0, 65.0, 85.0) -> optimal offset is +5.0s
    cues = [(s - 5.0, e - 5.0) for s, e in speech]
    fine_offsets = [4.75, 4.80, 4.85, 4.90, 4.95, 5.00, 5.05, 5.10, 5.15, 5.20, 5.25]

    scores, overlaps, _ = _score_offsets(cues, speech, fine_offsets, 0.05)
    assert len(scores) == len(fine_offsets)
    best_idx = max(range(len(scores)), key=lambda i: scores[i])
    assert fine_offsets[best_idx] == 5.00
    assert scores[best_idx] > 0.95


def test_compute_optimal_offset_subsecond_accuracy():
    """Perceptual offsets between 0.2s and 0.5s must be retained, not clamped to 0.0s."""
    from core.subtitle_sync.vad import compute_optimal_offset

    speech = [(10.0, 15.0), (30.0, 35.0), (60.0, 65.0)]
    # Cues delayed by 0.35s -> offset should be -0.35s
    cues = [(s + 0.35, e + 0.35) for s, e in speech]

    offset, conf = compute_optimal_offset(cues, speech, min_offset=-5.0, max_offset=5.0, step=0.05)
    assert abs(offset - (-0.35)) <= 0.05
    assert conf > 0.7


def test_srt_to_webvtt_formats_and_offsets():
    """srt_to_webvtt must shift both hh:mm:ss.ttt and mm:ss.ttt without duplicating WEBVTT."""
    from routers.subtitles import srt_to_webvtt

    vtt_raw = "WEBVTT\n\n00:04.500 --> 00:08.500\nHello\n\n1:02:03.000 --> 1:02:06.000\nWorld\n"
    shifted = srt_to_webvtt(vtt_raw, offset_seconds=2.0)
    assert shifted.count("WEBVTT") == 1
    # 00:04.500 + 2s = 00:00:06.500
    assert "00:00:06.500 --> 00:00:10.500" in shifted
    # 1:02:03.000 + 2s = 01:02:05.000
    assert "01:02:05.000 --> 01:02:08.000" in shifted


def test_dominant_delta_dense_large_shift():
    """A dense track with 50s shift must not be clipped by cue count windowing."""
    from core.subtitle_sync.vad import _dominant_delta

    # Reference cues every 1s from 0 to 200
    refs = [float(i) for i in range(200)]
    # Target shifted by +50s (so target starts at 50, refs[j] - t = -50 or +50)
    # Suppose target is delayed: starts at 50.0..250.0. delta = ref - target = -50.0
    shift = -50.0
    targets = [r - shift for r in refs[:100]]

    median_offset, inliers, supported = _dominant_delta(targets, refs, max_delta=120.0)
    assert abs(median_offset - shift) <= 0.2
    assert supported >= 90


def test_auto_sync_fft_waveform_alignment_user_scenario():
    """Verifies that FFT cross-correlation recovers exact +5.30s shift from speech waveform."""
    from core.subtitle_sync.vad import auto_sync_fft, compute_optimal_offset

    speech = [
        (10.0, 14.5),
        (20.0, 24.0),
        (32.0, 36.5),
        (45.0, 50.0),
        (65.0, 72.0),
    ]
    # Cues delayed by 5.30s (the exact user issue)
    cues_delayed = [(s + 5.30, e + 5.30) for s, e in speech]

    offset, conf = auto_sync_fft(speech, cues_delayed, sample_step_sec=0.010, max_lag_sec=60.0)
    assert abs(offset - (-5.30)) <= 0.05
    assert conf >= 0.50

    # Also verify compute_optimal_offset delegates to FFT and yields the same answer
    opt_offset, opt_conf = compute_optimal_offset(cues_delayed, speech)
    assert abs(opt_offset - (-5.30)) <= 0.05
    assert opt_conf >= 0.50


def test_retime_subtitles_linear():
    """Verifies affine drift retimer with FPS ratios and anchor points."""
    from core.subtitle_sync.vad import retime_subtitles_linear

    cues = [(100.0, 105.0), (200.0, 205.0), (300.0, 305.0)]

    # 1. Constant offset +2.5s
    c_off = retime_subtitles_linear(cues, offset_sec=2.5)
    assert c_off[0] == (102.5, 107.5)
    assert c_off[1] == (202.5, 207.5)

    # 2. PAL speedup (23.976 -> 25.0)
    pal = retime_subtitles_linear(cues, src_fps=23.976, dst_fps=25.0)
    expected_m = 23.976 / 25.0
    assert abs(pal[0][0] - round(100.0 * expected_m, 3)) < 1e-4

    # 3. Two anchor points ((sub_1, aud_1), (sub_2, aud_2))
    # sub at 100 is aud at 102 (offset +2), sub at 300 is aud at 306 (offset +6)
    anchored = retime_subtitles_linear(cues, anchor_points=((100.0, 102.0), (300.0, 306.0)))
    # m = (306 - 102) / (300 - 100) = 4 / 200 = 1.02
    # b = 102 - 102 = 0
    assert anchored[0] == (102.0, 107.1)
    assert anchored[2] == (306.0, 311.1)








