import json
import time
import pytest
from fastapi.testclient import TestClient
from main import app
from core.cometnet import CometNetNode, CometMessageType, get_cometnet_node


@pytest.fixture
def client():
    return TestClient(app)


def test_cometnet_stats_endpoint(client):
    res = client.get("/api/v1/cometnet/stats")
    assert res.status_code == 200
    data = res.json()
    assert "node_id" in data
    assert "public_key" in data
    assert len(data["node_id"]) == 64
    assert "torrents_indexed" in data
    assert "debrid_cached_entries" in data


def test_cometnet_announce_and_lookup_torrent(client):
    info_hash = "1111222233334444555566667777888899990000"
    title = "Sintel 4K Remaster Open Source Film"
    size = 1234567890

    # Announce torrent
    res = client.post(
        "/api/v1/cometnet/announce/torrent",
        json={
            "info_hash": info_hash,
            "title": title,
            "size": size,
            "trackers": ["udp://tracker.openbittorrent.com:80"],
        },
    )
    assert res.status_code == 200
    ann_data = res.json()
    assert ann_data["status"] == "announced"
    assert ann_data["message_id"]

    # Lookup torrent via CometNet
    lookup_res = client.get(f"/api/v1/cometnet/lookup/{info_hash}")
    assert lookup_res.status_code == 200
    item = lookup_res.json()
    assert item["found"] is True
    assert item["torrent"]["title"] == title
    assert item["torrent"]["size"] == size


def test_cometnet_announce_and_lookup_cache(client):
    info_hash = "abcdef0123456789abcdef0123456789abcdef01"

    # Announce debrid cache
    res = client.post(
        "/api/v1/cometnet/announce/cache",
        json={
            "info_hash": info_hash,
            "provider": "realdebrid",
            "cached": True,
        },
    )
    assert res.status_code == 200

    # Lookup
    lookup_res = client.get(f"/api/v1/cometnet/lookup/{info_hash}")
    assert lookup_res.status_code == 200
    item = lookup_res.json()
    assert item["found"] is True
    assert "realdebrid" in item["cached_providers"]


def test_cometnet_websocket_mesh_exchange(client):
    peer_node = CometNetNode(node_name="remote-peer-tester")
    test_hash = "9999888877776666555544443333222211110000"

    with client.websocket_connect("/api/v1/cometnet/ws") as websocket:
        # 1. Inbound connection receives initial intro/ping from server node
        intro_raw = websocket.receive_text()
        intro = json.loads(intro_raw)
        assert intro["type"] == "ping"

        # 2. Remote peer sends a signed torrent announcement
        signed_msg = peer_node.create_signed_message(
            CometMessageType.TORRENT_ANNOUNCE,
            {
                "info_hash": test_hash,
                "title": "Cosmos Laundromat 1080p",
                "size": 555000111,
                "trackers": [],
            },
        )
        websocket.send_text(json.dumps(signed_msg))

        # Check local node ingested the message into its catalog (allow background portal loop to process)
        local_node = get_cometnet_node()
        torrent = None
        for _ in range(20):
            torrent = local_node.lookup_torrent(test_hash)
            if torrent:
                break
            time.sleep(0.05)

        assert torrent is not None
        assert torrent["title"] == "Cosmos Laundromat 1080p"
