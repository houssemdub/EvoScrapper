# MISSION: Streaming & Buffering Overhaul + Full Flaw-Audit Remediation for EvoScrapper

You are working in the EvoScrapper repository (FastAPI backend + Node.js WebTorrent ESM micro-daemon in streamer/ + FFmpeg transmuxer core/transmuxer.py + Debrid proxy core/debrid/proxy.py + single-page player static/index.html + static/app.js + static/p2p-player.js). Execute this plan phase by phase. After EACH phase: run `pytest tests/ -x -q`, fix any regression, then commit with the given message. Do NOT skip verification. Read each target file fully before editing. Line numbers from the audit are approximate — always locate code by symbol name/function, not line number.

Ground truth (verify before editing):
- streamer/torrent_engine.js  -> TorrentEngine class, addTorrent(), applySlidingWindow(), createReadStream(), cleanupOtherSessions(), cleanupIdleSessions(), getStatus()
- streamer/server.js          -> daemon HTTP handlers (/stream, /warm, /probe, etc.) on port 8889
- core/transmuxer.py          -> find_ffmpeg(), _FFMPEG_SEMAPHORE, stream_transmuxed_video(), stream_hls_ts_segment(), generate_hls_manifest()
- core/torrent_streamer.py    -> Python client + daemon lifecycle (STREAM_PORT, TORRENT_PORT, DHT_PORT, kill_stale_daemon)
- routers/stream.py           -> /play (stream_raw_torrent), /warm, /transmux, /probe, /debrid/status (get_debrid_statuses), /hls/playlist.m3u8, /hls/segment (get_hls_segment), /stats
- core/debrid/proxy.py        -> DebridStreamProxy.create_upstream_stream()
- config.py                   -> Settings: MAX_CONCURRENT_FFMPEG, TORRENT_PORT, DHT_PORT
- static/app.js               -> triggerStreamProbe(), playStreamInBrowser(), seekPlayer(), settings-buffer-size-input
- static/p2p-player.js        -> window.evoP2PPlayer.setupPlayer()
- tests/test_player_and_buffering.py, tests/test_p2p_streaming_overhaul.py, tests/test_hls_stream.py
- AGENTS.md and SPEC.md define project conventions (async-first, Pydantic v2, no blocking I/O in event loop).

=====================================================================
PHASE 0 — CRITICAL HOTFIXES (Ship First; Each Is Small & Independent)
=====================================================================
Fix these five critical defects exactly as specified. Add a regression test for each.

0.1 [STRM-CRIT-01] 45-second hard socket kill on /play
    File: routers/stream.py, function stream_raw_torrent.
    Problem: upstream request uses aiohttp.ClientTimeout(total=45.0, sock_connect=8.0). In aiohttp, total= is the CUMULATIVE duration of the entire transaction — any continuous stream dies at exactly 45s with asyncio.TimeoutError.
    Fix: replace with `timeout = aiohttp.ClientTimeout(total=None, sock_connect=10.0, sock_read=45.0)` so streams run indefinitely but hung connections (no bytes for 45s) still abort. Audit ALL other ClientTimeout usages in routers/ and core/ for the same total-on-streaming bug; fix every streaming path.
    Test: assert timeout.total is None on the /play upstream call (monkeypatch session.get to capture kwargs).
    Commit: "fix(stream): remove 45s cumulative timeout killing live /play streams [STRM-CRIT-01]"

