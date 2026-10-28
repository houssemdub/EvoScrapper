"""
core/subtitle_sync/vad.py — Voice Activity Detection (VAD) via FFmpeg silencedetect.
Extracts active speech intervals and computes cross-track cue alignment.

The alignment routines here are intentionally dependency-free (pure Python) because
they also run inside request handlers on machines without numpy.
"""
import asyncio
import bisect
import math
import os
import re
import statistics
from typing import Any, Dict, List, Optional, Tuple

from core.logger import app_logger
from core.transmuxer import find_ffmpeg

# Candidate framerate ratios (PAL/NTSC conversions) used to recover from
# subtitle files that were retimed for a different release framerate.
_FRAMERATE_SCALES: Tuple[float, ...] = (
    0.95904,   # 23.976 -> 25
    1.04271,   # 25 -> 23.976
    0.96,      # 24 -> 25
    1.041667,  # 25 -> 24
    0.999,     # 24 -> 23.976
    1.001,     # 23.976 -> 24
)


def _last_processed_time(stderr_text: str) -> float:
    """Returns the last 'time=HH:MM:SS.xx' FFmpeg reported, or 0.0 if absent."""
    last = 0.0
    for m in re.finditer(r"time=(\d{1,2}):(\d{2}):(\d{2}(?:\.\d+)?)", stderr_text):
        try:
            last = max(
                last,
                int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3)),
            )
        except ValueError:
            continue
    return last


def parse_silencedetect_output(stderr_text: str, total_duration: float = 180.0) -> List[Tuple[float, float]]:
    """
    Parses FFmpeg silencedetect output and derives speech (non-silent) intervals.
    Lines resemble:
      [silencedetect @ ...] silence_start: 12.45
      [silencedetect @ ...] silence_end: 18.20 | silence_duration: 5.75
    """
    # When FFmpeg is killed by our timeout (or the stream ends early) the final
    # silence may never receive a silence_end line. Clamp the tail to the last
    # timestamp FFmpeg actually processed so we don't invent speech that was
    # never analysed.
    analyzed_end = _last_processed_time(stderr_text)
    effective_duration = total_duration
    if analyzed_end > 0.5:
        effective_duration = min(total_duration, analyzed_end) if total_duration > 0 else analyzed_end
    effective_duration = max(0.0, effective_duration)

    silences: List[Tuple[float, float]] = []
    current_start: Optional[float] = None

    for line in stderr_text.splitlines():
        if "silence_start:" in line:
            m = re.search(r"silence_start:\s*([0-9.]+)", line)
            if m:
                try:
                    current_start = float(m.group(1))
                except ValueError:
                    pass
        elif "silence_end:" in line:
            m = re.search(r"silence_end:\s*([0-9.]+)", line)
            if m and current_start is not None:
                try:
                    end_val = float(m.group(1))
                    if end_val > current_start:
                        silences.append((current_start, end_val))
                except ValueError:
                    pass
                current_start = None

    if current_start is not None and current_start < effective_duration:
        silences.append((current_start, effective_duration))

    # Invert silence intervals to produce active speech intervals
    speech: List[Tuple[float, float]] = []
    cur_pos = 0.0

    for s_start, s_end in silences:
        if s_start > cur_pos + 0.3:  # minimum speech threshold: 300ms
            speech.append((cur_pos, s_start))
        cur_pos = max(cur_pos, s_end)

    if cur_pos + 0.3 < effective_duration:
        speech.append((cur_pos, effective_duration))

    return speech


def _intervals_to_signal(
    intervals: List[Tuple[float, float]],
    start: float,
    end: float,
    bin_size: float,
) -> List[float]:
    """Builds a binary occupancy signal (1.0 while inside any interval)."""
    length = int(math.ceil(max(0.0, end - start) / bin_size)) + 1
    signal = [0.0] * length
    for raw_start, raw_end in intervals:
        a = max(start, float(raw_start))
        b = min(end, float(raw_end))
        if b <= a:
            continue
        i0 = int((a - start) / bin_size)
        i1 = int((b - start) / bin_size)
        i0 = max(0, min(i0, length - 1))
        i1 = max(0, min(i1, length - 1))
        for i in range(i0, i1 + 1):
            signal[i] = 1.0
    return signal


