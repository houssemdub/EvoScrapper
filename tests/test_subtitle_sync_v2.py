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





