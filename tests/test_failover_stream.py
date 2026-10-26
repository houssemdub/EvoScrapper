"""P4 completion: cross-source failover streaming at exact byte offsets."""
import asyncio
import sys
import os
from unittest.mock import AsyncMock, MagicMock

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from core.failover_stream import stream_with_failover, _resume_range, _range_start


class FakeContent:
    def __init__(self, chunks, raise_after=None):
        self._chunks = list(chunks)
        self._raise_after = raise_after

    async def iter_chunked(self, size):
        served = 0
        for chunk in self._chunks:
            if self._raise_after is not None and served >= self._raise_after:
                raise ConnectionResetError("simulated mid-stream stall")
            served += len(chunk)
            yield chunk


class FakeResponse:
    def __init__(self, status, headers, chunks, raise_after=None):
        self.status = status
        self.headers = headers
        self.content = FakeContent(chunks, raise_after)
        self.closed = False

    def close(self):
        self.closed = True


class FakeSession:
    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []

    async def get(self, url, headers=None, timeout=None):
        self.calls.append({"url": url, "headers": headers})
        resp = self._responses.pop(0)
        if isinstance(resp, Exception):
            raise resp
        return resp


def test_range_parsing():
    assert _range_start("bytes=100-500") == 100
    assert _range_start("bytes=-") == 0
    assert _range_start(None) == 0
    assert _resume_range("bytes=100-999", served=50, total=1000) == "bytes=150-"
    assert _resume_range("bytes=0-", served=900, total=1000) == "bytes=900-"
    assert _resume_range("bytes=0-", served=1000, total=1000) is None


@pytest.mark.asyncio
async def test_fails_over_at_exact_byte_offset():
    """Source A dies after 2 chunks; source B must resume at served offset."""
    session = FakeSession([
        FakeResponse(
            206,
            {"Content-Range": "bytes 0-999/1000"},
            [b"x" * 100, b"y" * 100],
            raise_after=200,  # dies after both chunks are consumed
        ),
        FakeResponse(
            206,
            {"Content-Range": "bytes 200-999/1000"},
            [b"z" * 200],
        ),
    ])

    out = []
    async for chunk in stream_with_failover(session, ["http://a", "http://b"], original_range="bytes=0-"):
        out.append(chunk)

    assert b"".join(out) == b"x" * 100 + b"y" * 100 + b"z" * 200
    assert len(session.calls) == 2
    assert session.calls[1]["headers"]["Range"] == "bytes=200-"


@pytest.mark.asyncio
async def test_unavailable_first_source_falls_through():
    session = FakeSession([
        ConnectionError("refused"),
        FakeResponse(206, {"Content-Length": "5"}, [b"hello"]),
    ])
    out = []
    async for chunk in stream_with_failover(session, ["http://a", "http://b"]):
        out.append(chunk)
    assert b"".join(out) == b"hello"
    assert session.calls[0]["url"] == "http://a"


@pytest.mark.asyncio
async def test_all_sources_dead_yields_nothing():
    session = FakeSession([ConnectionError("a"), ConnectionError("b")])
    out = []
    async for chunk in stream_with_failover(session, ["http://a", "http://b"]):
        out.append(chunk)
    assert out == []


@pytest.mark.asyncio
async def test_clean_eof_does_not_fail_over():
    session = FakeSession([
        FakeResponse(206, {"Content-Range": "bytes 0-99/100"}, [b"x" * 100]),
    ])
    out = []
    async for chunk in stream_with_failover(session, ["http://a", "http://b"], original_range="bytes=0-"):
        out.append(chunk)
    assert len(session.calls) == 1
    assert b"".join(out) == b"x" * 100


@pytest.mark.asyncio
async def test_client_disconnect_propagates_without_failover():
    """A cancelled client must not silently continue on the backup source."""
    session = FakeSession([
        FakeResponse(206, {"Content-Range": "bytes 0-999/1000"}, [b"a" * 10] * 100),
    ])

    async def consume():
        async for _ in stream_with_failover(session, ["http://a", "http://b"], original_range="bytes=0-"):
            await asyncio.sleep(0)
            break  # client aborts after first chunk

    await consume()
    # Client abort must not contact the backup source.
    assert len(session.calls) == 1
    assert session.calls[0]["url"] == "http://a"
