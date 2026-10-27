# EvoScrapper Architecture & Technical Documentation

Welcome to the comprehensive architecture and systems documentation for **EvoScrapper (v2.0.0)**. This document provides an in-depth breakdown of the internal subsystems, design patterns, streaming pipelines, debrid unrestrictors, and security hardening mechanisms.

---

## 1. High-Level System Architecture

EvoScrapper operates as a high-throughput, fault-tolerant media gateway combining asynchronous Python (FastAPI, HTTPX, Pydantic v2) with an external event-driven Node.js WebTorrent daemon.

```
                           +-----------------------------------+
                           |          Web Browser UI           |
                           |   (HTML5 / Video.js / Glass UI)   |
                           +-----------------+-----------------+
                                             |
                                HTTP / REST / SSE Stream
                                             |
                                             v
                           +-----------------------------------+
                           |      FastAPI Gateway (Port 8009)  |
                           |  - Security & API Key Validation  |
                           |  - Circuit Breakers & Rate Limits |
                           |  - Cache (Memory TTL + Disk LRU)  |
                           +--------+-----------------+--------+
                                    |                 |
          +-------------------------+                 +------------------------+
          |                                                                    |
          v                                                                    v
+-------------------+                                                +-------------------+
|  Stream Resolver  |                                                |  Subtitle Engine  |
| - Media-Type Caps |                                                | - OpenSubtitles   |
| - Debrid Manager  |                                                | - Gestdown        |
| - Web CDN Scraper |                                                | - SubDL (ZIP)     |
| - 12+ Indexers    |                                                | - SubSource       |
+---------+---------+                                                | - AnimeTosho      |
          |                                                          +---------+---------+
          |                                                                    |
          v                                                                    v
+-------------------+                                                +-------------------+
| WebTorrent Daemon | <--- IPC HTTP (Port 8008)                      | SSRF Proxy Guard  |
| - Sequential P2P  |                                                | - Private IP Ban  |
| - Piece Priority  |                                                | - Loopback Filter |
| - Memory/Disk LRU |                                                +-------------------+
+-------------------+
          |
          v
+-------------------+
| Transmuxer Engine |
| - FFmpeg Slicer   |
| - Virtual HLS     |
| - Native VLC PID  |
+-------------------+
```

---

## 2. Core Subsystems

### 2.1. Scraper Orchestrator & Provider Capability Matrix
EvoScrapper indexes 12+ public and semi-private torrent search indexers. To eliminate request flooding, each provider is mapped to a strict capability matrix (`PROVIDER_MEDIA_CAPABILITIES` in `core/stream_resolver.py`):

| Provider | Media Types Supported | Underlying Ingestion Mechanism |
|---|---|---|
| **YTS** | Movies | Official JSON REST API (`yts.mx` / `yts.bz`) |
| **EZTV** | TV Series, Anime | Official JSON REST API (`eztv.re`) |
| **The Pirate Bay** | Movies, TV, Anime, Games, Apps | Apibay JSON API (`apibay.org`) |
| **Nyaa.si** | Anime | Structured RSS XML (`nyaa:infoHash`) with trusted uploader boosts |
| **TokyoTosho** | Anime | Structured RSS XML with Base32-to-Hex infoHash conversion |
| **SubsPlease** | Anime (Simulcast) | JSON API (`subsplease.org/api`) |
| **1337x** | Movies, TV, Anime, Games, Apps | HTML DOM with bounded async infoHash resolver |
| **TorrentGalaxy** | Movies, TV, Anime | HTML DOM with direct row-level magnet extraction (zero N+1 calls) |
| **Torlock** | Movies, TV, Anime | HTML DOM with verified infoHash resolution |
| **Rutor** | Movies, TV | 1-Step search table DOM with URL-encoded query paths |
| **Comando** | Movies, TV (BR/PT) | WordPress REST API (`/wp-json/wp/v2/posts`) |
| **BluDV** | Movies, TV (BR/PT) | WordPress REST API (`/wp-json/wp/v2/posts`) |

