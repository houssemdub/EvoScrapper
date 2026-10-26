import asyncio
import socket
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import HTTPException

import core.security as security
import core.stremio_addon as addons
from core.client import HttpClient


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


@pytest.mark.parametrize("url", [
    "", None, "file:///etc/passwd", "ftp://8.8.8.8/file", "http://",
    "http://[::1", "http://8.8.8.8:invalid/", "http://user:secret@8.8.8.8/",
    "https://addon.example/\nrequest",
])
def test_rejects_malformed_or_credentialed_urls(url):
    with pytest.raises(HTTPException) as exc:
        security.validate_outbound_proxy_url(url)
    assert exc.value.status_code == 400


@pytest.mark.parametrize("url", [
    "http://127.0.0.1/", "http://10.0.0.1/", "http://169.254.169.254/",
    "http://100.64.0.1/", "http://224.0.0.1/", "http://[::1]/",
    "http://[::ffff:127.0.0.1]/", "http://[fc00::1]/", "http://[fe80::1]/",
    "http://[2001:db8::1]/",
])
def test_rejects_non_public_ip_literals(url):
    with pytest.raises(HTTPException) as exc:
        security.validate_outbound_proxy_url(url)
    assert exc.value.status_code == 403


@pytest.mark.parametrize("url", [
    "https://addon.example/manifest.json", "http://8.8.8.8/file",
    "https://[2606:4700:4700::1111]/file",
])
def test_accepts_public_urls_and_trims_whitespace(url):
    assert security.validate_outbound_proxy_url("  " + url + "  ") == url


@pytest.mark.parametrize("private_ip", ["10.0.0.1", "::1", "::ffff:127.0.0.1"])
def test_rejects_a_hostname_if_any_dns_address_is_non_public(monkeypatch, private_ip):
    monkeypatch.setattr(socket, "getaddrinfo", lambda host, port, **kwargs: [
        (socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("8.8.8.8", port)),
        (socket.AF_INET6, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", (private_ip, port, 0, 0)),
    ])
    with pytest.raises(HTTPException) as exc:
        security.validate_outbound_proxy_url("https://mixed.example/file")
    assert exc.value.status_code == 403


def test_rejects_unresolvable_or_empty_dns_results(monkeypatch):
    def fail_dns(*args, **kwargs):
        raise socket.gaierror("mock DNS failure")

    for lookup in (fail_dns, lambda *args, **kwargs: []):
        monkeypatch.setattr(socket, "getaddrinfo", lookup)
        with pytest.raises(HTTPException) as exc:
            security.validate_outbound_proxy_url("https://missing.example/file")
        assert exc.value.status_code == 400


class TrackedBody(httpx.AsyncByteStream):
    def __init__(self, data=b"mock payload", cancel=False):
        self.data = data
        self.cancel = cancel
        self.reads = 0
        self.closed = False

    async def __aiter__(self):
        self.reads += 1
        if self.cancel:
            raise asyncio.CancelledError()
        yield self.data

    async def aclose(self):
        self.closed = True


@pytest.mark.parametrize("redirect_code", [301, 302, 303, 307, 308])
async def test_blocks_private_redirect_before_sending_and_closes_intermediate(redirect_code):
    seen = []
    body = TrackedBody()

    def handle(request):
        seen.append(str(request.url))
        return httpx.Response(redirect_code, headers={"location": "http://127.0.0.1/private"}, stream=body)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle), follow_redirects=True) as client:
        with pytest.raises(HTTPException) as exc:
            await security.fetch_public_url(client, "https://addon.example/source")
    assert exc.value.status_code == 403
    assert seen == ["https://addon.example/source"]
    assert body.closed and body.reads == 0


async def test_follows_valid_relative_redirects_preserving_range_and_stream_ownership():
    seen = []
    intermediate = [TrackedBody(), TrackedBody()]
    final_body = TrackedBody(b"video bytes")

    def handle(request):
        seen.append(request)
        if len(seen) == 1:
            return httpx.Response(302, headers={"location": "/next"}, stream=intermediate[0])
        if len(seen) == 2:
            return httpx.Response(307, headers={"location": "https://cdn.example/video"}, stream=intermediate[1])
        return httpx.Response(206, headers={"content-range": "bytes 10-20/100"}, stream=final_body)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle), follow_redirects=True) as client:
        response = await security.fetch_public_url(
            client, "https://addon.example/source", stream=True,
            headers={"Range": "bytes=10-20", "Authorization": "secret", "Cookie": "session=secret"},
        )
        assert response.status_code == 206
        assert response.headers["content-range"] == "bytes 10-20/100"
        assert not response.is_stream_consumed and not final_body.closed
        assert all(body.closed and body.reads == 0 for body in intermediate)
        assert [str(request.url) for request in seen] == [
            "https://addon.example/source", "https://addon.example/next", "https://cdn.example/video",
        ]
        assert all(request.headers["range"] == "bytes=10-20" for request in seen)
        assert seen[1].headers["authorization"] == "secret"
        assert "authorization" not in seen[2].headers and "cookie" not in seen[2].headers
        assert b"".join([chunk async for chunk in response.aiter_bytes()]) == b"video bytes"
        await response.aclose()
    assert final_body.closed


