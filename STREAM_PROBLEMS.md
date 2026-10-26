# Comprehensive P2P Streaming, Buffering & Playback Flaw Audit: EvoScrapper

**Date of Audit:** October 2026  
**Audited System:** `EvoScrapper` (FastAPI / WebTorrent ESM Micro-Daemon / FFmpeg Transmuxer / Debrid Proxy)  
**Domain Standard:** `p2p-streaming-engineering` & Production BitTorrent / Stremio Architecture  

---

## Executive Summary

An in-depth, end-to-end architectural and operational audit of the streaming, sequential piece buffering, transmuxing, and playback pipelines in `EvoScrapper` was performed.

While the existing system provides foundational support for multi-provider stream resolution and WebTorrent streaming, systematic code inspection identified **18 distinct architectural defects and buffering vulnerabilities** across 6 core subsystems:
1. **P2P Swarm & Sequential Piece Buffering Engine (`streamer/torrent_engine.js`, `streamer/server.js`)**
2. **HTTP Range Server & Loopback Streaming Bridge (`routers/stream.py`)**
3. **FFmpeg Real-Time Transmuxing & A/V Synchronization Pipeline (`core/transmuxer.py`)**
4. **Debrid Multi-IP Cloud Streaming Proxy (`core/debrid/proxy.py`)**
5. **Virtual HLS Segment Generation Pipeline (`core/transmuxer.py`, `routers/stream.py`)**
6. **Web Player HUD, Codec Probing & Subtitle Synchronization (`static/app.js`, `static/p2p-player.js`)**

### Severity Summary
- **Critical Severity (5 Flaws):** Immediate playback termination (45s hard socket kill), destructive multi-session eviction, critical piece clearing race conditions, video-copy seeking A/V desync, and an unhandled `NameError` crash.
- **High Severity (5 Flaws):** Audio dialogue suppression (missing ITU-R BS.775 downmix), zero connection pooling on Debrid proxy, seek concurrency deadlocks in FFmpeg semaphore, unbounded HLS process explosion, and non-keyframe HLS segment slicing.
- **Medium Severity (5 Flaws):** Stream probe timeouts breaking scrubber and audio tracks, silent EOF terminations on stalled torrents, hardcoded ports with indiscriminate `taskkill`, dormant P2P WebRTC mesh engine, and backward seek piece starvation.
- **Low Severity (3 Flaws):** Excessive chunk cache memory footprint, real-time subtitle burn-in CPU saturation, and unlinked configuration settings.

---

## Master Vulnerability & Problem Matrix