def _zncc(x: List[float], y: List[float]) -> Optional[float]:
    """Zero-normalised cross correlation between two equal-length signals."""
    n = len(x)
    if n < 4:
        return None
    sx = 0.0
    sy = 0.0
    sxx = 0.0
    syy = 0.0
    sxy = 0.0
    for xi, yi in zip(x, y):
        sx += xi
        sy += yi
        sxx += xi * xi
        syy += yi * yi
        sxy += xi * yi
    cov = sxy - (sx * sy) / n
    var_x = sxx - (sx * sx) / n
    var_y = syy - (sy * sy) / n
    if var_x <= 1e-9 or var_y <= 1e-9:
        return None
    denom = math.sqrt(var_x * var_y)
    if denom <= 1e-12:
        return None
    return max(-1.0, min(1.0, cov / denom))


def _overlap_fraction(
    cue_signal: List[float],
    speech_signal: List[float],
    shift_bins: int,
) -> float:
    """Fraction of shifted cue occupancy that lands on speech occupancy."""
    n = len(speech_signal)
    if shift_bins >= 0:
        x = cue_signal[0:max(0, n - shift_bins)]
        y = speech_signal[shift_bins:n]
    else:
        x = cue_signal[min(n, -shift_bins):n]
        y = speech_signal[0:max(0, n + shift_bins)]
    total = sum(x)
    if total <= 0.0:
        return 0.0
    return sum(xi * yi for xi, yi in zip(x, y)) / total


def _score_offsets(
    cues: List[Tuple[float, float]],
    speech_intervals: List[Tuple[float, float]],
    offsets: List[float],
    bin_size: float,
) -> Tuple[List[float], List[float], float]:
    """
    Scores every candidate offset with zero-normalised cross correlation of the
    subtitle dialogue pattern against the detected speech pattern.

    Returns (scores, overlap_fractions, speech_coverage).
    """
    speech_end = max((s[1] for s in speech_intervals), default=0.0)
    speech_start = 0.0
    if speech_end <= 0.0 or not offsets:
        return [], [], 0.0

    n_bins = int(math.ceil(speech_end / bin_size)) + 1
    speech_signal = _intervals_to_signal(speech_intervals, speech_start, speech_end + bin_size, bin_size)
    if len(speech_signal) < n_bins:
        speech_signal += [0.0] * (n_bins - len(speech_signal))
    else:
        speech_signal = speech_signal[:n_bins]

    speech_coverage = sum(speech_signal) / max(1, len(speech_signal))

    # At candidate offset `off`, speech dialogue at time `t` corresponds to
    # subtitle cue time (t - off). Across all candidate offsets, the required
    # cue timeline is [speech_start - max_offset, speech_end - min_offset].
    min_offset = min(offsets)
    max_offset = max(offsets)
    range_start = speech_start - max_offset
    range_end = speech_end - min_offset + bin_size
    cue_signal = _intervals_to_signal(cues, range_start, range_end, bin_size)

    scores: List[float] = []
    overlaps: List[float] = []
    for off in offsets:
        start_index = int(round((speech_start - off - range_start) / bin_size))
        start_index = max(0, min(start_index, max(0, len(cue_signal) - n_bins)))
        window = cue_signal[start_index:start_index + n_bins]
        if len(window) < n_bins:
            window = window + [0.0] * (n_bins - len(window))
        overlap = _overlap_fraction(window, speech_signal, 0)
        overlaps.append(overlap)
        z = _zncc(window, speech_signal)
        if z is None:
            # Flat signal: correlation is meaningless, fall back to overlap so
            # the caller can at least measure support.
            z = max(0.0, overlap) * 0.5
        scores.append(z)

    return scores, overlaps, speech_coverage


