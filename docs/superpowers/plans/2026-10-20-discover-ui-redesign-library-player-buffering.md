# Discover UI Redesign, Library Overhaul, Smart Search & Player Buffering Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

## Overview
A comprehensive frontend and backend upgrade focused on:
1. Elevating the Discover page UI: removing the outdated "NEW" tag, establishing airy sleek filter tiers with generous breathing room, and designing polished glassmorphism card badges.
2. Implementing an interactive press-and-hold (long click) circular SVG loading animation on card bookmark buttons that reveals a quick multi-state status picker.
3. Transforming "MY LIST & FAVORITES" into a premium collapsible shelf with a `[+]` / `[-]` toggle button, persistent state, and rich cards backed by the unified library.
4. Redesigning the "My Library & Watchlist" modal into an expansive power-user manager with card zoom slider, search/filter/sort controls, and full JSON/CSV export & restore.
5. Isolating the top navigation bar from the GUI zoom slider so scaling only adjusts the application body.
6. Adding a smart autocomplete suggestion dropdown to the Discover search bar with media type, poster, year, and keyboard navigation.
7. Implementing an animated buffering progress HUD inside the video player showing buffer fill % and estimated time remaining before video starts.

---

## File Structure & Proposed Changes

| File | Responsibility |
|---|---|
| `static/index.html` | Markup updates: remove "NEW" tag from nav, restructure Discover filters into airy tiers, add collapsible `[+]` button to My List, expand Library modal header/toolbar with slider and backup/restore controls, add search suggestions dropdown container, add player buffering HUD. |
| `static/style.css` | CSS styling: navbar pixel lockdown (isolated from `--gui-scale-px`), Discover filter tiers with air flow, sleek card badges, circular SVG hold animation on bookmark button, collapsible shelf transition, expansive library modal styles, card size slider variable, smart search dropdown, and player buffering progress HUD. |
| `static/app.js` | UI logic: long-press pointer timer and SVG stroke-dashoffset animation on bookmark button, collapsible My List toggle with `localStorage`, Library modal card size slider / search / sort, JSON & CSV export/import restore handlers, smart search suggestions with debounced fetch and keyboard navigation, player buffering progress HUD tracker. |
| `core/library_manager.py` | Add `bulk_upsert_items` for restoring backup batches. |
| `routers/library.py` | Add `POST /api/v1/library/bulk` endpoint for JSON/CSV backup restoration. |
| `core/discover.py` | Add fast `get_discover_suggestions` method querying cached catalogs & popular titles. |
| `routers/discover.py` | Add `GET /api/v1/discover/suggestions?q=...` endpoint. |
| `tests/test_ui_enhancements.py` | Automated tests verifying bulk library upsert, suggestions endpoint, and API contracts. |

---

## Task 1: Navbar Isolation & Discover "NEW" Tag Removal

### Context & Goal
- Remove `<span class="tag tag-new">NEW</span>` from the Discover nav tab.
- Lock `.navbar` and `.nav-tab` font-sizes and paddings using explicit `px` units so that adjustments to the GUI scale slider (which modifies `--gui-scale-px` on `html`) only resize main view content without distorting the top navigation.

### Steps
- [ ] Remove `NEW` badge from `#nav-discover` in `static/index.html`.
- [ ] In `static/style.css`, update `.navbar`, `.navbar-inner`, `.logo`, `.nav-tabs`, `.nav-tab`, `.status-badge`, and `.gui-scale-control` to use explicit `px` values for `font-size`, `padding`, `gap`, and `height` instead of `rem`.
- [ ] Test GUI scale slider to ensure navbar elements remain completely stable while the page body scales.

---

## Task 2: Sleek Discover Filters with Breathing Room & Refined Card Badges

### Context & Goal
- Create separate, sleek filter bars with breathing room ("let the air flow between elements don't stick them too much together").
- Modernize the badges on `.discover-card`:
  - Top-Left: Type badge (`MOVIE`, `SERIES`, `ANIME`) with glassmorphism, subtle neon border.
  - Top-Right: Rating badge with amber glow.
  - Bottom-Left: Stacked format (`SPECIAL`, `OVA`, `TV`) and status (`FINISHED`, `AIRING`) above the year badge.
  - Bottom-Right: Bookmark button.

### Steps
- [ ] In `static/index.html`, restructure Discover controls into distinct airy tiers:
  - Tier 1: Media category pills (`MOVIES`, `TV SERIES`, `ANIME`) + Smart Search input container.
  - Tier 2: Anime format bar (when Anime is active) with generous spacing (`margin: 1.25rem 0`).
  - Tier 3: Genre filter pills with comfortable gap and subtle glass borders.
- [ ] In `static/style.css`, add styles for `.discover-nav-bar`, `.discover-filter-tier`, and refined badge styles with subtle box-shadows and backdrop blurs.
- [ ] In `static/app.js`, ensure `renderDiscoverGrid` applies the refined badge classes.

---

## Task 3: Bookmark Long-Press / Hold Interaction with Circular Loading Ring

### Context & Goal
- When clicking the bookmark icon normally, it performs a 1-click quick toggle.
- When pressing and holding (long-click for 600ms), a circular SVG border smoothly fills around the bookmark icon.
- When the hold duration completes, it opens a sleek floating radial/quick dropdown right above the button with status options (`Watching`, `Plan to Watch`, `Completed`, `On Hold`, `Dropped`, `Remove`).

