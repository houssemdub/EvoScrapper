import asyncio
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from core.library_manager import LibraryManager
from models.library import LibraryItem


async def test_library_manager():
    test_db = "data/test_library.json"
    if os.path.exists(test_db):
        os.remove(test_db)

    mgr = LibraryManager(storage_path=test_db)

    # 1. Add Fairy Tail to Plan to Watch
    item1 = LibraryItem(
        id="tt1528406",
        title="Fairy Tail",
        type="anime",
        year="2009",
        status="plan_to_watch",
        total_episodes=340,
    )
    await mgr.upsert_item(item1)

    # 2. Add Inception as Watching
    item2 = LibraryItem(
        id="tt1375666",
        title="Inception",
        type="movie",
        year="2010",
        status="watching",
        progress_percent=45,
    )
    await mgr.upsert_item(item2)

    # 3. Verify counts
    res = await mgr.get_items()
    assert res.total == 2, f"Expected 2 items, got {res.total}"
    assert res.counts["all"] == 2
    assert res.counts["plan_to_watch"] == 1
    assert res.counts["watching"] == 1
    assert res.counts["completed"] == 0
    print(f"[+] Initial library counts verified: {res.counts}")

    # 4. Update Fairy Tail progress: watched S01E08
    updated = await mgr.update_progress(
        item_id="tt1528406",
        season=1,
        episode=8,
        progress_percent=95,
    )
    assert updated is not None
    assert updated.status == "watching", f"Status should auto-transition to watching, got {updated.status}"
    assert updated.current_season == 1
    assert updated.current_episode == 8
    print(f"[+] Progress updated: '{updated.title}' is now {updated.status} S{updated.current_season}E{updated.current_episode}")

    # 5. Mark Fairy Tail as Completed
    completed = await mgr.update_status(item_id="tt1528406", status="completed")
    assert completed is not None
    assert completed.status == "completed"
    print(f"[+] Status updated: '{completed.title}' is now {completed.status}")

    # 6. Verify status filtering
    completed_res = await mgr.get_items(status="completed")
    assert completed_res.total == 1
    assert completed_res.items[0].id == "tt1528406"
    print(f"[+] Filter by status='completed' passed: 1 item found")

    # 7. Remove Inception
    removed = await mgr.remove_item("tt1375666")
    assert removed is True
    res_after = await mgr.get_items()
    assert res_after.total == 1
    print(f"[+] Remove item passed. Remaining items: {res_after.total}")

    # Clean up test file
    if os.path.exists(test_db):
        os.remove(test_db)


if __name__ == "__main__":
    asyncio.run(test_library_manager())
    print("[+] All Library Manager tests passed successfully!")
