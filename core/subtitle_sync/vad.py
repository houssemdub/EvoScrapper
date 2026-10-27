"""
core/subtitle_sync/vad.py — Voice Activity Detection (VAD) via FFmpeg silencedetect.
Extracts active speech intervals and computes cross-track cue alignment.
"""
import asyncio
import os
import re
import statistics
from typing import Any, Dict, List, Optional, Tuple

from core.logger import app_logger
from core.transmuxer import find_ffmpeg


def parse_silencedetect_output(stderr_text: str, total_duration: float = 180.0) -> List[Tuple[float, float]]:
    """
    Parses FFmpeg silencedetect output and derives speech (non-silent) intervals.
    Lines resemble:
      [silencedetect @ ...] silence_start: 12.45
      [silencedetect @ ...] silence_end: 18.20 | silence_duration: 5.75
    """
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

    if current_start is not None and current_start < total_duration:
        silences.append((current_start, total_duration))

    # Invert silence intervals to produce active speech intervals
    speech: List[Tuple[float, float]] = []
    cur_pos = 0.0

    for s_start, s_end in silences:
        if s_start > cur_pos + 0.3:  # minimum speech threshold: 300ms
            speech.append((cur_pos, s_start))
        cur_pos = max(cur_pos, s_end)

    if cur_pos + 0.3 < total_duration:
        speech.append((cur_pos, total_duration))

    return speech


def compute_optimal_offset(
    cues: List[Tuple[float, float]],
    speech_intervals: List[Tuple[float, float]],
    min_offset: float = -30.0,
    max_offset: float = 30.0,
    step: float = 0.1,
) -> Tuple[float, float]:
    """
    Finds the time shift delta_t in [min_offset, max_offset] that maximizes
    overlap between shifted subtitle cues and detected audio speech intervals.
    Returns (best_offset, confidence_0_to_1).
    """
    if not cues or not speech_intervals:
        return 0.0, 0.0

    # Bound cues to the analyzed speech window (e.g. first 5 minutes)
    max_speech_time = max((s[1] for s in speech_intervals), default=180.0)
    sample_cues = [c for c in cues if c[0] <= max_speech_time + abs(max_offset)]
    if not sample_cues:
        sample_cues = cues[:40]

    total_cue_duration = sum(max(0.1, c[1] - c[0]) for c in sample_cues)
    if total_cue_duration <= 0:
        return 0.0, 0.0

    best_offset = 0.0
    best_score = -1.0

    steps = int((max_offset - min_offset) / step)
    for i in range(steps + 1):
        offset = min_offset + (i * step)
        score = 0.0

        for c_start, c_end in sample_cues:
            shifted_start = c_start + offset
            shifted_end = c_end + offset
            if shifted_end <= 0 or shifted_start >= max_speech_time:
                continue

            for s_start, s_end in speech_intervals:
                # Fast rejection if no overlap possible
                if s_end <= shifted_start:
                    continue
                if s_start >= shifted_end:
                    break
                overlap = max(0.0, min(shifted_end, s_end) - max(shifted_start, s_start))
                score += overlap

        if score > best_score:
            best_score = score
            best_offset = offset

    confidence = round(min(1.0, max(0.0, best_score / total_cue_duration)), 2)
    return round(best_offset, 2), confidence


def align_to_reference_cues(
    target_cues: List[Tuple[float, float]],
    reference_cues: List[Tuple[float, float]],
    max_delta: float = 15.0,
) -> Tuple[float, float]:
    """
    Aligns target subtitle cues to a container ground-truth reference subtitle track.
    Calculates the median delta between nearest neighbor cues.
    Returns (offset_seconds, confidence_0_to_1).
    """
    if not target_cues or not reference_cues:
        return 0.0, 0.0

    # Sample the first 50 cues
    targets = target_cues[:50]
    refs = reference_cues[:80]
    deltas: List[float] = []

    for t_start, _ in targets:
        # Find nearest reference cue start
        nearest_delta = min((r_start - t_start for r_start, _ in refs), key=abs)
        if abs(nearest_delta) <= max_delta:
            deltas.append(nearest_delta)

    if not deltas:
        return 0.0, 0.0

    median_offset = statistics.median(deltas)
    # Confidence is determined by how closely clustered deltas are around the median
    consistent_count = sum(1 for d in deltas if abs(d - median_offset) <= 0.6)
    confidence = round(consistent_count / len(deltas), 2)

    return round(median_offset, 2), confidence


async def extract_speech_intervals_from_stream(
    source_url: str,
    duration: float = 90.0,
    noise_db: int = -30,
) -> List[Tuple[float, float]]:
    """
    Runs fast FFmpeg silencedetect on the audio stream and parses active speech intervals.
    Includes network reconnect resilience and stereo downmix for robust surround detection.
    """
    ffmpeg_bin = find_ffmpeg() or "ffmpeg"
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
        "-ss", "0",
        "-t", str(duration),
        "-i", source_url,
        "-vn",
        "-map", "0:a:0?",
        "-ac", "2",
        "-af", f"silencedetect=noise={noise_db}dB:d=0.35",
        "-f", "null",
        "-",
    ])

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            _, stderr_data = await asyncio.wait_for(proc.communicate(), timeout=35.0)
        except asyncio.TimeoutError:
            try:
                proc.kill()
            except Exception:
                pass
            _, stderr_data = await proc.communicate()

        stderr_text = stderr_data.decode("utf-8", errors="replace") if stderr_data else ""
        return parse_silencedetect_output(stderr_text, total_duration=duration)
    except Exception as e:
        app_logger.warning(f"[SubtitleSync] Speech extraction failed: {e}")
        return []