### Steps
- [ ] In `static/style.css`, style `.card-bookmark-btn` with an SVG circular progress ring overlay (`stroke-dasharray`, `stroke-dashoffset`).
- [ ] Add `.bookmark-quick-menu` floating popup styles with dark glass background and crisp status items.
- [ ] In `static/app.js`, implement `attachBookmarkHoldListener`:
  - On `pointerdown`: start 600ms hold timer and animate SVG circle.
  - On `pointerup` / `pointerleave`: if timer < 600ms, cancel animation and trigger standard toggle; if >= 600ms, open quick status menu.
  - On quick menu option click: update library status, show toast, and close menu.

---

## Task 4: Collapsible "MY LIST & FAVORITES" Shelf with High-End Cards

### Context & Goal
- Replace the legacy localStorage-based shelf with one rendering real titles from `state.library.items`.
- Add a collapsible `[+]` / `[-]` toggle button in the header.
- Persist collapsed state in `localStorage`.
- Style shelf cards with glassmorphism, progress bar, watch status badge, and hover play overlay.

### Steps
- [ ] In `static/index.html`, add `#btn-toggle-bookmarks-shelf` (`<button class="btn btn-xs btn-ghost"><i class="fa-solid fa-minus"></i></button>`) to `#bookmarks-section .shelf-header`.
- [ ] In `static/style.css`, style `.shelf-carousel`, `.shelf-collapse-wrap`, and `.shelf-card` with hover glow, poster jacket, and progress indicators.
- [ ] In `static/app.js`, rewrite `renderBookmarksShelf()`:
  - Read from `state.library.items`.
  - Render cards with title, poster, status tag, progress bar, and play trigger.
  - Implement `toggleBookmarksShelf()` to toggle collapsed class and store state in `localStorage.setItem('evoscrapper_shelf_mylist_collapsed')`.

---

## Task 5: Major Overhaul of "My Library & Watchlist" Modal

### Context & Goal
- Redesign the library modal to be spacious (`modal-xl`, 95vw, 90vh) and organized.
- Add toolbar:
  - Search filter input for saved titles.
  - Media type filter (`All`, `Movies`, `Series`, `Anime`).
  - Sorting dropdown (`Recently Added`, `Title A-Z`, `Rating`, `Progress %`).
  - Card Zoom / Size Slider (`120px` to `280px`).
  - Backup & Restore dropdown (`Export JSON`, `Export CSV`, `Restore File`).
- Add backend bulk upsert endpoint `POST /api/v1/library/bulk`.

### Steps
- [ ] In `core/library_manager.py`, add `bulk_upsert_items(items: List[LibraryItem])`.
- [ ] In `routers/library.py`, add endpoint `POST /api/v1/library/bulk`.
- [ ] In `static/index.html`, redesign `#library-modal`:
  - Add search input `#library-search-input`.
  - Add type dropdown `#library-type-filter`.
  - Add sort dropdown `#library-sort-select`.
  - Add card size slider `#library-zoom-slider`.
  - Add backup export and restore file buttons.
- [ ] In `static/app.js`:
  - Wire search, filter, sort, and zoom slider into `renderLibraryGrid`.
  - Implement `exportLibraryBackup(format)` to download `.json` or `.csv`.
  - Implement `importLibraryBackup(file)` to parse JSON/CSV and send to `/api/v1/library/bulk`.

---

## Task 6: Smart Search Bar with Live Suggestions Dropdown

### Context & Goal
- When typing in the Discover search bar, show an autocomplete suggestions dropdown with matching titles, year, media type, poster thumbnail, and rating.
- Clicking a suggestion opens the item or triggers the search.
- Support keyboard navigation (`ArrowUp`, `ArrowDown`, `Enter`, `Escape`).

### Steps
- [ ] In `core/discover.py` & `routers/discover.py`, implement `GET /api/v1/discover/suggestions?q={query}` returning up to 8 matched titles.
- [ ] In `static/index.html`, add `<div id="discover-search-suggestions" class="search-suggestions-dropdown hidden"></div>` right below the search input.
- [ ] In `static/style.css`, style `.search-suggestions-dropdown` and `.suggestion-item` with dark glass backing and glowing hover.
- [ ] In `static/app.js`, add debounced suggestion query handler with keyboard selection support.

---

## Task 7: In-Player Buffering Progress HUD & Countdown

### Context & Goal
- Replace the raw spinner with an animated buffering HUD inside the player:
  - Header: `[ BUFFERING P2P STREAM ]` with pulse radar.
  - Animated progress bar showing buffer fill percentage toward playback threshold.
  - Real-time download speed (`MB/s`) and connected peers.
  - Estimated countdown: "Playback starts in ~Xs...".
  - Smooth fade out when `<video>` emits `playing` or `canplay`.

### Steps
- [ ] In `static/index.html`, replace `#player-buffering-spinner` with `#player-buffering-hud` containing the progress bar, speed badge, peers badge, and countdown label.
- [ ] In `static/style.css`, style `#player-buffering-hud` with glass card, animated striped gradient bar, and neon glow.
- [ ] In `static/app.js`, implement `updateBufferingHUD(transferredBytes, targetBytes, speedBytesPerSec, peerCount)` and hook into stream warmup / video buffer events.

---

## Task 8: Verification & Delivery

### Steps
- [ ] Write and run automated tests in `tests/test_ui_enhancements.py` covering bulk restore and search suggestions.
- [ ] Restart server and verify live endpoints (`/api/v1/library/bulk`, `/api/v1/discover/suggestions`).
- [ ] Verify UI rendering, hold interaction, collapsible shelf, zoom slider, backup/restore, and player buffering HUD.
- [ ] Present completed work to the user.