| Flaw ID | Severity | Subsystem / Component | Root Cause & Failure Mechanism | Operational Impact |
|:---|:---|:---|:---|:---|
| **STRM-CRIT-01** | **Critical** | `routers/stream.py:142` | `aiohttp.ClientTimeout(total=45.0)` applied to long-lived `/play` stream proxy | Any continuous stream is abruptly killed at exactly 45 seconds |
| **STRM-CRIT-02** | **Critical** | `streamer/server.js:347`<br/>`streamer/torrent_engine.js:405` | `cleanupOtherSessions` executes `destroyStore: true` on every new stream request | Opening a second tab, preview, or multi-user stream wipes active torrent chunks and kills playback |
| **STRM-CRIT-03** | **Critical** | `streamer/torrent_engine.js:304` | `torrent._critical.fill(false)` wipes `FileIterator` critical pieces every 2 chunks | WebTorrent reader pieces lose emergency prioritization, inducing 5–15s periodic buffering stalls |
| **STRM-CRIT-04** | **Critical** | `core/transmuxer.py:347, 381` | `-noaccurate_seek -ss` with `-c:v copy` and `-c:a aac` creates start timestamp mismatch | Video PTS starts at previous keyframe while audio starts at seek time; causes severe desync or MSE freeze |
| **STRM-CRIT-05** | **Critical** | `routers/stream.py:643` | `get_debrid_statuses` references undefined variables `info_hash`, `file_idx`, `provider` | Calling `/api/v1/stream/debrid/status` crashes immediately with `NameError` (HTTP 500) |
| **STRM-HIGH-01** | **High** | `core/transmuxer.py:388` | Standard `-ac 2` without ITU-R BS.775 stereo downmix matrix on 5.1/7.1 audio tracks | Center dialogue is muted or muffled while background music/effects are deafening |
| **STRM-HIGH-02** | **High** | `core/debrid/proxy.py:101` | `httpx.AsyncClient` instantiated and destroyed on every individual HTTP Range chunk | 150–400ms TLS handshake latency added to every 2MB buffer chunk; high risk of socket exhaustion |
| **STRM-HIGH-03** | **High** | `core/transmuxer.py:302, 407` | Global `asyncio.Semaphore(4)` saturated by canceled FFmpeg processes during timeline scrubbing | Rapid seeking blocks new requests on the semaphore; player UI freezes with spinning wheel |
| **STRM-HIGH-04** | **High** | `core/transmuxer.py:432`<br/>`routers/stream.py:684` | Virtual HLS segment endpoint lacks semaphore or concurrency bounds | Hls.js/P2P Media Loader requests 10 parallel segments, launching 10 FFmpeg instances and pinning CPU at 100% |
| **STRM-HIGH-05** | **High** | `core/transmuxer.py:460` | MPEG-TS segment extraction uses `-c:v copy` with arbitrary 6-second timestamps | Non-GOP boundaries produce segments starting with non-keyframes; Hls.js throws `MEDIA_ERR_DECODE` |
| **STRM-MED-01** | **Medium** | `static/app.js:8000, 8136` | `triggerStreamProbe` aborts permanently after 4 retries (~13s) on cold swarms | Timeline duration displays 00:00/00:00, scrubber locks up, and audio tracks remain empty |
| **STRM-MED-02** | **Medium** | `core/transmuxer.py:417`<br/>`routers/stream.py:173` | Async generator breaks cleanly on stalled stream, emitting HTTP 200 EOF | Player pauses believing video has ended; no `error` event fires and no auto-reconnect occurs |
| **STRM-MED-03** | **Medium** | `core/torrent_streamer.py:13, 103` | Hardcoded ports (8889, 50000, 50001) and OS-wide `taskkill /F /PID` without process validation | Kills third-party apps sharing ports; crashes on startup if ports are in `TIME_WAIT` or privileged |
| **STRM-MED-04** | **Medium** | `static/p2p-player.js`<br/>`static/app.js:8155` | `playStreamInBrowser` assigns `video.src` directly, ignoring `EvoP2PPlayerManager` | WebRTC P2P Media Loader mesh is completely inactive; browser mesh bandwidth sharing is lost |
| **STRM-MED-05** | **Medium** | `streamer/torrent_engine.js:340` | `applySlidingWindow` deselects past pieces behind the cursor | Seeking backwards requires swarm to re-request previously downloaded pieces, causing buffering delays |
| **STRM-LOW-01** | **Low** | `streamer/torrent_engine.js:204` | `storeCacheSlots: 500` caches 500 pieces in memory | Consumes 1GB–2GB RAM on high-bitrate 4K torrents; risks Node.js V8 OOM crashes in Docker |
| **STRM-LOW-02** | **Low** | `core/transmuxer.py:358` | Burning PGS bitmap subtitles forces software video re-encoding on non-HW systems | Transcode speed drops below 1.0x on 1080p/4K; causes periodic buffering every 2 seconds |
| **STRM-LOW-03** | **Low** | `config.py:51`<br/>`core/torrent_streamer.py:13` | Settings in `config.py` (`MAX_CONCURRENT_FFMPEG`, `TORRENT_PORT`) ignored by modules | Configuration overrides via environment variables or `.env` have zero effect |

---

## Detailed Technical Problem Reports & Remediation

---

### Category A: P2P Torrent Swarm & Sequential Piece Buffering

