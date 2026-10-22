# Anime Categorization, Watchlist Library & Stream Title Matching Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix anime episode stream accuracy (resolve exact episode releases like Fairy Tail 2009 S01E08 while filtering out sequels like 100 Years Quest), integrate rich Anime APIs (Jikan / Kitsu) with categories (TV, Movie, OVA, Specials) and badges, and introduce a persistent Bookmark & Watchlist Manager with multi-state tracking ("Watching", "Plan to Watch", "Completed", "On Hold", "Dropped").

**Architecture:**
- **Stream Accuracy Engine**: Enhance `core/stream_resolver.py` and `core/anime_offset.py` to dispatch targeted absolute episode queries (`Fairy Tail - 08`, `Fairy Tail 008`) and implement title-boundary filtering to exclude distinct spin-offs/sequels (e.g. "100 Years Quest") when searching base titles.
- **Anime Enrichment Layer**: Build `core/anime_client.py` wrapping Jikan v4 / Kitsu APIs with caching to enrich titles with format (`TV`, `OVA`, `Movie`, `Special`, `ONA`), airing status, Japanese titles, and studio. Wire into `core/discover.py` and `routers/discover.py`.
- **Bookmark & Library Subsystem**: Create `routers/library.py` with persistent JSON backing (`data/library.json`), providing CRUD endpoints for user watchlists with status filters.
- **Frontend Presentation**: Add Anime Category pills to Discover tab, add "My Library" modal and quick bookmark controls to `static/index.html` and `static/app.js`.

**Tech Stack:** Python 3.14, FastAPI, asyncio, Jikan v4 API, Kitsu API, HTML5/CSS3, JavaScript (ES6+).

---

## Tasks

### Task 1: Fix Title Matching & Anime Absolute Episode Queries in Stream Resolver

**Files to modify:**
- `core/anime_offset.py`
- `core/stream_resolver.py`
- `tests/test_streaming.py`

- [ ] **Step 1.1**: Enhance `core/anime_offset.py` to generate prioritized queries for trackers:
  - Western seasonal: `{title} S{season:02d}E{episode:02d}`, `{title} Season {season} {episode:02d}`
  - Absolute numbering: `{title} - {episode:02d}`, `{title} {episode:02d}`, `{title} {episode:03d}`, `{title} 0{episode}`
  - Year-tagged queries for older long-running anime: `{title} 2009 {episode:02d}` or `{title} 2009`

- [ ] **Step 1.2**: In `core/stream_resolver.py`, pass all high-priority queries (up to 6) to providers concurrently (not just `queries[:3]`), and prioritize Nyaa scraper queries for anime absolute numbers.

- [ ] **Step 1.3**: In `core/stream_resolver.py`, implement `is_conflicting_spinoff_or_sequel(queried_title, release_title)`:
  - If `queried_title` does NOT contain "100 years quest" or "100 nen quest", but `release_title` contains "100 years quest" or "100 nen quest", reject it!
  - More generally, detect known distinguishing subtitle patterns (e.g. colon followed by new subtitle, numbers like `100-nen`, `the movie`, `final season` when season is 1) that do not appear in the search query.

- [ ] **Step 1.4**: Update `matches_target_episode` to ensure season packs are correctly identified, and run `pytest tests/test_streaming.py` or `python tests/test_streaming.py` to verify Fairy Tail S01E08 matches only valid S01 / Ep 08 releases.

---

### Task 2: Anime Categorization, Format Filtering & Jikan / Kitsu Enrichment

**Files to create/modify:**
- `core/anime_client.py` (New file)
- `models/discover.py`
- `core/discover.py`
- `routers/discover.py`
- `tests/test_anime_categories.py` (New file)

- [ ] **Step 2.1**: Create `core/anime_client.py` with asynchronous Jikan v4 / Kitsu integration:
  - Fetch anime details by query or MyAnimeList/Kitsu ID: format (`TV`, `OVA`, `Movie`, `Special`, `ONA`), airing status (`airing`, `complete`, `upcoming`), episodes, score, studios, and genres.
  - In-memory caching with 24-hour TTL to prevent rate limits.

