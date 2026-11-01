import pytest
from fastapi.testclient import TestClient
from main import app
from unittest.mock import AsyncMock, patch

client = TestClient(app)


def test_get_engine_info():
    response = client.get("/api/v1/stream/engine")
    assert response.status_code == 200
    data = response.json()
    assert "active_engine" in data
    assert "configured_engine" in data
    assert "url" in data


def test_get_engine_list():
    response = client.get("/api/v1/stream/engine/list")
    assert response.status_code == 200
    engines = response.json()
    assert isinstance(engines, list)
    names = [e["name"] for e in engines]
    assert "rust" in names
    assert "node" in names
    assert "python" in names


def test_switch_engine_success():
    with patch("core.engine_manager.NodeStreamingEngine.ensure_started", new=AsyncMock(return_value=True)), \
         patch("core.engine_manager.NodeStreamingEngine.is_healthy", new=AsyncMock(return_value=True)):

        response = client.post("/api/v1/stream/engine/switch", json={"engine": "node"})
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "switched"
        assert data["active_engine"] == "node"


def test_switch_engine_invalid():
    response = client.post("/api/v1/stream/engine/switch", json={"engine": "nonexistent_engine"})
    assert response.status_code == 400