#### [STRM-CRIT-02] Destructive Multi-Session Eviction (`destroyStore: true`) on Concurrent Streams
* **File:** [streamer/server.js](file:///F:/Projects/Torrent%20scrapping%20Apis/EvoScrapper/streamer/server.js#L347) & [streamer/torrent_engine.js](file:///F:/Projects/Torrent%20scrapping%20Apis/EvoScrapper/streamer/torrent_engine.js#L405-L417)
* **Severity:** Critical
* **Affected Functions:** `server.js (HTTP /stream handler)`, `TorrentEngine.cleanupOtherSessions`

##### Root Cause Analysis
In `streamer/server.js:347`:
```javascript
const torrent = await engine.addTorrent(infoHash, magnet);
engine.cleanupOtherSessions(torrent.infoHash);
```
And in `streamer/torrent_engine.js:405-417`:
```javascript
cleanupOtherSessions(activeHash) {
    if (!activeHash) return;
    const normActive = String(activeHash).toLowerCase();
    for (const [hash, sess] of this.sessions.entries()) {
        if (String(hash).toLowerCase() !== normActive) {
            console.log(`[TorrentEngine] Evicting non-active session and clearing cache: ${hash}`);
            try {
                this.client?.remove(sess.torrent, { destroyStore: true }, () => {});
            } catch (_) {}
            this.sessions.delete(hash);
        }
    }
}
```
Whenever an HTTP request arrives for `/stream`, the engine iterates through all other active sessions and removes them with `{ destroyStore: true }`.
If:
1. User A is watching a movie in living room, and User B opens an episode on their laptop.
2. A user opens a second tab or clicks an episode while pre-warming is active.
3. The UI queries `/probe` or extracts subtitles while a stream is running.

User A's torrent is instantly unregistered from WebTorrent, the socket is dropped, and all downloaded piece files on disk in `.stream_cache` are permanently deleted mid-playback.

##### Remediation
1. Remove `engine.cleanupOtherSessions()` from the hot request path in `/stream`.
2. Allow concurrent torrent sessions up to a configurable limit (e.g. `MAX_ACTIVE_TORRENTS = 3`).
3. Only reclaim sessions in `cleanupIdleSessions()` when `Date.now() - sess.lastActive > idleTimeoutMs` (e.g. 15 minutes of zero HTTP read activity).
4. When evicting idle sessions, retain piece store or clear it gracefully without disrupting active readers.

---

#### [STRM-CRIT-03] Critical Piece Bitfield Reset Race Wiping Pending `FileIterator` Pieces
* **File:** [streamer/torrent_engine.js](file:///F:/Projects/Torrent%20scrapping%20Apis/EvoScrapper/streamer/torrent_engine.js#L304-L307)
* **Severity:** Critical
* **Affected Functions:** `TorrentEngine.applySlidingWindow`, `TorrentEngine.createReadStream`

##### Root Cause Analysis
In `torrent_engine.js:304-307`:
```javascript
// Reset stale critical bitfield to prevent emergency queue starvation
if (torrent._critical && Array.isArray(torrent._critical)) {
    torrent._critical.fill(false);
}
```
This is executed every time `applySlidingWindow` is called, which occurs every 2 pieces downloaded during streaming (`createReadStream: stream.on('data')`).
However, WebTorrent 3.x uses `FileIterator` (`lib/file-iterator.js:60`):
```javascript
if (!this._torrent.bitfield.get(index)) {
    this._torrent.on('verified', listener)
    return this._torrent.critical(index, index + this._criticalLength)
}
```
When `FileIterator` is waiting for a piece needed by the HTTP stream socket, it sets `_critical[index] = true`. Every 2 chunks read, `applySlidingWindow` executes `torrent._critical.fill(false)`, wiping the critical flag.
As a result, WebTorrent's peer request loop drops the piece out of the urgent queue and reverts to standard round-robin or rarest-first distribution among connected wires.

##### Remediation
Do not blanket-reset `torrent._critical.fill(false)`. Instead:
1. Only clear critical flags for piece indices that have already been verified in `torrent.bitfield`.
2. Allow `FileIterator`'s current read index to maintain its critical status until verified.

---

#### [STRM-MED-05] Backward Seek Starvation from Deselected Pieces
* **File:** [streamer/torrent_engine.js](file:///F:/Projects/Torrent%20scrapping%20Apis/EvoScrapper/streamer/torrent_engine.js#L340-L344)
* **Severity:** Medium
* **Affected Functions:** `TorrentEngine.applySlidingWindow`

##### Root Cause Analysis
```javascript
if (cursorPiece > fileStartPiece + criticalCount) {
    try {
        torrent.deselect(fileStartPiece + criticalCount, cursorPiece - 1, false);
    } catch (_) {}
}
```
As playback proceeds forward, pieces behind the cursor are deselected to prevent wasting swarm bandwidth.
When a viewer rewinds 15–30 seconds to replay a scene:
1. The pieces for that range were explicitly deselected in WebTorrent's internal `_selections` list.
2. `applySlidingWindow(cursorPiece)` only schedules forward lookahead windows (`cursorPiece` to `cursorPiece + 64`).
3. The backward seek must wait for `FileIterator` to slowly register on-demand read requests without the benefit of the prioritized multi-peer horizon, resulting in a 5–10s stall.

##### Remediation
Maintain a sliding backward retention buffer of at least 5–10 pieces behind the cursor before calling `deselect()`. Only deselect pieces prior to `cursorPiece - 10`.

---

#### [STRM-LOW-01] Excessive In-Memory Piece Cache Footprint (`storeCacheSlots: 500`)
* **File:** [streamer/torrent_engine.js](file:///F:/Projects/Torrent%20scrapping%20Apis/EvoScrapper/streamer/torrent_engine.js#L204)
* **Severity:** Low
* **Affected Functions:** `TorrentEngine.addTorrent`

##### Root Cause Analysis
```javascript
const torrentOpts = {
    path: CACHE_DIR,
    announce: DEFAULT_TRACKERS,
    deselect: true,
    strategy: 'sequential',
    maxWebConns: 50,
    storeCacheSlots: 500
};
```
For standard 2MB piece sizes, 500 slots = 1,000MB (1GB) of memory. For 4K Remuxes with 4MB or 8MB pieces, this consumes 2GB–4GB of RAM in the Node.js process. In Docker containers or memory-constrained servers, this triggers V8 OOM aborts.

##### Remediation
Lower `storeCacheSlots` to 64–128 (sufficient for ~128MB–256MB lookahead window), relying on the filesystem cache for older chunks.

---

### Category B: HTTP Streaming Proxy & Socket Lifecycle

#### [STRM-CRIT-01] 45-Second Hard Socket Termination on Raw Torrent Streams (`/play`)
* **File:** [routers/stream.py](file:///F:/Projects/Torrent%20scrapping%20Apis/EvoScrapper/routers/stream.py#L142)
* **Severity:** Critical
* **Affected Functions:** `stream_raw_torrent`

##### Root Cause Analysis
In `routers/stream.py:137-143`:
```python
for attempt in range(4):
    try:
        upstream_resp = await session.get(
            target_url,
            headers=req_headers,
            timeout=aiohttp.ClientTimeout(total=45.0, sock_connect=8.0),
        )
```
In `aiohttp`, `ClientTimeout(total=45.0)` dictates the **total cumulative duration** of the entire HTTP transaction from connect to the last byte of the response body.
When streaming via `/play` (direct MP4/WebM in browser, VLC playback, or file download):
- If the client opens a single continuous stream or requests an open-ended byte range (`bytes=0-`), `aiohttp` terminates the connection after exactly 45.0 seconds with `asyncio.TimeoutError`.
- The FastAPI `stream_generator()` receives an unhandled exception, abruptly closes the socket to the player, and streaming freezes.

##### Remediation
For live streaming proxies, `total` MUST be `None`. Apply connection timeouts and read timeouts instead:
```python
timeout = aiohttp.ClientTimeout(total=None, sock_connect=10.0, sock_read=45.0)
```
This allows streams to play indefinitely while preserving protection against hung connections if no data arrives for 45 seconds.

---

#### [STRM-CRIT-05] Unhandled `NameError` Crash in Debrid Status Endpoint
* **File:** [routers/stream.py](file:///F:/Projects/Torrent%20scrapping%20Apis/EvoScrapper/routers/stream.py#L643)
* **Severity:** Critical
* **Affected Functions:** `get_debrid_statuses`

##### Root Cause Analysis
In `routers/stream.py:638-648`:
```python
@router.get("/debrid/status")
async def get_debrid_statuses():
    """
    Returns account and connection statuses for all configured Debrid providers.
    """
    debrid_logger.info(f"Resolving Debrid stream info_hash={info_hash} file_idx={file_idx} provider={provider}")
    from core.debrid.manager import get_debrid_manager
    manager = get_debrid_manager()
    statuses = await manager.get_all_statuses()
    return {"providers": statuses}
```
The logging call references `info_hash`, `file_idx`, and `provider`, none of which are arguments to `get_debrid_statuses()`. Any invocation of `/api/v1/stream/debrid/status` raises:
`NameError: name 'info_hash' is not defined`
and returns HTTP 500 Internal Server Error.

##### Remediation
Remove or correct the erroneous logger statement:
```python
debrid_logger.info("Fetching Debrid provider connection statuses")
```

---

#### [STRM-MED-02] Silent Premature Stream EOF Without Player Reconnect / Error Propagation
* **Files:** [core/transmuxer.py](file:///F:/Projects/Torrent%20scrapping%20Apis/EvoScrapper/core/transmuxer.py#L417-L422) & [routers/stream.py](file:///F:/Projects/Torrent%20scrapping%20Apis/EvoScrapper/routers/stream.py#L173-L177)
* **Severity:** Medium
* **Affected Functions:** `stream_transmuxed_video`, `stream_raw_torrent:stream_generator`

##### Root Cause Analysis
In `core/transmuxer.py:416-422`:
```python
try:
    while True:
        chunk = await process.stdout.read(chunk_size)
        if not chunk:
            break
        yield chunk
except (asyncio.CancelledError, GeneratorExit):
    pass
```
If FFmpeg terminates due to an upstream read timeout from the loopback daemon, or if the torrent temporarily stalls, FFmpeg's `stdout.read` returns `b""`.
The Python generator cleanly breaks, and FastAPI terminates the HTTP response with HTTP 200 OK.
Because the HTTP status is 200 OK:
- The browser's `<video>` element does NOT trigger an `error` event.
- The player assumes the video has legitimately reached the end of the file.
- The video pauses and remains frozen. The user must manually reload or scrub to resume.

##### Remediation
1. Check process exit code in `finally`: if FFmpeg terminated abnormally or exited before expected duration, log a warning.
2. In the browser player (`static/app.js`), if `video.ended` is triggered but `video.currentTime < active.totalDuration - 10`, treat it as an unexpected drop and trigger automatic seek-recovery at `video.currentTime`.

---

#### [STRM-MED-03] Hardcoded Fixed Network Ports & Destructive OS-Wide `taskkill`
* **File:** [core/torrent_streamer.py](file:///F:/Projects/Torrent%20scrapping%20Apis/EvoScrapper/core/torrent_streamer.py#L13-L16), [L103-L117](file:///F:/Projects/Torrent%20scrapping%20Apis/EvoScrapper/core/torrent_streamer.py#L103-L117)
* **Severity:** Medium
* **Affected Functions:** `kill_stale_daemon`, module-level constants

##### Root Cause Analysis
```python
STREAM_PORT = 8889
TORRENT_PORT = 50000
DHT_PORT = 50001
...
def kill_stale_daemon():
    if os.name == "nt":
        for port in (STREAM_PORT, 50000, 50001):
            out = subprocess.check_output(f"netstat -ano | findstr :{port}", shell=True, text=True)
            for line in out.strip().splitlines():
                if "LISTENING" in line:
                    parts = line.strip().split()
                    pid = int(parts[-1])
                    if pid > 0 and pid != os.getpid():
                        subprocess.run(f"taskkill /F /PID {pid}", shell=True, capture_output=True)
```
1. `config.py` defines `settings.TORRENT_PORT` and `settings.DHT_PORT`, but `torrent_streamer.py` hardcodes `STREAM_PORT = 8889`, `50000`, and `50001`.
2. `kill_stale_daemon` indiscriminately kills ANY process listening on ports 8889, 50000, or 50001 without checking whether the process is `node.exe` or belongs to EvoScrapper. If the user runs qBittorrent, a game, or Docker on port 50000, it is forcefully terminated.
3. If port 8889 is in `TIME_WAIT` or bound by a privileged service, the daemon crashes with `EADDRINUSE`.

##### Remediation
1. Check process image name (e.g. `wmic process where "ProcessId=PID" get Name` or `tasklist`) before killing.
2. Support dynamic port fallback: if port 8889 is occupied, probe 8890–8899 and pass the assigned port to the daemon via environment variables.

---

### Category C: FFmpeg Transmuxing, Transcoding & A/V Sync

#### [STRM-CRIT-04] Non-Keyframe Fast Seek in Video-Copy Transmuxing Causing Severe A/V Desync & Freezing
* **File:** [core/transmuxer.py](file:///F:/Projects/Torrent%20scrapping%20Apis/EvoScrapper/core/transmuxer.py#L347-L351), [L381-L383](file:///F:/Projects/Torrent%20scrapping%20Apis/EvoScrapper/core/transmuxer.py#L381-L383)
* **Severity:** Critical
* **Affected Functions:** `stream_transmuxed_video`

##### Root Cause Analysis
In `core/transmuxer.py:347-351`:
```python
if start_seconds and start_seconds > 0:
    if not transcode_video and burn_sub_idx is None:
        cmd.append("-noaccurate_seek")
    cmd.extend(["-ss", f"{start_seconds:.2f}"])
...
if not transcode_video:
    cmd.extend([
        "-c:v", "copy",
        *get_passthrough_fps_flag(),
    ])
```
When `-noaccurate_seek` and `-ss` precede `-i` with `-c:v copy`:
- FFmpeg jumps to the nearest keyframe *prior* to `start_seconds`. If keyframes are every 5 seconds and the user seeks to 14.0s, video starts emitting packets from t=10.0s.
- Audio is decoded and remuxed (`-c:a aac`), which seeks accurately to t=14.0s.
- While `-avoid_negative_ts make_zero` adjusts initial PTS, the first video packet has a PTS offset of ~4 seconds ahead or behind the audio timeline.
- Modern browser HTML5 `<video>` and MSE decoders stall waiting for missing video/audio frames matching the container start time, or play audio completely desynchronized by the entire keyframe interval.

##### Remediation
1. When copying video (`-c:v copy`), remove `-noaccurate_seek` and enforce `-copyts -avoid_negative_ts make_zero`.
2. Align audio start time with video packet PTS using `-af "aresample=async=1:first_pts=0"`.
3. If fine-grained seeking without GOP drift is required, automatically activate video transcoding for the first GOP, or instruct the browser to seek to the keyframe reported by the probe index.

---

#### [STRM-HIGH-01] Multi-Channel Surround Audio Downmix Suppresses Center Dialogue Channels
* **File:** [core/transmuxer.py](file:///F:/Projects/Torrent%20scrapping%20Apis/EvoScrapper/core/transmuxer.py#L388-L396)
* **Severity:** High
* **Affected Functions:** `stream_transmuxed_video`

##### Root Cause Analysis
```python
af_filters = ["aresample=async=1:first_pts=0:min_hard_comp=0.100000"]
if audio_boost and audio_boost > 0:
    af_filters.append(f"volume={audio_boost:.2f}")

cmd.extend([
    "-c:a", "aac",
    "-b:a", "192k",
    "-ac", "2",
    "-af", ",".join(af_filters),
])
```
The majority of 1080p and 4K torrents contain multi-channel surround audio: 5.1 Dolby Digital Plus (`eac3`), DTS-HD MA, or TrueHD Atmos (6 to 8 channels).
FFmpeg's default `-ac 2` downmix sums channels linearly or attenuates center dialogue by -3dB relative to loud surround channels. The result is classic "whisper quiet dialogue, ear-splitting explosions".
The `p2p-streaming-engineering` rule mandates the standard **ITU-R BS.775** stereo downmix formula.

##### Remediation
Apply the standard ITU-R BS.775 downmix pan filter when input has >2 channels:
```python
itu_downmix = "pan=stereo|FL < 1.0*FL + 0.707*FC + 0.707*BL|FR < 1.0*FR + 0.707*FC + 0.707*BR"
af_filters.insert(0, itu_downmix)
```

---

#### [STRM-HIGH-03] Concurrency Semaphore Deadlock During Fast Scrubbing / Seeking
* **File:** [core/transmuxer.py](file:///F:/Projects/Torrent%20scrapping%20Apis/EvoScrapper/core/transmuxer.py#L302), [L407](file:///F:/Projects/Torrent%20scrapping%20Apis/EvoScrapper/core/transmuxer.py#L407)
* **Severity:** High
* **Affected Functions:** `stream_transmuxed_video`

##### Root Cause Analysis
```python
_FFMPEG_SEMAPHORE = asyncio.Semaphore(4)
...
async with _FFMPEG_SEMAPHORE:
    process = await asyncio.create_subprocess_exec(...)
```
`_FFMPEG_SEMAPHORE` restricts the host to 4 concurrent FFmpeg instances.
When a user scrubs on the timeline slider in the UI:
1. The browser immediately fires 3 to 6 seek requests in rapid succession as the slider moves.
2. The browser aborts the earlier requests.
3. In Python/asyncio on Windows, subprocess cancellation and `taskkill`/`terminate()` cleanup takes between 500ms and 2000ms per process.
4. All 4 semaphore permits are consumed by abandoned, dying FFmpeg processes.
5. The actual intended seek request blocks waiting for an available permit. The player UI displays a spinning buffering indicator for several seconds.

##### Remediation
1. Implement client-side debounce in `static/app.js` during timeline dragging (e.g. 250ms debounce on `input` before firing `seekPlayer()`).
2. Make `_FFMPEG_SEMAPHORE` per-client or scale permits with CPU core count (`max(4, os.cpu_count())`).
3. Explicitly kill canceled processes immediately with `process.kill()` rather than waiting for graceful termination.

---

#### [STRM-LOW-02] Real-Time Subtitle Burn-In CPU Saturation on High-Bitrate Media
* **File:** [core/transmuxer.py](file:///F:/Projects/Torrent%20scrapping%20Apis/EvoScrapper/core/transmuxer.py#L358-L364)
* **Severity:** Low
* **Affected Functions:** `stream_transmuxed_video`

##### Root Cause Analysis
When burning bitmap PGS subtitles (`burn_sub_idx` is passed), FFmpeg MUST decode video, overlay bitmap graphics, and re-encode every video frame (`transcode_video = True`).
If no hardware acceleration (NVENC, QSV, AMF) is available, it falls back to software `libx264 -preset ultrafast`.
On 4K or 1080p 60fps video, software CPU encoding speed drops to 0.4x–0.8x real-time on standard quad-core and 6-core CPUs. The server cannot produce video frames as fast as the player consumes them, causing the player to freeze and buffer every 2–3 seconds.

##### Remediation
1. Prefer client-side canvas PGS decoding via `/api/v1/stream/subtitles/sup` (implemented in `static/pgs-decoder.js`) rather than server-side burn-in.
2. In the UI, warn the user when selecting PGS burn-in if hardware encoding is not detected.

---

### Category D: Debrid Cloud Caching & Multi-IP Proxy Gateway

#### [STRM-HIGH-02] Lack of Connection Pooling in Debrid Multi-IP Proxy
* **File:** [core/debrid/proxy.py](file:///F:/Projects/Torrent%20scrapping%20Apis/EvoScrapper/core/debrid/proxy.py#L101-L104)
* **Severity:** High
* **Affected Functions:** `DebridStreamProxy.create_upstream_stream`

##### Root Cause Analysis
```python
client = httpx.AsyncClient(
    follow_redirects=True,
    timeout=httpx.Timeout(connect=15.0, read=None, write=30.0, pool=None),
)
req = client.build_request("GET", upstream_url, headers=headers_to_send)
resp = await client.send(req, stream=True)
...
finally:
    await resp.aclose()
    await client.aclose()
```
The Debrid proxy instantiates a brand new `httpx.AsyncClient` for every single HTTP Range request from the player, and closes it in `finally`.
HTML5 video elements stream large files by issuing dozens or hundreds of sequential range requests (e.g. 2MB–5MB chunks).
Opening and destroying a client per chunk means:
1. Zero HTTP Keep-Alive connection reuse.
2. Every chunk incurs a 150–400ms delay for TCP handshake and TLS certificate exchange with Real-Debrid / AllDebrid edge servers.
3. Rapid range requests exhaust OS ephemeral ports (`TIME_WAIT` socket buildup).

##### Remediation
Use a shared, persistent `httpx.AsyncClient` singleton with an active connection pool:
```python
_shared_client = httpx.AsyncClient(
    limits=httpx.Limits(max_keepalive_connections=50, max_connections=200, keepalive_expiry=60.0),
    timeout=httpx.Timeout(connect=15.0, read=None, write=30.0, pool=15.0),
    follow_redirects=True,
)
```

---

### Category E: Virtual HLS & Segment Generation Pipelines

#### [STRM-HIGH-04] Unbounded Process Spawning & CPU Thrashing in HLS TS Segment Generator
* **Files:** [core/transmuxer.py](file:///F:/Projects/Torrent%20scrapping%20Apis/EvoScrapper/core/transmuxer.py#L432-L500) & [routers/stream.py](file:///F:/Projects/Torrent%20scrapping%20Apis/EvoScrapper/routers/stream.py#L684-L705)
* **Severity:** High
* **Affected Functions:** `stream_hls_ts_segment`, `get_hls_segment`

##### Root Cause Analysis
In `routers/stream.py:684-705`:
```python
@router.get("/hls/segment")
async def get_hls_segment(...):
    source_url = get_internal_stream_url(info_hash, file_idx, magnet=magnet, season=season, episode=episode)
    return StreamingResponse(
        stream_hls_ts_segment(source_url, start_seconds=start, duration_seconds=duration),
        media_type="video/mp2t",
    )
```
Unlike `stream_transmuxed_video`, `stream_hls_ts_segment` has NO semaphore and NO concurrency governor.
When an HLS player (e.g. `Hls.js` or P2P Media Loader) buffers ahead, it dispatches 5 to 15 concurrent segment requests (`segment 0, 1, 2, 3...`).
This immediately spawns 5 to 15 distinct `ffmpeg.exe` processes. Each process probes the media stream and executes audio resampling and remuxing simultaneously. This causes 100% CPU lockup and severe disk thrashing.

##### Remediation
1. Restrict `stream_hls_ts_segment` concurrency with an `asyncio.Semaphore(3)`.
2. Cache generated `.ts` segments to disk or memory so duplicate segment requests (common in P2P mesh swarms) return instantly without invoking FFmpeg.

---

#### [STRM-HIGH-05] Non-Keyframe Slicing in MPEG-TS Virtual HLS Segments
* **File:** [core/transmuxer.py](file:///F:/Projects/Torrent%20scrapping%20Apis/EvoScrapper/core/transmuxer.py#L460-L476)
* **Severity:** High
* **Affected Functions:** `stream_hls_ts_segment`

##### Root Cause Analysis
```python
cmd.extend([
    "-ss", f"{start_seconds:.3f}",
    "-t", f"{duration_seconds:.3f}",
    "-i", source_url_or_path,
    "-c:v", "copy",
    "-f", "mpegts",
    "-mpegts_copyts", "1",
    "-output_ts_offset", f"{start_seconds:.3f}",
    "pipe:1",
])
```
Because `-c:v copy` is used, FFmpeg cannot cut video on arbitrary 6.000-second intervals unless a keyframe (IDR frame) exists at that exact second.
In standard torrent encodes, GOP size varies between 24 and 250 frames (1s to 10s).
When a segment is sliced at a timestamp that falls on a P-frame or B-frame, the segment starts with delta frames lacking their reference keyframe.
`Hls.js` demuxer throws `bufferStallError`, `MEDIA_ERR_DECODE`, or produces severe visual pixel smearing.

##### Remediation
For true RFC-compliant HLS, either:
1. Transcode video at segment boundaries with forced keyframes (`-g 60 -keyint_min 60`), OR
2. Generate an fMP4 (`#EXT-X-MAP`) manifest indexed to actual keyframe byte ranges, OR
3. Deprecate virtual on-the-fly HLS TS slicing in favor of the direct fragmented MP4 transmuxer (`/api/v1/stream/transmux`), which streams keyframe fragments progressively with zero slicing errors.

---

#### [STRM-MED-04] Disconnected P2P WebRTC Mesh Engine (`static/p2p-player.js`)
* **Files:** [static/p2p-player.js](file:///F:/Projects/Torrent%20scrapping%20Apis/EvoScrapper/static/p2p-player.js) & [static/app.js](file:///F:/Projects/Torrent%20scrapping%20Apis/EvoScrapper/static/app.js#L8155-L8165)
* **Severity:** Medium
* **Affected Functions:** `playStreamInBrowser`

##### Root Cause Analysis
`static/p2p-player.js` implements a WebRTC P2P Media Loader mesh engine designed to connect browser viewers into a shared playback mesh.
However, in `static/app.js:8155-8165`:
```javascript
video.src = streamUrl;
video.load();
```
`playStreamInBrowser` directly sets `video.src` to the HTML5 video element, completely bypassing `window.evoP2PPlayer.setupPlayer()`.
The entire P2P WebRTC mesh client script is dead code during normal torrent streaming.

##### Remediation
Wire `window.evoP2PPlayer` into `playStreamInBrowser` when HLS or WebRTC mesh mode is toggled, or cleanly document that browser-native playback relies on the local Node.js WebTorrent daemon.

---

### Category F: Browser Web Player HUD, Codec Probing & Subtitle Sync

#### [STRM-MED-01] Premature Stream Probe Timeout Rendering Player Timeline & Codec Scrubber Broken
* **File:** [static/app.js](file:///F:/Projects/Torrent%20scrapping%20Apis/EvoScrapper/static/app.js#L8000-L8015), [L8136-L8146](file:///F:/Projects/Torrent%20scrapping%20Apis/EvoScrapper/static/app.js#L8136-L8146)
* **Severity:** Medium
* **Affected Functions:** `triggerStreamProbe`

##### Root Cause Analysis
In `static/app.js:8000-8015`:
- `triggerStreamProbe` starts 1.0 second after clicking play.
- If the swarm is establishing connections or downloading metadata, `ffprobe` in `/api/v1/stream/probe` times out or returns `success: false`.
- The retry logic executes:
  `window._evoProbeTimer = setTimeout(triggerStreamProbe, probeAttempts * 2000);`
- `maxProbeAttempts` is hardcoded to 4.
After 4 attempts (~13 seconds total), probing permanently stops.
If metadata takes 15–20 seconds to arrive (very common on public swarms):
1. `active.totalDuration` remains 0. The timeline slider is non-functional and duration displays `00:00 / 00:00`.
2. `active.audioTracks` remains empty. The audio selector menu displays nothing.
3. The player cannot auto-detect incompatible audio codecs (e.g. EAC3 5.1) and never upgrades to transmux mode, leaving the video silent.

##### Remediation
1. Increase `maxProbeAttempts` to 10 with progressive backoff (up to 45 seconds).
2. Hook `video.oncanplay` and `video.onplaying` to re-trigger `triggerStreamProbe()` if `!active.totalDuration || !active.audioTracks.length`.

---

#### [STRM-LOW-03] Config Settings Ignored by Transmuxer & Torrent Streamer Modules
* **Files:** [config.py](file:///F:/Projects/Torrent%20scrapping%20Apis/EvoScrapper/config.py#L51-L53), [core/transmuxer.py](file:///F:/Projects/Torrent%20scrapping%20Apis/EvoScrapper/core/transmuxer.py#L302), [core/torrent_streamer.py](file:///F:/Projects/Torrent%20scrapping%20Apis/EvoScrapper/core/torrent_streamer.py#L13-L15)
* **Severity:** Low
* **Affected Functions:** `core.transmuxer._FFMPEG_SEMAPHORE`, `core.torrent_streamer` port definitions

##### Root Cause Analysis
`config.py` explicitly declares:
- `MAX_CONCURRENT_FFMPEG: int = 4`
- `TORRENT_PORT: int = 50000`
- `DHT_PORT: int = 50001`
However:
- `core/transmuxer.py:302` uses a hardcoded `asyncio.Semaphore(4)`.
- `core/torrent_streamer.py:13-15` uses hardcoded `TORRENT_PORT = 50000`, `DHT_PORT = 50001`.
Any overrides configured in `.env` or system environment variables are completely ignored at runtime.

##### Remediation
Import `settings` from `config` and initialize constants dynamically:
```python
from config import settings

_FFMPEG_SEMAPHORE = asyncio.Semaphore(getattr(settings, "MAX_CONCURRENT_FFMPEG", 4))
TORRENT_PORT = getattr(settings, "TORRENT_PORT", 50000)
DHT_PORT = getattr(settings, "DHT_PORT", 50001)
```

---

## Prioritized Implementation Roadmap

To systematically resolve these streaming and buffering issues without introducing regressions, execution should follow a 3-phase remediation plan aligned with `p2p-streaming-engineering` principles:

```mermaid
flowchart TD
    subgraph Phase 1: Critical Stability & Crash Hotfixes
        P1A["STRM-CRIT-01: Remove 45s hard socket timeout on /play"]
        P1B["STRM-CRIT-02: Eliminate destroyStore multi-session wipe"]
        P1C["STRM-CRIT-05: Fix NameError in get_debrid_statuses"]
        P1D["STRM-CRIT-03: Protect FileIterator critical pieces"]
    end

    subgraph Phase 2: Transmuxing, Audio & Debrid Performance
        P2A["STRM-CRIT-04: Fix video-copy seek PTS/DTS drift"]
        P2B["STRM-HIGH-01: Implement ITU-R BS.775 5.1/7.1 stereo downmix"]
        P2C["STRM-HIGH-02: Implement persistent AsyncClient connection pooling for Debrid"]
        P2D["STRM-HIGH-03: Add debounce & dynamic scaling to FFmpeg semaphore"]
    end

    subgraph Phase 3: Player Resilience & Virtual HLS Stabilization
        P3A["STRM-MED-01: Extend stream probe retries with onplaying triggers"]
        P3B["STRM-MED-02: Implement auto-reconnect on premature stream EOF"]
        P3C["STRM-MED-03 & LOW-03: Wire config.py ports and graceful process management"]
        P3D["STRM-HIGH-04 & HIGH-05: Bound virtual HLS concurrency & cache segments"]
    end

    Phase 1 --> Phase 2
    Phase 2 --> Phase 3
```
