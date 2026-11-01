import pytest
from core.py_streamer import parse_range_header, is_py_streamer_healthy, start_py_streamer_daemon, stop_py_streamer_daemon


def test_py_streamer_range_header():
    # Full range
    start, end, length = parse_range_header("bytes=0-499", 1000)
    assert start == 0
    assert end == 499
    assert length == 500

    # Open end range
    start, end, length = parse_range_header("bytes=500-", 1000)
    assert start == 500
    assert end == 999
    assert length == 500

    # Suffix range
    start, end, length = parse_range_header("bytes=-200", 1000)
    assert start == 800
    assert end == 999
    assert length == 200

    # Invalid range raises ValueError
    with pytest.raises(ValueError):
        parse_range_header("bytes=1500-", 1000)


@pytest.mark.asyncio
async def test_py_streamer_lifecycle():
    port = 8895
    try:
        started = start_py_streamer_daemon(port)
        assert started is True

        # Check health
        import asyncio
        healthy = False
        for _ in range(10):
            await asyncio.sleep(0.2)
            if await is_py_streamer_healthy(port):
                healthy = True
                break
        assert healthy is True
    finally:
        stop_py_streamer_daemon()
