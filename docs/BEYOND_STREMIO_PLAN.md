# Beyond Stremio — The Collective Streaming Engine Plan

> Goal: make EvoScrapper not just match Stremio, but leapfrog it with capabilities
> Stremio's architecture (centralized catalog + single-node engine + addon resolver)
> structurally cannot offer. Generated 2026-10-26 after comparative analysis of
> `stremio-core` (Rust decision layer, streaming-server settings/statistics models)
> and `torrentio-scraper` (ranking + debrid orchestration).

---

## Vision

Stremio's ceiling is **a very good single-node engine**: one user, one machine,
one swarm at a time, learning nothing between sessions. Torrentio's ceiling is
**a very good central indexer**: fast, but centralized and per-user.

EvoScrapper's ceiling is **a collectively intelligent engine**: every viewer
makes the next viewer's playback faster. We already own the three ingredients
nobody else has combined:

1. **CometNet** — Ed25519-signed decentralized gossip mesh (already announces
   debrid cache hits, already has relay transport).
2. **Full-stack control** — one process owns resolution, scheduling,
   transmuxing, and serving. Stremio addons pick *one* stream and hand it off;
   they cannot race sources, switch mid-playback, or re-rank from telemetry.
3. **A browser WebRTC mesh already wired** (p2pml loader) — viewers can help
   each other directly, which Stremio's web player never does.

