"""
core/subtitle_sync/engine.py — Unified Multi-Modal Subtitle Synchronization Engine v2.
Fuses audio VAD, embedded reference tracks, external subtitle consensus,
forced subtitle filtering, framerate drift modeling, and adaptive playback controllers.
"""
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from core.logger import app_logger
from core.subtitle_sync.adaptive import AdaptiveSyncController
from core.subtitle_sync.consensus import ConsensusSync, SyncCandidate
from core.subtitle_sync.forced_subs import detect_forced_subtitles, filter_for_sync
from core.subtitle_sync.vad import (
    align_to_reference_cues,
    align_to_reference_cues_ex,
    compute_optimal_offset,
    extract_speech_intervals_from_stream,
)

# Two cue tracks whose start times agree within this tolerance are considered
# the same track (self-reference). Aligning a track against itself is a no-op
# and previously produced a bogus "+0.00s / 100% confidence" auto-sync result.
_SELF_REFERENCE_TOLERANCE = 0.15
_SELF_REFERENCE_RATIO = 0.85


def _is_self_reference(
    target_cues: List[Tuple[float, float, str]],
    reference_cues: List[Tuple[float, float, str]],
) -> bool:
    if not target_cues or not reference_cues:
        return False
    if len(reference_cues) > len(target_cues) * 3 or len(target_cues) > len(reference_cues) * 3:
        return False
    import bisect

    target_starts = sorted(float(c[0]) for c in target_cues)
    ref_starts = sorted(float(c[0]) for c in reference_cues)
    if not target_starts or not ref_starts:
        return False

    matches = 0
    for t in target_starts[:400]:
        idx = bisect.bisect_left(ref_starts, t)
        best = min(
            (abs(ref_starts[j] - t) for j in (idx - 1, idx, idx + 1) if 0 <= j < len(ref_starts)),
            default=1e9,
        )
        if best <= _SELF_REFERENCE_TOLERANCE:
            matches += 1
    return (matches / max(1, min(len(target_starts), 400))) >= _SELF_REFERENCE_RATIO


@dataclass
class SyncResult:
    success: bool
    offset: float                                     # Base shift in seconds
    confidence: float                                 # 0.0 to 1.0 calibrated confidence
    method: str                                       # "consensus", "embedded_ref", "audio_vad", etc.
    signals_used: List[str]                           # List of successful signals fused
    drift_model: Optional[Dict[str, Any]] = None      # Non-linear / framerate drift model if detected
    adaptive_controller: Optional[AdaptiveSyncController] = None
    cues_analyzed: int = 0
    message: Optional[str] = None


