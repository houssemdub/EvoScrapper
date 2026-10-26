"""Opt-in swarm pre-warm: resolve top search-result metadata before the user clicks play."""
import asyncio
import sys
import os
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from fastapi.testclient import TestClient

from main import app
from models.torrent import TorrentItem

client = TestClient(app)

A = "a" * 40
B = "b" * 40
C = "c" * 40


def _item(idx: int, info_hash) -> TorrentItem:
    return TorrentItem(
        id=str(idx),
        title=f"Release {idx}",
        info_hash=info_hash,
        magnet_uri=f"magnet:?xt=urn:btih:{info_hash}" if info_hash else "https://cdn.example/file",
        provider="fake",
    )


@pytest.mark.asyncio
async def test_prewarm_helper_respects_flag_and_filters(monkeypatch):
    import routers.torrents as rt

    resolved = []

    async def fake_get_torrent_files(info_hash, magnet=None):
        resolved.append(info_hash)
        return []

    monkeypatch.setattr(rt, "get_torrent_files", fake_get_torrent_files)
    items = [_item(1, A), _item(2, B), _item(3, C)]
    cdn_item = _item(9, None)

    monkeypatch.setattr(rt.settings, "PREWARM_SWARMS", True)
    rt._prewarm_top_swarms([cdn_item] + items)
    await asyncio.sleep(0.01)
    assert resolved == [A, B], f"expected top 2 valid hashes pre-warmed, got {resolved}"

    monkeypatch.setattr(rt.settings, "PREWARM_SWARMS", False)
    rt._prewarm_top_swarms(items)
    await asyncio.sleep(0.01)
    assert resolved == [A, B], "pre-warm fired while the flag was disabled"


@pytest.mark.asyncio
async def test_search_endpoint_triggers_prewarm(monkeypatch):
    import routers.torrents as rt

    prewarmed = []

    def fake_prewarm(items):
        prewarmed.extend(i.info_hash for i in items[:2])

    class FakeProvider:
        name = "fake"

        async def search(self, query, limit=50):
            return [_item(1, A), _item(2, B), _item(3, C)]

    monkeypatch.setattr(rt, "_prewarm_top_swarms", fake_prewarm)
    monkeypatch.setattr(rt, "TORRENT_PROVIDERS", {"fake": FakeProvider()})

    res = client.get("/api/v1/torrents/search?query=prewarm-unique-xyz")
    assert res.status_code == 200, res.text
    assert res.json()["total"] == 3
    assert prewarmed == [A, B], f"search did not hand its results to the pre-warm hook: {prewarmed}"