def compute_optimal_offset(
    cues: List[Tuple[float, float]],
    speech_intervals: List[Tuple[float, float]],
    min_offset: float = -180.0,
    max_offset: float = 180.0,
    step: float = 0.1,
) -> Tuple[float, float]:
    """
    Finds the time shift delta_t in [min_offset, max_offset] that maximizes
    the correlation between the subtitle dialogue pattern and detected audio
    speech intervals.

    Uses a coarse-to-fine normalised cross-correlation search so that dense
    dialogue cannot produce a flat overlap plateau (the previous overlap-only
    scoring returned near-100% confidence for almost every offset).

    Returns (best_offset, confidence_0_to_1).
    """
    if not cues or not speech_intervals:
        return 0.0, 0.0

    cues = sorted(((float(s), float(e)) for s, e in cues if float(e) > float(s)), key=lambda c: c[0])
    speech_intervals = sorted(
        ((float(s), float(e)) for s, e in speech_intervals if float(e) > float(s)),
        key=lambda c: c[0],
    )
    if not cues or not speech_intervals:
        return 0.0, 0.0

    speech_end = max(s[1] for s in speech_intervals)
    min_offset = float(min_offset)
    max_offset = float(max_offset)
    if max_offset < min_offset:
        min_offset, max_offset = max_offset, min_offset

    # ── Stage 1: coarse search over the full range ──────────────────────────
    coarse_step = 0.25
    span = max_offset - min_offset
    coarse_offsets = [
        min_offset + i * coarse_step
        for i in range(int(math.floor(span / coarse_step)) + 1)
    ]
    if coarse_offsets[-1] < max_offset - 0.01:
        coarse_offsets.append(max_offset)

    scores, overlaps, speech_coverage = _score_offsets(
        cues, speech_intervals, coarse_offsets, coarse_step
    )
    if not scores:
        return 0.0, 0.0

    best_i = max(range(len(scores)), key=lambda i: scores[i])
    best_score = scores[best_i]
    coarse_offset = coarse_offsets[best_i]

    # If speech detection saw (almost) no silence the pattern carries no
    # usable information; refuse to guess rather than shift subtitles randomly.
    if speech_coverage >= 0.97:
        return 0.0, 0.1
    if best_score <= 0.08:
        return 0.0, 0.1

    # ── Stage 2: fine search around the coarse peak ─────────────────────────
    fine_step = max(0.02, min(0.05, float(step) if step and step > 0 else 0.05))
    fine_min = max(min_offset, coarse_offset - coarse_step)
    fine_max = min(max_offset, coarse_offset + coarse_step)
    fine_offsets: List[float] = []
    k = fine_min
    while k <= fine_max + 1e-9:
        fine_offsets.append(round(k, 4))
        k += fine_step
    if not fine_offsets:
        fine_offsets = [coarse_offset]

    fine_scores, fine_overlaps, _ = _score_offsets(
        cues, speech_intervals, fine_offsets, fine_step
    )
    if fine_scores:
        best_j = max(range(len(fine_scores)), key=lambda i: fine_scores[i])
        if fine_scores[best_j] >= best_score - 0.02:
            best_offset = fine_offsets[best_j]
            best_score = fine_scores[best_j]
            best_overlap = fine_overlaps[best_j]
        else:
            best_offset = coarse_offset
            best_overlap = overlaps[best_i]
    else:
        best_offset = coarse_offset
        best_overlap = overlaps[best_i]

    best_offset = max(min_offset, min(max_offset, best_offset))
    # Subtitle cues within 150ms are perceptually imperceptible;
    # treat anything inside that narrow window as "already in sync".
    if abs(best_offset) < 0.15:
        best_offset = 0.0

    # Peak-to-background prominence. A correct alignment produces one sharp
    # peak; an ambiguous one sits on a broad plateau.
    ordered = sorted(scores)
    baseline = ordered[len(ordered) // 2]
    prominence = (best_score - baseline) / max(1e-6, 1.0 - baseline)
    prominence = max(0.0, min(1.0, prominence))

    support = max(0.0, min(1.0, best_overlap))
    confidence = 0.20 + 0.50 * prominence + 0.30 * support
    if best_score < 0.15:
        confidence = min(confidence, 0.2)
    if best_score < 0.30:
        confidence = min(confidence, 0.45)

    confidence = round(max(0.0, min(1.0, confidence)), 2)
    return round(best_offset, 3), confidence


def _dominant_delta(
    target_starts: List[float],
    reference_starts: List[float],
    max_delta: float,
) -> Tuple[float, List[float], int]:
    """
    Finds the dominant rigid offset between two sorted cue-start lists using
    all-pairs voting (not just nearest neighbour, which aliases by the cue
    spacing when subtitle lines are regularly spaced).

    Returns (median_offset, inlier_deltas, supported_target_count).
    """
    refs = reference_starts
    n_refs = len(refs)
    if n_refs == 0 or not target_starts:
        return 0.0, [], 0

    sampled = target_starts[:400]
    deltas_by_target: List[List[float]] = []
    flat: List[float] = []

    for t in sampled:
        lo = bisect.bisect_left(refs, t - max_delta)
        hi = bisect.bisect_left(refs, t + max_delta)
        row = [refs[j] - t for j in range(lo, hi)]
        deltas_by_target.append(row)
        flat.extend(row)

    if not flat:
        return 0.0, [], 0

    # Densest 0.5s cluster wins (robust against differently segmented tracks).
    ordered = sorted(flat)
    best_lo = 0
    best_hi = 0
    hi_idx = 0
    for lo_idx in range(len(ordered)):
        while hi_idx < len(ordered) and ordered[hi_idx] - ordered[lo_idx] <= 0.5:
            hi_idx += 1
        if (hi_idx - lo_idx) > (best_hi - best_lo):
            best_lo, best_hi = lo_idx, hi_idx

    cluster = ordered[best_lo:best_hi] or ordered
    median_offset = statistics.median(cluster)

    inliers: List[float] = []
    supported = 0
    for row in deltas_by_target:
        if not row:
            continue
        row_inliers = [d for d in row if abs(d - median_offset) <= 0.6]
        if row_inliers:
            supported += 1
            inliers.extend(row_inliers)

    return median_offset, inliers, supported


def align_to_reference_cues(
    target_cues: List[Tuple[float, float]],
    reference_cues: List[Tuple[float, float]],
    max_delta: float = 120.0,
) -> Tuple[float, float]:
    """
    Aligns target subtitle cues to a container ground-truth reference subtitle track.
    Uses a robust dominant-cluster vote of pairwise start deltas.
    Returns (offset_seconds, confidence_0_to_1).
    """
    if not target_cues or not reference_cues:
        return 0.0, 0.0

    target_starts = sorted(float(c[0]) for c in target_cues)
    reference_starts = sorted(float(c[0]) for c in reference_cues)
    if not target_starts or not reference_starts:
        return 0.0, 0.0

    # Only consider target cues that can actually match the reference span.
    max_ref = reference_starts[-1]
    considered = [t for t in target_starts if t <= max_ref + max_delta]
    if not considered:
        considered = target_starts

    median_offset, inliers, supported = _dominant_delta(considered, reference_starts, max_delta)
    if not inliers:
        return 0.0, 0.0

    considered_sample = considered[:400]
    confidence = supported / max(1, len(considered_sample))
    if supported < 2:
        confidence = min(confidence, 0.5)

    # Ambiguity guard. Dense, regularly spaced cue tracks can match almost any
    # offset within 0.6s (e.g. dialogue every 2s), which made a wrong reference
    # look like a 100% confident alignment. Measure support at decoy offsets
    # that are not multiples of common cue spacings and only trust the margin
    # above the best decoy.
    tolerance = 0.6
    decoy_support = 0.0
    for decoy in (11.11, 23.33, 37.77, 71.19, 103.03, -13.37, -41.41, -83.83):
        hits = 0
        shift = median_offset + decoy
        for t in considered_sample:
            expected = t + shift
            idx = bisect.bisect_left(reference_starts, expected - tolerance)
            if idx < len(reference_starts) and reference_starts[idx] <= expected + tolerance:
                hits += 1
        decoy_support = max(decoy_support, hits / max(1, len(considered_sample)))

    if decoy_support >= 0.98:
        confidence = 0.0
    else:
        confidence = (confidence - decoy_support) / max(1e-6, 1.0 - decoy_support)
    confidence = round(max(0.0, min(1.0, confidence)), 2)
    return round(median_offset, 3), confidence


def align_to_reference_cues_ex(
    target_cues: List[Tuple[float, float]],
    reference_cues: List[Tuple[float, float]],
    max_delta: float = 120.0,
) -> Dict[str, Any]:
    """
    Extended reference alignment that also detects framerate drift.

    Returns:
        {
          "offset": float,
          "confidence": float,
          "drift_model": Optional[{"model": "linear", "params": [a, b], "rmse": float}],
          "matched_cues": int,
        }
    """
    offset, confidence = align_to_reference_cues(target_cues, reference_cues, max_delta)
    result: Dict[str, Any] = {
        "offset": offset,
        "confidence": confidence,
        "drift_model": None,
        "matched_cues": 0,
    }
    if len(target_cues) < 8 or len(reference_cues) < 8:
        return result

    target_starts = sorted(float(c[0]) for c in target_cues)
    reference_starts = sorted(float(c[0]) for c in reference_cues)
    ref_span = reference_starts[-1] - reference_starts[0]
    if ref_span < 30.0:
        return result

    _, inliers, supported = _dominant_delta(target_starts, reference_starts, max_delta)
    result["matched_cues"] = supported

    # If a rigid shift already explains the data almost perfectly, there is no
    # meaningful framerate drift to model.
    if confidence >= 0.85 and inliers:
        residual = statistics.median(abs(d - offset) for d in inliers)
        if residual <= 0.35:
            return result

    # Try discrete framerate conversion ratios. For each candidate scale we
    # re-vote on scaled target starts; a true drift produces a much tighter
    # cluster (higher inlier ratio) than the unscaled fit.
    best: Optional[Tuple[float, float, int, float]] = None  # (scale, offset, inliers, ratio)
    for scale in (1.0, *_FRAMERATE_SCALES):
        scaled = [t * scale for t in target_starts]
        cand_offset, cand_inliers, cand_supported = _dominant_delta(scaled, reference_starts, max_delta)
        if not cand_inliers:
            continue
        considered = sum(
            1
            for t in scaled
            if reference_starts[0] - max_delta <= t <= reference_starts[-1] + max_delta
        )
        ratio = cand_supported / max(1, min(considered, 400))
        if best is None or (ratio, cand_supported) > (best[3], best[2]):
            best = (scale, cand_offset, cand_supported, ratio)

    if best is None:
        return result

    scale, scaled_offset, inlier_count, inlier_ratio = best

    # Keep the rigid fit when scaling does not materially improve support.
    if scale == 1.0:
        # Do not overwrite the decoy-corrected confidence with the raw inlier
        # ratio: for dense/regular tracks the raw ratio is inflated and the
        # ambiguity guard above is the trustworthy signal.
        result["confidence"] = round(max(0.0, min(1.0, confidence)), 2)
        result["offset"] = round(offset, 3)
        return result
    if inlier_count < 8 or inlier_ratio < max(0.35, confidence):
        return result

    # Refit precisely on the matched pairs using the ORIGINAL cue timeline, so
    # the returned model is directly applicable to the client-side cues.
    def _pair_samples(scale_value: float, base_offset: float, tolerance: float) -> List[Tuple[float, float]]:
        pairs: List[Tuple[float, float]] = []
        last_idx = -1
        for t in target_starts:
            expected = t * scale_value + base_offset
            lo = bisect.bisect_left(reference_starts, expected - tolerance)
            hi = bisect.bisect_left(reference_starts, expected + tolerance)
            best_i = None
            best_d = tolerance
            for idx in range(max(lo, last_idx + 1), hi):
                d = abs(reference_starts[idx] - expected)
                if d < best_d:
                    best_i = idx
                    best_d = d
            if best_i is not None:
                pairs.append((t, reference_starts[best_i]))
                last_idx = best_i
        return pairs

    gap_estimate = 3.0
    if len(target_starts) > 1:
        gaps = [b - a for a, b in zip(target_starts, target_starts[1:]) if 0.2 < (b - a) < 12.0]
        if gaps:
            gap_estimate = statistics.median(gaps)
    tolerance = max(1.0, min(4.0, gap_estimate * 0.6))

    from core.subtitle_sync.drift import DriftModel

    pairs = _pair_samples(scale, scaled_offset, tolerance)
    fitted = None
    for _ in range(3):
        if len(pairs) < 6:
            break
        fitted = DriftModel.fit_drift([p[0] for p in pairs], [p[1] for p in pairs])
        if fitted.get("model") != "linear":
            break
        a, b = fitted["params"]
        # Trim gross outliers (usually cues missing from one of the tracks)
        # and re-pair using the newly fitted model.
        trimmed = [
            (t, r) for t, r in pairs
            if abs((t + a * t + b) - r) <= 1.5
        ]
        if len(trimmed) < 6 or len(trimmed) == len(pairs):
            break
        pairs = _pair_samples(1.0 + a, b, tolerance)
        fitted = DriftModel.fit_drift([p[0] for p in pairs], [p[1] for p in pairs])

    if not fitted or len(pairs) < 6 or (pairs[-1][0] - pairs[0][0]) < 45.0:
        return result

    slope = fitted["params"][0] if fitted.get("params") else 0.0
    rmse = fitted.get("rmse", 1.0)
    if fitted.get("model") == "linear" and abs(slope) > 0.0004 and rmse <= 0.75:
        result["drift_model"] = {
            "model": "linear",
            "params": [round(slope, 6), round(fitted["params"][1], 4)],
            "rmse": rmse,
            "scale": round(scale, 6),
        }
        result["offset"] = round(fitted["params"][1], 3)
        result["confidence"] = round(min(1.0, 0.8 + 0.2 * inlier_ratio), 2)
        result["matched_cues"] = len(pairs)

    return result


async def extract_speech_intervals_from_stream(
    source_url: str,
    duration: float = 90.0,
    noise_db: int = -30,
    start_time: float = 0.0,
) -> List[Tuple[float, float]]:
    """
    Runs fast FFmpeg silencedetect on the audio stream and parses active speech intervals.
    Includes network reconnect resilience and stereo downmix for robust surround detection.
    When start_time > 0, seeks to start_time and shifts parsed intervals to absolute stream PTS.
    """
    ffmpeg_bin = find_ffmpeg() or "ffmpeg"
    duration = max(5.0, float(duration))
    start_time = max(0.0, float(start_time or 0.0))
    cmd = [
        ffmpeg_bin,
        "-hide_banner",
        "-loglevel", "info",
    ]
    if source_url.startswith("http"):
        cmd.extend([
            "-reconnect", "1",
            "-reconnect_at_eof", "1",
            "-reconnect_streamed", "1",
            "-reconnect_on_network_error", "1",
            "-reconnect_delay_max", "5",
        ])
    cmd.extend([
        "-ss", f"{start_time:.2f}",
        "-t", str(duration),
        "-i", source_url,
        "-vn",
        "-map", "0:a:0?",
        "-ac", "2",
        "-af", f"silencedetect=noise={noise_db}dB:d=0.35",
        "-f", "null",
        "-",
    ])

    # Budget roughly 0.6x realtime plus header/swarm warm-up.
    timeout = max(35.0, duration * 0.6 + 20.0)
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            _, stderr_data = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            try:
                proc.kill()
            except Exception:
                pass
            try:
                _, stderr_data = await proc.communicate()
            except Exception:
                stderr_data = b""

        stderr_text = stderr_data.decode("utf-8", errors="replace") if stderr_data else ""
        raw_intervals = parse_silencedetect_output(stderr_text, total_duration=duration)
        if start_time > 0:
            return [(round(s + start_time, 3), round(e + start_time, 3)) for s, e in raw_intervals]
        return raw_intervals
    except Exception as e:
        app_logger.warning(f"[SubtitleSync] Speech extraction failed: {e}")
        return []