class SubtitleSyncEngine:
    """
    Unified Subtitle Synchronization Coordinator.
    Runs multi-signal alignment concurrently and performs RANSAC consensus fusion.
    """

    def __init__(self, min_consensus: int = 2, max_outlier_sec: float = 1.5):
        self.min_consensus = min_consensus
        self.max_outlier_sec = max_outlier_sec

    async def sync(
        self,
        video_source: Optional[str] = None,
        subtitle_cues: Optional[List[Tuple[float, float, str]]] = None,
        reference_cues: Optional[List[Tuple[float, float, str]]] = None,
        external_cues_list: Optional[List[List[Tuple[float, float, str]]]] = None,
        embedded_ref_idx: Optional[int] = None,
        preferred_lang: Optional[str] = None,
        vad_duration: float = 90.0,
        start_time: float = 0.0,
    ) -> SyncResult:
        """
        Coordinates full multi-signal alignment pipeline.
        """
        if not subtitle_cues:
            return SyncResult(
                success=False,
                offset=0.0,
                confidence=0.0,
                method="none",
                signals_used=[],
                message="No subtitle cues provided",
            )

        # 1. Filter out forced subtitles, signs, and screen text
        mask = detect_forced_subtitles(subtitle_cues)
        clean_cues = filter_for_sync(subtitle_cues, mask)
        if not clean_cues:
            # If all cues were filtered, fallback to raw cues
            clean_cues = subtitle_cues

        target_cue_times = [(c[0], c[1]) for c in clean_cues]

        # A reference that is identical to the target track cannot reveal any
        # playback-pipeline offset; ignore it so audio VAD becomes the signal.
        reference_is_self = False
        if reference_cues:
            reference_is_self = _is_self_reference(subtitle_cues, reference_cues)
            if reference_is_self:
                reference_cues = None

        candidates: List[SyncCandidate] = []
        reference_drift: Optional[Dict[str, Any]] = None
        reference_offset: Optional[float] = None
        reference_conf = 0.0

        # 2. Signal A: Embedded Reference Track
        if reference_cues:
            ref_mask = detect_forced_subtitles(reference_cues)
            clean_ref = filter_for_sync(reference_cues, ref_mask) or reference_cues
            ref_cue_times = [(r[0], r[1]) for r in clean_ref]
            aligned = align_to_reference_cues_ex(target_cue_times, ref_cue_times)
            offset = aligned["offset"]
            conf = aligned["confidence"]
            if conf > 0.3:
                reference_offset = offset
                reference_conf = conf
                candidates.append(
                    SyncCandidate(
                        offset=offset,
                        confidence=conf,
                        method="embedded_ref",
                        metadata={"ref_cues_count": len(ref_cue_times)},
                    )
                )
                reference_drift = aligned.get("drift_model")

        # 3. Signal B: External Subtitles Consensus (SubDL, OpenSubtitles, AnimeTosho, etc.)
        if external_cues_list:
            for idx, ext_cues in enumerate(external_cues_list):
                if not ext_cues:
                    continue
                ext_mask = detect_forced_subtitles(ext_cues)
                clean_ext = filter_for_sync(ext_cues, ext_mask) or ext_cues
                ext_cue_times = [(e[0], e[1]) for e in clean_ext]
                offset, conf = align_to_reference_cues(target_cue_times, ext_cue_times)
                if conf > 0.3:
                    candidates.append(
                        SyncCandidate(
                            offset=offset,
                            confidence=conf,
                            method=f"external_ref_{idx}",
                            metadata={"ext_index": idx, "cues_count": len(ext_cue_times)},
                        )
                    )

        # 4. Signal C: Audio Voice Activity Detection (VAD) via FFmpeg silencedetect
        # A high-confidence container reference already pins the timeline
        # exactly. Analysing two minutes of swarm audio would add tens of
        # seconds of latency without changing the answer.
        vad_drift_model = None
        reference_is_authoritative = reference_offset is not None and reference_conf >= 0.85
        if video_source and not reference_is_authoritative:
            try:
                # If start_time not provided, but dialogue only starts later (e.g. after intro),
                # sample audio around the dialogue onset to prevent empty silence matching.
                effective_start = start_time
                if effective_start <= 0.0 and clean_cues and clean_cues[0][0] > 60.0:
                    effective_start = max(0.0, clean_cues[0][0] - 10.0)

                span = (clean_cues[-1][0] - clean_cues[0][0]) if len(clean_cues) >= 2 else 0.0
                is_http_stream = str(video_source).startswith("http")
                # For HTTP streaming sources (torrents), avoid seeking far ahead into unbuffered media
                # which causes piece starvation and times out the VAD task.
                multi_window = span >= 300.0 and not reference_cues and not is_http_stream
                w2_start = round(clean_cues[0][0] + span * 0.5, 1) if multi_window else 0.0

                if multi_window:
                    tasks = [
                        extract_speech_intervals_from_stream(video_source, duration=vad_duration, start_time=effective_start),
                        extract_speech_intervals_from_stream(video_source, duration=min(60.0, vad_duration), start_time=w2_start),
                    ]
                    results = await asyncio.gather(*tasks, return_exceptions=True)
                    speech = results[0] if not isinstance(results[0], Exception) else []
                    speech2 = results[1] if multi_window and not isinstance(results[1], Exception) else []
                else:
                    speech = await extract_speech_intervals_from_stream(
                        video_source, duration=vad_duration, start_time=effective_start
                    )
                    speech2 = []

                vad_offset1 = None
                vad_conf1 = 0.0
                if speech:
                    offset, conf = compute_optimal_offset(target_cue_times, speech)
                    if conf > 0.2:
                        vad_offset1 = offset
                        vad_conf1 = conf
                        candidates.append(
                            SyncCandidate(
                                offset=offset,
                                confidence=conf,
                                method="audio_vad",
                                metadata={"speech_intervals": len(speech)},
                            )
                        )

                if speech2:
                    cues_w2 = [(s, e) for s, e in target_cue_times if w2_start - 30.0 <= s <= w2_start + vad_duration + 30.0]
                    if len(cues_w2) >= 3:
                        offset2, conf2 = compute_optimal_offset(cues_w2, speech2)
                        if conf2 > 0.25:
                            candidates.append(
                                SyncCandidate(
                                    offset=offset2,
                                    confidence=conf2,
                                    method="audio_vad_w2",
                                    metadata={"speech_intervals": len(speech2)},
                                )
                            )
                            # Fit linear drift between window 1 and window 2 if confidence is solid
                            if vad_offset1 is not None and vad_conf1 >= 0.35 and conf2 >= 0.35:
                                dt = w2_start - effective_start
                                if dt >= 180.0:
                                    slope = (offset2 - vad_offset1) / dt
                                    if 0.00015 <= abs(slope) <= 0.08:
                                        intercept = vad_offset1 - slope * effective_start
                                        vad_drift_model = {
                                            "model": "linear",
                                            "params": [round(slope, 6), round(intercept, 3)],
                                            "rmse": 0.0,
                                        }
            except Exception as e:
                app_logger.warning(f"[SubtitleSyncEngine] VAD analysis failed: {e}")

        if not candidates:
            return SyncResult(
                success=False,
                offset=0.0,
                confidence=0.0,
                method="none",
                signals_used=[],
                cues_analyzed=len(clean_cues),
                message=(
                    "Reference track matches the active subtitles and audio analysis "
                    "could not determine an offset"
                    if reference_is_self
                    else "No alignment signals succeeded"
                ),
            )

        # 5. Multi-Source Consensus Fusion
        consensus_engine = ConsensusSync(
            min_consensus=self.min_consensus,
            max_outlier_sec=self.max_outlier_sec,
        )
        for cand in candidates:
            consensus_engine.add_candidate(cand)

        consensus = consensus_engine.compute_consensus()
        if not consensus:
            consensus = max(candidates, key=lambda c: c.confidence)

        final_offset = consensus.offset
        final_conf = consensus.confidence
        final_method = consensus.method
        signals_used = consensus.metadata.get("methods", [c.method for c in candidates])

        # 6. Framerate Drift Modeling (from the container reference track)
        # A drift fit maps the whole timeline, so its constant term is the
        # correct anchor. Averaging it with a VAD offset measured over an early
        # window would bias the anchor by slope * window_midpoint.
        drift_model = None
        if reference_drift is not None and reference_offset is not None:
            drift_params = list(reference_drift.get("params") or [0.0, reference_offset])
            drift_params[1] = reference_offset
            final_offset = round(float(reference_offset), 3)
            final_conf = max(final_conf, reference_conf)
            final_method = "embedded_ref_drift"
            drift_model = dict(reference_drift)
            drift_model["params"] = drift_params
        elif vad_drift_model is not None:
            drift_model = vad_drift_model
            final_method = "audio_vad_drift"

        # 7. Adaptive Real-Time Controller instantiation
        adaptive_ctrl = AdaptiveSyncController(
            initial_offset=final_offset,
            initial_confidence=final_conf,
        )

        message = None
        if reference_is_self:
            message = "Embedded reference matches the active subtitle timing; audio VAD used instead."

        return SyncResult(
            success=True,
            offset=final_offset,
            confidence=final_conf,
            method=final_method,
            signals_used=signals_used,
            drift_model=drift_model,
            adaptive_controller=adaptive_ctrl,
            cues_analyzed=len(clean_cues),
            message=message,
        )
