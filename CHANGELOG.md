# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [2.3.2] - 2026-10-27

### Beyond Stremio Completion: SQLite Swarm DAL, Profiles, Stremio Portal & Intelligence UI

#### Added
- **Embedded SQLite Storage (T4.1 Complete)**: Async WAL-mode SQLite DAL (`core/database.py`) absorbing library bookmarks, watch history, `SeekHeatmapStore` buckets, and `DebridCoverageIndex` records with automatic schema management (v2) and legacy JSON migration.
- **Household Multi-User Profiles & PIN Locks (T4.4 Complete)**: Multi-profile management API (`routers/profiles.py`, `core/profile_manager.py`) with Kids mode filtering and constant-time salted SHA-256 PIN verification.
- **Stremio Addon Configuration Web Portal (T4.6 Complete)**: `/configure` and `/stremio/configure` responsive dashboard allowing preferred language selection, max stream limit tuning, and 1-click `stremio://` addon installation; manifest now advertises `behaviorHints: { configurable: true }`.
- **Crowd Scene Skip UI (P3 Complete)**: Player HUD overlay (`#player-scene-skip-container`) tracking `currentTime` against gossiped scene intervals and exposing seamless "Skip Intro" / "Skip Credits" chips.
- **Trick-Play Scrubber Hover Preview (P7 Complete)**: Timeline preview tooltip (`#player-timeline-preview-thumb`) dynamically computing sprite sheet grid column/row coordinates from `--evo-sprite-sheet`.
- **"Why This Stream?" Breakdown UI (P10 Complete)**: Stream card "Why?" action badge and inspector modal (`#stream-explain-modal`) displaying provider cache status, live swarm telemetry, keyframe inventory, and first-frame prediction.
- **Modular Subsystems (T4.2 Started)**: Extracted `static/js/party.js` watch-party transport and state sync module.

#### Tests
- Added unit tests for SQLite swarm persistence (`tests/test_swarm_sqlite.py`), multi-user profiles (`tests/test_profiles.py`), and Stremio configuration portal (`tests/test_stremio_server.py`) — test suite now at 477 passing tests.

---

## [2.3.1] - 2026-10-27

### Pipeline Completion: Failover Relay, Watch-Party UI, DHT Persistence

#### Fixed
- **CI (Python 3.12)**: `typing.Dict` import in `stream_resolver` — PEP 649 (Python 3.14) defers annotation evaluation, which masked the missing import locally while CI's 3.12 evaluates annotations eagerly.
- Stale `streamer/daemon.log` orphan removed (the daemon logs to stdout).
- README badge/count drift (322 → 381) and version strings (banner and FastAPI now 2.3.0).