#### Bounded Concurrency & Semaphores
Rather than fanning out 60+ unconstrained HTTP requests concurrently, the orchestrator routes queries only to providers matching the target media type (`movie`, `series`, `anime`) through an `asyncio.Semaphore(10)` execution pool.

---

### 2.2. Circuit Breaker & Fail-Fast Protection
Upstream tracker downtime, Cloudflare challenges, or DNS poisoning are automatically isolated by the `CircuitBreaker` pattern (`core/circuit_breaker.py`):

```
       [Success]
     +----------+
     |          |
     v          |
+---------+  3 Failures   +------+   90s Elapsed   +-----------+
| CLOSED  | ------------> | OPEN | --------------> | HALF-OPEN |
+---------+               +------+                 +-----------+
     ^                                                   |
     |                     Success                       |
     +---------------------------------------------------+
                           Failure
```

- **CLOSED**: Requests proceed normally. Latency and success metrics are tracked.
- **OPEN**: Triggered upon 3 consecutive failures. Upstream calls are instantly short-circuited for 90 seconds without network delays.
- **HALF-OPEN**: After 90 seconds, a single canary request tests provider availability. Success resets to CLOSED; failure trips back to OPEN.

---

### 2.3. P2P WebTorrent Daemon (`streamer/`)
Direct browser video playback requires rapid, sequential piece acquisition. EvoScrapper delegates torrent downloads to a dedicated Node.js sidecar service (`streamer/server.js` & `streamer/torrent_engine.js`):

- **Sequential Priority**: WebTorrent pieces are dynamically reprioritized. The first 2% of pieces (containing MP4 `moov` atoms or MKV cluster headers) and the final 1% are downloaded with critical priority, followed by linear sequential downloading.
- **Byte-Range Seeking**: Supports HTTP 206 Partial Content range requests, allowing users to jump anywhere on the playback timeline instantly.
- **Active Swarm Memory Management**: Automatically executes `this.client.remove(torrent, { destroyStore: true })` on timed-out searches, user disconnects, or idle sessions to prevent locked duplicates and disk exhaustion.

---

### 2.4. Multi-Debrid Cloud Integration (`core/debrid/`)
For instantaneous playback without relying on P2P swarm seeders, EvoScrapper integrates 6 major Debrid services:

1. **Real-Debrid** (`core/debrid/realdebrid.py`)
2. **AllDebrid** (`core/debrid/alldebrid.py` - with tuple-preserving multi-hash checks)
3. **Debrid-Link** (`core/debrid/debridlink.py`)
4. **Premiumize.me** (`core/debrid/premiumize.py`)
5. **TorBox** (`core/debrid/torbox.py` - authenticated `requestdl` link generator)
6. **PikPak** (`core/debrid/pikpak.py`)

#### Debrid Tokenized Streaming Proxy
Debrid download URLs often expose private user tokens or expire quickly. EvoScrapper wraps resolved links in secure, signed HMAC proxy tokens (`/api/v1/debrid/proxy/{token}`). The proxy streams the media with byte-range support while hiding credentials from the frontend player.

---

### 2.5. Transmuxing & VLC Native Launcher (`core/transmuxer.py`)
- **Virtual HLS Segmentation**: For clients requiring HLS, `/api/v1/stream/hls/segment` slices video into true MPEG-TS segments (`-f mpegts`) with `-output_ts_offset <start_time>` to maintain strict PTS/DTS timestamp continuity across segment boundaries.
- **Targeted Child Process VLC Launch**: Launches native VLC via `launch_vlc_process` with `--no-one-instance`, `--network-caching=2000`, and tracks child PIDs directly. Destructive OS-wide `taskkill` commands have been eliminated.

---