0.2 [STRM-CRIT-02] Destructive multi-session eviction (destroyStore:true)
    Files: streamer/server.js (in the /stream handler: engine.cleanupOtherSessions(torrent.infoHash)), streamer/torrent_engine.js cleanupOtherSessions().
    Problem: EVERY new /stream request removes all other sessions with { destroyStore: true }, permanently deleting downloaded pieces mid-playback when a second tab/user opens anything, or when the UI probes/subtitles during a stream.
    Fix:
      a) Remove the cleanupOtherSessions() call from the /stream hot path entirely.
      b) Enforce concurrency instead: cap active sessions at MAX_ACTIVE_TORRENTS (default 3, env-tunable); when over cap, evict only the LEAST-recently-active IDLE session (lastActive older than idleTimeoutMs), never one with an open read stream.
      c) In cleanupIdleSessions(): keep destroyStore:false for recently-watched hashes (see Phase 6.1 disk-resume cache); only truly stale hashes (>EVO_KEEP_CACHE budget) get destroyStore:true.
      d) Track sess.activeReaders count (increment/decrement around createReadStream consumers); sessions with activeReaders > 0 are NEVER evictable.
    Delete or repurpose cleanupOtherSessions so it can never be invoked from a request path; if kept for admin use, rename to forceEvictSession and require explicit flag.
    Test (JS-side via existing daemon test harness, or Python integration): start stream A, issue /warm+/stream for B, assert torrent A remains in engine.sessions and its store files are untouched.
    Commit: "fix(engine): stop destroying concurrent sessions/stores on every /stream [STRM-CRIT-02]"

0.3 [STRM-CRIT-03] Critical bitfield reset wipes FileIterator emergency pieces
    File: streamer/torrent_engine.js, inside applySlidingWindow():
      if (torrent._critical && Array.isArray(torrent._critical)) { torrent._critical.fill(false); }
    Problem: WebTorrent's FileIterator calls torrent.critical(i, i+len) to mark pieces the live reader is waiting on. Blanket fill(false) every 2 chunks strips emergency priority from in-flight reader pieces -> 5–15s periodic stalls.
    Fix: never blanket-fill. Clear ONLY indices already verified: iterate the array and set false where torrent.bitfield.get(i) === true. Leave unverified critical bits intact (WebTorrent clears them itself on receipt). Re-add stale-flag hygiene by clearing critical bits for pieces more than (window max) behind the cursor AND verified.
    Test: simulate _critical with mixed verified/unverified bits, run applySlidingWindow, assert unverified reader-critical bits survive.
    Commit: "fix(engine): preserve FileIterator critical pieces; clear only verified bits [STRM-CRIT-03]"

0.4 [STRM-CRIT-04] Video-copy fast seek causes A/V desync / MSE freeze
    File: core/transmuxer.py, stream_transmuxed_video().
    Problem: when start_seconds>0 and video is stream-copied (-c:v copy), the code adds -noaccurate_seek before -ss. FFmpeg then starts video at the previous KEYFRAME (e.g. t=10.0 for a seek to 14.0) while AAC audio seeks accurately to 14.0 -> PTS mismatch up to a full GOP; browsers stall or play badly desynced.
    Fix:
      a) Remove the -noaccurate_seek branch entirely for copy mode.
      b) For copy-mode seeks emit: `-ss <t>` (input-side, accurate enough with demuxer keyframe seek) plus output flags `-copyts -avoid_negative_ts make_zero` and audio filter alignment `-af aresample=async=1:first_pts=0:min_hard_comp=0.1` (this filter chain must merge with the af_filters built in 1 below).
      c) Expose the actual first-video-packet timestamp: after spawn, parse ffmpeg stderr once (or ffprobe the output head) and return header X-Evo-Seek-Keyframe so the player can optionally snap video.currentTime to the real keyframe.
      d) If |audio_start - video_first_pts| would exceed 2s (long-GOP sources), fall back to transcoding ONLY the first GOP: run a short pre-segment with libx264 ultrafast from keyframe->seek point, then switch to copy (document as stretch goal; ship a+b+c minimum, and log a warning when long GOP detected).
    Test: unit-test command construction asserting '-noaccurate_seek' absent and '-copyts' present for copy+seek; parser test for keyframe extraction from sample ffmpeg stderr.
    Commit: "fix(transmux): accurate keyframe-aligned copy seeks; drop -noaccurate_seek [STRM-CRIT-04]"

