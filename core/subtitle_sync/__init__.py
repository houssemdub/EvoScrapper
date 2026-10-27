"""
core/subtitle_sync — Subtitle Synchronization Engine v2.
Multi-modal fusion: Audio VAD, Multi-Source Consensus, Drift Modeling, Forced Subtitle Filtering, and Adaptive Real-Time Learning.
"""
from core.subtitle_sync.adaptive import AdaptiveSyncController
from core.subtitle_sync.consensus import ConsensusSync, SyncCandidate, calibrate_confidence
from core.subtitle_sync.drift import DriftModel
from core.subtitle_sync.engine import SubtitleSyncEngine, SyncResult
from core.subtitle_sync.forced_subs import detect_forced_subtitles, filter_for_sync
from core.subtitle_sync.vad import (
    align_to_reference_cues,
    compute_optimal_offset,
    extract_speech_intervals_from_stream,
    parse_silencedetect_output,
)

__all__ = [
    "SubtitleSyncEngine",
    "SyncResult",
    "AdaptiveSyncController",
    "ConsensusSync",
    "SyncCandidate",
    "calibrate_confidence",
    "DriftModel",
    "detect_forced_subtitles",
    "filter_for_sync",
    "parse_silencedetect_output",
    "compute_optimal_offset",
    "align_to_reference_cues",
    "extract_speech_intervals_from_stream",
]