### 2.6. Subtitle Engine ("EvoSubs")
Subtitle synchronization supports multiple lookup and alignment strategies:
- **Subtitle Sync Engine v2 (`core/subtitle_sync/`)**: Multi-modal alignment fusing Audio Voice Activity Detection (silencedetect), container-embedded reference tracks, external subtitle provider consensus, forced subtitle / sign filtering, and framerate drift modeling.
- **Real-Time Adaptive Playback Controller**: Stateful session engine allowing interactive user sync adjustments (`H`/`J` keypress deltas) that dynamically converge across playback timestamps with exponential proximity decay weighting.
- **Hash Matching**: 64-bit uint64 OpenSubtitles checksum and Shooter MD5 hashing against local or streamed media files.
- **Multi-Provider Search**: Queries OpenSubtitles, Gestdown, SubDL, SubSource, AnimeTosho, and YIFY Subtitles.
- **ZIP Language Disambiguation**: In multi-file subtitle archives, `select_zip_subtitle_member` analyzes file paths and extracts the exact requested language rather than picking arbitrary first members.
- **WebVTT Conversion**: Dynamically converts SubRip (`.srt`) to WebVTT (`.vtt`) and filters unsupported ASS/SSA drawing vector commands for clean rendering in HTML5 video elements.

---

### 2.7. CometNet Decentralized P2P Gossip (`core/cometnet.py`)
Inspired by decentralized torrent metadata sharing, `CometNetNode` allows peers to announce new releases and debrid cache availability:
- **Ed25519 Digital Signatures**: Every message is cryptographically signed using an Ed25519 private key and verified by peers before ingestion.
- **Deterministic Canonicalization**: Payload dictionaries are normalized into deterministic byte sequences before signing.
- **Bounded Ingestion**: Ingested messages are deduplicated using a rolling 10,000-element FIFO index.

---

## 3. Security Hardening Summary

EvoScrapper has undergone a comprehensive 28-point security and architectural audit (see [`FLAWS.md`](FLAWS.md)):

| Threat / Vulnerability | Remediation Implementation |
|---|---|
| **SSRF (Server-Side Request Forgery)** | `validate_outbound_proxy_url` filters private RFC1918 IPs, IPv6 loopback (`::1`), `127.0.0.1`, `localhost`, and invalid schemes on all download and VTT proxy routes. |
| **Timing Attacks on API Keys** | API key comparison uses `hmac.compare_digest` in `core/security.py`. |
| **Unprotected Internal Endpoints** | Streaming and VLC launch endpoints enforce `verify_api_key` dependency. |
| **Data Loss on Crash** | Watchlist/library persistence uses atomic replacement (`tempfile` + `os.fsync` + `os.replace`). |
| **In-Memory Cache Pollution** | `MemoryCache.get` returns isolated deep copies via `model_copy(deep=True)` or `copy.deepcopy()`. |
| **Codec Regex Destruction** | Lookaheads preserve dots in versioned tokens (`H.264`, `H.265`, `5.1`, `7.1`). |
| **Numeric Title Truncation** | Movies starting with years (*1917*, *2001*, *2012*) are preserved by guarding index-0 cuts. |

---

## 4. Configuration Reference

Configuration is managed via Pydantic Settings in `config.py`. All settings can be overridden via environment variables or a `.env` file:

```ini
# Server
HOST=0.0.0.0
PORT=8009
DEBUG=false
API_KEY=your_optional_secret_api_key

# Concurrency & Timeouts
DEFAULT_TIMEOUT=4.0
CIRCUIT_BREAKER_FAIL_THRESHOLD=3
CIRCUIT_BREAKER_RECOVERY_TIME=90.0

# Optional Subtitle API Keys
SUBDL_API_KEY=
SUBSOURCE_API_KEY=
OPENSUBTITLES_API_KEY=

# Optional Debrid API Keys
REALDEBRID_API_KEY=
ALLDEBRID_API_KEY=
DEBRIDLINK_API_KEY=
PREMIUMIZE_API_KEY=
TORBOX_API_KEY=

# Streaming Cache
STREAM_CACHE_DIR=.stream_cache
MAX_DISK_CACHE_GB=15
PIKPAK_USERNAME=
PIKPAK_PASSWORD=
```

---

## 5. Streaming Engine & Player Architecture

### Flaw-Fix Matrix (Streaming & Buffering Overhaul)