- [ ] **Step 2.2**: Update `models/discover.py` to include optional anime metadata fields in `DiscoverItem` and `DiscoverDetail`:
  - `anime_format: Optional[str] = None` (e.g. "TV", "OVA", "Movie", "Special", "ONA")
  - `anime_status: Optional[str] = None` (e.g. "Airing", "Finished", "Upcoming")
  - `studio: Optional[str] = None`

- [ ] **Step 2.3**: Update `core/discover.py` and `routers/discover.py`:
  - Support category query parameter for anime: `sub_type` / `anime_category`: `all`, `tv`, `movie`, `ova`, `specials`.
  - Enrich discover anime items with format and airing status badges.

- [ ] **Step 2.4**: Create `tests/test_anime_categories.py` to verify anime formatting, sub-category fetching, and Jikan enrichment.

---

### Task 3: Bookmark & Watchlist Manager ("My Library") with Multi-State Tracking

**Files to create/modify:**
- `models/library.py` (New file)
- `core/library_manager.py` (New file)
- `routers/library.py` (New file)
- `main.py`
- `tests/test_library.py` (New file)

- [ ] **Step 3.1**: Create `models/library.py`:
  - `LibraryItem`: `id` (IMDb/Kitsu ID), `title`, `type` (`movie`, `series`, `anime`), `poster`, `backdrop`, `year`, `rating`, `status` (`watching`, `plan_to_watch`, `completed`, `on_hold`, `dropped`), `current_season`, `current_episode`, `total_episodes`, `progress_percent`, `created_at`, `updated_at`.

- [ ] **Step 3.2**: Create `core/library_manager.py`:
  - Persistent JSON storage in `data/library.json` (auto-creates directory if missing).
  - Methods: `get_all(status_filter=None)`, `get_item(id)`, `upsert_item(item)`, `remove_item(id)`, `update_progress(id, season, episode, progress_pct)`.

- [ ] **Step 3.3**: Create `routers/library.py` with endpoints:
  - `GET /api/v1/library` (list with optional `status` filter)
  - `GET /api/v1/library/{id}` (get single bookmark)
  - `POST /api/v1/library` (add or update bookmark)
  - `PATCH /api/v1/library/{id}/status` (quick status change)
  - `PATCH /api/v1/library/{id}/progress` (quick progress update)
  - `DELETE /api/v1/library/{id}` (remove bookmark)

- [ ] **Step 3.4**: Register `routers/library.py` in `main.py`.

- [ ] **Step 3.5**: Create and run `tests/test_library.py` to verify CRUD and progress operations.

---

### Task 4: Frontend UI Integration & User Experience

**Files to modify:**
- `static/index.html`
- `static/css/style.css`
- `static/app.js`

- [ ] **Step 4.1**: In `static/index.html`:
  - Add "My Library" button to top navigation bar.
  - In Discover Anime view, add sub-category pills: `[All]`, `[TV Series]`, `[Movies]`, `[OVA / ONA]`, `[Specials / Off-Season]`.
  - Add "My Library" modal with tabs (`All`, `Watching`, `Plan to Watch`, `Completed`, `On Hold`, `Dropped`) and grid view.
  - Add Bookmark dropdown button to title cards and to the `#discover-modal`.

- [ ] **Step 4.2**: In `static/css/style.css`:
  - Style anime format badges (`.tag-anime-tv`, `.tag-anime-ova`, `.tag-anime-movie`, `.tag-anime-special`).
  - Style status badges (`.tag-status-airing`, `.tag-status-finished`).
  - Style Library modal, filter chips, and bookmark action controls.

- [ ] **Step 4.3**: In `static/app.js`:
  - Implement library state and functions: `loadLibrary()`, `renderLibrary()`, `setBookmarkStatus(id, status)`, `removeBookmark(id)`.
  - Connect player watch history so starting/resuming a stream automatically updates status to "Watching" and tracks `current_season` and `current_episode`.
  - Wire Anime category sub-pills in discover catalog.

---

### Task 5: End-to-End Verification

- [ ] **Step 5.1**: Restart backend and test `resolve_streams` for `Fairy Tail S01E08` to ensure only legitimate Fairy Tail 2009 episode 8 streams and season packs are returned (no "100 Years Quest" hijack).
- [ ] **Step 5.2**: Test Anime Categories in Discover (`TV`, `OVA`, `Movie`, `Specials`).
- [ ] **Step 5.3**: Test Bookmark Manager: add item as "Watching", switch to "Completed", verify persistence across reloads.
