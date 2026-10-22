import asyncio
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from core.debrid.proxy import DebridStreamProxy, get_debrid_proxy

@pytest.fixture
def proxy():
    return DebridStreamProxy(secret_key="test-secret-key-12345")

def test_token_generation_and_verification(proxy):
    upstream_url = "https://cdn.real-debrid.com/d/ABCD/sample_movie.mp4"
    token = proxy.generate_token(upstream_url, filename="sample_movie.mp4", expires_in=3600)
    assert token is not None
    assert isinstance(token, str)

    payload = proxy.verify_token(token)
    assert payload is not None
    assert payload["url"] == upstream_url
    assert payload["filename"] == "sample_movie.mp4"
    assert "exp" in payload

def test_token_expiration(proxy):
    upstream_url = "https://cdn.real-debrid.com/d/ABCD/sample_movie.mp4"
    # Negative expiration -> expired immediately
    token = proxy.generate_token(upstream_url, expires_in=-10)
    payload = proxy.verify_token(token)
    assert payload is None

def test_token_tampering(proxy):
    upstream_url = "https://cdn.real-debrid.com/d/ABCD/sample_movie.mp4"
    token = proxy.generate_token(upstream_url, expires_in=3600)
    # Tamper with the token
    tampered = token[:-4] + ("AAAA" if token[-4:] != "AAAA" else "BBBB")
    assert proxy.verify_token(tampered) is None

def test_proxy_url_generation(proxy):
    upstream_url = "https://cdn.alldebrid.com/dl/xyz"
    proxy_url = proxy.get_proxy_url(upstream_url, filename="test.mkv")
    assert proxy_url.startswith("/api/v1/stream/debrid/proxy?token=")
    assert "&filename=test.mkv" in proxy_url or "test.mkv" in proxy_url

@pytest.mark.asyncio
async def test_proxy_stream_headers_and_status(proxy):
    upstream_url = "https://cdn.real-debrid.com/stream/video.mp4"
    
    mock_response = MagicMock()
    mock_response.status_code = 206
    mock_response.headers = {
        "content-range": "bytes 0-1023/5000000",
        "content-length": "1024",
        "content-type": "video/mp4",
        "accept-ranges": "bytes",
    }
    
    async def mock_aiter_bytes(*args, **kwargs):
        yield b"x" * 512
        yield b"y" * 512

    mock_response.aiter_bytes = mock_aiter_bytes
    mock_response.aclose = AsyncMock()

    class MockAsyncClient:
        def __init__(self, *args, **kwargs):
            self.aclose = AsyncMock()
        async def __aenter__(self):
            return self
        async def __aexit__(self, *args):
            pass
        async def send(self, req, stream=True):
            return mock_response
        def build_request(self, method, url, headers=None):
            return MagicMock()

    with patch("httpx.AsyncClient", MockAsyncClient):
        stream_gen, status, resp_headers = await proxy.create_upstream_stream(
            upstream_url,
            incoming_headers={"range": "bytes=0-1023", "user-agent": "VLC/3.0"}
        )
        assert status == 206
        assert resp_headers["Content-Range"] == "bytes 0-1023/5000000"
        assert resp_headers["Content-Type"] == "video/mp4"
        assert resp_headers["Accept-Ranges"] == "bytes"

        chunks = []
        async for chunk in stream_gen:
            chunks.append(chunk)
        assert len(chunks) == 2
        assert sum(len(c) for c in chunks) == 1024
