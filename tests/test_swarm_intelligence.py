"""P1/P2/P3 swarm intelligence: seek heatmap, coverage index, scene boundaries, gossip wiring."""
import asyncio
import sys
import os
import time

import pytest
from unittest.mock import AsyncMock, patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from core.swarm_intelligence import (
    DebridCoverageIndex,
    SeekHeatmapStore,
    derive_scene_boundaries,
)
from core.cometnet import CometNetNode, CometMessageType

HASH = "c" * 40


@pytest.fixture
def heatmap(tmp_path):
    return SeekHeatmapStore(path=str(tmp_path / "heatmap.json"))


@pytest.fixture
def coverage(tmp_path):
    return DebridCoverageIndex(path=str(tmp_path / "coverage.json"))


class TestSeekHeatmap:
    def test_record_and_rank_targets(self, heatmap):
        heatmap.record(HASH, 2520.0)   # bucket 84
        heatmap.record(HASH, 2530.0)   # same bucket -> weight 2
        heatmap.record(HASH, 600.0)    # bucket 20
        targets = heatmap.top_seek_targets(HASH, k=2)
        assert targets[0]["bucket"] == 84
        assert targets[0]["weight"] == pytest.approx(2.0)
        assert len(targets) == 2

    def test_old_observations_decay(self, heatmap):
        old_ts = time.time() - 72 * 3600  # one half-life
        heatmap.record(HASH, 600.0, recorded_at=old_ts)
        heatmap.record(HASH, 610.0)      # fresh, same bucket
        targets = heatmap.top_seek_targets(HASH, k=1)
        assert targets[0]["weight"] == pytest.approx(1.5)

    def test_invalid_input_ignored(self, heatmap):
        heatmap.record("", 100.0)
        heatmap.record(HASH, -5.0)
        heatmap.record(HASH, float("nan"))
        assert heatmap.bucket_count(HASH) == 0

    def test_persistence_roundtrip(self, tmp_path):
        path = str(tmp_path / "hm.json")
        store = SeekHeatmapStore(path=path)
        store.record(HASH, 300.0)
        reloaded = SeekHeatmapStore(path=path)
        assert reloaded.top_seek_targets(HASH, k=1)[0]["bucket"] == 10


class TestDebridCoverageIndex:
    def test_record_and_confidence_order(self, coverage):
        now = time.time()
        coverage.record(HASH, "realdebrid", observed_at=now - 20 * 3600)
        coverage.record(HASH, "torbox", observed_at=now)
        providers = coverage.providers_for(HASH)
        assert providers[0]["provider"] == "torbox"
        assert providers[0]["confidence"] > providers[1]["confidence"]

    def test_corroboration_boosts_confidence(self, coverage):
        now = time.time()
        coverage.record(HASH, "realdebrid", observed_at=now)
        coverage.record(HASH, "realdebrid", observed_at=now, corroborated=True)
        coverage.record(HASH, "torbox", observed_at=now)
        providers = coverage.providers_for(HASH)
        assert providers[0]["provider"] == "realdebrid"

    def test_expired_entries_drop_out(self, coverage):
        coverage.record(HASH, "realdebrid", observed_at=time.time() - 48 * 3600)
        assert coverage.providers_for(HASH) == []


class TestSceneBoundaries:
    def test_intro_credits_and_scene_classification(self):
        targets = [
            {"position": 50 * 30.0, "bucket": 50, "weight": 6.0},     # ~5% -> intro
            {"position": 1200 * 30.0, "bucket": 1200, "weight": 4.0},  # middle -> scene
            {"position": 4100 * 30.0, "bucket": 4100, "weight": 8.0},  # ~93% -> credits
        ]
        scenes = derive_scene_boundaries(targets, total_duration_seconds=4400 * 30.0)
        kinds = [s["type"] for s in scenes]
        assert kinds == ["intro", "scene", "credits"]

    def test_low_weight_hotspots_are_ignored(self):
        targets = [{"position": 100.0, "bucket": 3, "weight": 1.0}]
        assert derive_scene_boundaries(targets, total_duration_seconds=7200.0) == []

    def test_adjacent_same_kind_merge(self):
        targets = [
            {"position": 20 * 30.0, "bucket": 20, "weight": 5.0},
            {"position": 21 * 30.0, "bucket": 21, "weight": 5.0},
        ]
        scenes = derive_scene_boundaries(targets, total_duration_seconds=7200.0)
        assert len(scenes) == 1