0.5 [STRM-CRIT-05] NameError crash in /debrid/status
    File: routers/stream.py, get_debrid_statuses().
    Problem: log line references undefined info_hash/file_idx/provider -> guaranteed HTTP 500.
    Fix: replace that logger call with debrid_logger.info("Fetching Debrid provider connection statuses"). Then grep the whole repo for f-strings referencing names not in scope within their function (quick pyflakes pass: `python -m pyflakes routers core streamer 2>/dev/null || pip install pyflakes -q && python -m pyflakes routers core`); fix any siblings found.
    Test: GET /api/v1/stream/debrid/status returns 200 in TestClient suite.
    Commit: "fix(api): remove undefined-name logging crashing /debrid/status [STRM-CRIT-05]"

=====================================================================
PHASE 1 — Persistent HLS Muxer with Segment Cache (fixes STRM-HIGH-04 + enables HIGH-05 work)
=====================================================================
Problem: routers/stream.py get_hls_segment calls core.transmuxer.stream_hls_ts_segment(), which spawns a fresh FFmpeg process per ~6s chunk with NO semaphore and NO bounds. Hls.js/P2P Media Loader requesting 10 parallel segments launches 10 FFmpeg instances -> 100% CPU lockup and disk thrash. Duplicate segment requests re-mux from scratch.

Tasks:
1.1 In core/transmuxer.py add an async `HlsSegmentCache` class:
    - Key: (info_hash, file_idx, segment_idx, start, duration, source_fingerprint).
      source_fingerprint = daemon-reported download % of the byte range covering the segment (so incomplete ranges are never cached as final).
    - Value: bytes on disk under data/hls_cache/<key>.ts + .done marker + mtime.
    - TTL 30 min, LRU eviction at configurable max bytes (default 2 GB, env EVO_HLS_CACHE_MAX_MB).
    - Single-flight: concurrent requests for the same key await one shared asyncio.Task.
1.2 Bound muxer concurrency: wrap every stream_hls_ts_segment spawn in a dedicated `asyncio.Semaphore(max(1, int(os.getenv("EVO_HLS_MAX_CONCURRENCY", "3"))))`. This directly fixes [STRM-HIGH-04].
1.3 Refactor stream_hls_ts_segment() into `_spawn_ts_segment(...)` used ONLY on cache miss. On hit, serve the cached file via FileResponse/StreamingResponse with Content-Type video/mp2t and Cache-Control: public, max-age=300, immutable.
1.4 Background prefetch: when segment N is served, enqueue muxing of N+1..N+3 through the SAME bounded semaphore. Prefetch must abort if the source range is not yet locally buffered (ask daemon /range-status).
1.5 Wire into get_hls_segment(); keep endpoint signature backward compatible.
Acceptance: (a) second playthrough of same torrent serves segments with ZERO ffmpeg spawns (test monkeypatches asyncio.create_subprocess_exec to count invocations); (b) stress test firing 15 concurrent /hls/segment requests asserts max 3 simultaneous subprocess spawns.
Commit: "feat(hls): persistent segment cache + single-flight + bounded mux concurrency [STRM-HIGH-04]"

=====================================================================
PHASE 2 — Time/Bitrate-Adaptive Sliding Window + Seek-Safe Reservoir (fixes STRM-MED-05)
=====================================================================
Problem: applySlidingWindow() selects fixed piece counts (8 immediate / 24 mid / 32 lookahead) regardless of bitrate; and it deselects everything behind the cursor, so rewinding 15–30s forces the swarm to re-fetch pieces already downloaded once (5–10s stall).

Tasks:
2.1 Lightweight probe: on session ready, read container metadata via ffprobe against the daemon's local cache path (new daemon endpoint GET /file-info?hash=&idx= returning duration_seconds and avg_bitrate_bps; cache on session object). Fall back to 8 Mbps estimate if unavailable.
2.2 Rewrite applySlidingWindow(torrent, file, byteOffset, opts) to compute windows in SECONDS:
    - criticalSec = 20s ahead at priority 3 + torrent.critical()
    - bufferSec   = 90s at priority 2
    - horizonSec  = 240s at priority 1
    pieces = ceil(seconds * avgBitrateBps / 8 / pieceLength). Clamp totals to [8, 256] pieces.
