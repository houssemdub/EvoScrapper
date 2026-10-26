"""P8 watch-together rooms, T4.6 Stremio subtitles, T4.5 Jackett Torznab provider."""
import sys
import os
from unittest.mock import AsyncMock, patch

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from core.cometnet import CometNetNode, CometMessageType
from core.watch_party import WatchPartyError, WatchPartyManager, WatchPartyRoom

HASH = "a" * 40
TORZNAB_XML = """<?xml version="1.0" encoding="UTF-8"?>
<rss xmlns:torznab="http://torznab.com/schemas/2015/feed" version="1.0">
  <channel>
    <title>Jackett</title>
    <item>
      <title>Show.S01E02.1080p.WEB-DL.DDP5.1.H264-GRP</title>
      <guid>magnet:?xt=urn:btih:1111111111111111111111111111111111111111</guid>
      <link>https://tracker.example/dl/1</link>
      <comments>https://tracker.example/t/1</comments>
      <pubDate>Sat, 25 Oct 2026 12:00:00 +0000</pubDate>
      <attr name="infohash" value="1111111111111111111111111111111111111111"/>
      <attr name="seeders" value="42"/>
      <attr name="peers" value="7"/>
      <attr name="size" value="2147483648"/>
    </item>
    <item>
      <title>NoHash.Release.1080p</title>
      <guid>https://tracker.example/t/2</guid>
    </item>
  </channel>
</rss>"""


class TestWatchParty:
    def test_room_lifecycle_and_event_sequencing(self):
        manager = WatchPartyManager()
        room = manager.create_room(HASH, "host-1")
        assert room.code and len(room.code) == 6
        assert room.is_member("host-1")

        manager.join_room(room.code, "guest-1")
        e1 = manager.post_event(room.code, "host-1", "play", 0.0)
        e2 = manager.post_event(room.code, "guest-1", "seek", 42.5)
        assert e2["seq"] == e1["seq"] + 1
        assert [e["seq"] for e in room.events_since(0)] == [1, 2]
        assert [e["seq"] for e in room.events_since(1)] == [2]

    def test_membership_and_actions_enforced(self):
        manager = WatchPartyManager()
        room = manager.create_room(HASH, "host-1")
        with pytest.raises(WatchPartyError):
            manager.post_event(room.code, "stranger", "play", 0.0)
        with pytest.raises(WatchPartyError):
            manager.post_event(room.code, "host-1", "rewind", 5.0)
        assert manager.get_room("zzzzzz") is None

    def test_room_capacity_and_validation(self):
        manager = WatchPartyManager()
        room = manager.create_room(HASH, "host-1")
        for i in range(11):
            manager.join_room(room.code, f"guest-{i}")
        with pytest.raises(WatchPartyError):
            manager.join_room(room.code, "overflow")
        with pytest.raises(WatchPartyError):
            manager.create_room("tooshort", "host-1")

    def test_gossip_event_applies_to_local_room_with_fresh_timestamp(self):
        node_a = CometNetNode(node_name="a")
        node_b = CometNetNode(node_name="b")
        manager_b = WatchPartyManager()
        manager_b.rooms["abc123"] = WatchPartyRoom("abc123", HASH, "host-1")

        msg = node_a.announce_party_event("abc123", "remote-peer", "seek", 77.0)
        assert msg["type"] == CometMessageType.PARTY_EVENT.value
        # Swap node B's manager for the isolated one, then ingest.
        import core.watch_party as wp
        original = wp._manager
        wp._manager = manager_b
        try:
            assert node_b.ingest_message(msg) is True
        finally:
            wp._manager = original

        room = manager_b.get_room("abc123")
        assert room.is_member("remote-peer")
        events = room.events_since(0)
        assert events and events[-1]["action"] == "seek" and events[-1]["position"] == 77.0

    def test_stale_gossip_event_ignored(self):
        manager = WatchPartyManager()
        room = WatchPartyRoom("def456", HASH, "host-1")
        manager.rooms["def456"] = room
        before = len(room.events)
        assert manager.apply_gossip_event("def456", "x", "seek", 1.0, ts=0.0) is False
        assert len(room.events) == before


class TestStremioSubtitles:
    @pytest.mark.asyncio
    async def test_subtitles_resource_maps_to_stremio_shape(self):
        from routers.stremio import get_stremio_subtitles

        class FakeSub:
            id = "sub-1"
            url = "https://subs.example/download/1"
            language_code = "en"

        class FakeResponse:
            data = [FakeSub()]

        with patch("routers.subtitles.search_subtitles", new=AsyncMock(return_value=FakeResponse())):
            result = await get_stremio_subtitles(stype="series", item_id="tt0944947", season=1, episode=2)

        assert result["subtitles"][0]["url"] == "https://subs.example/download/1"
        assert result["subtitles"][0]["lang"] == "en"

    @pytest.mark.asyncio
    async def test_non_imdb_id_returns_empty(self):
        from routers.stremio import get_stremio_subtitles

        result = await get_stremio_subtitles(stype="series", item_id="kitsu:4502")
        assert result == {"subtitles": []}


class TestJackettProvider:
    def test_parse_torznab_response(self):
        from providers.torrents.jackett import JackettProvider

        provider = JackettProvider(base_url="http://127.0.0.1:9117", api_key="k" * 20)
        items = provider._parse_response(TORZNAB_XML, limit=50)
        assert len(items) == 1  # no-hash item skipped
        item = items[0]
        assert item.info_hash == "1" * 40
        assert item.seeders == 42
        assert item.size_bytes == 2147483648
        assert item.magnet_uri.startswith("magnet:?xt=urn:btih:")
        assert item.upload_date == "2026-10-25"

    @pytest.mark.asyncio
    async def test_search_via_client(self):
        from providers.torrents.jackett import JackettProvider

        provider = JackettProvider(base_url="http://127.0.0.1:9117", api_key="k" * 20)
        with patch("providers.torrents.jackett.http_client") as mock_client:
            mock_client.get_text = AsyncMock(return_value=TORZNAB_XML)
            items = await provider.search("Show S01E02", limit=10)

        assert len(items) == 1
        called_url = mock_client.get_text.await_args.args[0]
        assert "/api/v2.0/indexers/all/results/torznab/api?" in called_url
        assert "apikey=" in called_url and "t=search" in called_url

    @pytest.mark.asyncio
    async def test_unconfigured_provider_searches_nothing(self):
        from providers.torrents.jackett import JackettProvider

        provider = JackettProvider(base_url="", api_key="")
        assert provider.is_configured is False
        assert await provider.search("anything") == []

    def test_registry_excludes_jackett_when_unconfigured(self):
        from providers.torrents import TORRENT_PROVIDERS

        assert "jackett" not in TORRENT_PROVIDERS or TORRENT_PROVIDERS["jackett"].is_configured
