# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