| Flaw ID | Severity | Phase | Files Touched | Tests | Status |
|---|---|---|---|---|---|
| `STRM-CRIT-01` | Critical | Phase 0 | `routers/stream.py` | `tests/test_streaming_overhaul_phase0.py` | FIXED |
| `STRM-CRIT-02` | Critical | Phase 0 | `streamer/server.js`, `streamer/torrent_engine.js` | `tests/test_streaming_overhaul_phase0.py` | FIXED |
| `STRM-CRIT-03` | Critical | Phase 0 | `streamer/torrent_engine.js` | `tests/test_streaming_overhaul_phase0.py` | FIXED |
| `STRM-CRIT-04` | Critical | Phase 0 | `core/transmuxer.py` | `tests/test_streaming_overhaul_phase0.py` | FIXED |
| `STRM-CRIT-05` | Critical | Phase 0 | `routers/stream.py`, `core/discover.py` | `tests/test_streaming_overhaul_phase0.py` | FIXED |
| `STRM-HIGH-01` | High | Phase 5 | `core/transmuxer.py`, `routers/stream.py` | `tests/test_transmux_audio_and_concurrency.py` | FIXED |
| `STRM-HIGH-02` | High | Phase 6 | `core/debrid/proxy.py`, `main.py` | `tests/test_debrid_pooling.py` | FIXED |
| `STRM-HIGH-03` | High | Phase 5 | `core/transmuxer.py` | `tests/test_transmux_audio_and_concurrency.py` | FIXED |
| `STRM-HIGH-04` | High | Phase 1 | `core/transmuxer.py`, `routers/stream.py` | `tests/test_hls_stream.py` | FIXED |
| `STRM-HIGH-05` | High | Phase 7 | `core/transmuxer.py`, `routers/stream.py` | `tests/test_hls_keyframes.py` | FIXED |
| `STRM-MED-01` | Medium | Phase 3 | `streamer/torrent_engine.js`, `streamer/server.js` | `tests/test_buffer_watchdog.py` | FIXED |
| `STRM-MED-02` | Medium | Phase 3 | `core/transmuxer.py`, `static/app.js` | `tests/test_buffer_watchdog.py` | FIXED |
| `STRM-MED-03` | Medium | Phase 9 | `core/torrent_streamer.py`, `streamer/server.js` | `tests/test_process_management.py` | FIXED |
| `STRM-MED-04` | Medium | Phase 10 | `static/app.js`, `static/p2p-player.js` | `tests/test_webrtc_mesh_wiring.py` | FIXED |
| `STRM-MED-05` | Medium | Phase 2 | `streamer/torrent_engine.js`, `routers/stream.py` | `tests/test_p2p_streaming_overhaul.py` | FIXED |
| `STRM-LOW-01` | Low | Phase 8 | `streamer/torrent_engine.js` | `tests/test_engine_hygiene.py` | FIXED |
| `STRM-LOW-02` | Low | Phase 5 | `static/app.js`, `static/index.html` | `tests/test_transmux_audio_and_concurrency.py` | FIXED |
| `STRM-LOW-03` | Low | Phase 9 | `config.py`, `core/torrent_streamer.py` | `tests/test_process_management.py` | FIXED |

### 5.1. 4-Tier Concurrent Swarm Buffering (streamer/torrent_engine.js)
To eliminate playback stalls during 4K and 1080p high-bitrate streaming, the WebTorrent streaming engine employs an adaptive 4-tier piece prioritization horizon:
1. **Tier 1 (Critical Header & Index Lock)**:
   - Pieces covering container metadata (MP4 `moov` atom, MKV EBML headers) at file start (first 4 pieces) and index/seek tables at file end (last 2 pieces) are locked at **Priority 3**.
2. **Tier 2 (Immediate Playback Horizon)**:
   - The current playback piece plus the next 8 pieces ahead (~16MB) are selected at **Priority 3** for instant frame decoding and zero seek-stutter.
