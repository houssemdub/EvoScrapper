"""
Swarm Intelligence Layer (Beyond-Stremio P1/P2/P3).

Collective, decentralized playback intelligence gossiped over CometNet:
- SeekHeatmapStore (P1): anonymous quantized seek events, aggregated per
  info_hash, drive predictive piece pre-warming at likely seek targets.
- DebridCoverageIndex (P2): which debrid providers reportedly hold which
  hashes, with recency x corroboration confidence, to order resolve attempts.
- derive_scene_boundaries (P3): behavioral intro/credits/scene hotspots from
  the seek heatmap. Zero ML, purely observational.

Privacy: info-hash level data only — no IPs, accounts, or titles. All gossip
messages are Ed25519-signed by the CometNet node before leaving the machine.
"""
import json
import math
import os
import time
from collections import defaultdict
from typing import Any, Dict, List, Optional, Tuple

SEEK_BUCKET_SECONDS = 30.0
HEATMAP_DECAY_HALF_LIFE_HOURS = 72.0
HEATMAP_MAX_BUCKETS_PER_HASH = 64
HEATMAP_MAX_HASHES = 2000
COVERAGE_TTL_HOURS = 24.0
COVERAGE_MAX_HASHES = 5000
SEEK_HINT_WINDOW_SECONDS = 120.0
SCENE_MIN_WEIGHT = 3.0


def _atomic_write_json(path: str, data: Dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = f"{path}.tmp.{os.getpid()}.{time.time_ns()}"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, separators=(",", ":"))
    os.replace(tmp, path)


def _read_json(path: str) -> Dict[str, Any]:
    try:
        if os.path.isfile(path):
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                return data
    except Exception:
        pass
    return {}


