import pytest
from core.cometnet import CometNetNode, CometMessageType

@pytest.fixture
def node():
    return CometNetNode(node_name="test-node-1")

@pytest.fixture
def peer_node():
    return CometNetNode(node_name="test-node-2")

def test_node_identity_generation(node):
    assert node.node_id is not None
    assert len(node.node_id) == 64  # SHA-256 hex string
    assert node.public_key_hex is not None
    assert len(node.public_key_hex) > 0

def test_message_signing_and_verification(node, peer_node):
    msg = node.create_signed_message(
        msg_type=CometMessageType.TORRENT_ANNOUNCE,
        payload={
            "info_hash": "4a1d4d3d8a6fc5b7507eb23521d8b13d6a4c2810",
            "title": "Big Buck Bunny (2008) 1080p",
            "size": 1054320000,
            "trackers": ["udp://tracker.opentrackr.org:1337/announce"],
        }
    )

    assert msg["sender_id"] == node.node_id
    assert msg["signature"] != ""
    assert msg["type"] == CometMessageType.TORRENT_ANNOUNCE.value

    # Peer node verifies the signed message
    assert peer_node.verify_message(msg) is True

    # Tampered message should fail verification
    tampered_msg = dict(msg)
    tampered_msg["payload"] = dict(msg["payload"])
    tampered_msg["payload"]["size"] = 999999999
    assert peer_node.verify_message(tampered_msg) is False

def test_message_deduplication_and_ingestion(node, peer_node):
    info_hash = "4a1d4d3d8a6fc5b7507eb23521d8b13d6a4c2810"
    msg = node.create_signed_message(
        msg_type=CometMessageType.TORRENT_ANNOUNCE,
        payload={
            "info_hash": info_hash,
            "title": "Big Buck Bunny (2008)",
            "size": 100000,
            "trackers": [],
        }
    )

    # First ingestion -> True (new message)
    is_new = peer_node.ingest_message(msg)
    assert is_new is True

    # Check that torrent was added to local catalog
    stored = peer_node.lookup_torrent(info_hash)
    assert stored is not None
    assert stored["title"] == "Big Buck Bunny (2008)"

    # Second ingestion -> False (duplicate message ignored)
    is_duplicate = peer_node.ingest_message(msg)
    assert is_duplicate is False

def test_debrid_cache_gossip(node, peer_node):
    info_hash = "d3b07384d113edec49eaa6238ad5ff0000000000"
    
    # Node 1 announces Real-Debrid cache
    msg1 = node.create_signed_message(
        msg_type=CometMessageType.CACHE_ANNOUNCE,
        payload={
            "info_hash": info_hash,
            "provider": "realdebrid",
            "cached": True,
        }
    )
    peer_node.ingest_message(msg1)
    
    # Another peer announces AllDebrid cache for the same torrent
    node3 = CometNetNode(node_name="test-node-3")
    msg2 = node3.create_signed_message(
        msg_type=CometMessageType.CACHE_ANNOUNCE,
        payload={
            "info_hash": info_hash,
            "provider": "alldebrid",
            "cached": True,
        }
    )
    peer_node.ingest_message(msg2)

    cached_providers = peer_node.lookup_cache(info_hash)
    assert "realdebrid" in cached_providers
    assert "alldebrid" in cached_providers