3. **Tier 3 (Multi-Peer Swarm Horizon)**:
   - The next 32 pieces ahead are prioritized at **Priority 2**, dispatching parallel piece requests across multiple connected swarm wires simultaneously.
4. **Tier 4 (Predictive Background Reservoir)**:
   - The next 64 pieces ahead are prioritized at **Priority 1**, filling the disk/RAM cache ahead of time to cushion against swarm network dips.
5. **Continuous Rolling Sliding Window**:
   - `createReadStream()` continuously monitors stream consumption. Every 2 pieces transferred, `applySlidingWindow()` rolls the entire 4-tier horizon forward, maintaining an unbroken 64MB–100MB buffer reservoir.

### 5.2. WebTorrent Critical Piece Hotswapping
Under traditional BitTorrent piece reservation strategies, pieces assigned to slow or choked peers block playback pipeline progress even if dozens of fast peers are idle.
- In `streamer/torrent_engine.js`, EvoScrapper invokes `torrent.critical(cursorPiece, cursorPiece + 3)` upon stream initialization and subsequent playback seeks.
- The `critical()` directive bypasses normal piece reservation queues and instructs the wire manager to burst requests for the target blocks across **all** connected active wires concurrently.
- The first wire to deliver the block completes the piece; redundant outstanding requests to slower wires are cancelled immediately via standard cancel messages, slashing initial buffer latency by up to 80%.

### 5.3. Double-NAT & Fixed P2P Port Traversal Architecture
Home network topologies often involve cascading routers (e.g. an ISP fiber ONT/Modem in router mode connected to a high-speed WiFi router). This creates a **Double-NAT** environment where P2P clients fail to receive incoming connections unless ports are deterministically configured and forwarded:

```
[ Internet / Public Swarm ]
          |
    (Public IP: 105.101.x.x)
          v
+-----------------------------+
| Huawei Fiber Modem / ONT    |
| - DMZ Host: 192.168.96.200  |  <-- Passes all unsolicited inbound traffic to Router WAN
+--------------+--------------+
               |
         (192.168.96.200)
               v
+-----------------------------+
| Tenda TX2 Pro Router        |
| - Port 50000 (TCP/UDP)      |  <-- Port Forwarded to Host PC
| - Port 50001 (UDP)          |  <-- DHT / uTP Forwarded to Host PC
+--------------+--------------+
               |
         (192.168.0.169)
               v
+-----------------------------+
| EvoScrapper WebTorrent Node |
| - TCP Listener: Port 50000  |  <-- Inbound BT wire connections accepted
| - UDP Listener: Port 50001  |  <-- Inbound DHT, PEX, and uTP packets accepted
+-----------------------------+
```

1. **Deterministic Ports (50000 TCP / 50001 UDP)**:
   - Rather than binding to random ephemeral ports on every startup (which renders static router port forwarding useless), EvoScrapper binds WebTorrent explicitly to `50000` (TCP/UDP) and `50001` (UDP).
2. **Overcoming Asymmetric Swarm Choking**:
   - When inbound ports are closed, a P2P node can only connect outbound to un-firewalled peers.
   - Opening inbound ports enables bi-directional wire connections with 100% of swarm participants, including seedboxes and firewalled leechers who can now connect into EvoScrapper.
   - Result: Connected swarm wires surge from 5–10 up to 60+ wires, achieving full saturation of 600Mbps+ fiber connections.

### 5.4. Precision Subtitle Language Tokenization Matrix
When searching and presenting multi-language subtitle tracks, simple substring matching (`string.includes(code)`) produces severe false-positive collisions. For example, matching the Arabic code `ar` against string labels like `Hungarian` (`hungARian`) or `Bulgarian` (`bulgARian`) incorrectly injects foreign language subtitles into the Arabic drawer.

EvoScrapper eliminates this via a two-stage tokenized classification engine in `static/app.js`:

1. **Word-Tokenized Lexical Isolation**:
   - Release titles and language names are tokenized into word boundaries via regex:
     ```javascript
     const nameWords = (sub.lang || sub.label || '').toLowerCase().split(/[^a-z0-9]+/);
     ```
