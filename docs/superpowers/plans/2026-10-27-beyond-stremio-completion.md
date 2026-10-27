# Beyond Stremio Remaining Tasks Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Complete all partial, pending, and foundation tasks outlined in `docs/BEYOND_STREMIO_PLAN.md` to achieve 100% plan completion with full test coverage and verified UI integration.

**Architecture:** Extend the newly introduced async SQLite DAL (`core/database.py`) to absorb swarm heatmaps and debrid coverage indexes (T4.1) as well as multi-user profiles (T4.4). Wire the remaining frontend interfaces in the player (P3 Scene Skip, P7 Trick-play hover preview) and discover catalog (P10 "Why This Stream?"), implement the Stremio `/configure` manifest endpoint (T4.6), and modularize `static/app.js` (T4.2).

**Tech Stack:** Python 3.12/3.14, FastAPI, aiosqlite, pytest, vanilla ES6+, HTML5/CSS3 custom video player, Stremio Addon Protocol v3.

**Spec:** `docs/BEYOND_STREMIO_PLAN.md`

## Global Constraints
- **Spec-Driven & TDD**: Every backend addition must be preceded or accompanied by isolated `pytest` regression tests.
- **Deterministic Verification**: `pytest` must pass with zero failures at every task boundary.
- **No Speculative Rewrites**: UI modifications must be strictly scoped diffs in `static/app.js` and `static/style.css` preserving all existing player hotkeys, HLS, WebRTC, and Stremio streaming flows.
- **Token & Quota Economy**: Keep modifications concise, well-tested, and surgical.

## Review Focus
1. SQLite concurrency: WAL mode must keep readers non-blocking during heavy gossip insertion batches.
2. Player scrub accuracy: Thumbnail preview coordinates must map correctly to `EVO_SPRITE_SCAN_SECONDS` and sprite sheet grid dimensions without throwing on unprobed videos.
3. Scene skip boundary precision: Intro/credits skip chips must appear and disappear synchronously with `video.currentTime` without interrupting manual scrub operations.
4. Profile PIN security: PIN comparison must use constant-time hashing (`hashlib.sha256` with salt) rather than plaintext comparison.
5. Legacy browser fallback: ES module extraction must ensure backward compatibility for embedded WebViews and TV browsers.

---

## Tasks

### Task 1: Complete T4.1 SQLite Storage for Swarm Intelligence (Heatmaps & Debrid Coverage)
- [x] Add `seek_heatmaps` and `debrid_coverage` tables to `core/database.py` schema with appropriate indexes.
- [x] Extend `SeekHeatmapStore` and `DebridCoverageIndex` in `core/swarm_intelligence.py` to persist to SQLite when database is initialized, with automatic JSON fallback/migration.
- [x] Write unit tests in `tests/test_swarm_sqlite.py` verifying async persistence, decay calculations, and index lookups.
- [x] Run verification: `pytest tests/test_swarm_sqlite.py`.

### Task 2: T4.6 Stremio `/configure` Web Route & Manifest Alignment
- [x] Add `GET /configure` and `GET /stremio/configure` endpoint in `routers/stremio.py` rendering a clean, responsive HTML configuration page for Debrid API keys, streaming options, and "Install Addon" button (`stremio://...`).
- [x] Update manifest in `routers/stremio.py` to declare `behaviorHints: { configurable: true, configurationRequired: false }`.
- [x] Write unit test in `tests/test_stremio_server.py` verifying `/configure` returns status 200 with HTML content and manifest matches v3 spec.
- [x] Run verification: `pytest tests/test_stremio_server.py`.

### Task 3: T4.4 Household Multi-User Profiles & PIN Verification
- [x] Add `profiles` table to `core/database.py` (`id`, `name`, `avatar`, `pin_hash`, `salt`, `is_kids`, `created_at`, `updated_at`).
- [x] Create `core/profile_manager.py` with CRUD methods: list profiles, create profile, switch active profile, set PIN, and verify PIN.
- [x] Add API routes in `routers/profiles.py` (`GET /api/v1/profiles`, `POST /api/v1/profiles`, `POST /api/v1/profiles/switch`, `POST /api/v1/profiles/verify-pin`).
- [x] Register `routers/profiles.py` in `main.py`.
- [x] Write unit tests in `tests/test_profiles.py` validating profile creation, PIN hashing, kids mode filtering, and session switching.
- [x] Run verification: `pytest tests/test_profiles.py`.

### Task 4: P3 Scene Boundaries UI (Intro / Credits Skip Buttons)
- [x] Add `#player-scene-skip-container` overlay elements in `static/index.html` and styling in `static/style.css`.
- [x] In `static/app.js`: fetch `GET /api/v1/cometnet/scenes?info_hash=...&duration=...` upon starting playback.
- [x] In `video.ontimeupdate`: evaluate if `currentTime` falls within an intro or credits scene interval; render a sleek "Skip Intro" or "Skip Credits" button.
- [x] On click: seek seamlessly to `scene.end` and track skip engagement.

### Task 5: P7 Scrubber Hover Preview Tooltip UI
- [x] Add `#player-timeline-preview` thumbnail tooltip element in `static/index.html` with styling in `static/style.css` (dimensions 160x90px, border-radius, drop-shadow, timestamp badge).
- [x] In `static/app.js`: attach `mousemove` and `mouseleave` listeners to `#player-timeline-container`.
- [x] On hover: calculate hovering timestamp; compute sprite column and row offsets (`col = idx % 5`, `row = floor(idx / 5)`) from `--evo-sprite-sheet`; update tooltip position and display.

### Task 6: P10 "Why This Stream?" Breakdown UI
- [x] Add "Why This Stream?" action button / badge (`.stream-explain-btn`) to stream cards in the Discover streams modal.
- [x] Add `#stream-explain-modal` drawer in `static/index.html` with styling in `static/style.css`.
- [x] In `static/app.js`: wire click handler on `.stream-explain-btn` to call `GET /api/v1/stream/explain` and render a breakdown of provider cache state, seeds, measured bitrate, codec compatibility, and first-frame prediction.

### Task 7: T4.2 Code Modularization of `static/app.js`
- [x] Create `static/js/` directory structure.
- [x] Extract `static/js/party.js`: Watch-party transport & sync (P8).
- [x] Integrate cleanly with existing globals and scripts in `static/index.html`.
- [x] Run full regression suite: `pytest`.
