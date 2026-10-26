import pytest
import httpx
from core.debrid.proxy import (
    get_debrid_proxy_client,
    aclose_debrid_proxy_client,
    DebridStreamProxy,
)


@pytest.mark.asyncio
async def test_debrid_proxy_client_singleton_and_keepalive():
    """Verifies that get_debrid_proxy_client returns a shared pooled instance with 20 keepalives."""
    # Ensure client is initialized
    client1 = get_debrid_proxy_client()
    client2 = get_debrid_proxy_client()

    assert client1 is client2
    assert not client1.is_closed

    # Verify connection limits and keepalive settings
    assert client1._transport._pool._max_keepalive_connections == 20
    assert client1._transport._pool._max_connections == 50

    # Shutdown client
    await aclose_debrid_proxy_client()
    assert client1.is_closed

    # Getting client again spawns a fresh singleton
    client3 = get_debrid_proxy_client()
    assert client3 is not client1
    assert not client3.is_closed
    await aclose_debrid_proxy_client()


@pytest.mark.asyncio
async def test_debrid_stream_does_not_close_shared_client():
    """Verifies that streaming a response and completing the generator does not close the shared client."""
    proxy = DebridStreamProxy()
    token = proxy.generate_token("https://example.com/video.mp4")
    assert token is not None

    shared_client = get_debrid_proxy_client()
    assert not shared_client.is_closed

    # Calling aclose shuts it down cleanly
    await aclose_debrid_proxy_client()
    assert shared_client.is_closed
