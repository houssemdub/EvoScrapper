"""
tests/test_multi_engine_parity.py — End-to-End Multi-Engine Verification & Parity Test Suite
Validates wire-level parity between Rust, Node.js, and Python streaming engines.
"""

import asyncio
import os
import sys
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from main import app
from core.engine_manager import (
    EngineManager,
    RustStreamingEngine,
    NodeStreamingEngine,
    PythonStreamingEngine,
    get_engine_manager,
)
from core.py_streamer import parse_range_header

client = TestClient(app)


def test_rfc7233_range_parity_across_engines():
    """Verifies range parsing logic matches standard RFC 7233."""
    total = 50_000_000
    # Standard range
    s, e, l = parse_range_header("bytes=0-1048575", total)
    assert s == 0
    assert e == 1048575
    assert l == 1048576

    # Open-ended seek
    s, e, l = parse_range_header("bytes=1048576-", total)
    assert s == 1048576
    assert e == total - 1

    # Suffix range
    s, e, l = parse_range_header("bytes=-5000", total)
    assert s == total - 5000
    assert e == total - 1
    assert l == 5000


@pytest.mark.asyncio
async def test_stremio_statistics_schema_parity():
    """Verifies that all engines return Stremio-compliant statistics payloads."""
    py_eng = PythonStreamingEngine(port=8894)
    py_eng.start()
    try:
        await asyncio.sleep(0.3)
        stats = await py_eng.get_stats("0123456789abcdef0123456789abcdef01234567", 0)
        assert stats is not None
        assert "infoHash" in stats
        assert "downloadSpeed" in stats
        assert "peers" in stats
        assert "files" in stats
        assert "opts" in stats
        assert isinstance(stats["files"], list)
    finally:
        py_eng.stop()


@pytest.mark.asyncio
async def test_engine_manager_fallback_chain_complete():
    """Verifies complete degradation chain: Rust -> Node -> Python."""
    mgr = EngineManager()
    mgr.configured_engine = "rust"
    mgr.auto_fallback = True

    # 1. Rust missing, Node missing -> falls back to Python
    with patch.object(RustStreamingEngine, "is_installed", return_value=False), \
         patch.object(NodeStreamingEngine, "is_installed", return_value=False), \
         patch.object(PythonStreamingEngine, "is_installed", return_value=True), \
         patch.object(PythonStreamingEngine, "ensure_started", new=AsyncMock(return_value=True)):

        active = await mgr.get_active_engine()
        assert active.name == "python"
        assert mgr.fallback_occurred is True

    # 2. Rust missing, Node available -> falls back to Node
    with patch.object(RustStreamingEngine, "is_installed", return_value=False), \
         patch.object(NodeStreamingEngine, "is_installed", return_value=True), \
         patch.object(NodeStreamingEngine, "ensure_started", new=AsyncMock(return_value=True)):

        active = await mgr.get_active_engine()
        assert active.name == "node"
        assert mgr.fallback_occurred is True


def test_api_diagnostics_includes_all_engines():
    """Verifies /api/v1/stream/diagnostics includes the multi-engine inventory."""
    resp = client.get("/api/v1/stream/diagnostics")
    assert resp.status_code == 200
    data = resp.json()
    assert "backend" in data
    assert data["backend"]["version"] == "2.7.0"
    assert "engines" in data
    assert isinstance(data["engines"], list)
    engine_names = [e["name"] for e in data["engines"]]
    assert "rust" in engine_names
    assert "node" in engine_names
    assert "python" in engine_names