2.3 Replace the byte-counter slide trigger (every 2 pieces) with a 1-second setInterval per active read stream PLUS immediate slide on 'peer'/'wire' events.
2.4 Explicit seek support: daemon endpoint POST /window {hash, fileIdx, byteOffset} calling applySlidingWindow immediately; core/torrent_streamer.py exposes warm_window(hash, file_idx, offset); call from /warm and before transmux spawns.
2.5 [STRM-MED-05] Backward-seek starvation: maintain a retention tail. Never deselect closer than RETAIN_BEHIND_PIECES = 10 behind the cursor: change the deselect call to `torrent.deselect(fileStartPiece, cursorPiece - 1 - 10, false)` guarded so end >= start. Additionally, when a NEW cursor position lands behind the previous cursor (detect in /window handler), immediately re-select the range [newCursor - 2, newCursor + criticalCount] at priority 3 and mark those pieces critical BEFORE FileIterator has to wait on them.
2.6 User tuning: extend settings-buffer-size-input (static/index.html) to send ?buffer_mb= through to the daemon, scaling bufferSec/horizonSec proportionally.
Acceptance: unit test in tests/test_p2p_streaming_overhaul.py asserting (a) 20 Mbps file gets smaller piece horizon than 2 Mbps file for identical seconds targets; (b) JS-level test (or string-inspection test matching existing repo patterns) that deselect bound is cursorPiece-11 and backwards /window re-selects behind-cursor range.
Commit: "perf(engine): bitrate-adaptive time-based window + backward-seek retention [STRM-MED-05]"

=====================================================================
PHASE 3 — Buffer-Health Watchdog, EOF Recovery & Probe Resilience (fixes STRM-MED-01, STRM-MED-02)
=====================================================================
Problem: nothing monitors throughput vs playback; stalled streams silently end as HTTP-200 EOF (player thinks the movie finished); cold-swarm probes die after ~13s leaving 00:00/00:00 timelines and empty audio-track lists.

Tasks:
3.1 In streamer/torrent_engine.js track per-session EMA of downloadSpeed and deficit = avgBitrateBps/8 - emaDownBps. Expose in getStatus(): ema_down_bps, bitrate_bps, deficit_ratio, seconds_ahead (bytes buffered past cursor / bitrate).
3.2 Engine watchdog (every 5s per active session):
    - deficit_ratio > 1.25 AND seconds_ahead < 30 -> widen horizonSec x1.5 (cap 600s)
    - numPeers < 3 for > 20s -> force tracker re-announce + DHT bootstrap refresh
    - seconds_ahead < 10 -> emit event; server.js exposes GET /health-watch?hash= returning {state: healthy|degraded|critical, suggestion: debrid|transcode_low|wait}
3.3 routers/stream.py: include header X-Evo-Buffer-State on /play and /transmux responses; player polls /api/v1/stream/stats every 3s.
3.4 [STRM-MED-02] Silent premature EOF:
    a) core/transmuxer.py stream_transmuxed_video: in finally, inspect process.returncode and whether expected duration was reached; if FFmpeg died early or exited nonzero, log warning and (since mid-body status can't change) flush a sentinel: prefer raising inside the generator AFTER zero bytes sent (let FastAPI emit 502) else terminate the chunk stream deliberately without trailing moof/cluster so MSE signals an error rather than clean EOF. Simplest robust variant: when abnormal exit occurs before yielding ANY bytes, raise HTTPException(502); after bytes flowed, append nothing and rely on (b).
    b) static/app.js: hook video.addEventListener('ended') — if active.totalDuration > 0 && video.currentTime < active.totalDuration - 10, treat as unexpected drop: show toast "Stream dropped — reconnecting…", then re-issue the current source URL via seekPlayer(video.currentTime) auto-recovery (max 3 attempts, exponential backoff 2/5/10s). Also hook video 'error' to the same recovery ladder before escalating to Phase 3.5 fallback.
