import socket
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from config import settings
from core.client import http_client
from core.debrid import proxy as debrid_proxy
from main import app
from routers import stremio as stremio_router


@pytest.fixture(autouse=True)
def public_dns(monkeypatch):
    """Never consult real DNS or private services in these tests."""
    monkeypatch.setattr(socket, "gethostbyname", lambda host: "8.8.8.8")
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda host, port, **kwargs: [
            (socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("8.8.8.8", port))
        ],
    )


@pytest.fixture
def client():
    return TestClient(app)


def _mock_http_transport(monkeypatch, handler):
    async def transport_client():
        return client

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler), follow_redirects=True)
    monkeypatch.setattr(http_client, "get_httpx_client", AsyncMock(side_effect=transport_client))
    return client


@pytest.mark.parametrize("endpoint", ["/api/v1/subtitles/download", "/api/v1/subtitles/vtt"])
def test_subtitle_routes_block_private_redirects(client, monkeypatch, endpoint):
    seen = []

    def handle(request):
        seen.append(str(request.url))
        return httpx.Response(302, headers={"location": "http://127.0.0.1/private"})

    _mock_http_transport(monkeypatch, handle)
    response = client.get(endpoint, params={"url": "https://subs.example/file.srt"})

    assert response.status_code == 403
    assert seen == ["https://subs.example/file.srt"]


def test_subtitle_download_follows_public_redirect_and_returns_bytes(client, monkeypatch):
    payload = b"1\n00:00:01,000 --> 00:00:02,000\nHello\n"

    def handle(request):
        if request.url.host == "subs.example":
            return httpx.Response(302, headers={"location": "https://cdn.example/file.srt"})
        return httpx.Response(200, content=payload, headers={"content-type": "application/x-subrip"})

    _mock_http_transport(monkeypatch, handle)
    response = client.get(
        "/api/v1/subtitles/download", params={"url": "https://subs.example/file.srt"}
    )

    assert response.status_code == 200
    assert response.content == payload


async def test_debrid_proxy_blocks_private_redirect(monkeypatch):
    seen = []

    def handle(request):
        seen.append(str(request.url))
        return httpx.Response(302, headers={"location": "http://127.0.0.1/private"})

    proxy_client = httpx.AsyncClient(transport=httpx.MockTransport(handle), follow_redirects=True)
    monkeypatch.setattr(debrid_proxy, "get_debrid_proxy_client", lambda: proxy_client)

    proxy = debrid_proxy.DebridStreamProxy(secret_key="test-secret")
    with pytest.raises(HTTPException) as exc:
        await proxy.create_upstream_stream("https://debrid.example/file.mkv")

    assert exc.value.status_code == 403
    assert seen == ["https://debrid.example/file.mkv"]


def test_external_addon_endpoints_require_configured_api_key(client, monkeypatch):
    monkeypatch.setattr(settings, "API_KEY", "secret-key")
    calls = []

    async def fake_manifest(url):
        calls.append(url)
        return {"id": "mock", "name": "Mock"}

    async def fake_streams(**kwargs):
        calls.append(kwargs["addon_url"])
        return []

    monkeypatch.setattr(stremio_router, "fetch_addon_manifest", fake_manifest)
    monkeypatch.setattr(stremio_router, "fetch_addon_streams", fake_streams)

    manifest_params = {"url": "https://addon.example"}
    assert client.get("/api/v1/addons/manifest", params=manifest_params).status_code == 403
    assert (
        client.get(
            "/api/v1/addons/manifest", params=manifest_params, headers={"X-API-Key": "wrong"}
        ).status_code
        == 403
    )
    assert (
        client.get(
            "/api/v1/addons/manifest", params=manifest_params, headers={"X-API-Key": "secret-key"}
        ).status_code
        == 200
    )

    stream_params = {"url": "https://addon.example", "item_id": "tt0000000"}
    assert client.get("/api/v1/addons/streams", params=stream_params).status_code == 403
    assert (
        client.get(
            "/api/v1/addons/streams", params=stream_params, headers={"X-API-Key": "secret-key"}
        ).status_code
        == 200
    )
    assert calls == ["https://addon.example", "https://addon.example"]


def test_external_addon_endpoints_open_when_api_key_is_unset(client, monkeypatch):
    monkeypatch.setattr(settings, "API_KEY", "")

    async def fake_manifest(url):
        return {"id": "mock", "name": "Mock"}

    monkeypatch.setattr(stremio_router, "fetch_addon_manifest", fake_manifest)
    response = client.get("/api/v1/addons/manifest", params={"url": "https://addon.example"})

    assert response.status_code == 200


def test_native_stremio_endpoints_stay_public(client, monkeypatch):
    monkeypatch.setattr(settings, "API_KEY", "secret-key")

    for path in ("/manifest.json", "/stremio/manifest.json"):
        response = client.get(path)
        assert response.status_code == 200
        assert response.json()["id"] == "org.evoscrapper.addon"
