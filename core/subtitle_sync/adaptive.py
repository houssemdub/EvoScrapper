"""
core/subtitle_sync/adaptive.py — Real-Time Adaptive Subtitle Synchronization Controller.
Learns from interactive user corrections (e.g. 'H' / 'J' delay keys during playback)
and converges to frame-accurate alignment using temporal proximity weighting.
"""
import asyncio
from collections import deque
import math
import time
from typing import Deque, List, Optional, Tuple


class AdaptiveSyncController:
    """
    Stateful controller maintaining active sync offset during client playback session.
    Thread/asyncio-safe using asyncio.Lock.
    """

    def __init__(self, initial_offset: float = 0.0, initial_confidence: float = 0.5):
        self.offset: float = float(initial_offset)
        self.initial_confidence: float = float(initial_confidence)
        # Records: list of [position_sec, current_total_offset, timestamp]
        self.corrections: List[List[float]] = []
        self._lock = asyncio.Lock()

    async def apply_user_correction(self, position_sec: float, delta_ms: int) -> float:
        """
        User pressed hotkey (H/J) to adjust delay by delta_ms.
        Positive delta_ms delays subtitles, negative advances subtitles.
        Rapid consecutive taps within the same playback segment coalesce into the cumulative offset.
        Returns the updated offset.
        """
        delta_sec = delta_ms / 1000.0
        now = time.time()
        async with self._lock:
            self.offset = round(self.offset + delta_sec, 4)
            # If the latest correction was in the same playback window (within 45s) and made recently (<45s ago),
            # coalesce it into the new cumulative offset rather than keeping intermediate steps.
            if (
                self.corrections
                and abs(self.corrections[-1][0] - position_sec) <= 45.0
                and (now - self.corrections[-1][2]) <= 45.0
            ):
                self.corrections[-1] = [float(position_sec), self.offset, now]
            else:
                self.corrections.append([float(position_sec), self.offset, now])
                if len(self.corrections) > 50:
                    self.corrections.pop(0)

            return self.offset

    def get_offset(self, position_sec: float) -> float:
        """
        Retrieves the recommended offset for a given playback position.
        Uses exponential proximity weighting if corrections exist across the timeline.
        """
        if not self.corrections:
            return round(self.offset, 3)

        # Weight recent corrections near position_sec
        weights: List[float] = []
        offsets: List[float] = []

        for pos, off, _ in self.corrections:
            dist = abs(pos - position_sec)
            # 180s half-life for temporal influence
            w = math.exp(-dist / 180.0)
            weights.append(w)
            offsets.append(off)

        total_w = sum(weights)
        if total_w < 1e-6:
            return round(self.offset, 3)

        weighted_offset = sum(o * w for o, w in zip(offsets, weights)) / total_w
        return round(weighted_offset, 3)

    def get_confidence(self) -> float:
        """
        Calculates confidence score based on consistency of recent corrections.
        """
        if not self.corrections:
            return round(self.initial_confidence, 2)

        if len(self.corrections) == 1:
            return 0.75

        # Calculate standard deviation of offsets in the last 10 corrections
        recent = [off for _, off, _ in self.corrections[-10:]]
        mean_off = sum(recent) / len(recent)
        variance = sum((x - mean_off) ** 2 for x in recent) / len(recent)
        std_dev = math.sqrt(variance)

        # If std_dev <= 0.2s, user has settled on an offset -> high confidence (up to 0.95)
        consistency = 1.0 - min(std_dev / 0.8, 1.0)
        conf = 0.60 + (0.35 * consistency)
        return round(min(conf, 0.95), 2)
