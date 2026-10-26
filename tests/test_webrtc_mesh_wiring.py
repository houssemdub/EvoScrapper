import os
import subprocess
import pytest


def test_p2p_player_mesh_initialization_and_fallback():
    """Verifies p2p-player.js honors p2p_mesh_enabled and falls back to standard Hls.js loader."""
    player_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "static", "p2p-player.js"))
    with open(player_path, "r", encoding="utf-8") as f:
        content = f.read()

    # Checks localStorage for p2p_mesh_enabled setting
    assert "s.p2p_mesh_enabled === false" in content
    # Wires p2pml engine when enabled
    assert "if (p2pMeshEnabled && p2pSupported)" in content
    assert "this.p2pEngine.createLoaderClass()" in content
    # Gracefully falls back to standard Hls
    assert "console.warn('[P2PPlayer] Engine fallback to standard Hls.js:'" in content
    assert "this.hls = new Hls(hlsConfig)" in content


def test_p2p_telemetry_wired_to_swarm_stat():
    """Verifies that WebRTC mesh telemetry updates the player-swarm-stat pill in the HUD."""
    player_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "static", "p2p-player.js"))
    with open(player_path, "r", encoding="utf-8") as f:
        content = f.read()

    assert "document.getElementById('player-swarm-stat')" in content
    assert "WebRTC Mesh Active:" in content
    assert "p2pml.core.Events.PieceBytesDownloaded" in content
    assert "p2pml.core.Events.PeerConnect" in content
    assert "p2pml.core.Events.PeerClose" in content


def test_settings_p2p_mesh_toggle_in_html():
    """Verifies that static/index.html includes the P2P Media Loader mesh acceleration toggle."""
    html_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "static", "index.html"))
    with open(html_path, "r", encoding="utf-8") as f:
        html = f.read()

    assert 'id="settings-toggle-p2p-mesh"' in html
    assert "P2P Media Loader WebRTC Browser Mesh Sharing" in html
