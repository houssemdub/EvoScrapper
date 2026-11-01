import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from core.engine_manager import (
    EngineManager,
    EngineType,
    BaseStreamingEngine,
    RustStreamingEngine,
    NodeStreamingEngine,
    PythonStreamingEngine,
    get_engine_manager,
)


def test_engine_type_enum():
    assert EngineType.RUST.value == "rust"
    assert EngineType.NODE.value == "node"
    assert EngineType.PYTHON.value == "python"
    assert EngineType.AUTO.value == "auto"


@pytest.mark.asyncio
async def test_engine_manager_auto_fallback_when_rust_missing():
    mgr = EngineManager()
    mgr.configured_engine = "rust"
    mgr.auto_fallback = True

    # Mock Rust as unavailable, Node as healthy
    with patch.object(RustStreamingEngine, "is_installed", return_value=False), \
         patch.object(NodeStreamingEngine, "is_healthy", new=AsyncMock(return_value=True)), \
         patch.object(NodeStreamingEngine, "start", return_value=True):

        active = await mgr.get_active_engine()
        assert active.name == "node"
        assert mgr.fallback_occurred is True
        assert mgr.last_fallback_reason == "Rust binary not installed; fell back to Node.js"


@pytest.mark.asyncio
async def test_engine_manager_switch_engine():
    mgr = EngineManager()

    with patch.object(NodeStreamingEngine, "ensure_started", new=AsyncMock(return_value=True)), \
         patch.object(NodeStreamingEngine, "is_healthy", new=AsyncMock(return_value=True)):

        result = await mgr.switch_engine("node")
        assert result["status"] == "switched"
        assert result["active_engine"] == "node"
        assert mgr.configured_engine == "node"


@pytest.mark.asyncio
async def test_engine_manager_list_engines():
    mgr = EngineManager()

    with patch.object(RustStreamingEngine, "is_installed", return_value=False), \
         patch.object(NodeStreamingEngine, "is_installed", return_value=True), \
         patch.object(PythonStreamingEngine, "is_installed", return_value=True):

        engines = await mgr.list_engines()
        assert len(engines) == 3
        engine_map = {e["name"]: e for e in engines}

        assert engine_map["rust"]["available"] is False
        assert engine_map["node"]["available"] is True
        assert engine_map["python"]["available"] is True