async def test_closes_a_buffered_final_response_and_preserves_bytes():
    body = TrackedBody()
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200, stream=body))) as client:
        response = await security.fetch_public_url(client, "https://addon.example/file", timeout=2.0)
    assert response.content == b"mock payload"
    assert response.is_closed and body.closed and body.reads == 1


async def test_closes_buffered_response_on_cancellation():
    body = TrackedBody(cancel=True)
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200, stream=body))) as client:
        with pytest.raises(asyncio.CancelledError):
            await security.fetch_public_url(client, "https://addon.example/file")
    assert body.closed


async def test_bounds_redirects_without_reading_redirect_bodies():
    bodies = []

    def handle(request):
        body = TrackedBody()
        bodies.append(body)
        return httpx.Response(302, headers={"location": "/loop"}, stream=body)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle), follow_redirects=True) as client:
        with pytest.raises(HTTPException) as exc:
            await security.fetch_public_url(client, "https://addon.example/loop")
    assert exc.value.status_code == 400
    assert len(bodies) == 6
    assert all(body.closed and body.reads == 0 for body in bodies)


@pytest.mark.parametrize("location", ["file:///etc/passwd", "http://[invalid"])
async def test_rejects_invalid_redirect_targets(location):
    body = TrackedBody()
    async with httpx.AsyncClient(transport=httpx.MockTransport(
        lambda request: httpx.Response(302, headers={"location": location}, stream=body),
    )) as client:
        with pytest.raises(HTTPException) as exc:
            await security.fetch_public_url(client, "https://addon.example/file")
    assert exc.value.status_code == 400
    assert body.closed and body.reads == 0


@pytest.mark.parametrize("target", ["http://127.0.0.1/file", "https://addon.example/file"])
async def test_public_json_client_blocks_initial_private_urls_and_redirects(monkeypatch, target):
    seen = []

    def handle(request):
        seen.append(str(request.url))
        return httpx.Response(302, headers={"location": "http://127.0.0.1/private"})

    wrapper = HttpClient()
    async with httpx.AsyncClient(transport=httpx.MockTransport(handle), follow_redirects=True) as client:
        monkeypatch.setattr(wrapper, "get_httpx_client", AsyncMock(return_value=client))
        with pytest.raises(HTTPException) as exc:
            await wrapper.get_public_json(target, timeout=2.0)
    assert exc.value.status_code == 403
    assert seen == ([] if target.startswith("http://127.") else [target])


async def test_public_json_client_accepts_valid_redirects(monkeypatch):
    def handle(request):
        if request.url.host == "addon.example":
            return httpx.Response(302, headers={"location": "https://cdn.example/manifest.json"})
        return httpx.Response(200, json={"id": "mock.addon", "name": "Mock Addon"})

    wrapper = HttpClient()
    async with httpx.AsyncClient(transport=httpx.MockTransport(handle), follow_redirects=True) as client:
        monkeypatch.setattr(wrapper, "get_httpx_client", AsyncMock(return_value=client))
        assert await wrapper.get_public_json("https://addon.example/manifest.json") == {
            "id": "mock.addon", "name": "Mock Addon",
        }


async def call_addon(resource, url):
    if resource == "manifest":
        return await addons.fetch_addon_manifest(url)
    return await addons.fetch_addon_streams(url, "movie", "tt0000000")


@pytest.mark.parametrize("resource", ["manifest", "streams"])
@pytest.mark.parametrize("target", ["http://127.0.0.1/addon", "https://addon.example"])
async def test_addon_fetchers_block_private_targets_and_redirects(monkeypatch, resource, target):
    seen = []

    def handle(request):
        seen.append(str(request.url))
        if request.url.host == "addon.example":
            return httpx.Response(302, headers={"location": "http://127.0.0.1/private"})
        return httpx.Response(200, json={"id": "mock.addon", "name": "Mock Addon", "streams": []})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle), follow_redirects=True) as client:
        monkeypatch.setattr(addons.http_client, "get_httpx_client", AsyncMock(return_value=client))
        with pytest.raises(HTTPException) as exc:
            await call_addon(resource, target)
    assert exc.value.status_code == 403
    assert len(seen) == (0 if target.startswith("http://127.") else 1)
    assert all("127.0.0.1" not in url for url in seen)


@pytest.mark.parametrize("resource", ["manifest", "streams"])
async def test_addon_fetchers_preserve_valid_results(monkeypatch, resource):
    payload = {
        "id": "mock.addon", "name": "Mock Addon",
        "streams": [{"infoHash": "a" * 40, "title": "Mock Film", "fileIdx": 2}],
    }
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200, json=payload))) as client:
        monkeypatch.setattr(addons.http_client, "get_httpx_client", AsyncMock(return_value=client))
        result = await call_addon(resource, "stremio://addon.example/manifest.json")
    if resource == "manifest":
        assert result["id"] == "mock.addon"
        assert result["_base_url"] == "https://addon.example"
    else:
        assert result[0]["info_hash"] == "a" * 40
        assert result[0]["file_idx"] == 2
        assert result[0]["magnet"].startswith("magnet:?xt=urn:btih:")
