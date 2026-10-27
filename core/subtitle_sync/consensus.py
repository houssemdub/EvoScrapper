"""
core/subtitle_sync/consensus.py — Multi-Source Consensus Alignment Engine.
Uses RANSAC consensus clustering and confidence-weighted voting across multiple
subtitle tracks, audio VAD signals, and embedded reference tracks.
"""
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class SyncCandidate:
    offset: float
    confidence: float
    method: str
    metadata: Dict[str, Any] = field(default_factory=dict)


CONFIDENCE_THRESHOLDS = {
    "embedded_ref": 0.95,
    "fingerprint": 0.85,
    "audio_vad": 0.80,
    "visual_scenes": 0.70,
    "external_consensus": 0.85,
    "consensus": 0.90,
}


def calibrate_confidence(method: str, raw_conf: float, num_signals: int) -> float:
    """
    Calibrates candidate confidence, boosting agreement when multiple distinct signals agree.
    """
    base = CONFIDENCE_THRESHOLDS.get(method, 0.75)
    # Multi-signal agreement boost: up to +0.20
    boost = min(0.08 * max(0, num_signals - 1), 0.20)
    score = (base * 0.4) + (raw_conf * 0.6) + boost
    return round(min(score, 0.99), 2)


class ConsensusSync:
    """
    Fuses multiple synchronization candidates using RANSAC clustering and weighted voting.
    """

    def __init__(self, min_consensus: int = 2, max_outlier_sec: float = 1.5):
        self.min_consensus = min_consensus
        self.max_outlier = max_outlier_sec
        self.candidates: List[SyncCandidate] = []

    def add_candidate(self, candidate: SyncCandidate) -> None:
        if candidate is not None:
            self.candidates.append(candidate)

    def compute_consensus(self, candidates: Optional[List[SyncCandidate]] = None) -> Optional[SyncCandidate]:
        pool = candidates if candidates is not None else self.candidates
        if not pool:
            return None

        if len(pool) == 1:
            return pool[0]

        offsets = [c.offset for c in pool]
        weights = [max(0.01, c.confidence) for c in pool]

        # RANSAC clustering: find center with highest aggregate inlier weight
        best_cluster: List[int] = []
        best_weight = -1.0

        for i, center in enumerate(offsets):
            cluster = [j for j, o in enumerate(offsets) if abs(o - center) <= self.max_outlier]
            cluster_weight = sum(weights[j] for j in cluster)
            if cluster_weight > best_weight or (cluster_weight == best_weight and len(cluster) > len(best_cluster)):
                best_weight = cluster_weight
                best_cluster = cluster

        # If not enough candidates reached consensus, fallback to the highest confidence candidate
        if len(best_cluster) < self.min_consensus:
            highest_conf_candidate = max(pool, key=lambda c: c.confidence)
            return highest_conf_candidate

        inliers = [pool[idx] for idx in best_cluster]
        inlier_offsets = [c.offset for c in inliers]
        inlier_weights = [max(0.01, c.confidence) for c in inliers]

        total_inlier_weight = sum(inlier_weights)
        final_offset = sum(o * w for o, w in zip(inlier_offsets, inlier_weights)) / total_inlier_weight

        # Distinct methods represented in the consensus cluster
        methods = list(set(c.method for c in inliers))
        avg_raw_conf = sum(c.confidence for c in inliers) / len(inliers)
        calibrated_conf = calibrate_confidence("consensus", avg_raw_conf, len(methods))

        return SyncCandidate(
            offset=round(final_offset, 2),
            confidence=calibrated_conf,
            method="consensus",
            metadata={
                "cluster_size": len(inliers),
                "total_candidates": len(pool),
                "methods": [c.method for c in inliers],
                "distinct_methods": methods,
            },
        )
