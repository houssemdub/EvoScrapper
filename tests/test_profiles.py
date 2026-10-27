import os
import tempfile
import pytest
from fastapi.testclient import TestClient

from core.database import Database
from core.profile_manager import ProfileManager, _hash_pin
from main import app


@pytest.fixture
def client():
    return TestClient(app)


@pytest.mark.asyncio
async def test_profile_manager_lifecycle():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "profiles_test.db")
        db = Database(db_path)
        await db.connect()

        mgr = ProfileManager(db)

        # 1. Default profile created automatically
        profiles = await mgr.list_profiles()
        assert len(profiles) == 1
        assert profiles[0]["id"] == "default"
        assert profiles[0]["has_pin"] is False
        assert profiles[0]["is_kids"] is False

        # 2. Create kid profile
        kid = await mgr.create_profile(name="Kids Corner", avatar="avatar_kids", is_kids=True)
        assert kid["is_kids"] is True
        assert kid["has_pin"] is False

        # 3. Create PIN-protected adult profile
        adult = await mgr.create_profile(name="Parent", avatar="avatar_parent", pin="1234", is_kids=False)
        assert adult["has_pin"] is True

        # 4. Verify PIN
        assert await mgr.verify_pin(adult["id"], "1234") is True
        assert await mgr.verify_pin(adult["id"], "0000") is False
        assert await mgr.verify_pin(kid["id"], "") is True  # No PIN required

        # 5. List profiles
        all_profs = await mgr.list_profiles()
        assert len(all_profs) == 3

        # 6. Delete profile
        deleted = await mgr.delete_profile(kid["id"])
        assert deleted is True
        assert len(await mgr.list_profiles()) == 2

        # 7. Cannot delete when only 1 profile left
        await mgr.delete_profile(adult["id"])
        assert len(await mgr.list_profiles()) == 1
        assert await mgr.delete_profile("default") is False  # Cannot delete last profile

        await db.close()


def test_profiles_api_endpoints(client):
    # Test GET /api/v1/profiles
    res = client.get("/api/v1/profiles")
    assert res.status_code == 200
    profiles = res.json()
    assert isinstance(profiles, list)
    assert len(profiles) >= 1

    # Test POST /api/v1/profiles
    create_res = client.post(
        "/api/v1/profiles",
        json={"name": "Test User", "avatar": "avatar_2", "pin": "9876", "is_kids": False},
    )
    assert create_res.status_code == 201
    created = create_res.json()
    assert created["name"] == "Test User"
    assert created["has_pin"] is True
    prof_id = created["id"]

    # Test GET /api/v1/profiles/{id}
    get_res = client.get(f"/api/v1/profiles/{prof_id}")
    assert get_res.status_code == 200
    assert get_res.json()["name"] == "Test User"

    # Test verify PIN endpoint
    bad_pin_res = client.post(f"/api/v1/profiles/{prof_id}/verify-pin", json={"pin": "0000"})
    assert bad_pin_res.status_code == 403

    good_pin_res = client.post(f"/api/v1/profiles/{prof_id}/verify-pin", json={"pin": "9876"})
    assert good_pin_res.status_code == 200
    assert good_pin_res.json()["verified"] is True

    # Test DELETE /api/v1/profiles/{id}
    del_res = client.delete(f"/api/v1/profiles/{prof_id}")
    assert del_res.status_code == 200