3.5 Player-side degraded recovery: when stats state=critical for >5s, auto-switch to Debrid proxy URL if a configured provider has the hash cached (reuse /resolve + /debrid/proxy); otherwise show buffering HUD with "Switching to cloud relay…" toast. Persist last-good decisions in data/ JSON keyed by info_hash so next open prefers the winning source.
3.6 [STRM-MED-01] Probe resilience in static/app.js triggerStreamProbe():
    - Raise maxProbeAttempts from 4 to 10 with progressive backoff capped at ~6s/attempt (~45s total).
    - Hook video.oncanplay and video.onplaying: if (!active.totalDuration || !active.audioTracks.length) re-arm triggerStreamProbe() (reset attempt counter once per successful data arrival).
    - When probe eventually reports incompatible audio (e.g. EAC3/DTS in MP4), automatically upgrade the source to /transmux mode instead of leaving silent video.
Acceptance: tests simulating low throughput assert widened horizon + suggestion payload; app.js inspection test asserts maxProbeAttempts>=10, oncanplay/onplaying hooks exist, and ended-handler guard exists.
Commit: "feat(stream): buffer-health watchdog + EOF auto-reconnect + resilient probing [STRM-MED-01][STRM-MED-02]"

=====================================================================
PHASE 4 — Range Serving & Proxy-Hop Reduction
=====================================================================
Problem: FFmpeg/range reads traverse FastAPI proxy -> aiohttp -> daemon, adding latency and copies on every byte; seeks pay this tax repeatedly.

Tasks:
4.1 Ensure streamer/server.js range endpoint answers byte ranges directly from the WebTorrent store with proper 206/Content-Range and no full-file buffering (audit; fix gaps).
4.2 core/torrent_streamer.py: when API server and daemon share localhost, redirect players/FFmpeg straight to the daemon (307 with rewritten Location) instead of streaming through FastAPI. Gate behind EVO_DIRECT_RANGE=true, enabled ONLY when request.client.host is 127.0.0.1/::1 (never leak daemon URLs to remote clients — respect core/security.py SSRF conventions).
4.3 For /transmux, pass the direct daemon URL as FFmpeg input instead of the proxied URL.
4.4 Verify the shared aiohttp.ClientSession is actually reused everywhere; replace ad-hoc session creation.
Acceptance: test that /play issues 307 for localhost clients with no body proxied; remote clients still receive streamed bytes.
Commit: "perf(stream): direct daemon range serving + 307 redirect for localhost"

=====================================================================
PHASE 5 — Transmux Audio Correctness & Semaphore Hygiene (fixes STRM-HIGH-01, STRM-HIGH-03, STRM-LOW-02)
=====================================================================
5.1 [STRM-HIGH-01] ITU-R BS.775 stereo downmix: in stream_transmuxed_video(), when audio must be transcoded (browser-incompatible codec or transcode path) detect input channels (from /probe metadata already fetched, or ffprobe -select_streams a:0). If channels > 2, prepend the standard downmix to af_filters:
      pan=stereo|FL=< 1.0*FL + 0.707*FC + 0.707*BL + 0.707*SL|FR=< 1.0*FR + 0.707*FC + 0.707*BR + 0.707*SR
    Keep -ac 2 AFTER the pan filter. Apply the same matrix in any audio-only transcode helper. Unit-test command construction for 6-channel inputs (assert pan present, order correct) and 2-channel inputs (assert absent).
5.2 [STRM-HIGH-03] Scrub deadlock on _FFMPEG_SEMAPHORE:
    a) Size permits dynamically: max(settings.MAX_CONCURRENT_FFMPEG, os.cpu_count() // 2) floor-clamped to >=4 (also satisfies LOW-03 wiring).
    b) On client disconnect / CancelledError, kill the process IMMEDIATELY: process.kill() (SIGKILL-equivalent) first, then await wait(timeout=2) — never await graceful terminate chains while holding the permit. Release the semaphore in a finally that cannot block >2s.
    c) Debounce seeking in static/app.js: timeline slider 'input' events debounced 250ms before firing seekPlayer(); 'change' fires immediately. Coalesce duplicate in-flight seeks to the same target (+/-1s) by aborting the previous fetch.
