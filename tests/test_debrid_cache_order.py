"""Cache-aware debrid resolution: prefer providers that already hold the torrent."""
import asyncio
import sys
import os

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from core.debrid.base import DebridStreamResult
from core.debrid.manager import DebridManager

HASH = "f" * 40


class FakeProvider:
    def __init__(self, name: str, cached: bool, fail_probe: bool = False):
        self.provider_name = name
        self.is_configured = True
        self._cached = cached
        self._fail_probe = fail_probe
        self.resolve_calls = 0
        self.probe_calls = 0

    async def check_cache(self, info_hashes):
        self.probe_calls += 1
        if self._fail_probe:
            raise RuntimeError("probe endpoint down")
        return {h: self._cached for h in info_hashes}

    async def resolve_stream(self, info_hash, file_idx=0, magnet=None, season=None, episode=None):
        self.resolve_calls += 1
        return DebridStreamResult(
            url=f"https://{self.provider_name.lower()}/direct/{info_hash}",
            filename="movie.mkv",
            size=1024,
            provider=self.provider_name,
        )

    async def get_user_info(self):
        return {}


@pytest.mark.asyncio
async def test_resolve_stream_prefers_cached_provider():
    manager = DebridManager()
    uncached_first = FakeProvider("RealDebrid", cached=False)
    cached_second = FakeProvider("TorBox", cached=True)
    manager.providers = {"realdebrid": uncached_first, "torbox": cached_second}

    res = await manager.resolve_stream(HASH)

    assert res.provider == "TorBox", f"resolved from uncached provider: {res.provider}"
    assert cached_second.resolve_calls == 1
    assert uncached_first.resolve_calls == 0, "uncached provider was tried despite a cached alternative"


@pytest.mark.asyncio
async def test_resolve_stream_without_cache_respects_preference():
    manager = DebridManager()
    preferred = FakeProvider("TorBox", cached=False)
    other = FakeProvider("RealDebrid", cached=False)
    manager.providers = {"realdebrid": other, "torbox": preferred}

    res = await manager.resolve_stream(HASH, preferred_provider="torbox")

    assert preferred.resolve_calls == 1 and other.resolve_calls == 0
    assert "torbox" in res.url


@pytest.mark.asyncio
async def test_preferred_provider_wins_among_cached_ties():
    manager = DebridManager()
    preferred = FakeProvider("RealDebrid", cached=True)
    other_cached = FakeProvider("TorBox", cached=True)
    manager.providers = {"realdebrid": preferred, "torbox": other_cached}

    res = await manager.resolve_stream(HASH, preferred_provider="RealDebrid")

    assert preferred.resolve_calls == 1 and other_cached.resolve_calls == 0
    assert res.provider == "RealDebrid"


@pytest.mark.asyncio
async def test_cache_probe_failure_falls_back_to_preference_order():
    manager = DebridManager()
    broken = FakeProvider("RealDebrid", cached=False, fail_probe=True)
    backup = FakeProvider("TorBox", cached=False)
    manager.providers = {"realdebrid": broken, "torbox": backup}

    res = await manager.resolve_stream(HASH, preferred_provider="torbox")

    assert broken.probe_calls == 1, "probe failure should not abort resolution"
    assert backup.resolve_calls == 1 and broken.resolve_calls == 0
    assert "torbox" in res.url
