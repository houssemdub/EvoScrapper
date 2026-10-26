"""P4 dual-source race + P5 quality ladder endpoint tests."""
import asyncio
import sys
import os
from unittest.mock import AsyncMock, patch

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from core.source_racer import race_stream_sources


class TestSourceRacing:
    @pytest.mark.asyncio
    async def test_single_candidate_wins_by_default(self):
        res = await race_stream_sources("http://p2p", None)
        assert res["winner"] == "p2p"
        assert res["raced"] is False
        assert res["backup"] is None

    @pytest.mark.asyncio
    async def test_no_candidates_yields_none(self):
        res = await race_stream_sources(None, None)
        assert res["winner"] is None

    @pytest.mark.asyncio
    async def test_fast_debrid_beats_slow_swarm(self, monkeypatch):
        import core.source_racer as sr

        async def fake_probe(url, api_key=None, timeout=3.0):
            if "cdn" in url:
                await asyncio.sleep(0.01)
                return True
            await asyncio.sleep(1.0)  # swarm: cancelled mid-probe
            return True

        monkeypatch.setattr(sr, "_fetch_probe", fake_probe)
        res = await race_stream_sources("http://p2p", "http://cdn", race_window_seconds=2.0)
        assert res["winner"] == "debrid"
        assert res["backup"] == "p2p"
        assert res["raced"] is True

    @pytest.mark.asyncio
    async def test_swarm_wins_when_cdn_dead(self, monkeypatch):
        import core.source_racer as sr

        async def fake_probe(url, api_key=None, timeout=3.0):
            if "cdn" in url:
                return False
            await asyncio.sleep(0.01)
            return True

        monkeypatch.setattr(sr, "_fetch_probe", fake_probe)
        res = await race_stream_sources("http://p2p", "http://cdn", race_window_seconds=2.0)
        assert res["winner"] == "p2p"
        assert res["backup"] == "debrid"

    @pytest.mark.asyncio
    async def test_window_timeout_falls_back_to_debrid(self, monkeypatch):
        import core.source_racer as sr

        async def fake_probe(url, api_key=None, timeout=3.0):
            await asyncio.sleep(30.0)  # neither answers in time
            return True

        monkeypatch.setattr(sr, "_fetch_probe", fake_probe)
        res = await race_stream_sources("http://p2p", "http://cdn", race_window_seconds=0.05)
        assert res["winner"] == "debrid"
        assert res["backup"] == "p2p"


class FakeStreamItem:
    def __init__(self, title, score, size_bytes, info_hash, file_idx=0):
        self.name = "badge"
        self.title = title
        self.score = score
        self.size_bytes = size_bytes
        self.info_hash = info_hash
        self.file_idx = file_idx
        self.seeds = 50
        self.magnet = f"magnet:?xt=urn:btih:{info_hash}"


class TestQualityLadder:
    @pytest.mark.asyncio
    async def test_ladder_disabled_without_flag(self, monkeypatch):
        from routers.stream import find_ladder_candidates

        monkeypatch.setattr("routers.stream.QUALITY_LADDER_ENABLED", False)
        res = await find_ladder_candidates(title="X", current_size_bytes=10_000_000_000, season=1, episode=2)
        assert res["enabled"] is False
        assert res["candidates"] == []

    @pytest.mark.asyncio
    async def test_ladder_prefers_smaller_same_episode_releases(self, monkeypatch):
        from routers.stream import find_ladder_candidates

        monkeypatch.setattr("routers.stream.QUALITY_LADDER_ENABLED", True)

        big = FakeStreamItem("Show.S01E02.2160p.REMUX", 500.0, 30_000_000_000, "b" * 40)
        mid = FakeStreamItem("Show.S01E02.1080p.WEB", 400.0, 4_000_000_000, "m" * 40)
        tiny = FakeStreamItem("Show.S01E02.720p", 300.0, 1_200_000_000, "t" * 40)
        other_ep = FakeStreamItem("Show.S01E03.1080p", 900.0, 2_000_000_000, "o" * 40)

        class FakeResponse:
            streams = [big, mid, tiny, other_ep]

        async def fake_resolve(**kwargs):
            return FakeResponse()

        with patch("routers.stream.resolve_streams", side_effect=fake_resolve):
            res = await find_ladder_candidates(
                title="Show", current_size_bytes=30_000_000_000, season=1, episode=2
            )

        assert res["enabled"] is True
        hashes = [c["info_hash"] for c in res["candidates"]]
        assert hashes[0] == "m" * 40  # largest lower-bitrate step first
        assert "b" * 40 not in hashes  # current release excluded
        assert "o" * 40 not in hashes  # different episode excluded

    @pytest.mark.asyncio
    async def test_ladder_requires_meaningful_size_drop(self, monkeypatch):
        from routers.stream import find_ladder_candidates

        monkeypatch.setattr("routers.stream.QUALITY_LADDER_ENABLED", True)

        barely_smaller = FakeStreamItem("Show.S01E02.1080p", 400.0, 28_000_000_000, "s" * 40)

        class FakeResponse:
            streams = [barely_smaller]

        async def fake_resolve(**kwargs):
            return FakeResponse()

        with patch("routers.stream.resolve_streams", side_effect=fake_resolve):
            res = await find_ladder_candidates(
                title="Show", current_size_bytes=30_000_000_000, season=1, episode=2
            )
        assert res["candidates"] == []