2. **Length-Gated Alias Matching**:
   - **Short Aliases ($\le 3$ chars, e.g. `ar`, `ara`, `hu`, `hun`, `es`, `spa`)**:
     - Strict match on standard ISO codes: `code === a || code.startsWith(a + '-') || code.startsWith(a + '_')`.
     - Word boundary match: `nameWords.includes(a)`.
     - Substring containment is strictly forbidden for short codes.
   - **Full Language Names ($> 3$ chars, e.g. `arabic`, `hungarian`, `spanish`)**:
     - Substring search `name.includes(a)` is permitted only for distinct strings exceeding 3 characters.
3. **Comprehensive ISO Family Mapping**:
   - Explicit definitions for Arabic (`ar`, `ara`, `arabic`), Hungarian (`hu`, `hun`, `hungarian`, `magyar`), Bulgarian (`bg`, `bul`, `bulgarian`), Greek (`el`, `gre`, `greek`), Romanian (`ro`, `ron`, `romanian`), Polish (`pl`, `pol`, `polish`), and 15+ additional global dialects.

### 5.5. Cinematic Player Experience & DOM Streamlining
- **Floating Fullscreen Cinema HUD**: Overlay hierarchy (`.player-hud-header`, `.player-bottom-controls`, `.player-hud-footer`) floats transparently over `#player-video-wrap`.
- **Idle HUD Auto-Hide**: After 3 seconds of user inactivity during playback, the HUD smoothly translates out of the viewport and hides the mouse cursor (`cursor: none`), maximizing viewable canvas.
- **Uncluttered Viewport**: Distracting floating overlays (such as skip intro buttons) have been completely removed from the DOM, CSS, and event loops, ensuring a clean, distraction-free movie and episodic viewing experience.
- **Centerline Baseline Alignment**: Transport controls, volume slider track, 10s skip dials, and time indicators are locked to an identical vertical centerline with robust air-gap spacing.

### 5.6. Discover Default Stream Sorting
- When querying streams for movies or episodic TV series in Discover mode, stream results default to **Seeds (High to Low)** (`seeds_desc`), presenting the most swarm-healthy, high-speed releases first.

### 5.7. Contract-First Testing Suite (SPEC.md)
- Architectural boundaries and I/O contracts are formally defined in `SPEC.md` and enforced via deterministic unit and regression tests in `tests/test_core_contract.py`, `tests/test_player_and_buffering.py`, `tests/test_player_alignment_and_discover_sort.py`, and `tests/test_subs_lang_and_player_cleanup.py`.

### 5.8. Bitrate-Adaptive Sliding Window & Backward-Seek Retention [STRM-MED-05]
- Instead of static piece counts, window boundaries dynamically calculate from file bitrate:
  - Critical playback horizon: 20 seconds ahead at Priority 3 + `critical()`.
  - Multi-peer swarm horizon: 90 seconds ahead * buffer multiplier at Priority 2.
  - Background lookahead reservoir: 240 seconds ahead * buffer multiplier at Priority 1.
- **Backward-Seek Protection**: Maintains a 10-piece retention tail behind cursor (`cursorPiece - 11`) and immediately re-selects critical priority upon backward seek to eliminate playback stalls.

### 5.9. Virtual HLS Keyframe Snapping & Persistent Cache [STRM-HIGH-04, STRM-HIGH-05]
- `HlsSegmentCache` persists generated TS/fMP4 segments to disk with single-flight mutex deduplication, background prefetching of sequential segments, and LRU eviction.
- Keyframe boundary analysis (`ffprobe`) indexes video keyframes (`data/keyframes/<hash>_<idx>.json`) and aligns `#EXTINF` segment durations to exact keyframes, eliminating timestamp discontinuities.
- Supports fragmented MP4 container format with `#EXT-X-MAP:URI="init.mp4"` for zero-transmuxing overhead.

