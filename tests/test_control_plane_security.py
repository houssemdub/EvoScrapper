import hashlib
import hmac
import json
import os
import shutil
import socket
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from config import settings
from main import app

REPO_ROOT = Path(__file__).resolve().parent.parent
NODE = shutil.which("node")
DAEMON_TOKEN = "control-plane-test-token-0123456789abcdef"
TOKEN_HEADER = "x-evo-streamer-token"


pytestmark = pytest.mark.skipif(NODE is None, reason="Node.js binary not found on system")


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _http(port: int, path: str, *, headers=None, method="GET", timeout=2.0):
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}",
        method=method,
        headers=headers or {},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, response.read(), dict(response.headers)
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read(), dict(exc.headers)


def _lan_ip():
    try:
        address = socket.gethostbyname(socket.gethostname())
    except OSError:
        return None
    if address.startswith(("127.", "169.254.")):
        return None
    return address


@pytest.fixture(scope="module")
def streamer_daemon(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("streamer-daemon")
    port = _free_port()
    log_path = tmp / "daemon.log"
    log_file = open(log_path, "w", encoding="utf-8")
    env = {
        **os.environ,
        "PORT": str(port),
        "STREAM_PORT": str(port),
        "TORRENT_PORT": "0",
        "DHT_PORT": "0",
        "EVO_STREAM_BIND_HOST": "127.0.0.1",
        "EVO_STREAMER_TOKEN": DAEMON_TOKEN,
        "EVO_STREAM_CACHE_DIR": str(tmp / "cache"),
        "EVO_ENGINE_OFFLINE": "1",
    }
    proc = subprocess.Popen(
        [NODE, str(REPO_ROOT / "streamer" / "server.js")],
        cwd=str(REPO_ROOT),
        env=env,
        stdout=log_file,
        stderr=log_file,
        text=True,
    )
    try:
        deadline = time.time() + 20
        ready = False
        while time.time() < deadline:
            if proc.poll() is not None:
                raise AssertionError(f"daemon exited early:\n{log_path.read_text(encoding='utf-8')}")
            try:
                status, _, _ = _http(port, "/health", timeout=0.5)
            except OSError:
                status = None
            if status == 200:
                ready = True
                break
            time.sleep(0.1)
        if not ready:
            raise AssertionError(f"daemon did not become ready:\n{log_path.read_text(encoding='utf-8')}")
        yield port
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)
        log_file.close()


@pytest.fixture
def client():
    return TestClient(app)


def test_daemon_binds_loopback_and_reports_identity(streamer_daemon):
    status, body, _ = _http(streamer_daemon, "/health")
    assert status == 200
    health = json.loads(body)
    assert health["bind_host"] == "127.0.0.1"
    assert health["auth_required"] is True
    assert isinstance(health["pid"], int) and health["pid"] > 0

    lan_ip = _lan_ip()
    if lan_ip:
        with pytest.raises(OSError):
            socket.create_connection((lan_ip, streamer_daemon), timeout=0.75).close()


def test_control_plane_requires_shared_secret(streamer_daemon):
    status, _, _ = _http(streamer_daemon, "/status")
    assert status == 401

    status, _, _ = _http(streamer_daemon, "/status", headers={TOKEN_HEADER: "wrong"})
    assert status == 401

    status, _, _ = _http(streamer_daemon, "/status", headers={TOKEN_HEADER: DAEMON_TOKEN})
    assert status == 200

    status, _, _ = _http(streamer_daemon, "/files?info_hash=" + "a" * 40)
    assert status == 401

    # Liveness stays available, but presenting a wrong secret is rejected.
    assert _http(streamer_daemon, "/health")[0] == 200
    assert _http(streamer_daemon, "/health", headers={TOKEN_HEADER: "wrong"})[0] == 401