5.3 [STRM-LOW-02] PGS burn-in saturation: default subtitle strategy for bitmap (PGS/VobSub) tracks becomes CLIENT-side rendering via existing static/pgs-decoder.js + /subtitles/sup endpoint; server burn-in only when explicitly requested (query param) OR non-browser clients (VLC launcher path). On burn-in requests, probe hardware encoders (find existing hw detection in transmuxer; extend if needed) and when none available, set response header X-Evo-BurnWarn: 1 and have the player toast "Software subtitle burn-in may cause buffering on high-bitrate sources."
Commit: "fix(transmux): BS.775 downmix, kill-fast semaphore release, PGS client-side default [STRM-HIGH-01][STRM-HIGH-03][STRM-LOW-02]"

=====================================================================
PHASE 6 — Debrid Connection Pooling (fixes STRM-HIGH-02)
=====================================================================
Problem: core/debrid/proxy.py create_upstream_stream() constructs a fresh httpx.AsyncClient per range chunk and closes it in finally — zero keep-alive reuse, 150–400ms TLS handshake per 2MB chunk, ephemeral-port exhaustion under scrubbing.

Tasks:
6.1 Create a module-level lazy singleton:
      _shared_client = httpx.AsyncClient(
          limits=httpx.Limits(max_keepalive_connections=50, max_connections=200, keepalive_expiry=60.0),
          timeout=httpx.Timeout(connect=15.0, read=None, write=30.0, pool=15.0),
          follow_redirects=True,
      )
    Guard creation with an asyncio.Lock; expose aclose_shared_client() and register it in the FastAPI lifespan/shutdown hook (check main.py pattern).
6.2 In create_upstream_stream(): use _shared_client.build_request/send; in finally close ONLY resp.aclose() — never the client. Preserve per-request headers exactly.
6.3 Keep all SSRF/vetting behavior: route through whatever transport validation core/security.py enforces today (do not bypass proxies/validation for the pooled client).
6.4 Audit other httpx.AsyncClient(...) instantiations across core/ for the same per-request anti-pattern; pool them where they hit hot paths.
Acceptance: test monkeypatching httpx.AsyncClient asserts constructor called once across 10 sequential range requests, and resp closed each time.
Commit: "perf(debrid): shared pooled AsyncClient for range proxying [STRM-HIGH-02]"

=====================================================================
PHASE 7 — Virtual HLS Keyframe Integrity (fixes STRM-HIGH-05)
=====================================================================
Problem: stream_hls_ts_segment slices with -c:v copy at arbitrary 6.000s boundaries. Torrent rips have GOPs of 1–10s; segments starting on P/B frames lack reference keyframes -> Hls.js MEDIA_ERR_DECODE / bufferStallError / pixel smear.

