# Subtitle Auto-Sync Engine & Synchronization Fix Implementation Plan

> **Goal:** Fix subtitle desynchronization permanently across all playback modes and provide an automated, zero-effort Subtitle Auto-Sync Engine that aligns subtitle timing to video audio and container cues.

## Root Causes of Subtitle Desync in EvoScrapper
1. **Embedded Subtitle Suppression**: When a video stream starts, `autoLoadSubtitles` loads an external generic subtitle from OpenSubtitles/SubDL before probe finishes, and then refuses to switch to the embedded track even though embedded tracks are demuxed directly from the container with 100% sample-accurate sync.
2. **Keyframe Snapping Asymmetry in Transmux Seeking**: When seeking in transmux mode (`-ss`), backend snaps to the preceding keyframe container boundary (e.g. 116.2s for a 120s seek) while client recorded `playbackOffset = 120s`, shifting all subtitle cues by (120 - 116.2) = 3.8s early.
3. **External Release Mismatch (Intros & FPS)**: External subtitles are ripped from releases with different studio intros (2s–15s offset) or different framerates (23.976 fps vs 25 fps PAL).

## Architecture & Deliverables

### 1. Backend Auto-Sync Engine (`core/subtitle_sync.py` & `routers/subtitles.py`)
- Extract speech activity intervals from the stream audio using FFmpeg `silencedetect=noise=-30dB:d=0.35` on the opening 180 seconds.
- Cross-correlate subtitle cues against detected speech activity intervals to calculate the optimal delay offset $\Delta t \in [-30.0, +30.0]$ with maximum dialogue overlap.
- When an embedded reference subtitle exists, compute cross-track cue alignment with millisecond precision.
- Endpoint: `POST /api/v1/stream/subtitles/auto-sync` (accepts `info_hash`, `file_idx`, `cues`, returns `{ offset, method, confidence }`).

### 2. Embedded Subtitle Ground-Truth Priority (`static/app.js`)
- Prioritize embedded text subtitles (`/api/v1/stream/subtitles`) on stream start whenever a track matches the user's preferred language.
- Badge embedded tracks with `[Container Synced]` in the subtitle drawer.

### 3. Keyframe-Aligned Transmux Seeking Fix (`static/app.js`)
- Snap client `playbackOffset` to the keyframe container boundary before sending to `/api/v1/stream/transmux`, ensuring video frames and subtitle cues share the identical timebase.

### 4. Player UI Auto-Sync & Calibration Controls (`static/index.html` & `static/app.js`)
- **1-Click Auto-Sync Button**: `🪄 Auto-Sync Subtitles` button in the subtitle drawer that calls the auto-sync engine and applies the optimal offset with a toast notification.
- **Sync to Current Voice ("Sync Here")**: Calibrates the active cue to `video.currentTime` when user hears a line of dialogue.
- **Framerate Stretch Presets**: `23.976 ➔ 25 fps` (+4.27%) and `25 ➔ 23.976 fps` (-4.1%).
- **Standard Hotkeys**: `Z` / `X` for instantaneous -250ms / +250ms offset adjustment with on-screen HUD toast.

---

## Tasks
1. **Task 1**: Build `core/subtitle_sync.py` (VAD speech interval extraction and cross-correlation offset finder) with unit tests in `tests/test_subtitle_sync.py`.
2. **Task 2**: Expose `POST /api/v1/stream/subtitles/auto-sync` in `routers/subtitles.py` (or `routers/stream.py`) with API integration tests.
3. **Task 3**: Fix embedded subtitle priority and transmux seek keyframe snapping in `static/app.js`.
4. **Task 4**: Add 1-Click Auto-Sync, "Sync Here", framerate presets, and `Z`/`X` hotkeys to the player HUD and drawer in `static/index.html`, `static/style.css`, and `static/app.js`.
5. **Task 5**: Full verification across `pytest`.