Each feature below is tagged: **[PARITY]** (close a gap Stremio has), or
**[NOVEL]** (nothing in Stremio/Torrentio's architecture does this).

---

## Tier 0 — Parity catch-up (small, do first)

| # | Item | Source insight | Effort |
|---|------|----------------|--------|
| T0.1 | Swarm pause/resume hysteresis: when `seconds_ahead` > 90s deselect everything beyond retention and stop `critical()`; resume < 60s | stremio `swarm_paused` | S |
| T0.2 | Torrentio health gate in aggregator: ≥50 results with ≥5 seeders → suppress dead ones; unhealthy swarms cap at 5 results; skip gate when debrid configured | torrentio `sort.js` constants | S |
| T0.3 | Split circuit breakers: availability vs resolve per debrid provider | torrentio `circuitBreaker.js` | S |
| T0.4 | Negative-result TTLs: empty search/cache-check results cached shorter (e.g. 120s vs 900s) | torrentio `cache.js` ttl-as-function | S |
| T0.5 | Optional download shaping: soft limit = 2x measured bitrate, hard = 4x (`EVO_BT_SOFT_LIMIT_MULT`) | stremio `bt_download_speed_soft/hard_limit` | M |
| T0.6 | Per-tracker-source accounting: found/uniq/tries counters per session; periodic cached-peer re-injection | stremio `Statistics.sources` | M |

## Tier 1 — Swarm Intelligence Layer (CometNet 2.0) [NOVEL]

### P1. Collective Seek Forecasting ("crowd-buffering")
- **What**: Gossip anonymous, quantized seek events `(info_hash, bucketed_position)`
  over CometNet. Each node aggregates a seek-heatmap per hash. The scheduler
  pre-warms pieces at statistically-likely seek targets (intro end, post-recap,
  episode midpoint) at priority 1, before any user touches the timeline.
- **Why novel**: Netflix predicts seeks with per-title ML server-side. No P2P
  player learns seek behavior *from other viewers*. Stremio learns nothing.
- **Design**: new `SeekHeatmapStore` (bucketed 30s slots, EWMA decay);
  `cometnet.announce_seek()` alongside `announce_cache()`; engine query
  `topSeekTargets(hash, cursor, k)` → inject priority-1 selections ~120s around
  each target when idle bandwidth exists. All gossip signed; no user IDs; no
  titles — hashes only.
- **Acceptance**: with synthetic gossip of 100 seeks at 42:00, engine pre-selects
  pieces covering 41:30–43:30 without any local seek; heatmap decays after TTL.
- **Effort**: M. **Risk**: cold-start noise → require min N observations before warming.

### P2. Distributed Debrid Coverage Index
- **What**: Extend the existing `announce_cache` gossip into a persistent,
  queryable index: hash → {provider, last_seen}. New nodes (or restarts) consult
  the mesh before probing all 6 providers; `resolve_stream` uses mesh hints to
  order providers, falling back to live probes.
- **Why novel**: Torrentio knows cache status centrally per-user-key; nobody
  shares coverage knowledge *decentrally across users*.
- **Design**: merge gossip into `data/cometnet_cache_index.json` (or SQLite when
  T4.1 lands); TTL 24h; confidence = recency × corroboration count. Privacy:
  hash-level only, no account linkage.
- **Acceptance**: node A announces RD-cached hash; node B's resolve order puts
  RD first without any local API call; stale hints degrade to live probe.
- **Effort**: S–M. **Risk**: wrong hints → wasted resolve → always keep live
  probe as confirmation before streaming.

### P3. Crowd-Sourced Scene Boundaries (intro/recap/credits skip)
- **What**: From the seek-heatmap (P1), derive behaviorally-salient boundaries:
  spikes of "+30s jumps" = intro/recap end; playback abandon cluster = credits
  start. Expose `GET /api/v1/stream/scenes/{hash}` → player renders Skip buttons.
- **Why novel**: Stremio has no skip at all; Netflix uses per-title ML. This is
  zero-AI, purely behavioral, and improves as more people watch.
- **Design**: offline derivation job on the heatmap (peak detection on
  forward-jump deltas); local library contributes own seeks; bootstrap fallback
  = none until N viewers.
- **Acceptance**: synthetic "everyone jumps from 0:50→1:58" produces a Skip
  Intro button spanning that range in the player.
- **Effort**: M. **Depends on**: P1. **Risk**: false boundaries → confidence
  threshold + manual dismiss feedback loop.

## Tier 2 — Playback Pipeline [NOVEL]

### P4. Dual-Source Racing (P2P vs Debrid CDN)
- **What**: On play, if a debrid provider *might* have it cached and swarm
  looks healthy, start BOTH: race first-buffered-byte; winner serves, loser
  becomes a hot backup that transparently takes over if the winner stalls
  (watchdog already detects starvation).
- **Why novel**: Stremio addons must pick exactly one stream and hand off —
  architecture forbids racing. Multi-CDN racing exists server-side (Mux etc.);
  client racing a BitTorrent swarm against a CDN does not exist in any player.
- **Design**: `routers/stream.py` resolve → two candidate internal URLs;
  daemon `/stream` gains `?source=p2p|cdn` parity; player (or `/play` proxy for
  external players) issues parallel HEAD/range requests, first 256KB wins.
  Backup kept warm ≤60s then dropped. Cache the winner per hash for the session.
- **Acceptance**: integration test with mock CDN (fast) vs fake slow swarm →
  CDN wins, P2P connection torn down; reversed latencies → P2P wins; winner
  stalls mid-stream → automatic handover without player error.
- **Effort**: M–L. **Risk**: bandwidth waste → only race when both look viable
  (cached-probability ≥ threshold AND seeds ≥ 3); hard cap race window 3s.

### P5. Cross-Torrent Quality Ladder (ABR across releases)
- **What**: When buffer health stays `starved`/`deficit` for N seconds, resolver
  finds the same content at a lower bitrate, and playback hot-swaps to it at the
  nearest keyframe — the viewer sees a quality dip, never a spinner. Optionally
  upscale back on recovery.
- **Why novel**: every player's ABR switches *renditions of one file*. Switching
  *torrents* mid-playback seamlessly is unexplored territory.
- **Design**: resolver already scores alternates; keyframe caches exist for both
  releases; swap = seek-aligned `/transmux` restart at current time (we already
  do this on seek); player keeps timeline continuity via `X-Content-Duration`.
  V1 constraint: swap only on sustained starvation (not proactive), and only
  between releases sharing the same episode identity.
- **Acceptance**: simulated swarm collapse → ladder swaps within 5s of deficit,
  timeline continuity ±1s, no player reload. **Effort**: L. **Risk**: A/V
  timeline drift across releases → mitigate with container-level probe of both;
  ship behind `EVO_QUALITY_LADDER=true` default off until proven.

### P6. Deep Next-Episode Staging
- **What**: Upgrade next-episode pre-warm from metadata-only to a *bytes* staged
  prefetch: during current episode's last 3 minutes, fetch next episode's first
  60s of media at priority 1 under the speed-shaping budget (T0.5).
- **Why novel**: Stremio pre-buffers within one file; nobody stages the next
  *torrent's* opening bytes during credits.
- **Acceptance**: binge session measurement shows next-episode `first_byte_ms`
  ~0 (all pieces already verified) vs baseline. **Effort**: S–M. **Depends on**: T0.5.

## Tier 3 — Experience [NOVEL unless noted]

### P7. Trick-Play Sprite Previews
- Thumbnails sprite (one FFmpeg pass, cached beside keyframes) + scrubber hover.
  Stremio has no previews. **Effort**: S–M.
### P8. Watch-Together Over CometNet + WebRTC
- Signed party links; play/pause/seek sync events over existing gossip channels;
  media still served locally per viewer (each keeps own best source; P4 helps).
  Jellyfin has SyncPlay, Stremio has nothing — parity with the field, novelty
  for this ecosystem. **Effort**: M.
### P9. Language-Aware Stream Ranking
- Probe data already exposes audio/sub languages; rank releases matching the
  user's audio/sub preference, not just seeds/quality. Nobody cross-references
  subtitle inventory into stream ranking. **Effort**: S–M.
### P10. "Why This Stream?" Panel
- Every stream card exposes its decision breakdown: provider cache state (incl.
  mesh hints from P2), seeds, measured bitrate, codec compatibility, predicted
  time-to-first-frame. Builds trust + debuggability. Stremio shows nothing.
  **Effort**: S.

## Tier 4 — Foundation (enablers, not visible)

| # | Item | Why it gates |
|---|------|--------------|
| T4.1 | SQLite (SQLModel async) for library/history/heatmaps/indexes | P1–P3 data volume; multi-user |
| T4.2 | `app.js` (8.9k lines) → ES modules | Tier 3 player features |
| T4.3 | DNS-rebinding-proof outbound transport | any public deployment |
| T4.4 | Multi-user profiles + PINs | T4.1; household use |
| T4.5 | Jackett/Prowlarr Torznab provider | catalog breadth [PARITY with power users] |
| T4.6 | Stremio `/subtitles` + `/configure` endpoints | Stremio-ecosystem distribution [PARITY] |

---

## Execution order & release mapping

```
v2.3.0  T0.1–T0.4 (parity sprint)                      — all S, ~1 week
v2.4.0  P2 + T0.5/T0.6 + P10                           — mesh value, low risk
v2.4.x  P1 + P6 (needs T0.5 shaping)                   — crowd-buffering core
v2.5.0  P4 (racing) + P7 (sprites) + P9                — the "fastest player" release
v2.6.0  P3 (scene skip, needs P1 data) + P8 (parties)
v2.7.0  P5 (quality ladder, default-off flag) + T4.5/T4.6
ongoing T4.1–T4.4 land opportunistically before the release that needs them
```

Dependency chain: P1 → P3; T0.5 → P6; T4.1 → (P1 at scale, P2 at scale, T4.4);
P4 independent; P5 last and flagged.

## Success metrics (how we know we passed Stremio)

1. **Time-to-first-frame** p50/p95 on 4K HEVC, pre-warmed vs cold (seed_reader_measure harness extended to full pipeline).
2. **Seek-to-frame latency** p95 (target < 1.5s on cached ranges).
3. **Stall rate**: minutes played / buffer events (watchdog history already records this).
4. **Mesh hit rate**: % of plays where P2 hint or P1 pre-warm measurably reduced first-byte or seek latency.
5. **Feature delta**: count of [NOVEL] features shipped with tests — the number Stremio cannot match without re-architecting.

## Non-goals / explicit risks

- No content curation or hosting — we remain an engine.
- Gossip privacy: hashes and quantized positions only; no IPs, accounts, or titles in announcements; all messages Ed25519-signed (already enforced).
- P5 stays opt-in until timeline-drift evidence across 20+ real release pairs says otherwise.
- Windows Defender exclusion of cache dirs remains the single biggest free win on the dev machine; document it in README ops section.
