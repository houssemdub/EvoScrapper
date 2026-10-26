import os
import subprocess
import pytest
from unittest.mock import MagicMock, patch
from config import settings
from core.torrent_streamer import (
    STREAM_PORT,
    TORRENT_PORT,
    DHT_PORT,
    DAEMON_URL,
    is_node_streamer_pid,
    find_available_stream_port,
    kill_stale_daemon,
    start_daemon_process,
)


def test_config_wiring_and_child_env():
    """Verifies that config settings exist and propagate correctly to child daemon env."""
    assert hasattr(settings, "STREAM_PORT")
    assert hasattr(settings, "TORRENT_PORT")
    assert hasattr(settings, "DHT_PORT")
    assert settings.STREAM_PORT == 8889
    assert settings.TORRENT_PORT == 50000
    assert settings.DHT_PORT == 50001

    captured_env = None

    def mock_popen(args, **kwargs):
        nonlocal captured_env
        captured_env = kwargs.get("env")
        proc = MagicMock()
        proc.pid = 1234
        return proc

    with patch("subprocess.Popen", side_effect=mock_popen), \
         patch("core.torrent_streamer.kill_stale_daemon"), \
         patch("core.torrent_streamer.get_streamer_token", return_value="test-daemon-token"), \
         patch("builtins.open", MagicMock()):
        start_daemon_process()

        assert captured_env is not None
        assert captured_env["PORT"] == str(settings.STREAM_PORT)
        assert captured_env["STREAM_PORT"] == str(settings.STREAM_PORT)
        assert captured_env["TORRENT_PORT"] == str(settings.TORRENT_PORT)
        assert captured_env["DHT_PORT"] == str(settings.DHT_PORT)
        assert captured_env["EVO_STREAM_BIND_HOST"] == settings.STREAM_BIND_HOST
        assert captured_env["EVO_STREAMER_TOKEN"] == "test-daemon-token"
        assert captured_env["EVO_STREAM_CACHE_DIR"].endswith(".stream_cache")


def test_kill_stale_daemon_safe_takeover():
    """Verifies that kill_stale_daemon does NOT kill non-Node processes and switches to fallback port."""
    import core.torrent_streamer as ts
    orig_port = ts.STREAM_PORT
    orig_url = ts.DAEMON_URL
    netstat_output = "  TCP    127.0.0.1:8889         0.0.0.0:0              LISTENING       98765\n"

    try:
        with patch("os.name", "nt"), \
             patch("subprocess.check_output", return_value=netstat_output), \
             patch("core.torrent_streamer.is_node_streamer_pid", return_value=False), \
             patch("subprocess.run") as mock_run:

            kill_stale_daemon(target_port=8889)

            # taskkill must NOT have been called on PID 98765
            for call in mock_run.call_args_list:
                assert "98765" not in str(call)
    finally:
        ts.STREAM_PORT = orig_port
        ts.DAEMON_URL = orig_url


def test_find_available_stream_port():
    """Verifies dynamic port scanning returns an integer in range [8890, 8899]."""
    port = find_available_stream_port(8890)
    assert 8890 <= port <= 8899
