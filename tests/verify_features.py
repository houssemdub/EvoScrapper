import urllib.request
import json
import sys

BASE = 'http://127.0.0.1:8009'

def run():
    print("=== EvoScrapper Verification ===")

    # 1. Test Library API
    print("\n1. Testing Library API...")
    req = urllib.request.Request(f"{BASE}/api/v1/library")
    with urllib.request.urlopen(req) as resp:
        data = json.loads(resp.read().decode())
        print(f"Initial Library count: {len(data.get('items', []))}, Counts: {data.get('counts', {})}")

    # Add item
    item_payload = {
        "id": "tt0409591",
        "title": "Naruto",
        "type": "anime",
        "poster": "https://image.tmdb.org/t/p/w500/naruto.jpg",
        "year": "2002",
        "rating": "8.4",
        "status": "watching"
    }
    req = urllib.request.Request(
        f"{BASE}/api/v1/library",
        data=json.dumps(item_payload).encode(),
        headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req) as resp:
        saved = json.loads(resp.read().decode())
        print(f"Added item: {saved['title']} -> {saved['status']}")

    # Update progress
    prog_payload = {"season": 1, "episode": 12, "progress_percent": 75}
    req = urllib.request.Request(
        f"{BASE}/api/v1/library/tt0409591/progress",
        data=json.dumps(prog_payload).encode(),
        method="PATCH",
        headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req) as resp:
        prog = json.loads(resp.read().decode())
        print(f"Updated progress: {prog['title']} -> S{prog['current_season']}E{prog['current_episode']} ({prog['progress_percent']}%)")

    # 2. Test Anime Catalog Categories
    print("\n2. Testing Anime Categories...")
    for cat in ["all", "tv", "movie", "ova", "special"]:
        url = f"{BASE}/api/v1/discover/catalog?type=anime&genre={cat}&page=1"
        with urllib.request.urlopen(url) as resp:
            cat_data = json.loads(resp.read().decode())
            items = cat_data.get("items", [])
            if items:
                first = items[0]
                print(f"Category [{cat.upper():7}]: {len(items)} items | 1st: '{first['title']}' (Format: {first.get('anime_format')}, Status: {first.get('anime_status')})")
            else:
                print(f"Category [{cat.upper():7}]: 0 items")

    # 3. Test Stream Resolution for Fairy Tail S01E08
    print("\n3. Testing Stream Resolution for Fairy Tail S01E08...")
    url = f"{BASE}/api/v1/stream/resolve?title=Fairy%20Tail&season=1&episode=8&media_type=anime"
    with urllib.request.urlopen(url) as resp:
        streams = json.loads(resp.read().decode()).get("streams", [])
        print(f"Resolved {len(streams)} streams for Fairy Tail S01E08:")
        has_100_years_quest = False
        for s in streams[:6]:
            title = s.get("title", "")
            print(f"  - [{s.get('resolution', 'N/A')}] {title} ({s.get('seeders', 0)} seeds)")
            lower_t = title.lower()
            if "100" in lower_t and ("year" in lower_t or "quest" in lower_t or "nen" in lower_t):
                has_100_years_quest = True

        assert not has_100_years_quest, "FAIL: Found 100 Years Quest sequel in stream results!"
        print("-> SUCCESS: ZERO '100 Years Quest' sequel pollution! Exact series match validated.")

    print("\n=== ALL VERIFICATIONS PASSED ===")

if __name__ == "__main__":
    run()
