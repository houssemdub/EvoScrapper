"""
tests/test_alass_engine.py — Unit tests for the Sequence Alignment & Interval DTW Engine.
"""
import random
import pytest
from core.subtitle_sync.alass_engine import (
    alass_align_intervals,
    detect_piecewise_breakpoints,
    find_candidate_offsets,
    refine_offset_peak,
    score_intervals_penalized,
)


def test_exact_match():
    cues = [(10.0, 14.5), (25.0, 31.0), (45.0, 48.0), (60.0, 67.2)]
    res = alass_align_intervals(cues, cues, allow_framerate_drift=False)
    assert abs(res["offset"]) <= 0.02
    assert res["confidence"] == 1.0
    assert res["matched_cues"] == 4
    assert res["drift_model"] is None


def test_shifted_cues_positive_and_negative():
    ground_truth = [(12.0, 15.5), (24.0, 29.0), (38.0, 44.0), (52.0, 59.0), (75.0, 83.0)]

    # Subtitles delayed by 6.2s
    delayed_cues = [(s + 6.2, e + 6.2) for s, e in ground_truth]
    res_del = alass_align_intervals(delayed_cues, ground_truth, allow_framerate_drift=False)
    assert abs(res_del["offset"] - (-6.2)) <= 0.05
    assert res_del["confidence"] >= 0.95

    # Subtitles advanced (early) by 4.8s
    early_cues = [(s - 4.8, e - 4.8) for s, e in ground_truth]
    res_ear = alass_align_intervals(early_cues, ground_truth, allow_framerate_drift=False)
    assert abs(res_ear["offset"] - 4.8) <= 0.05
    assert res_ear["confidence"] >= 0.95


def test_large_shift_over_one_minute():
    ground_truth = [(15.0 + i * 5.0, 18.0 + i * 5.0) for i in range(50)]
    shift = 92.5
    target = [(s + shift, e + shift) for s, e in ground_truth]
    res = alass_align_intervals(target, ground_truth, max_delta=180.0, allow_framerate_drift=False)
    assert abs(res["offset"] - (-shift)) <= 0.05
    assert res["confidence"] >= 0.90


def test_framerate_drift_pal_speedup():
    random.seed(42)
    starts = []
    t = 5.0
    for _ in range(400):
        starts.append(round(t, 3))
        t += random.uniform(1.5, 9.0)
    ref = [(s, s + random.uniform(1.2, 4.0)) for s in starts]

    scale = 0.95904  # 23.976 -> 25 fps
    offset = 3.2
    target = [(s / scale + offset, e / scale + offset) for s, e in ref]

    res = alass_align_intervals(target, ref, max_delta=180.0, allow_framerate_drift=True)
    assert res["drift_model"] is not None
    assert abs(res["drift_model"]["params"][0] + 0.04096) < 1e-4
    assert abs(res["offset"] + 3.2 * scale) <= 0.08
    assert res["confidence"] >= 0.90


def test_framerate_drift_film_slowdown():
    random.seed(99)
    starts = []
    t = 5.0
    for _ in range(400):
        starts.append(round(t, 3))
        t += random.uniform(1.5, 9.0)
    ref = [(s, s + random.uniform(1.2, 4.0)) for s in starts]

    scale = 1.04271  # 25 -> 23.976 fps
    offset = -1.5
    target = [(s / scale + offset, e / scale + offset) for s, e in ref]

    res = alass_align_intervals(target, ref, max_delta=180.0, allow_framerate_drift=True)
    assert res["drift_model"] is not None
    assert abs(res["drift_model"]["params"][0] - (scale - 1.0)) < 1e-4
    assert abs(res["offset"] - (-offset * scale)) <= 0.08
    assert res["confidence"] >= 0.90


def test_noise_immunity_and_mismatch_penalty():
    # Ground truth clean dialogue
    random.seed(7)
    dialogue = [(10.0 + i * 8.0, 13.5 + i * 8.0) for i in range(30)]

    # Audio VAD has 20 spurious background noise false detections (explosions/music)
    noisy_ref = list(dialogue)
    for _ in range(20):
        noise_start = random.uniform(0.0, 250.0)
        noisy_ref.append((noise_start, noise_start + random.uniform(0.5, 2.0)))
    noisy_ref.sort(key=lambda x: x[0])

    target = [(s + 5.0, e + 5.0) for s, e in dialogue]
    res = alass_align_intervals(target, noisy_ref, allow_framerate_drift=False)
    # Must lock onto true shift despite noise
    assert abs(res["offset"] - (-5.0)) <= 0.05
    assert res["confidence"] >= 0.80


def test_piecewise_scene_cut_detection():
    random.seed(1337)
    t = 0.0
    ref = []
    for _ in range(500):
        dur = random.uniform(1.5, 3.5)
        gap = random.uniform(2.0, 7.0)
        ref.append((t, t + dur))
        t += dur + gap

    # Segment 1 (cues 0-200) has offset +5.0s, Segment 2 (cues 200-500) has offset +20.0s (15s commercial break)
    target = [(s + 5.0, e + 5.0) for s, e in ref[:200]] + [(s + 20.0, e + 20.0) for s, e in ref[200:]]

    res = alass_align_intervals(target, ref, allow_framerate_drift=False)
    assert res["piecewise"] is not None
    offsets = [b["offset"] for b in res["piecewise"]]
    assert any(abs(off - (-5.0)) <= 0.2 for off in offsets)
    assert any(abs(off - (-20.0)) <= 0.2 for off in offsets)


def test_ambiguity_decoy_guard():
    # Regularly spaced dense track (every 2.0s with 1.5s lines)
    ref = [(4.0 + i * 2.0, 5.5 + i * 2.0) for i in range(1500)]
    target = [(s + 7.0, e + 7.0) for s, e in ref[:600]]

    res = alass_align_intervals(target, ref, allow_framerate_drift=False)
    assert abs(res["offset"] + 7.0) <= 0.1
    # Ambiguous track cannot report high confidence
    assert res["confidence"] < 0.35


def test_movie_two_hours_vs_ninety_seconds_audio_window():
    # Full 2-hour movie subtitle track (1000+ cues)
    random.seed(1)
    movie_cues = []
    t = 10.0
    while t < 7000.0:
        movie_cues.append((round(t, 2), round(t + random.uniform(1.5, 4.0), 2)))
        t += random.uniform(3.0, 10.0)

    # Subtitles in MKV delayed by 5.5s
    delay = 5.5
    target_cues = [(round(s + delay, 2), round(e + delay, 2)) for s, e in movie_cues]

    # Live playback at minute 15: audio VAD extracts 90 seconds [900s .. 990s]
    speech_window = [(s, e) for s, e in movie_cues if 900.0 <= s <= 990.0]
    assert len(speech_window) >= 10

    res = alass_align_intervals(target_cues, speech_window, allow_framerate_drift=False)
    # Must recover the exact -5.5s offset with high confidence (> 0.85), NOT 0.0% confidence!
    assert abs(res["offset"] - (-delay)) <= 0.08
    assert res["confidence"] >= 0.85
    assert res["matched_cues"] == len(speech_window)

