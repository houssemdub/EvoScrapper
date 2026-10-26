import os
import subprocess
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from fastapi import HTTPException
from core.transmuxer import stream_transmuxed_video


def test_watchdog_detects_deficit():
    """Verifies torrent_engine.js buffer-health watchdog detects download speed deficits."""
    node_cmd = [
        "node", "--input-type=module", "-e",
        """
        import engine from './streamer/torrent_engine.js';
        let criticalCalled = false;
        const dummyTorrent = {
            pieceLength: 1048576,
            downloadSpeed: 50000, // 50 KB/s - well below 8Mbps (1MB/s)
            numPeers: 5,
            infoHash: 'c'.repeat(40),
            wires: [{ connected: true, downloaded: 0, lastActive: Date.now() - 5000, choke: () => {} }],
            select: () => {},
            critical: () => { criticalCalled = true; }
        };
        // 2 verified pieces ahead = 2MB = ~2s buffer (< 5s threshold)
        dummyTorrent.bitfield = { get: (i) => i <= 1 };
        const dummyFile = { offset: 0, length: 100 * 1048576 };
        engine.sessions.set('c'.repeat(40), { lastActive: Date.now(), avg_bitrate_bps: 8000000 });

        const res = engine.checkBufferHealth(dummyTorrent, dummyFile, 0);
        if (res.health_state !== 'deficit') {
            console.error('Expected health_state deficit, got:', res);
            process.exit(1);
        }
        if (!criticalCalled) {
            console.error('Expected critical pieces to be engaged during deficit');
            process.exit(2);
        }
        """
    ]
    res = subprocess.run(node_cmd, capture_output=True, text=True)
    assert res.returncode == 0, f"Node script failed: {res.stderr}\n{res.stdout}"


@pytest.mark.asyncio
async def test_transmuxer_empty_ffmpeg_raises_502():
    """Verifies that if FFmpeg terminates with non-zero exit code before yielding any bytes, a 502 error is raised."""
    mock_proc = MagicMock()
    mock_proc.returncode = 1
    mock_proc.stdout = AsyncMock()
    mock_proc.stdout.read = AsyncMock(return_value=b"")
    mock_proc.stderr = AsyncMock()
    mock_proc.stderr.readline = AsyncMock(side_effect=[b"Invalid data found when processing input\n", b""])
    mock_proc.terminate = MagicMock()
    mock_proc.wait = AsyncMock()

    with patch("asyncio.create_subprocess_exec", AsyncMock(return_value=mock_proc)):
        gen = stream_transmuxed_video("http://127.0.0.1:8888/stream?fake=1")
        with pytest.raises(HTTPException) as exc_info:
            async for _ in gen:
                pass
        assert exc_info.value.status_code == 502
        assert "Transmuxer failed to start" in exc_info.value.detail


def test_unexpected_eof_triggers_reconnect():
    """Verifies static/app.js implements auto-reconnect on unexpected EOF."""
    app_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "static", "app.js"))
    with open(app_path, "r", encoding="utf-8") as f:
        app_js = f.read()

    assert "Math.abs(cur - active.totalDuration) > 15" in app_js
    assert "Stream interrupted by swarm. Resuming playback at" in app_js
    assert "window._evoAutoReconnectFailures" in app_js
    assert "maxProbeAttempts = 10" in app_js