def test_signed_stream_query_is_accepted_but_not_control_plane(streamer_daemon):
    expires = int(time.time()) + 60
    signature = hmac.new(
        DAEMON_TOKEN.encode("utf-8"),
        str(expires).encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    query = urllib.parse.urlencode({"expires": expires, "sig": signature})

    # Authentication passes, so the route reaches input validation.
    status, body, _ = _http(streamer_daemon, f"/stream?{query}")
    assert status == 400
    assert b"Missing info_hash" in body

    status, _, _ = _http(streamer_daemon, f"/stream?expires={expires}&sig=deadbeef")
    assert status == 401

    # A signed stream URL must not unlock the control plane.
    status, _, _ = _http(streamer_daemon, f"/status?{query}")
    assert status == 401


def test_foreign_host_header_is_rejected(streamer_daemon):
    status, _, _ = _http(streamer_daemon, "/health", headers={"Host": "evil.example"})
    assert status == 403


def test_control_plane_has_no_wildcard_cors(streamer_daemon):
    status, _, headers = _http(streamer_daemon, "/health")
    assert status == 200
    assert headers.get("Access-Control-Allow-Origin") is None


def test_api_key_session_cookie_authenticates_media(client, monkeypatch):
    monkeypatch.setattr(settings, "API_KEY", "secret-key")
    monkeypatch.setattr(
        "routers.stream.get_daemon_status",
        AsyncMock(return_value={"status": "offline", "active_torrents": 0, "sessions": []}),
    )

    status = client.get("/api/v1/auth/status")
    assert status.status_code == 200
    assert status.json() == {"auth_required": True, "authenticated": False}

    assert client.get("/api/v1/stream/status").status_code == 403

    wrong = client.post("/api/v1/auth/session", json={"api_key": "wrong"})
    assert wrong.status_code == 403

    login = client.post("/api/v1/auth/session", json={"api_key": "secret-key"})
    assert login.status_code == 200
    cookie_header = login.headers["set-cookie"].lower()
    assert "httponly" in cookie_header
    assert "samesite=lax" in cookie_header
    assert "max-age" in cookie_header

    assert client.get("/api/v1/auth/status").json()["authenticated"] is True
    media = client.get("/api/v1/stream/status")
    assert media.status_code == 200
    assert media.json()["status"] == "offline"

    assert client.get(
        "/api/v1/stream/status", headers={"X-API-Key": "secret-key"}
    ).status_code == 200

    session_cookie = client.cookies.get("evo_session")
    client.cookies.set("evo_session", session_cookie[:-2] + "00")
    assert client.get("/api/v1/stream/status").status_code == 403


def test_session_logout_and_open_mode(client, monkeypatch):
    monkeypatch.setattr(settings, "API_KEY", "secret-key")
    client.post("/api/v1/auth/session", json={"api_key": "secret-key"})
    logout = client.delete("/api/v1/auth/session")
    assert logout.status_code == 200
    assert logout.json()["authenticated"] is False
    assert client.get("/api/v1/auth/status").json()["authenticated"] is False

    monkeypatch.setattr(settings, "API_KEY", "")
    status = client.get("/api/v1/auth/status")
    assert status.json() == {"auth_required": False, "authenticated": True}
    assert client.post("/api/v1/auth/session", json={"api_key": "anything"}).status_code == 400


def test_cometnet_announcements_require_api_key(client, monkeypatch):
    monkeypatch.setattr(settings, "API_KEY", "secret-key")
    info_hash = "2222333344445555666677778888999900001111"
    torrent_payload = {"info_hash": info_hash, "title": "Protected Announce", "size": 1234}
    cache_payload = {"info_hash": info_hash, "provider": "realdebrid", "cached": True}

    assert client.post("/api/v1/cometnet/announce/torrent", json=torrent_payload).status_code == 403
    assert client.post("/api/v1/cometnet/announce/cache", json=cache_payload).status_code == 403

    assert client.get("/api/v1/cometnet/stats").status_code == 200
    assert client.get(f"/api/v1/cometnet/lookup/{info_hash}").status_code == 200

    allowed = {"X-API-Key": "secret-key"}
    assert client.post(
        "/api/v1/cometnet/announce/torrent", json=torrent_payload, headers=allowed
    ).status_code == 200
    assert client.post(
        "/api/v1/cometnet/announce/cache", json=cache_payload, headers=allowed
    ).status_code == 200


def test_session_cookie_reaches_media_route_with_daemon_secret(client, monkeypatch):
    import core.torrent_streamer as ts

    monkeypatch.setattr(settings, "API_KEY", "secret-key")
    monkeypatch.setattr(ts, "_streamer_token", None)
    monkeypatch.setenv("EVO_STREAMER_TOKEN", "media-daemon-token")
    # This test exercises proxy-hop token propagation; pin the proxy path explicitly.
    monkeypatch.setenv("EVO_DIRECT_RANGE", "false")

    login = client.post("/api/v1/auth/session", json={"api_key": "secret-key"})
    assert login.status_code == 200

    captured = {}

    class MockContent:
        async def iter_chunked(self, size):
            yield b"media-bytes"

    class MockResponse:
        status = 206
        headers = {"Content-Type": "video/mp4", "Content-Length": "11"}
        content = MockContent()

        def close(self):
            pass

    class MockSession:
        async def get(self, url, headers=None, timeout=None):
            captured["url"] = url
            captured["headers"] = dict(headers or {})
            return MockResponse()

    async def mock_session():
        return MockSession()

    monkeypatch.setattr(
        "routers.stream.ensure_streaming_daemon", AsyncMock(return_value=True)
    )
    monkeypatch.setattr("routers.stream.get_http_session", mock_session)

    response = client.get(
        "/api/v1/stream/play?info_hash=" + "a" * 40 + "&file_idx=0",
        headers={"Range": "bytes=0-10"},
    )
    assert response.status_code == 206
    assert response.content == b"media-bytes"

    assert captured["headers"]["X-Evo-Streamer-Token"] == "media-daemon-token"
    assert captured["headers"]["Range"] == "bytes=0-10"
    assert "expires=" in captured["url"]
    assert "sig=" in captured["url"]


def test_ui_bootstraps_a_cookie_session_before_loading_data():
    app_js = (REPO_ROOT / "static" / "app.js").read_text(encoding="utf-8")

    assert "/api/v1/auth/status" in app_js
    assert "/api/v1/auth/session" in app_js
    assert "await ensureAuthSession()" in app_js
    assert "window.location.reload()" in app_js


def test_python_daemon_spawn_uses_token_and_stops_verified_process(tmp_path, monkeypatch):
    import asyncio
    import core.torrent_streamer as ts

    port = _free_port()
    torrent_port = _free_port()
    dht_port = _free_port()

    monkeypatch.setattr(ts, "STREAM_PORT", port)
    monkeypatch.setattr(ts, "DAEMON_URL", f"http://127.0.0.1:{port}")
    monkeypatch.setattr(ts, "TORRENT_PORT", torrent_port)
    monkeypatch.setattr(ts, "DHT_PORT", dht_port)
    monkeypatch.setattr(ts, "_daemon_process", None)
    monkeypatch.setattr(ts, "_streamer_token", None)
    monkeypatch.setattr(ts, "_anonymous_daemon_warned", False)
    monkeypatch.setattr(settings, "STREAM_BIND_HOST", "127.0.0.1")
    monkeypatch.setattr(settings, "STREAM_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.delenv("EVO_STREAMER_TOKEN", raising=False)
    monkeypatch.delenv("STREAMER_TOKEN", raising=False)
    monkeypatch.setenv("EVO_STREAM_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("EVO_ENGINE_OFFLINE", "1")

    assert ts.start_daemon_process() is True
    proc = ts._daemon_process
    assert proc is not None

    async def probe_until_ready():
        try:
            for _ in range(75):
                if await ts.is_daemon_healthy():
                    return await ts.get_daemon_status()
                await asyncio.sleep(0.2)
            return None
        finally:
            if ts._session and not ts._session.closed:
                await ts._session.close()
            ts._session = None

    try:
        status = asyncio.run(probe_until_ready())
        assert status is not None and status.get("status") == "online", status

        token_path = tmp_path / "cache" / "streamer.token"
        assert token_path.is_file()
        token = token_path.read_text(encoding="utf-8").strip()
        assert len(token) >= 32

        assert _http(port, "/status")[0] == 401
        assert _http(port, "/status", headers={TOKEN_HEADER: token})[0] == 200
    finally:
        ts.stop_daemon_process()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)

    assert proc.poll() is not None


def test_streamer_token_persists_in_cache(tmp_path, monkeypatch):
    import core.torrent_streamer as ts

    monkeypatch.delenv("EVO_STREAMER_TOKEN", raising=False)
    monkeypatch.delenv("STREAMER_TOKEN", raising=False)
    monkeypatch.delenv("EVO_STREAM_CACHE_DIR", raising=False)
    monkeypatch.setattr(settings, "STREAMER_TOKEN", None)
    monkeypatch.setattr(settings, "STREAM_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setattr(ts, "_streamer_token", None)

    token = ts.get_streamer_token()
    assert len(token) >= 32
    token_path = tmp_path / "cache" / "streamer.token"
    assert token_path.is_file()
    assert token_path.read_text(encoding="utf-8") == token

    monkeypatch.setattr(ts, "_streamer_token", None)
    assert ts.get_streamer_token() == token

    monkeypatch.setenv("EVO_STREAMER_TOKEN", "env-token-value")
    monkeypatch.setattr(ts, "_streamer_token", None)
    assert ts.get_streamer_token() == "env-token-value"


def test_internal_stream_url_carries_short_lived_hmac(monkeypatch):
    import core.torrent_streamer as ts

    monkeypatch.setenv("EVO_STREAMER_TOKEN", "url-signing-token")
    monkeypatch.setattr(ts, "_streamer_token", None)

    url = ts.get_internal_stream_url("a" * 40, file_idx=2)
    query = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
    expires = int(query["expires"][0])
    assert time.time() < expires <= time.time() + ts.STREAM_URL_TTL_SECONDS + 5
    expected = hmac.new(
        b"url-signing-token",
        str(expires).encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    assert query["sig"][0] == expected

    stale = int(time.time()) - 1
    stale_sig = hmac.new(
        b"url-signing-token", str(stale).encode("utf-8"), hashlib.sha256
    ).hexdigest()
    assert not ts.verify_stream_signature(stale, stale_sig)
    assert not ts.verify_stream_signature(expires, "00" * 32)
    assert ts.verify_stream_signature(expires, expected)


def test_process_identity_requires_the_actual_streamer_script(monkeypatch):
    import core.torrent_streamer as ts

    fake = MagicMock()
    fake.name.return_value = "node.exe"
    fake.cmdline.return_value = ["C:\\Program Files\\nodejs\\node.exe", "C:\\other\\app.js"]
    fake.cwd.return_value = "C:\\other"
    with patch("psutil.Process", return_value=fake):
        assert ts.is_node_streamer_pid(1234) is False

    fake.cmdline.return_value = ["C:\\Program Files\\nodejs\\node.exe", ts.SERVER_SCRIPT]
    fake.cwd.return_value = ts.STREAMER_DIR
    with patch("psutil.Process", return_value=fake):
        assert ts.is_node_streamer_pid(1234) is True

    fake.cmdline.return_value = ["node", "server.js"]
    fake.cwd.return_value = ts.STREAMER_DIR
    with patch("psutil.Process", return_value=fake):
        assert ts.is_node_streamer_pid(1234) is True

    fake.cmdline.return_value = ["python", "server.js"]
    fake.name.return_value = "python.exe"
    with patch("psutil.Process", return_value=fake):
        assert ts.is_node_streamer_pid(1234) is False


def test_stop_daemon_refuses_unverified_process(monkeypatch):
    import core.torrent_streamer as ts

    fake = MagicMock()
    fake.pid = 4321
    monkeypatch.setattr(ts, "_daemon_process", fake)
    monkeypatch.setattr(ts, "is_node_streamer_pid", lambda pid: False)

    ts.stop_daemon_process()
    fake.terminate.assert_not_called()
    fake.kill.assert_not_called()
    assert ts._daemon_process is None
