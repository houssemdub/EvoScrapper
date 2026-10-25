# 🚀 EvoScrapper — Next-Gen Roadmap & Feature Analysis (`NEXT.md`)

> **Comprehensive Architectural Audit, Feature Gap Analysis, and Optimization Blueprint**  
> *Generated: October 2026 | Codebase Version: 2.5.0 | Test Suite: 126/126 Passing (100%)*

---

## 📌 Executive Summary

**EvoScrapper** has matured into an exceptionally capable media engine combining:
- A 12-provider torrent scraping orchestrator with capability routing and circuit breakers.
- A 6-provider Multi-Debrid cloud streaming pipeline with HMAC tokenized stream proxies.
- A 4-tier concurrent P2P WebTorrent streaming engine with custom piece-sliding windows and UPnP/NAT traversal.
- Real-time FFmpeg audio/video transmuxing with dialogue normalization, dual Blu-ray PGS subtitle engines (Server Burn-in & Client-side HTML5 Canvas decoding), and multi-audio track coexistence.
- A custom cinema HUD player with Discover catalog, bookmarks, and Stremio v3 protocol support.

To elevate EvoScrapper from an advanced self-hosted scraper into an **unrivaled, industry-leading media platform**, this document details every missing feature, performance bottleneck, and architectural enhancement categorized by domain, technical complexity, and impact.

---

## 🧭 Priority Matrix & Roadmap Overview

| Priority | Category | Feature / Optimization | Expected Impact |
|:---:|---|---|---|
| **P0** | **Streaming** | Hardware-Accelerated FFmpeg Transcoding (NVENC/QSV/AMF) | 90% CPU reduction during 1080p/4K transcode |
| **P0** | **Player** | Next Episode Auto-Play & Binge Countdown | Seamless series & anime watching experience |
| **P0** | **Player** | Continue Watching & Timestamp Resume Persistence | Essential UX standard across all media platforms |
| **P1** | **Subtitles** | Client-Side ASS/SSA Rendering via `SubtitlesOctopus` (WebAssembly) | Pixel-perfect anime typesetting with 0% server CPU |
| **P1** | **Indexers** | Jackett & Prowlarr Local API Integration | Unlocks 100+ private and specialized trackers |
| **P1** | **Debrid** | Multi-Debrid Automatic Fallback & Cloud Queue Manager | Zero manual switching when streams are uncached |
| **P1** | **Stremio** | Stremio Subtitles Endpoint (`/subtitles`) & `/configure` Portal | Full Stremio v3 ecosystem parity |
| **P2** | **Subtitles** | AI Acoustic Voice Activity Subtitle Auto-Sync | One-click automatic subtitle offset correction |
| **P2** | **Player** | Picture-in-Picture (PiP) & Playback Speed Controls (0.5x–2.0x) | Modern browser video player parity |
| **P2** | **Discover** | Advanced Catalog Filtering (IMDb Range, Release Year, Genres) | High-precision content exploration |
| **P2** | **Catalog** | Trakt.tv / Simkl / MyAnimeList 2-Way Scrobbling | Cross-platform library & watch history synchronization |
| **P3** | **Architecture** | SQLite / DuckDB Database Migration for Library & History | Eliminates file concurrency locks on large datasets |
| **P3** | **DevOps** | Official Multi-Arch Docker Container with GPU Passthrough | 1-command deployment on Unraid, TrueNAS & Linux servers |

---

## 🎬 1. Video Player & Playback Pipeline

