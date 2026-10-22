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
Subtitle synchronization supports multiple lookup strategies:
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
```