#### Added
- **Automatic Cross-Source Failover (P4 complete)**: `core/failover_stream.py` streams from an ordered candidate list and resumes at the exact byte offset on the next source when the active one stalls; `GET /api/v1/stream/relay` resolves both sources, orders them via the race probe, and serves one URL with failover for external players. The race probe now captures the winner's total size for exact 206 headers.
- **Watch-Together UI (P8 complete)**: player HUD button with create/join panel, 2s event polling, and echo-suppressed application of remote play/pause/seek; local transport events are shared to members.
- **Quality Ladder Wiring (P5 wired)**: 5s buffer-health polling with a 3-starved-streak trigger; fetches ladder candidates and hot-swaps to the largest lighter release of the same episode at the current position.
- **DHT Routing-Table Persistence (NEXT.md 3.4)**: the daemon saves its DHT routing table to `.stream_cache/dht_table.json` every 5 minutes and bootstraps from it on restart for near-instant non-tracker peer discovery.
- **Mesh Impact Metric (plan metric #4)**: per-session seek-hint hit-rate in daemon status; `GET /api/v1/cometnet/impact` aggregates hint hits, heatmap volume, and coverage-index size.
- **hls.js VOD tuning**: deep buffering (90s/600s/256MB) and disabled LL-HLS scheduling for local VOD playback.
- **`EVO_SPRITE_SCAN_SECONDS`**: configurable trick-play coverage window.

#### Tests
- 66 parametrized regression tests sealing the HLS playlist `division by zero` crash class (pathological keyframe shapes x durations, route-level, plus real cached keyframes).
- Failover offset continuation, DHT roundtrip, hint hit-rate, and mesh impact coverage (381 → 457 tests).

## [2.3.0] - 2026-10-26

### Beyond Stremio — Swarm Intelligence Layer & Playback Pipeline

Full plan: `docs/BEYOND_STREMIO_PLAN.md`. Comparison baseline: `stremio-core` and `torrentio-scraper`.

#### Added
- **Swarm Pause/Resume Hysteresis (T0.1)**: with >90s of verified buffer the lookahead tier stops requesting entirely and resumes below 60s — stremio `swarm_paused` semantics with anti-flap hysteresis (`streamer/torrent_engine.js`).
- **Download Shaping (T0.5)**: when the swarm runs >2x playback rate with a deep buffer, the lookahead tier halves (level 1) or pauses (via hysteresis); starvation always restores full bandwidth.
- **Deep Next-Episode Staging (P6)**: binge pre-warm now fetches the next episode's opening ~60 seconds of media bytes, not just metadata (`stage_seconds` end-to-end: UI → /warm → daemon).
- **Collective Seek Forecasting (P1)** [NOVEL]: anonymous 30s-bucket seek events gossiped over CometNet (`SEEK_ANNOUNCE`, Ed25519-signed); per-hash seek heatmap with 72h half-life decay (`core/swarm_intelligence.py`); the daemon scheduler pre-selects low-priority pieces around crowd hotspots (`/seek-hints`); seeks captured server-side on /transmux and client-side on direct playback.
- **Distributed Debrid Coverage Index (P2)** [NOVEL]: gossip cache announcements feed a persistent hash→provider index with recency×corroboration confidence; `resolve_stream` uses mesh hints to order provider attempts before the live probe confirms.
- **Crowd Scene Boundaries (P3)** [NOVEL]: behavioral intro/credits/scene hotspots derived from the seek heatmap (`GET /api/v1/cometnet/scenes`) — zero-ML skip support that improves as more people watch.
- **Dual-Source Racing (P4)** [NOVEL]: `POST /api/v1/stream/race` probes the P2P swarm and the best Debrid CDN in parallel for the first 256KB; winner serves, loser reported as a warm backup (`core/source_racer.py`).
- **Cross-Torrent Quality Ladder (P5)** [NOVEL, opt-in `QUALITY_LADDER=true`]: `POST /api/v1/stream/ladder` returns lower-bitrate releases of the same episode, largest-first, for keyframe-aligned hot-swap instead of a spinner.
- **Watch-Together Rooms (P8)**: short-code rooms with sequenced play/pause/seek events, fanned out across instances as signed `PARTY_EVENT` gossip (`/api/v1/cometnet/party/*`, `core/watch_party.py`).
- **Language-Aware Stream Ranking (P9)**: torrentio-style partitioning by release-language tags against a preferred language (`/resolve?lang=...`).
- **"Why This Stream?" (P10)**: `GET /api/v1/stream/explain` — debrid coverage hints, configured providers, live swarm telemetry, keyframe inventory, and an honest first-frame prediction.
- **Trick-Play Sprites (P7)**: `GET /api/v1/stream/sprites` generates a cached tiled thumbnail contact sheet (v1 covers the opening 15 minutes; bounded to avoid full-file P2P scans); the player prefetches it on metadata load.
- **Swarm-Health Result Gate (T0.2)**: torrentio's healthy-seeders heuristic in the aggregator — strong swarms suppress dead torrents, weak swarms cap at 5 candidates, skipped when Debrid is configured.
- **Split Debrid Circuit Breakers (T0.3)**: independent availability vs resolve breakers per provider — a broken resolve endpoint no longer disables cache checks.
- **Negative-Result TTLs (T0.4)**: empty search results cached 120s vs 900s for full results, so newly-seeded torrents surface quickly.
- **Peer-Source Accounting & Re-Injection (T0.6)**: per-session tracker/DHT/webseed discovery stats in daemon status; known-good cached peers re-injected into thinning swarms every 2 minutes.
- **Jackett/Prowlarr Passthrough (T4.5)**: Torznab aggregate provider joins the search pool when `JACKETT_URL`/`JACKETT_API_KEY` are set.
- **Stremio Subtitles Resource (T4.6)**: `/subtitles/{type}/{id}.json` serves the aggregated subtitle providers to official Stremio apps; manifest now advertises `stream` + `subtitles`.

## [2.2.2] - 2026-10-26

### Security Hardening, Measured-Bitrate Scheduling & Streaming Throughput

#### Security
- **Outbound Request Guard** (`core/security.py`): public-IP DNS validation for every external HTTP(S) target and redirect hop, applied to external addons, subtitle downloads, and Debrid range streaming.
- **Browser Session Auth** (`routers/auth.py`): `POST /api/v1/auth/session` exchanges the API key for an HttpOnly, SameSite=Lax cookie (12h TTL) so fetch, EventSource, `<video>`, and HLS requests authenticate without the long-lived key in playback URLs; the UI bootstraps the session before loading data.
- **Daemon Control Plane**: Node streaming daemon binds loopback, validates `Host` headers, emits no wildcard CORS, requires a shared secret on all routes except authenticated health probing, and accepts short-lived HMAC query signatures on `/stream` for media tools.
- **Packaging**: `.dockerignore` excludes secrets, local `node_modules`, tests, logs, and runtime caches; Docker no longer publishes the internal daemon port.

#### Performance
- **Measured-Bitrate Piece Scheduling**: ffprobe-derived duration/bitrate now flows from `/probe` and `/warm` into the daemon session (`setSessionMetadata`), so the sliding window, buffer-health watchdog, and lookahead scans are sized by the real bitrate instead of a hardcoded 8 Mbps — piece windows on 4K/HEVC content were up to 6x undersized before.
- **Direct-Daemon Range Redirect by Default**: `EVO_DIRECT_RANGE` now defaults to `true`; localhost clients receive a 307 to the signed daemon URL instead of proxying every range request through Python (set it to `false` to restore the proxy hop).
- **Write-Behind Peer Cache**: `peers.json` persistence is debounced (`EVO_PEER_CACHE_FLUSH_MS`, 15s default) instead of a synchronous full-file read/modify/write on every peer connection.
- **Chunk-Merge Stream Serving**: daemon range responses merge ~16 KB piece-iterator chunks into ~1 MB writes (`EVO_STREAM_MERGE_BYTES`), cutting pipe/socket round-trips per byte by two orders of magnitude.
- **Parallel HLS Lookahead Prefetch**: the next 1-3 virtual HLS segments now mux concurrently (bounded by the existing semaphore) with in-flight deduplication, refilling post-seek buffers in a fraction of the sequential time.
- **Cache-Aware Debrid Resolution**: `DebridManager.resolve_stream` probes cache availability first and resolves from a provider that already holds the torrent (instant playback) before trying uncached providers; user preference still wins among cached ties, and a failed probe falls back cleanly.

#### Added
- **Opt-In Swarm Pre-Warm** (`PREWARM_SWARMS=true`): search results pre-resolve the top candidates' metadata and peer connections in the background so click-to-play skips the metadata wait; nothing downloads until a reader appears.
- **Continuous Integration** (`.github/workflows/ci.yml`): the full pytest suite and both deterministic Node engine harnesses (scheduler harness + loopback seed/reader measurement) run on every push and pull request.

#### Fixed
- Test isolation: the Debrid proxy streaming test no longer leaks a mocked HTTP client into the module-level singleton consumed by other suites.

---

## [2.2.1] - 2026-10-26

### Audio/Video & Subtitle Seek Synchronization Fix

#### Fixed
- **A/V & Subtitle Desync on Seek**:
  - Eliminated mid-GOP seek asymmetry where video stream copy mode (`-c:v copy`) anchored to the nearest preceding keyframe while audio transcoding accurate-sought forward, resulting in a 1–5 second audio lead over video.
  - Added `-noaccurate_seek` before `-ss` in copy mode so FFmpeg demuxes both audio and video starting from the identical keyframe container boundary.
  - Removed `asetpts=PTS-STARTPTS` filter which was injecting multi-second timestamp gaps between audio packet 0 and packet 1; continuous monotonic audio clock synchronization is now maintained gaplessly by `aresample=async=1:min_hard_comp=0.100000` with `-avoid_negative_ts make_zero`.
  - Re-engineered `probe_keyframes` to use fast container packet inspection (`-show_packets -show_entries packet=pts_time,flags -of csv=p=0`) without full video decoding, slashing probe time from ~8s to ~30ms.
  - Player frontend pre-loads stream keyframes in the background and snaps timeline seek operations to keyframe boundaries, guaranteeing sample-accurate alignment between video frames, audio samples, and subtitle cue intervals.

---

## [2.2.0] - 2026-10-26

### Comprehensive Streaming & Buffering Overhaul

This release delivers an architectural overhaul of the P2P streaming engine, live transmuxer, virtual HLS generator, and WebRTC playback pipeline, eliminating stall points and desync issues across 11 implementation phases.

#### Added
- **Persistent Virtual HLS Segment Cache (`HlsSegmentCache`)**: Disk-backed MPEG-TS/fMP4 segment caching with single-flight mutex deduplication, background lookahead prefetching (1–3 segments), and LRU cache eviction under `EVO_HLS_CACHE_MAX_MB` budget (`core/transmuxer.py`).
- **Bitrate-Adaptive Sliding Window & Seek Retention Tail**:
  - Dynamically calculates piece horizons from video bitrate: 20s immediate critical horizon (prio 3), 90s multi-peer swarm horizon (prio 2), and 240s background lookahead reservoir (prio 1).
  - Backward-seek retention buffer (`cursorPiece - 11`) and instant critical re-selection on reverse seeks (`streamer/torrent_engine.js`).
- **Buffer-Health Watchdog & Telemetry**:
  - Continuous download speed deficit ratio and `seconds_ahead` tracking with dynamic wire unchoking and burst piece re-requesting.
  - Real-time `/api/v1/stream/health-watch` endpoint and `X-Evo-Buffer-State` response headers (`healthy`, `deficit`, `starved`).
- **Virtual HLS Keyframe Boundary Snapping**:
  - Video keyframe indexing (`ffprobe`) cached to `data/keyframes/<hash>_<idx>.json`.
  - `#EXTINF` segment durations snapped to actual keyframe boundaries in `generate_hls_manifest`, eliminating timestamp drift.
  - Fragmented MP4 (`prefer_fmp4`) RFC 8216 EXT-X-MAP init segment generation (`/api/v1/stream/hls/init.mp4`).
  - Probed keyframes API endpoint (`/api/v1/stream/keyframes`).
- **ITU-R BS.775 Surround Sound Audio Downmixing**: Center dialogue boosting and phase cancellation mitigation for 5.1/7.1 audio tracks downmixed to stereo AAC.
- **Shared Connection Pooling for Debrid Streaming**:
  - Replaced per-request HTTP clients with singleton `httpx.AsyncClient` maintaining 20 keepalive and 50 max connections with clean app lifespan shutdown (`core/debrid/proxy.py`).
- **WebRTC Mesh Acceleration & Safe Direct Fallback**:
  - Opt-in WebRTC P2P Media Loader integration in player UI (`p2p_mesh_enabled`).
  - Swarm peer count and mesh downloaded bytes wired to `#player-swarm-stat` with automatic HTTP fallback on ICE/mesh timeout.
- **System Diagnostics Expansion**:
  - `/api/v1/stream/diagnostics` extended with HLS cache hit ratio, first-byte latency, FFmpeg permit utilization, debrid connection pool telemetry, and watchdog history ring buffer.
- **Engine Hygiene & Peer Persistence**:
  - Swarm peer cache persistence (`.stream_cache/peers.json`) preloaded on torrent addition to eliminate cold-start discovery delays.
  - Bounded V8 heap chunk cache (`EVO_STORE_CACHE_SLOTS: 128`).
- **Safe Daemon Process Takeover**: Process inspection (`server.js`) before cleanup and dynamic port fallback (`8890–8899`) on port collisions.

#### Changed
- **Client Playback Resiliency**:
  - Auto-reconnect on premature stream EOF with exponential backoff and duration gap check (`static/app.js`).
  - Timeline seek debouncing (250ms) to prevent FFmpeg process spam.
  - PGS bitmap subtitles default to client-side WebAssembly canvas overlay (`pgs-decoder.js`), avoiding costly video re-encoding.
  - Direct 307 temporary redirect to local daemon for localhost range requests (`EVO_DIRECT_RANGE=true`).
- **Streaming Response Headers**: Added `X-Evo-Seek-Keyframe` and `X-Evo-BurnWarn`.

#### Fixed
- `[STRM-CRIT-01]`: Removed cumulative `total=45.0` stream timeout; replaced with decoupled connect (10s) and socket read (45s) timeouts.
- `[STRM-CRIT-02]`: Eliminated destructive `engine.cleanupOtherSessions()` calls on active streams.
- `[STRM-CRIT-03]`: Fixed critical piece bitfield clearing to only deselect verified pieces.
- `[STRM-CRIT-04]`: Removed `-noaccurate_seek` for transmux copy mode; added `-copyts` to prevent A/V desync.
- `[STRM-CRIT-05]`: Fixed `NameError` in debrid stream resolution and undefined array appends in discover catalog.
- `[STRM-HIGH-03]`: Bound FFmpeg concurrency to dynamic semaphore with 1.0s kill-fast termination on client disconnect.
- `[STRM-MED-02]`: Handled empty FFmpeg stdout with immediate `HTTPException(502)` instead of hanging generators.
- `[STRM-LOW-03]`: Centralized port settings (`STREAM_PORT: 8889`, `TORRENT_PORT: 50000`, `DHT_PORT: 50001`) across Python daemon launcher and Node.js child environment.

---

## [2.1.0] - 2026-10-24
### Added
- Multi-provider debrid caching engine with support for Real-Debrid, AllDebrid, Premiumize, TorBox, Debrid-Link, and PikPak.
- Decentralized P2P metadata gossip network (CometNet).
- Cinematic video player with neon UI components and embedded subtitle track extractor.

---

## [2.0.0] - 2026-10-15
### Added
- Initial public release of EvoScrapper next-generation torrent and subtitle scraping engine.
- Fast multi-tracker aggregation, quality parsing, Stremio addon integration, and local WebTorrent streaming.