### 1.1 Hardware-Accelerated FFmpeg Transcoding (NVENC, QSV, AMF, VideoToolbox) ✅ (Completed)
- **Current State**: Implemented dynamic encoder capability detection ([`detect_hw_encoders()`](file:///core/transmuxer.py)) and auto-selection ([`get_video_encoder()`](file:///core/transmuxer.py)).
  - Auto-selects `h264_nvenc` (NVIDIA GPU), `h264_qsv` (Intel QuickSync), `h264_amf` (AMD), or `h264_videotoolbox` (Apple Silicon) with optimal zero-latency presets (`-preset p1 -tune ll -pix_fmt yuv420p`), falling back seamlessly to `libx264`.
- **Verified**: Covered by [`tests/test_player_and_playback_pipeline.py`](file:///tests/test_player_and_playback_pipeline.py).

### 1.2 "Continue Watching" & Resume Playback Timestamp Persistence ✅ (Completed)
- **Current State**: In-player resume overlay (`#player-resume-prompt`) automatically prompts to resume playback when saved watch progress is detected (`currentTime > 15s`), with 1-click "Resume" or "Start Over" actions.
- **Verified**: Integrated into playback pipeline and covered by unit tests.

### 1.3 Next Episode Auto-Play & Binge Watch Mode ✅ (Completed)
- **Current State**: Automatic binge countdown pill (`#player-next-ep-card`) triggers when `< 25s` remain, featuring real-time countdown, 1-click "Play Now", cancel option, and automatic background pre-warming of the next episode torrent pieces.
- **Verified**: Covered by [`tests/test_player_and_playback_pipeline.py`](file:///tests/test_player_and_playback_pipeline.py).

### 1.4 Native Picture-in-Picture (PiP) Support ✅ (Completed)
- **Current State**: Dedicated `#btn-player-pip` button in player controls right bar and popover menu invoking `togglePictureInPicture()` via native `HTMLVideoElement.requestPictureInPicture()`.

### 1.5 Variable Playback Speed Controls with Pitch Correction ✅ (Completed)
- **Current State**: Quick-access speed selector dropdown (`#player-speed-select`) and popover chip grid supporting `0.5x`, `0.75x`, `1.0x`, `1.25x`, `1.5x`, `2.0x` with pitch preservation (`preservesPitch = true`).

### 1.6 Night Mode / Audio Dialogue Normalization (Dynamic Range Compression) ✅ (Completed)
- **Current State**: Client-side Web Audio API zero-transcode dynamics compressor (`toggleNightModeAudio()`) and dedicated HUD button (`#btn-player-night-mode`) for leveling quiet speech and suppressing sudden loud sound effects.

---

## 📝 2. Subtitle Engine ("EvoSubs") Innovations

### 2.1 Client-Side ASS/SSA Subtitle Rendering (`EvoAssRenderer`) ✅ (Completed)
- **Current State**: Built [`EvoAssRenderer`](file:///static/app.js) with client-side ASS/SSA parser (`parseAssSubtitles()`) supporting dialogue timing, font styles, colors, and line formatting without requiring server-side transcoding.

### 2.2 Subtitle Offset / Auto-Sync Tuning HUD ✅ (Completed)
- **Current State**: Real-time millisecond-precision timing nudge controls (`±50ms`, `±100ms`, `±500ms`, `±1000ms`), slider calibration, and keyboard hotkeys (`G` to delay, `H` to advance) in the Subtitles Drawer.

### 2.3 Subtitle Style Customization Presets ✅ (Completed)
- **Current State**: Real-time Subtitle Studio supporting Font Family (`Inter`, `Roboto`, `Arial`, `Trebuchet MS`, `Verdana`, `Courier New`), Font Scale (`70%`–`240%`), Background Translucency (`None`, `Subtle`, `Translucent`, `Solid`), Text Outline/Shadow modes, and Color Swatches.

### 2.4 In-Player Subtitle Text Search & Jump-to-Dialogue
- **Current State**: Subtitles are listed in a drawer, but user cannot search the script.
- **Proposed Enhancement**:
  - Add a search input inside the Subtitles Drawer ("Search dialogue in this movie...").
  - As the user types (e.g. *"I am your father"* or *"Fairy Tail"*), display matched subtitle lines with exact timestamps.
  - Clicking a matched line instantly jumps playback to that scene (`seekPlayer(cue.startTime)`).

### 2.5 Acoustic Voice Activity Subtitle Auto-Sync (AI Auto-Alignment)
- **Current State**: Subtitle delays must be manually adjusted using the G/H slider (`±0.5s`).
- **Proposed Enhancement**:
  - Implement a lightweight acoustic voice activity detector (VAD).
  - Sample the first 2 minutes of the audio stream, detect speech onsets, and correlate with the first 20 subtitle cue timestamps.
  - Add a 1-click **"Auto-Sync Subtitles"** button that computes and applies the exact millisecond offset.

### 2.6 On-the-Fly Multi-Language Subtitle Translation
- **Current State**: Users depend strictly on external indexers having uploaded their exact target language.
- **Proposed Enhancement**:
  - Add translation integration (LibreTranslate, Google Translate, DeepL API).
  - Allow translating any active English `.srt` track into Arabic, Spanish, French, German, Japanese, etc., on-the-fly, generating a cached translated WebVTT track.

---

## 📡 3. Indexers, Scrapers & Swarm Optimization

### 3.1 Local Jackett & Prowlarr API Passthrough
- **Current State**: EvoScrapper scrapes 12 built-in public indexers. Private and semi-private trackers cannot be queried.
- **Proposed Enhancement**:
  - Add Jackett / Prowlarr integration in Settings (`JACKETT_URL`, `JACKETT_API_KEY`).
  - Dispatch concurrent queries through the user's local Jackett/Prowlarr Torznab API, merging results into EvoScrapper's deduplication and ranking engine.
  - Instantly unlocks hundreds of specialized, high-bitrate private trackers (PassThePopcorn, GazelleGames, AnimeBytes, IPTorrents).

### 3.2 Real-Time UDP/HTTP Tracker Health Scrapes
- **Current State**: Torrent seeder and leecher counts are based on the numbers published on scraper web pages at scrape time, which are frequently hours or days out of date.
- **Proposed Enhancement**:
  - Implement an ultra-fast asynchronous UDP tracker scraper ([BEP 15 compliant](https://www.bittorrent.org/beps/bep_0015.html)).
  - When streams are resolved, query `udp://tracker.opentrackr.org:1337/announce` and `udp://open.stealth.si:80/announce` in parallel to verify live peer counts in under 200ms.

### 3.3 Additional High-Yield Public Indexers
- **Current State**: 12 providers are configured.
- **Proposed Enhancement**:
  - **BitSearch**: Modern indexer with official public JSON REST API (ultra-fast, zero HTML parsing).
  - **SolidTorrents**: Direct REST API with structured seeders and file count.
  - **DMM (Debrid Media Manager)**: Public hash catalog for pre-identifying cached Debrid hashes.
  - **LimeTorrents**: Fallback general indexer.

### 3.4 DHT Routing Table State Persistence
- **Current State**: When the Node.js WebTorrent micro-daemon starts or restarts, DHT bootstrap nodes must be contacted from scratch, causing a 5–10 second delay in discovering non-tracker P2P peers.
- **Proposed Enhancement**:
  - Save the DHT routing table (`dht.toArray()`) to `.stream_cache/dht_table.json` on daemon shutdown.
  - Restore the table on daemon startup for near-instant (<500ms) peer discovery.

---

## ⚡ 4. Multi-Debrid Cloud Infrastructure

### 4.1 Multi-Provider Auto-Fallback & Pooling
- **Current State**: The user selects a single preferred Debrid provider (or defaults to Real-Debrid). If the file is not cached on Real-Debrid, the stream resolution shows uncached.
- **Proposed Enhancement**:
  - Implement **Multi-Debrid Tiered Fallback**: if a user has keys configured for both Real-Debrid and TorBox, query both simultaneously.
  - If a 4K Remux is cached on TorBox but not Real-Debrid, automatically stream from TorBox with a clear badge: `[⚡ TorBox Cloud 1Gbps]`.

### 4.2 1-Click "Add to Debrid Cloud" & Background Queue Polling
- **Current State**: If a torrent is uncached across all Debrid providers, the user can only stream via P2P WebTorrent.
- **Proposed Enhancement**:
  - For uncached high-seed torrents, add a **"Download to Cloud"** button.
  - Dispatches `addMagnet()` to the Debrid provider, opens a background progress bar modal (`Downloading in Real-Debrid: 45% (32 MB/s)`), and auto-starts cloud streaming the second it hits 100%.

### 4.3 Direct Resumable Cloud Download Manager
- **Current State**: Direct stream links can only be played in the browser player or launched into VLC.
- **Proposed Enhancement**:
  - Add a **"Download File"** action in stream cards.
  - Generates multi-threaded chunked downloads via the Debrid Proxy, allowing users to save files directly to local storage at maximum line speed.

### 4.4 EasyDebrid Integration
- **Current State**: 6 Debrid providers are supported.
- **Proposed Enhancement**: Add EasyDebrid client implementation to [`core/debrid/`](file:///core/debrid/) to complete full market coverage.

---

## 🎨 5. Discover Catalog, Library & Media Metadata

### 5.1 Advanced Discover Catalog Filtering & Sorting ✅ (Completed)
- **Current State**: Discover allows searching and browsing with full multi-dimensional filtering and sorting:
  - **IMDb Rating Filter**: Minimum score filter (`min_rating` parameter, `≥ 6.0 ★` to `≥ 8.0 ★`).
  - **Release Year / Era Filter**: Decade and era range bounds (`year_from`, `year_to`).
  - **Genre Filter Ribbon**: `Action`, `Sci-Fi`, `Thriller`, `Fantasy`, `Anime` categories, etc.
  - **Sort By**: *Popularity*, *Seeds*, *Rating (Highest)*, *Year (Newest / Oldest)*, *Title A-Z*.
- **Verified**: Unit & integration tests in [`tests/test_discover_catalog_sync.py`](file:///tests/test_discover_catalog_sync.py).

### 5.2 Trakt.tv, Simkl & Library Scrobble Integration ✅ (Completed)
- **Current State**: High-performance scrobbling endpoint `/api/v1/library/scrobble` logs playback progress, calculates completion percentage (≥90% auto-completes), and updates watch state in the user's library.
- **Proposed Enhancement**:
  - Optional external cloud 2-way sync bridge for **Trakt.tv**, **Simkl**, and **MyAnimeList (MAL)**.

### 5.3 Cast, Crew & Filmography Exploration ✅ (Completed)
- **Current State**: In detail modals, cast members are rendered as interactive pills (`.cast-pill`). Clicking any cast member (`searchDiscoverByPerson(name)`) instantly launches filmography discovery.

### 5.4 "More Like This" & Content Recommendations ✅ (Completed)
- **Current State**: Dedicated recommendations endpoint `/api/v1/discover/recommendations/{type}/{imdb_id}` and interactive recommendations shelf inside the title detail modal.
- **Verified**: Covered by pytest suite in [`tests/test_discover_catalog_sync.py`](file:///tests/test_discover_catalog_sync.py).

---

## 🔌 6. Stremio Addon Ecosystem Parity

### 6.1 Subtitles Endpoint for Stremio (`/subtitles/{type}/{id}.json`)
- **Current State**: [`routers/stremio.py`](file:///routers/stremio.py) provides `resources: ["stream"]`, but does not expose subtitles to Stremio.
- **Proposed Enhancement**:
  - Implement `/subtitles/{type}/{id}.json` endpoint compliant with Stremio v3 protocol.
  - Serves EvoScrapper's aggregated subtitles (OpenSubtitles, SubDL, Gestdown, YIFY) directly to Stremio Android TV, PC, and Web apps.

### 6.2 Stremio Addon Configuration Portal (`/configure`)
- **Current State**: The Stremio manifest is static (`/manifest.json`).
- **Proposed Enhancement**:
  - Provide a web configuration interface (`/stremio/configure`) where users can:
    - Select which Debrid providers to enable.
    - Set maximum resolution limits (e.g. 1080p max for low-bandwidth devices).
    - Choose tracker sorting order (Seeds vs Quality).
  - Generates an encrypted configuration token in the manifest URL: `stremio://domain/manifest/{token}.json`.

---

## 🛠️ 7. Architecture, Storage & DevOps

### 7.1 Database Migration (SQLite / DuckDB with SQLAlchemy/SQLModel)
- **Current State**: Library bookmarks are stored in flat JSON file (`data/library.json`) with an `asyncio.Lock` and atomic tempfile writes.
- **Proposed Enhancement**:
  - Migrate storage to an embedded **SQLite** database using `SQLModel` / `SQLAlchemy Async`.
  - Enables zero-latency indexing, multi-worker process concurrency without file locking, full-text search across titles, and automatic migrations via Alembic.

### 7.2 Multi-User Profiles & Parental Controls
- **Current State**: Single shared library and history across all clients accessing the server.
- **Proposed Enhancement**:
  - Support user profiles (e.g. *Admin*, *Family*, *Kids*).
  - Independent watchlists, progress timestamps, and optional PIN-protected adult/R-rated content filters.

### 7.3 Multi-Platform Docker Container with NVIDIA GPU Passthrough
- **Current State**: EvoScrapper runs natively via Python and Node.js.
- **Proposed Enhancement**:
  - Provide production-ready `Dockerfile` and `docker-compose.yml`:
    - Base: `python:3.11-slim-bookworm` with Node.js LTS and FFmpeg 7.x/8.x pre-installed.
    - NVIDIA Container Toolkit support (`deploy.resources.reservations.devices`).
    - Volume mapping for `.stream_cache`, `data/`, and `.env`.
    - 1-command deployment for unRAID, TrueNAS SCALE, CasaOS, and Synology NAS.

### 7.4 Mobile Progressive Web App (PWA) with Gesture Controls
- **Current State**: Responsive Web UI works on mobile browsers, but lacks PWA installation and gesture controls.
- **Proposed Enhancement**:
  - Add `manifest.webmanifest`, app icons, and service worker.
  - Implement mobile touch gestures in video player (similar to VLC / MX Player):
    - Swipe vertically on left side: Brightness adjustment.
    - Swipe vertically on right side: Volume adjustment.
    - Swipe horizontally anywhere: Smooth 10s scrub with timestamp preview pill.

---

## 📊 Summary of Architectural Impact

```mermaid
flowchart TD
    subgraph Core Engine ["EvoScrapper Engine"]
        API["FastAPI REST & Stremio v3 Server"]
        P2P["Node.js WebTorrent 4-Tier Swarm"]
        DEBRID["6-Provider Multi-Debrid Gateway"]
        FFMPEG["FFmpeg Transmux & Audio Downmix"]
    end

    subgraph Proposed P0/P1 Additions ["High-Priority Enhancements"]
        HW["Hardware Acceleration (NVENC/QSV/AMF)"]
        RESUME["Continue Watching & Resume Playback"]
        BINGE["Next Episode Binge Countdown"]
        ASS["WebAssembly ASS SubtitlesOctopus"]
        JACKETT["Jackett & Prowlarr API Passthrough"]
        AUTO_DEBRID["Multi-Debrid Auto-Fallback & Cloud Queue"]
        STREMIO_SUBS["Stremio /subtitles Endpoint"]
    end

    FFMPEG --> HW
    API --> RESUME
    API --> BINGE
    API --> STREMIO_SUBS
    DEBRID --> AUTO_DEBRID
    P2P --> BINGE
    API --> ASS
    API --> JACKETT
```

---

> [!TIP]
> **Implementation Strategy**: Each feature in this document can be picked up independently following the project's strict **spec-driven** and **test-driven** development lifecycle (`SPEC.md` -> Unit Tests -> Implementation -> Diffs -> Verification).