class TestGossipWiring:
    def test_seek_announce_roundtrip_between_nodes(self, tmp_path, monkeypatch):
        import core.swarm_intelligence as si
        monkeypatch.setattr(si, "_heatmap_store", SeekHeatmapStore(path=str(tmp_path / "hm.json")))

        node_a = CometNetNode(node_name="a")
        node_b = CometNetNode(node_name="b")
        msg = node_a.announce_seek(HASH, 1500.0)
        assert msg["type"] == CometMessageType.SEEK_ANNOUNCE.value
        assert node_b.ingest_message(msg) is True

        targets = si.get_seek_heatmap().top_seek_targets(HASH, k=1)
        assert targets and targets[0]["bucket"] == 50

    def test_cache_announce_feeds_coverage_index(self, tmp_path, monkeypatch):
        import core.swarm_intelligence as si
        monkeypatch.setattr(si, "_coverage_store", DebridCoverageIndex(path=str(tmp_path / "cov.json")))

        node_a = CometNetNode(node_name="a")
        node_b = CometNetNode(node_name="b")
        msg = node_a.announce_cache(HASH, "realdebrid", cached=True)
        assert node_b.ingest_message(msg) is True

        providers = si.get_coverage_index().providers_for(HASH)
        assert providers and providers[0]["provider"] == "realdebrid"

    def test_tampered_seek_message_rejected(self, tmp_path, monkeypatch):
        import core.swarm_intelligence as si
        monkeypatch.setattr(si, "_heatmap_store", SeekHeatmapStore(path=str(tmp_path / "hm.json")))

        node_a = CometNetNode(node_name="a")
        node_b = CometNetNode(node_name="b")
        msg = node_a.announce_seek(HASH, 1500.0)
        before = si.get_seek_heatmap().bucket_count(HASH)  # node A's own ingest
        msg["payload"]["position"] = 99999.0
        assert node_b.ingest_message(msg) is False
        assert si.get_seek_heatmap().bucket_count(HASH) == before

    def test_invalid_seek_payload_ingest_is_safe(self, tmp_path, monkeypatch):
        import core.swarm_intelligence as si
        monkeypatch.setattr(si, "_heatmap_store", SeekHeatmapStore(path=str(tmp_path / "hm.json")))

        node_a = CometNetNode(node_name="a")
        node_b = CometNetNode(node_name="b")
        msg = node_a.create_signed_message(CometMessageType.SEEK_ANNOUNCE, {"info_hash": HASH, "position": "not-a-number"})
        assert node_b.ingest_message(msg) is True
        assert si.get_seek_heatmap().bucket_count(HASH) == 0


class TestCoverageSeededResolve:
    @pytest.mark.asyncio
    async def test_mesh_hint_orders_resolve_attempts(self, tmp_path, monkeypatch):
        import core.swarm_intelligence as si
        from core.debrid.manager import DebridManager
        from tests.test_tier0_parity import FakeDebridProvider

        monkeypatch.setattr(si, "_coverage_store", DebridCoverageIndex(path=str(tmp_path / "cov.json")))
        si.get_coverage_index().record("f" * 40, "torbox")

        manager = DebridManager()
        rd = FakeDebridProvider("RealDebrid")
        tb = FakeDebridProvider("TorBox")
        manager.providers = {"realdebrid": rd, "torbox": tb}

        res = await manager.resolve_stream("f" * 40)
        assert res.provider == "TorBox", "mesh coverage hint did not order the resolve attempt"
        assert rd.resolve_calls == 0


class TestMeshImpact:
    @pytest.mark.asyncio
    async def test_impact_aggregates_heatmap_and_coverage(self, tmp_path, monkeypatch):
        import core.swarm_intelligence as si
        from routers.cometnet import get_mesh_impact

        monkeypatch.setattr(si, "_heatmap_store", SeekHeatmapStore(path=str(tmp_path / "hm.json")))
        monkeypatch.setattr(si, "_coverage_store", DebridCoverageIndex(path=str(tmp_path / "cov.json")))
        si.get_seek_heatmap().record(HASH, 1500.0)
        si.get_coverage_index().record(HASH, "torbox")

        daemon_status = {"sessions": [{"hint_stats": {"seeks": 4, "hits": 3}}]}
        with patch("core.torrent_streamer.get_daemon_status", new=AsyncMock(return_value=daemon_status)):
            result = await get_mesh_impact()

        assert result["hint_hit_rate_pct"] == 75.0
        assert result["hint_seeks"] == 4 and result["hint_hits"] == 3
        assert result["heatmap_hashes_tracked"] == 1
        assert result["coverage"]["tracked_hashes"] == 1
