import sys
import os

# Ensure EvoScrapper root is in python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from fastapi.testclient import TestClient
from main import app

client = TestClient(app)


def test_root_ui():
    response = client.get("/")
    assert response.status_code == 200
    assert "EvoScrapper" in response.text
    assert "text/html" in response.headers.get("content-type", "")


def test_api_manifest():
    response = client.get("/api")
    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "EvoScrapper API"
    assert data["version"] == app.version  # track the app version, not a hardcoded string


def test_health():
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["app"] == "EvoScrapper"
    assert data["total_providers"] >= 15
    assert len(data["providers"]) >= 15
    assert "subsystems" in data


def test_ready():
    response = client.get("/ready")
    assert response.status_code == 200
    data = response.json()
    assert data["ready"] is True
    assert data["healthy_providers"] > 0


def test_providers_status():
    response = client.get("/api/v1/providers/status")
    assert response.status_code == 200
    providers = response.json()
    assert isinstance(providers, list)
    names = [p["name"] for p in providers]
    assert "yts" in names
    assert "thepiratebay" in names
    assert "nyaa" in names
    assert "opensubtitles" in names
    assert "gestdown" in names


def test_torrent_search_single_provider():
    # Test YTS with Avatar
    response = client.get("/api/v1/torrents/search?query=avatar&provider=yts&limit=3")
    assert response.status_code == 200
    data = response.json()
    assert data["provider"] == "yts"
    assert "data" in data
    print(f"[+] YTS search test returned {len(data['data'])} items in {data['time_taken']}s")


def test_subtitles_search():
    # Test OpenSubtitles fallback with Interstellar IMDb ID
    response = client.get("/api/v1/subtitles/search?imdb_id=tt0816692&limit=5")
    assert response.status_code == 200
    data = response.json()
    assert "data" in data
    print(f"[+] Subtitle search returned {len(data['data'])} subtitles in {data['time_taken']}s")


def test_media_lookup():
    # Test combined media bundle
    response = client.get("/api/v1/media/lookup?query=avatar&limit=5")
    assert response.status_code == 200
    data = response.json()
    assert "torrents" in data
    assert "subtitles" in data
    print(f"[+] Media lookup returned {data['total_torrents']} torrents and {data['total_subtitles']} subs in {data['execution_time_seconds']}s")


if __name__ == "__main__":
    print("[*] Running E2E API tests...")
    test_root_ui()
    test_api_manifest()
    test_health()
    test_ready()
    test_providers_status()
    test_torrent_search_single_provider()
    test_subtitles_search()
    test_media_lookup()
    print("[+] ALL E2E API tests passed successfully!")
