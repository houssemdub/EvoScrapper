# Hardening and Seed-Loading Plan

## Scope and execution

Interpret the requested four items as the four recommended work areas from the
project assessment. Work on one isolated component per turn, with failing
regression tests before implementation. Do not replace the existing UI SPEC.md,
rewrite large files, or alter the user's pre-existing .gitignore changes.

### 1. Security

- [x] **Outbound HTTP requests.** Validate public HTTP(S) targets, every
  redirect, and all returned IPv4/IPv6 DNS addresses. Reject loopback, private,
  link-local, reserved, multicast, and non-global addresses. Applied to external
  addons, subtitle downloads/conversion, and Debrid range streaming. External
  addon-client endpoints require the configured API key; native Stremio
  manifest/stream endpoints stay compatible and public.
- [x] **Internal daemon and mesh control plane.** The Node daemon binds
  loopback by default, validates the `Host` header, emits no wildcard CORS, and
  requires a shared secret on every route except authenticated health probing.
  `/stream` accepts a short-lived HMAC query so media tools need not carry the
  long-lived secret. HTTP CometNet announcements require the API key. Streamer
  process identity is verified against the repository's `server.js` path before
  termination.
- [x] **Browser-compatible authentication.** `POST /api/v1/auth/session`
  exchanges the API key for an HttpOnly, SameSite=Lax cookie with a 12-hour TTL.
  `verify_api_key` accepts the header or that cookie, so fetch, EventSource,
  `<video>`, and HLS requests authenticate without putting the long-lived key in
  playback URLs. The UI bootstraps the session before loading data.
- [ ] **Residual outbound risk.** The URL guard validates DNS answers before the
  request but does not pin the connection's resolved address. A hostile resolver
  could still rebind between validation and connection. Rebinding-resistant
  transport/egress enforcement remains necessary before unrestricted public
  deployment.

### 2. Reliable startup

- [x] Declare missing runtime/test dependencies (`aiofiles`, `psutil`) and keep
  the requirements list aligned with runtime imports.
- [x] Make `.env.example` and Compose list settings accept JSON arrays,
  comma-separated values, `*`, or blank, with startup tests.
- [x] Add a narrowly scoped `.dockerignore` excluding secrets, local
  `node_modules`, Git metadata, tests, logs, and runtime caches. Docker no longer
  publishes the internal daemon port.

### 3. Playback and seed-loading behavior

- [x] HLS: reject non-positive/non-finite durations, include the final partial
  segment, and ensure each advertised format matches the actual segment bytes.
  Initialization contains only `ftyp+moov`; media strips init boxes and `mfra`
  and rewrites `tfdt` to the HLS timeline. Verified with generated local FFmpeg
  fixtures.
- [x] Reader lifecycle: release each reader exactly once on end/close/error;
  never reclaim a session with another active reader. Maintain independent
  reader cursors so concurrent reads do not overwrite one another's windows.
- [x] Piece scheduling: bounded priority-3 urgent, priority-2 horizon, and
  priority-1 retention ranges per reader, separated by one-piece gaps so
  WebTorrent cannot merge them. Preserve container headers and file-end index
  pieces. Contract the horizon under starvation; expand only with verified
  contiguous data.
- [x] Peer recovery: bounded stalled-request reassignment via `wire.cancel()`
  after verifying the installed API, limited to two urgent requests per
  8-second cooldown and only when another unchoked wire has the piece. No
  indiscriminate choking, tracker flooding, or connection-count inflation.
- [x] Measure time to metadata, first byte, and contiguous seconds ahead with
  deterministic local seed/reader fixtures. The measurement reports
  `metadata_ms`, `first_byte_ms`, `seconds_ahead`, and bounded `scan_pieces`
  without public trackers or copyrighted content.

### 4. Verification and incremental refactoring

- [x] Prefer execution-level tests over source-string assertions. Scheduler and
  control-plane behavior is covered by Node harnesses and Python integration
  tests; focused suites run after each diff, and the complete regression suite
  runs before completion.
- [x] Extract only the scheduler/authentication helpers needed for the preceding
  contracts; unrelated UI restructuring and database migration remain deferred.

## Locked contract: current outbound-request component

- Input: a URL string, an existing pooled HTTPX client, optional request headers
  and timeout, and whether the final response should remain streaming.
- Output: the final HTTPX response; preserve Range, upstream status, and bytes.
- Only GET requests to public HTTP(S) targets are supported. Trim outer whitespace;
  reject malformed hosts/ports, URL credentials, and control characters with 400.
  Reject non-public addresses with 403 before sending that request.
- Disable automatic redirects per request. Follow at most five validated redirects;
  close each intermediate response without reading its body. Reject excess hops
  with 400 and do not forward credential headers to a different origin.
- DNS resolution must not block the async request loop. A buffered final response
  is closed after reading; a streaming final response remains caller-owned and
  must close on completion/cancellation.
- External addon endpoints reject a missing/incorrect configured API key with
  403 before any outbound request. With no API key configured, retain the existing
  local-use authentication policy, but still enforce the URL guard.
- Scope limitation: DNS checking and redirect validation are not connection-level
  DNS pinning. Rebinding-resistant transport/egress enforcement remains necessary
  before declaring the application safe for unrestricted public deployment.
- Verification uses MockTransport/ASGITransport and deterministic DNS fixtures;
  no private service or public tracker is contacted.