class SeekHeatmapStore:
    """
    P1: per-hash seek heat. Buckets are 30-second slots; each observation is a
    seek LANDING bucket. Weights decay with a 72h half-life so stale titles
    fade out of the forecast.
    """

    def __init__(self, path: Optional[str] = None):
        self.path = path or os.path.join("data", "cometnet", "seek_heatmap.json")
        raw = _read_json(self.path)
        # hash -> {bucket_index: weight}
        self._heat: Dict[str, Dict[int, float]] = {}
        for h, buckets in raw.items():
            try:
                self._heat[str(h)[:64]] = {int(b): float(w) for b, w in buckets.items()}
            except Exception:
                continue
        self._dirty = False

    @staticmethod
    def bucket_for(position_seconds: float) -> int:
        try:
            pos = float(position_seconds)
        except (TypeError, ValueError):
            return -1
        if not math.isfinite(pos) or pos < 0:
            return -1
        return int(pos // SEEK_BUCKET_SECONDS)

    def _decay_factor(self, recorded_at: float) -> float:
        age_hours = max(0.0, (time.time() - recorded_at) / 3600.0)
        if age_hours < 0.1:
            return 1.0
        return 0.5 ** (age_hours / HEATMAP_DECAY_HALF_LIFE_HOURS)

    def record(self, info_hash: str, position_seconds: float, weight: float = 1.0, recorded_at: Optional[float] = None) -> None:
        h = (info_hash or "").strip().lower()
        bucket = self.bucket_for(position_seconds)
        if not h or bucket < 0 or weight <= 0:
            return
        decay = self._decay_factor(recorded_at if recorded_at is not None else time.time())
        buckets = self._heat.setdefault(h, {})
        buckets[bucket] = buckets.get(bucket, 0.0) + weight * decay
        self._prune_hash(h)
        self._dirty = True
        self.save()

    def _prune_hash(self, info_hash: str) -> None:
        buckets = self._heat.get(info_hash)
        if buckets and len(buckets) > HEATMAP_MAX_BUCKETS_PER_HASH:
            top = sorted(buckets.items(), key=lambda kv: kv[1], reverse=True)[:HEATMAP_MAX_BUCKETS_PER_HASH]
            self._heat[info_hash] = dict(top)
        if len(self._heat) > HEATMAP_MAX_HASHES:
            # Drop hashes whose total residual heat is lowest.
            totals = sorted(
                ((h, sum(b.values())) for h, b in self._heat.items()),
                key=lambda kv: kv[1],
            )
            for h, _ in totals[: len(self._heat) - HEATMAP_MAX_HASHES]:
                self._heat.pop(h, None)

    def top_seek_targets(self, info_hash: str, k: int = 3, min_weight: float = 1.0) -> List[Dict[str, float]]:
        h = (info_hash or "").strip().lower()
        buckets = self._heat.get(h, {})
        ranked = sorted(
            ((b, w) for b, w in buckets.items() if w >= min_weight),
            key=lambda kv: kv[1],
            reverse=True,
        )[: max(0, k)]
        return [
            {"position": b * SEEK_BUCKET_SECONDS, "bucket": b, "weight": round(w, 2)}
            for b, w in ranked
        ]

    def bucket_count(self, info_hash: str) -> int:
        return len(self._heat.get((info_hash or "").strip().lower(), {}))

    def save(self) -> None:
        if not self._dirty:
            return
        payload = {h: {str(b): w for b, w in buckets.items()} for h, buckets in self._heat.items()}
        try:
            _atomic_write_json(self.path, payload)
            self._dirty = False
        except Exception:
            pass


class DebridCoverageIndex:
    """
    P2: gossip-fed hash -> provider coverage with recency x corroboration
    confidence. Live provider probes always confirm before streaming; this
    index only orders the attempts.
    """

    def __init__(self, path: Optional[str] = None):
        self.path = path or os.path.join("data", "cometnet", "debrid_coverage.json")
        raw = _read_json(self.path)
        # hash -> {provider: {"ts": float, "hits": int}}
        self._index: Dict[str, Dict[str, Dict[str, float]]] = {}
        for h, providers in raw.items():
            if not isinstance(providers, dict):
                continue
            self._index[str(h)[:64]] = {
                str(p)[:32]: {"ts": float(v.get("ts", 0.0)), "hits": float(v.get("hits", 1))}
                for p, v in providers.items() if isinstance(v, dict)
            }

    def _decay(self, ts: float) -> float:
        age_hours = max(0.0, (time.time() - ts) / 3600.0)
        if age_hours >= COVERAGE_TTL_HOURS:
            return 0.0
        return 0.5 ** (age_hours / (COVERAGE_TTL_HOURS / 2))

    def record(self, info_hash: str, provider: str, observed_at: Optional[float] = None, corroborated: bool = False) -> None:
        h = (info_hash or "").strip().lower()
        p = (provider or "").strip().lower()
        if not h or not p:
            return
        entry = self._index.setdefault(h, {})
        cur = entry.get(p, {"ts": 0.0, "hits": 0.0})
        ts = observed_at if observed_at is not None else time.time()
        entry[p] = {"ts": max(cur["ts"], ts), "hits": cur["hits"] + (2.0 if corroborated else 1.0)}
        if len(entry) > 8:
            best = sorted(entry.items(), key=lambda kv: kv[1]["ts"], reverse=True)[:8]
            self._index[h] = dict(best)
        if len(self._index) > COVERAGE_MAX_HASHES:
            oldest = sorted(self._index.items(), key=lambda kv: max((v["ts"] for v in kv[1].values()), default=0.0))
            for h_old, _ in oldest[: len(self._index) - COVERAGE_MAX_HASHES]:
                self._index.pop(h_old, None)
        self.save()

    def providers_for(self, info_hash: str) -> List[Dict[str, Any]]:
        h = (info_hash or "").strip().lower()
        out = []
        for p, v in self._index.get(h, {}).items():
            confidence = self._decay(v["ts"]) * min(3.0, v["hits"])
            if confidence > 0:
                out.append({"provider": p, "confidence": round(confidence, 3), "hits": v["hits"], "age_hours": round((time.time() - v["ts"]) / 3600.0, 2)})
        out.sort(key=lambda item: item["confidence"], reverse=True)
        return out

    def stats(self) -> Dict[str, Any]:
        total_hashes = len(self._index)
        total_providers = sum(len(p) for p in self._index.values())
        return {"tracked_hashes": total_hashes, "provider_entries": total_providers}

    def save(self) -> None:
        try:
            _atomic_write_json(self.path, self._index)
        except Exception:
            pass


def derive_scene_boundaries(
    heat_targets: List[Dict[str, Any]],
    total_duration_seconds: float,
    min_weight: float = SCENE_MIN_WEIGHT,
) -> List[Dict[str, Any]]:
    """
    P3: classify hot seek-landing buckets as behavioral scene boundaries.
    First 10% of the runtime -> intro, last 15% -> credits, otherwise scene.
    Spans are +/- one bucket around the landing point.
    """
    if not heat_targets or total_duration_seconds <= 0:
        return []
    scenes = []
    for target in sorted(heat_targets, key=lambda t: t["position"]):
        if target["weight"] < min_weight:
            continue
        pos = target["position"]
        span = SEEK_BUCKET_SECONDS * 2
        kind = "scene"
        if pos <= total_duration_seconds * 0.10:
            kind = "intro"
        elif pos >= total_duration_seconds * 0.85:
            kind = "credits"
        scenes.append({
            "type": kind,
            "start": max(0.0, pos - span),
            "end": min(total_duration_seconds, pos + span),
            "confidence": round(min(1.0, target["weight"] / 10.0), 2),
        })
    # Merge adjacent same-kind boundaries.
    merged: List[Dict[str, Any]] = []
    for scene in scenes:
        if merged and scene["type"] == merged[-1]["type"] and scene["start"] <= merged[-1]["end"]:
            merged[-1]["end"] = max(merged[-1]["end"], scene["end"])
            merged[-1]["confidence"] = max(merged[-1]["confidence"], scene["confidence"])
        else:
            merged.append(dict(scene))
    return merged


_heatmap_store: Optional[SeekHeatmapStore] = None
_coverage_store: Optional[DebridCoverageIndex] = None


def get_seek_heatmap() -> SeekHeatmapStore:
    global _heatmap_store
    if _heatmap_store is None:
        _heatmap_store = SeekHeatmapStore()
    return _heatmap_store


def get_coverage_index() -> DebridCoverageIndex:
    global _coverage_store
    if _coverage_store is None:
        _coverage_store = DebridCoverageIndex()
    return _coverage_store
