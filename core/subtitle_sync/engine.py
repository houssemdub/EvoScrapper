"""
core/subtitle_sync/engine.py — Unified Multi-Modal Subtitle Synchronization Engine v2.
Fuses audio VAD, embedded reference tracks, external subtitle consensus,
forced subtitle filtering, framerate drift modeling, and adaptive playback controllers.
"""
import asyncio
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from core.logger import app_logger
from core.subtitle_sync.adaptive import AdaptiveSyncController
from core.subtitle_sync.consensus import ConsensusSync, SyncCandidate, calibrate_confidence
from core.subtitle_sync.drift import DriftModel
from core.subtitle_sync.forced_subs import detect_forced_subtitles, filter_for_sync
from core.subtitle_sync.vad import (
    align_to_reference_cues,
    compute_optimal_offset,
    extract_speech_intervals_from_stream,
)


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

        candidates: List[SyncCandidate] = []
        tasks = []

        # 2. Signal A: Embedded Reference Track
        if reference_cues:
            ref_mask = detect_forced_subtitles(reference_cues)
            clean_ref = filter_for_sync(reference_cues, ref_mask) or reference_cues
            ref_cue_times = [(r[0], r[1]) for r in clean_ref]
            offset, conf = align_to_reference_cues(target_cue_times, ref_cue_times)
            if conf > 0.3:
                candidates.append(
                    SyncCandidate(
                        offset=offset,
                        confidence=conf,
                        method="embedded_ref",
                        metadata={"ref_cues_count": len(ref_cue_times)},
                    )
                )

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
        async def _run_vad() -> Optional[SyncCandidate]:
            if not video_source:
                return None
            try:
                speech = await extract_speech_intervals_from_stream(video_source, duration=180.0)
                if speech:
                    offset, conf = compute_optimal_offset(target_cue_times, speech)
                    if conf > 0.2:
                        return SyncCandidate(
                            offset=offset,
                            confidence=conf,
                            method="audio_vad",
                            metadata={"speech_intervals": len(speech)},
                        )
            except Exception as e:
                app_logger.warning(f"[SubtitleSyncEngine] VAD analysis failed: {e}")
            return None

        vad_task = asyncio.create_task(_run_vad())
        vad_candidate = await vad_task
        if vad_candidate is not None:
            candidates.append(vad_candidate)

        if not candidates:
            return SyncResult(
                success=False,
                offset=0.0,
                confidence=0.0,
                method="none",
                signals_used=[],
                message="No alignment signals succeeded",
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

        # 6. Framerate Drift Modeling
        drift_model = None
        # If we have a reliable reference (embedded or external) with enough points
        ref_for_drift = None
        if reference_cues:
            ref_for_drift = [(r[0], r[1]) for r in reference_cues]
        elif external_cues_list and external_cues_list[0]:
            ref_for_drift = [(e[0], e[1]) for e in external_cues_list[0]]

        if ref_for_drift and len(target_cue_times) >= 5 and len(ref_for_drift) >= 5:
            # Pair target cue starts with nearest reference cue starts
            paired_targets: List[float] = []
            paired_refs: List[float] = []
            for t_start, _ in target_cue_times[:30]:
                nearest = min(ref_for_drift, key=lambda r: abs(r[0] - (t_start + final_offset)))
                if abs(nearest[0] - (t_start + final_offset)) <= 2.0:
                    paired_targets.append(t_start)
                    paired_refs.append(nearest[0])

            if len(paired_targets) >= 5:
                fitted = DriftModel.fit_drift(paired_targets, paired_refs)
                # Check if slope indicates real framerate mismatch (|a| > 0.0005)
                slope = abs(fitted["params"][0]) if fitted.get("params") else 0.0
                if slope > 0.0005 and fitted.get("rmse", 1.0) < 0.35:
                    drift_model = fitted

        # 7. Adaptive Real-Time Controller instantiation
        adaptive_ctrl = AdaptiveSyncController(
            initial_offset=final_offset,
            initial_confidence=final_conf,
        )

        return SyncResult(
            success=True,
            offset=final_offset,
            confidence=final_conf,
            method=final_method,
            signals_used=signals_used,
            drift_model=drift_model,
            adaptive_controller=adaptive_ctrl,
            cues_analyzed=len(clean_cues),
        )
