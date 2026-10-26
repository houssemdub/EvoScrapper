"""Tier 0 parity sprint: swarm-health gate, split debrid breakers, negative-result TTLs."""
import asyncio
import sys
import os
from unittest.mock import AsyncMock

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from core.aggregator import gate_by_swarm_health
from core.cache import MemoryCache
from core.debrid.base import DebridStreamResult
from core.debrid.manager import DebridManager
from models.torrent import TorrentItem


def _item(idx: int, seeders: int) -> TorrentItem:
    return TorrentItem(
        id=str(idx),
        title=f"Release {idx}",
        info_hash=f"{idx:040x}",
        magnet_uri=f"magnet:?xt=urn:btih:{idx:040x}",
        seeders=seeders,
        provider="fake",
    )


class TestSwarmHealthGate:
    def test_strong_swarm_suppresses_dead_torrents(self):
        items = [_item(i, seeders=20) for i in range(60)] + [_item(100 + i, seeders=0) for i in range(40)]
        gated = gate_by_swarm_health(items)
        assert len(gated) == 60
        assert all(x.seeders >= 5 for x in gated)

    def test_weak_swarm_caps_at_five_candidates(self):
        items = [_item(i, seeders=0) for i in range(30)]
        gated = gate_by_swarm_health(items)
        assert len(gated) == 5

    def test_some_seeded_results_fill_the_gap(self):
        items = [_item(i, seeders=2) for i in range(10)]
        gated = gate_by_swarm_health(items)
        assert len(gated) == 10  # 10 >= MAX_UNHEALTHY_COUNT seeded -> seeded slice

    def test_debrid_configured_skips_gate_entirely(self):
        items = [_item(i, seeders=0) for i in range(30)]
        assert gate_by_swarm_health(items, debrid_configured=True) == items

    def test_small_result_list_passes_through(self):
        items = [_item(i, seeders=1) for i in range(4)]
        assert gate_by_swarm_health(items) == items


class FakeDebridProvider:
    def __init__(self, name: str, fail_probe: bool = False, fail_resolve: bool = False):
        self.provider_name = name
        self.is_configured = True
        self._fail_probe = fail_probe
        self._fail_resolve = fail_resolve
        self.resolve_calls = 0
        self.probe_calls = 0

    async def check_cache(self, info_hashes):
        self.probe_calls += 1
        if self._fail_probe:
            raise RuntimeError("availability API down")
        return {h: False for h in info_hashes}

    async def resolve_stream(self, info_hash, file_idx=0, magnet=None, season=None, episode=None):
        self.resolve_calls += 1
        if self._fail_resolve:
            raise RuntimeError("resolve API down")
        return DebridStreamResult(url=f"https://{self.provider_name.lower()}/x", filename="f", size=1, provider=self.provider_name)

    async def get_user_info(self):
        return {}


class TestSplitCircuitBreakers:
    @pytest.mark.asyncio
    async def test_resolve_breaker_opens_after_threshold(self):
        manager = DebridManager()
        broken = FakeDebridProvider("Broken", fail_resolve=True)
        backup = FakeDebridProvider("Backup")
        manager.providers = {"broken": broken, "backup": backup}

        for _ in range(3):
            res = await manager.resolve_stream("f" * 40)
            assert res.provider == "Backup"

        assert broken.resolve_calls == 3
        assert manager._resolve_breaker_open("broken")
        # After the breaker opens, the broken provider is skipped entirely.
        await manager.resolve_stream("f" * 40)
        assert broken.resolve_calls == 3
        assert backup.resolve_calls == 4

    @pytest.mark.asyncio
    async def test_availability_breaker_is_independent(self):
        manager = DebridManager()
        broken = FakeDebridProvider("Broken", fail_probe=True)
        healthy = FakeDebridProvider("Healthy")
        manager.providers = {"broken": broken, "healthy": healthy}

        for _ in range(3):
            await manager.check_cache(["f" * 40])
        assert manager._availability_breaker_open("broken")
        assert broken.probe_calls == 3

        # Probe breaker open, but resolve still works on the same provider.
        res = await manager.resolve_stream("f" * 40)
        assert res.provider == "Broken"
        assert broken.resolve_calls == 1

    @pytest.mark.asyncio
    async def test_success_resets_breaker(self):
        manager = DebridManager()
        flaky = FakeDebridProvider("Flaky")
        manager.providers = {"flaky": flaky}
        flaky._fail_resolve = True
        for _ in range(3):
            await manager.resolve_stream("f" * 40)
        assert manager._resolve_breaker_open("flaky")
        flaky._fail_resolve = False
        manager._record_resolve_success("flaky")
        assert not manager._resolve_breaker_open("flaky")


class TestNegativeResultTTLs:
    @pytest.mark.asyncio
    async def test_empty_and_full_results_get_different_ttls(self):
        from routers.torrents import search_result_ttl

        assert search_result_ttl([_item(1, 5)]) == 900
        assert search_result_ttl([]) == 120

    @pytest.mark.asyncio
    async def test_search_endpoint_caches_empty_result_briefly(self, monkeypatch):
        from fastapi.testclient import TestClient
        from main import app

        client = TestClient(app)
        import routers.torrents as rt
        fresh_cache = MemoryCache()
        monkeypatch.setattr(rt, "cache", fresh_cache)

        class FakeProvider:
            name = "fake"

            async def search(self, query, limit=50):
                return []

        monkeypatch.setattr(rt, "TORRENT_PROVIDERS", {"fake": FakeProvider()})

        res = client.get("/api/v1/torrents/search?query=negative-ttl-xyz")
        assert res.status_code == 200
        assert res.json()["total"] == 0

        # The empty result must be cached under the short TTL.
        cached = await fresh_cache.get("torrent_search:all:negative-ttl-xyz:None:None:0:50")
        assert cached is not None
        assert cached.total == 0