### 5.10. High-Fidelity Audio Downmixing (ITU-R BS.775) & PGS Canvas [STRM-HIGH-01, STRM-LOW-02]
- Audio streams with > 2 channels (5.1 / 7.1) are downmixed using the ITU-R BS.775 stereo pan matrix (`FL=0.5*c0+0.7071*c2+0.7071*c4|FR=0.5*c1+0.7071*c2+0.7071*c5`), restoring center dialogue clarity.
- PGS bitmap subtitles default to client-side WebAssembly canvas decoding (`pgs-decoder.js` via `/api/v1/stream/subtitles/sup`), avoiding GPU/CPU video re-encoding.

### 5.11. WebRTC Mesh Acceleration & Kill-Fast Hygiene [STRM-HIGH-03, STRM-MED-04]
- Client player integrates P2P Media Loader over WebRTC with automatic direct HTTP chunk fallback.
- Transmux FFmpeg processes are bounded by dynamic semaphore sizing and terminated with 1.0s kill-fast timeout on client disconnect to prevent hanging processes.

### 5.12. Subtitle Sync Engine v2: Multi-Modal Fusion & Adaptive Alignment
The Subtitle Sync Engine v2 (`core/subtitle_sync/`) addresses subtitle lead/lag, framerate mismatch, and cue desynchronization via a multi-signal fusion pipeline:

1. **Forced Subtitle / Signs Isolation (`forced_subs.py`)**:
   - Matches regex patterns for bracketed signs (`[Sign: ...]`, `(Music ...)`), title cards (`Sign: Hospital`), credits headers (`Credits: ...`), and ultra-short cues ($\le 1.0$s duration with $\le 2$ words).
   - Strips non-dialogue cues from target cues prior to cross-track alignment to eliminate artificial skew.

2. **Multi-Source RANSAC Consensus (`consensus.py`)**:
   - Collects sync candidate offsets from embedded reference tracks, audio VAD speech intervals, and external subtitle releases (OpenSubtitles, SubDL, AnimeTosho).
   - Applies RANSAC clustering with a configurable maximum outlier threshold (`max_outlier_sec = 1.5s`) to group agreeing timings and compute a confidence-weighted average offset.
   - Calibrates confidence with multi-signal agreement boosts up to 0.99.

3. **Framerate Drift Modeling (`drift.py`)**:
   - Detects linear framerate conversion drift (e.g., 23.976 fps NTSC vs 24.0 fps Film vs 25.0 fps PAL) using pure Python closed-form Ordinary Least Squares regression:
     $$\text{offset}(t) = a \cdot t + b$$
   - Solves for $a$ (drift rate) and $b$ (initial lead/lag). When $|a| > 0.0005$ and RMSE is low, attaches the drift model to dynamically adjust subtitles across long playback durations.

4. **Real-Time Adaptive Playback Controller (`adaptive.py`)**:
   - Bounded session controller (`ADAPTIVE_CONTROLLERS`) updated in real time via `POST /api/v1/stream/subtitles/adjust`.
   - Coalesces rapid sequential keypresses (e.g. repeated `H` delay taps) into the current cumulative offset.
   - Computes position-weighted offset using exponential timeline proximity:
     $$w_i = \exp\left(-\frac{|p_i - \text{position\_sec}|}{180.0}\right)$$
   - Calculates real-time user alignment confidence based on correction variance.

5. **Resilient VAD & Cold-Swarm Embedded Delivery**:
   - Audio speech interval extraction downmixes surround streams (`-ac 2`), establishes resilient HTTP reconnect parameters (`-reconnect 1 -reconnect_at_eof 1 -reconnect_streamed 1 -reconnect_delay_max 5`), and bounds sampling to 90 seconds to prevent player buffering stalls.
   - Cold swarms or unsupported text formats register terminal extraction failures in memory (`_sub_vtt_failed`), returning HTTP 200 with clear diagnostics and without `X-Evo-Sub-Pending` headers to terminate frontend polling loops cleanly.
   - The Web Player HUD presents online fallback subtitles immediately while background extraction proceeds, seamlessly replacing them when embedded tracks finish.
