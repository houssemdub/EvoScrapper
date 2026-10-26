import os
import subprocess
import pytest


def test_torrent_engine_store_cache_slots_bounded():
    """Verifies that torrent_engine.js limits storeCacheSlots to <= 128 by default to bound RAM usage."""
    engine_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "streamer", "torrent_engine.js"))
    with open(engine_path, "r", encoding="utf-8") as f:
        content = f.read()

    assert "process.env.EVO_STORE_CACHE_SLOTS || '128'" in content
    assert "storeCacheSlots: storeSlots" in content
    assert "maxWebConns: maxWebConns" in content


def test_peer_cache_save_and_load():
    """Verifies that torrent_engine.js correctly saves and loads peers to/from .stream_cache/peers.json."""
    node_cmd = [
        "node", "--input-type=module", "-e",
        """
        import engine from './streamer/torrent_engine.js';
        const testHash = '1122334455667788990011223344556677889900';
        const peers = ['192.168.1.100:6881', '10.0.0.50:51413'];
        engine.saveCachedPeers(testHash, peers);
        const loaded = engine.loadCachedPeers(testHash);
        if (!loaded.includes('192.168.1.100:6881') || !loaded.includes('10.0.0.50:51413')) {
            console.error('Failed to load saved peers:', loaded);
            process.exit(1);
        }
        """
    ]
    res = subprocess.run(node_cmd, capture_output=True, text=True)
    assert res.returncode == 0, f"Node peer cache test failed: {res.stderr}\n{res.stdout}"