Tasks:
7.1 Build a keyframe index per (info_hash, file_idx): run ffprobe ONCE per source (`ffprobe -select_streams v:0 -show_entries packet=pts_time,flags -of csv` filtered to K-frame flags), persist to data/keyframes/<hash>_<idx>.json. Expose via new daemon-adjacent endpoint GET /api/v1/stream/keyframes?info_hash=&file_idx=.
7.2 generate_hls_manifest(): snap every EXTINF boundary to the nearest ACTUAL keyframe pts (segments become variable-length 4–12s — valid HLS). get_hls_segment/start params then always land on IDR frames; document that segment times come from the manifest, not fixed math.
7.3 Fallback ladder when keyframing is impossible (weird GOPs, interlaced, VFR):
    Option A (preferred default): route browser playback to the existing fragmented-MP4 transmux path (/transmux with #EXT-X-MAP init segment) instead of virtual TS slicing — keyframe-aligned fragments with zero slicing errors.
    Option B: forced-keyframe transcode muxer with -force_key_frames expr:gte(t,n_forced*6) -g 180 -keyint_min 180 only when HW encoder available.
    Keep legacy fixed-slice TS mode behind env EVO_HLS_LEGACY_SLICE=1 for compatibility.
7.4 Update Phase 1 cache keys to include the keyframe-index version so stale misaligned segments invalidate automatically.
Acceptance: test asserting generated playlist segment starts are all members of the fake keyframe index; decode-error regression note in docs.
Commit: "fix(hls): keyframe-aligned segment boundaries + fMP4 preference [STRM-HIGH-05]"

=====================================================================
PHASE 8 — Engine Hygiene: Store Footprint, Peer Persistence, Resume Cache (fixes STRM-LOW-01)
=====================================================================
8.1 [STRM-LOW-01] In streamer/torrent_engine.js addTorrent torrentOpts: lower storeCacheSlots: 500 -> 128 (or env EVO_STORE_CACHE_SLOTS, clamp 16–256). Comment why: 500 slots x 4MB pieces = 2GB V8 heap risk in Docker. Rely on OS filesystem cache for older chunks.
8.2 Disk-resident resume: cleanup paths (from Phase 0.2) keep pieces on disk in CACHE_DIR up to EVO_KEEP_CACHE_MB budget with LRU purge beyond; reopening a purged-but-cached torrent must report buffer_pct > 0 instantly (verify WebTorrent store reuse across daemon restarts; audit storeCache interaction).
8.3 Persist known-good peer lists per info_hash to .stream_cache/peers.json; on add, seed torrent.addPeer() from saved peers to skip cold discovery (respect private torrents).
8.4 Tracker health scoring: EWMA rank trackers by observed peer-yield; sort announce order dynamically; persist alongside peers.json.
Acceptance: reopening a cached torrent yields immediate buffer; OOM-risk constant gone (grep test for storeCacheSlots value).
Commit: "feat(engine): bounded piece cache, peer persistence, disk-resident resume [STRM-LOW-01]"

=====================================================================
PHASE 9 — Ports, Process Management & Config Wiring (fixes STRM-MED-03, STRM-LOW-03)
=====================================================================
9.1 [STRM-LOW-03] Wire config.py Settings through runtime:
    - core/transmuxer.py: _FFMPEG_SEMAPHORE sized from settings.MAX_CONCURRENT_FFMPEG (combine with Phase 5.2a formula).
    - core/torrent_streamer.py: STREAM_PORT/TORRENT_PORT/DHT_PORT read from settings (add STREAM_PORT to config.py Settings if missing; default 8889). Pass to daemon child via env vars (DAEMON_PORT, TORRENT_PORT, DHT_PORT); streamer/*.js must consume process.env with current values as defaults.
    - Grep for any remaining hardcoded 8889/50000/50001 in Python/JS/docs; centralize.
9.2 [STRM-MED-03] Safe stale-daemon handling in kill_stale_daemon():
    a) NEVER kill blindly. Identify candidate PID via netstat/lsof, then verify identity before terminating:
       - Windows: tasklist /FI "PID eq <pid>" must show node.exe AND (wmic/Get-CimInstance) command line contains the daemon script path (streamer/server.js).
       - POSIX: readlink /proc/<pid>/cmdline equivalent (ps -p <pid> -o args=) checked for the daemon entrypoint.
    b) Prefer non-destructive takeover: first try GET http://127.0.0.1:<port>/health — if a HEALTHY EvoScrapper daemon already answers, reuse it instead of killing anything.
    c) Dynamic port fallback: if 8889 occupied by foreign process, probe 8890–8899, bind successfully, and propagate chosen port to both the Python client (module-level resolution + stored in data/daemon_port.json) and subsequent callers. Handle TIME_WAIT by retrying bind with small backoff before falling to next port.
Acceptance: test with mocked ps/netstat output asserts foreign-PID is skipped and EvoScrapper-node-PID is killed; port-fallback test binds 8890 when 8889 taken.
Commit: "fix(daemon): validated process takeover, dynamic ports, config wiring [STRM-MED-03][STRM-LOW-03]"

=====================================================================
PHASE 10 — Activate or Retire the WebRTC Mesh (fixes STRM-MED-04)
=====================================================================
Problem: static/p2p-player.js implements a full WebRTC P2P Media Loader mesh, but static/app.js playStreamInBrowser() sets video.src directly, bypassing window.evoP2PPlayer.setupPlayer() — the mesh is dead code; browser viewers share zero bandwidth.

Tasks:
10.1 Wire-up path: add player setting "Browser P2P mesh" (default OFF, localStorage-backed like other settings). When ON and source is HLS-capable, playStreamInBrowser() must instantiate the p2p-media-loader engine via window.evoP2PPlayer.setupPlayer({ hlsUrl, segmentUrlBase }) and attach to the video element instead of raw video.src; when OFF, current behavior unchanged.
10.2 Configure loader segment map to match Phase 7 variable durations; enable memory+indexedDB caching so revisits pull from local mesh/cache instantly; prioritize segments within forwardBufferGoalSeconds.
10.3 Safety rails: mesh engine must gracefully fall back to plain video.src on setup failure or ICE timeout (10s) — playback reliability beats sharing. Log fallback reason to telemetry ring (Phase 11).
10.4 If any blocker makes wiring unsafe (e.g. p2p-player.js API drift), then DELETE the dead path cleanly: remove unused exports, document in DOCS.md that browser-native playback relies on the local Node.js daemon, and leave a tracked TODO. Choose ONE outcome; do not leave dead code silently.
10.5 Next-episode prewarm: on episode selection, fire-and-forget /warm for the NEXT episode (concurrency 1) using Phase 2's /window at offset 0.
Acceptance: grep/behavioral test asserting setupPlayer referenced from playStreamInBrowser under the flag, or the documented removal.
Commit: "feat(player): opt-in WebRTC mesh wiring with safe fallback [STRM-MED-04]"

=====================================================================
PHASE 11 — Observability & Docs
=====================================================================
11.1 Extend GET /api/v1/stream/diagnostics with: HLS cache hit ratio, avg first-byte latency, watchdog state history (ring buffer 100 samples), current window sizes, ffmpeg permit usage, debrid pooled-client stats (open/idle connections), mesh on/off + fallback reasons.
11.2 Update DOCS.md + APIDOCS.md for: new endpoints (/file-info, /window, /keyframes, changed /hls/segment semantics, X-Evo-Buffer-State, X-Evo-Seek-Keyframe, X-Evo-BurnWarn headers) and env vars (EVO_HLS_CACHE_MAX_MB, EVO_HLS_MAX_CONCURRENCY, EVO_DIRECT_RANGE, EVO_KEEP_CACHE_MB, EVO_STORE_CACHE_SLOTS, EVO_HLS_LEGACY_SLICE, STREAM_PORT).
11.3 Update .env.example accordingly; add a "Streaming Tuning Guide" section mapping each knob to its flaw ID.
11.4 Add a FLAW_FIX_MATRIX table (Flaw ID -> Phase -> files -> test) at the top of the changelog/docs.
Commit: "docs: streaming overhaul endpoints, env vars, flaw-fix matrix"

=====================================================================
GLOBAL RULES
=====================================================================
- Never block the event loop: all disk/network in FastAPI stays async; FFmpeg via create_subprocess_exec.
- Preserve SSRF protections in core/security.py — any new URL fetching must go through the vetted client.
- All new endpoints follow existing router conventions (models/ Pydantic v2 response models, versioned prefix /api/v1).
- Keep public API backward compatible; new behavior behind env flags with safe defaults.
- Every flaw ID [STRM-*] above must have at least one named test proving the fix; list unmapped flaws as blockers, not assumptions.
- Final step: run full `pytest tests/ -q`, then summarize per-phase results, per-flaw-ID status table, and any flaky tests observed.