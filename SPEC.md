# Player Bar Alignment & Discover Default Sort Specification (`SPEC.md`)

## 1. Target Modules
- `static/style.css` (Player bottom controls row alignment, volume slider flexbox, and item breathing room)
- `static/app.js` (Discover stream sorting initialization to `seeds_desc`)

---

## 2. Core Contracts

### A. Player Bottom Controls Bar Alignment Contract
1. **Single Strict Baseline & Vertical Center (`align-items: center`):**
   - `.player-controls-row`, `.player-controls-left`, and `.player-controls-right` must enforce `display: flex; align-items: center;`.
   - `.player-volume-wrap` must enforce `display: inline-flex; align-items: center; gap: 0.5rem;` so the speaker icon and volume range track sit strictly on the identical horizontal centerline.
   - `.player-volume-slider-wrap` must be vertically centered (`display: inline-flex; align-items: center;`).
   - `#player-volume-slider` must have no uncentered margins or baseline offsets.
   - `.player-skip-num` within rewind/forward buttons must be vertically centered and balanced with the icon.
2. **Generous Spacing ("Air Between Them"):**
   - Spacing between primary control groups on the left (`gap: 0.9rem`) and right (`gap: 0.9rem`).
   - Individual buttons and pills must have uniform height (`32px` to `34px`) and line-height so all items sit on the same optical axis.

### B. Discover Stream Sorting Default Contract
1. **Default Sort Mode:**
   - When resolving streams for any movie or series episode via `resolveStreamsForCurrentSelection()`:
     - `state.discover.streamFilter.sort` MUST default to `'seeds_desc'`.
   - `renderStreamFilterAndCards()` select element `#streams-sort-select` MUST default to `<option value="seeds_desc" selected>Sort: Seeds (High to Low)</option>`.
   - Resulting stream cards MUST be sorted with the highest seed count at the top.

---

## 3. Deterministic Acceptance Tests
1. `test_player_controls_bar_css_alignment`: Verify CSS guarantees `align-items: center` on `.player-controls-row`, `.player-controls-left`, `.player-controls-right`, `.player-volume-wrap`, and `.player-volume-slider-wrap`.
2. `test_player_controls_air_gap`: Verify `gap` on `.player-controls-left` and `.player-controls-right` is at least `0.75rem`.
3. `test_discover_default_stream_sort`: Verify in `static/app.js` that `streamFilter.sort` defaults to `'seeds_desc'` and `seeds_desc` is the default option in stream filter select.
