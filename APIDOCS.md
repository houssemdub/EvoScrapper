# EvoScrapper REST API Documentation (v2.0.0)

EvoScrapper exposes a high-performance REST and Server-Sent Events (SSE) API for torrent indexing, subtitle extraction, media discovery, debrid unrestriction, and sequential P2P streaming.

- **Base URL**: `http://localhost:8009` (default)
- **Interactive Swagger UI**: `http://localhost:8009/docs`
- **Interactive ReDoc**: `http://localhost:8009/redoc`
- **API Catalog Manifest**: `GET /api`

---

## 1. Authentication

When `API_KEY` is configured in the server environment, all protected endpoints require authentication via the `x-api-key` HTTP header (or `?api_key=` query parameter):

```bash
curl -H "x-api-key: your_secret_key" "http://localhost:8009/api/v1/torrents/search?query=Dune"
```

If authentication fails, the server responds with:
```json
{
  "detail": "Invalid or missing API Key"
}
```

---

## 2. API Endpoints

### 2.1. Torrents Engine (`/api/v1/torrents`)

#### `GET /api/v1/torrents/search`
Queries specific indexers or all default trackers with pagination.

**Query Parameters:**
| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `query` | `string` | **Yes** | - | Movie title, TV show, anime, or search term |
| `providers` | `string` | No | `all` | Comma-separated list (`yts,nyaa,1337x,piratebay,eztv`) |
| `limit` | `int` | No | `50` | Maximum results to return per provider |
| `category` | `string` | No | `None` | Filter by category (`movies`, `tv`, `anime`, `games`, `apps`) |
| `sort_by` | `string` | No | `seeds` | Sort field (`seeds`, `size`, `date`) |

**Example Request:**
```bash
curl "http://localhost:8009/api/v1/torrents/search?query=Inception&limit=10"
```

**Example Response (200 OK):**
```json
{
  "query": "Inception",
  "total_results": 24,
  "providers_queried": ["yts", "piratebay", "1337x"],
  "items": [
    {
      "id": "c1205d5e0e64cc0aab4f7e60cfb669e4b477bc4c",
      "title": "Inception (2010) [1080p] [YTS.MX]",
      "info_hash": "c1205d5e0e64cc0aab4f7e60cfb669e4b477bc4c",
      "magnet_uri": "magnet:?xt=urn:btih:c1205d5e0e64cc0aab4f7e60cfb669e4b477bc4c&dn=Inception",
      "size_bytes": 1825361100,
      "size_formatted": "1.70 GB",
      "seeders": 450,
      "leechers": 35,
      "category": "movies",
      "uploader": "YTS",
      "provider": "yts",
      "sources": ["yts"],
      "details_url": "https://yts.mx/movies/inception-2010",
      "metadata": {
        "resolution": "1080p",
        "quality": "BluRay",
        "codec": "x264",
        "audio": "AAC",
        "channels": "2.0",
        "year": 2010
      }
    }
  ]
}
```

---

#### `GET /api/v1/torrents/combo`
Aggregates, deduplicates duplicate releases across trackers by canonical SHA-1 `info_hash`, sums aggregate peer seeders, and ranks items using the EvoScrapper quality score.

```bash
curl "http://localhost:8009/api/v1/torrents/combo?query=Interstellar"
```

---

#### `GET /api/v1/torrents/stream`
Server-Sent Events (SSE) real-time streaming endpoint. Streams batches of torrent results incrementally as each upstream tracker responds, eliminating UI latency.

```bash
curl -N "http://localhost:8009/api/v1/torrents/stream?query=Oppenheimer"
```

---

#### `GET /api/v1/torrents/trending`
Retrieves trending torrents from supported indexers.

**Query Parameters:**
- `category` (`string`, optional): `movies`, `tv`, `anime`
- `limit` (`int`, optional): Default `50`

---

### 2.2. Stream & Video Transmuxing (`/api/v1/stream`)

#### `GET /api/v1/stream/resolve`
Resolves ranked stream sources across Debrid caches, verified torrent seeders, and Stremio community addons.

**Query Parameters:**
| Parameter | Type | Required | Description |
|---|---|---|---|
| `title` | `string` | **Yes** | Media title |
| `imdb_id` | `string` | No | IMDb identifier (e.g. `tt1375666`) |
| `season` | `int` | No | TV season number (e.g. `1`) |
| `episode` | `int` | No | Episode number (e.g. `5`) |

**Example Response (200 OK):**
```json
{
  "title": "Breaking Bad S01E01",
  "imdb_id": "tt0903747",
  "season": 1,
  "episode": 1,
  "streams": [
    {
      "name": "⚡ RealDebrid [CACHED]",
      "title": "Breaking.Bad.S01E01.Pilot.1080p.BluRay.x264",
      "info_hash": "a1b2c3d4e5f6...",
      "stream_url": "/api/v1/debrid/proxy/eyJh...token...",
      "provider": "RealDebrid",
      "resolution": "1080p",
      "seeds": 120,
      "score": 380.0,
      "cached": true
    },
    {
      "name": "P2P WebTorrent (1080p)",
      "title": "Breaking Bad S01E01 1080p BluRay",
      "info_hash": "a1b2c3d4e5f6...",
      "stream_url": "/api/v1/stream/play?info_hash=a1b2c3d4e5f6...&file_idx=0",
      "provider": "eztv",
      "resolution": "1080p",
      "seeds": 85,
      "score": 210.0,
      "cached": false
    }
  ]
}
```

---

#### `GET /api/v1/stream/play`
Direct HTTP video stream with HTTP 206 Partial Content byte-range support. Directly streams sequential video pieces from the WebTorrent client daemon.

**Query Parameters:**
- `info_hash` (`string`, required): 40-character hexadecimal torrent infoHash.
- `file_idx` (`int`, optional): Target video file index inside multi-file torrent.

**Header Semantics:**
- Client sends: `Range: bytes=10485760-`
- Server responds: `HTTP/206 Partial Content`, `Accept-Ranges: bytes`, `Content-Range: bytes 10485760-1825361099/1825361100`, `Content-Type: video/mp4` (or `video/x-matroska`).
- Under the hood, the streaming daemon immediately issues `torrent.critical()` for the requested byte offset, hotswapping piece requests across all connected wires.

---

#### `GET /api/v1/stream/status`
Returns real-time telemetry from the P2P streaming daemon for a specific active torrent or global swarm metrics.

**Query Parameters:**
- `info_hash` (`string`, required): 40-character hexadecimal torrent infoHash.

**Example Response (200 OK):**
```json
{
  "info_hash": "c1205d5e0e64cc0aab4f7e60cfb669e4b477bc4c",
  "name": "Inception.2010.1080p.BluRay.x264.mp4",
  "progress": 0.142,
  "download_speed_bps": 8945120,
  "upload_speed_bps": 234100,
  "num_peers": 62,
  "wires_active": 48,
  "p2p_port_tcp": 50000,
  "p2p_port_udp": 50001,
  "buffer_ready": true,
  "buffer_reserve_bytes": 74317824,
  "critical_pieces": [12, 13, 14, 15]
}
```

---

#### `GET /api/v1/stream/hls/manifest.m3u8`
Generates a virtual HLS (HTTP Live Streaming) master manifest for a torrent stream.

---

#### `GET /api/v1/stream/hls/segment`
Zero-latency virtual MPEG-TS segment generator with FFmpeg.
- **Query Parameters**: `info_hash`, `start` (seconds), `duration` (seconds).
- Preserves PTS timestamp continuity via `-output_ts_offset`.

---

#### `POST /api/v1/stream/launch-vlc`
Launches the native desktop VLC media player targeting the stream URL with `--no-one-instance`, custom window title, and tracked child process PID.

**Request Body (JSON):**
```json
{
  "stream_url": "http://127.0.0.1:8889/stream/c1205d5e...",
  "title": "Inception (2010)"
}
```

---

### 2.3. Subtitles Engine ("EvoSubs") (`/api/v1/subtitles`)

#### `GET /api/v1/subtitles/search`
Searches subtitles across multiple providers with tokenized lexical language filtering and disambiguation.

**Query Parameters:**
| Parameter | Type | Required | Description |
|---|---|---|---|
| `query` | `string` | No | Movie or TV series title |
| `imdb_id` | `string` | No | IMDb ID (`tt...`) |
| `season` | `int` | No | Season number |
| `episode` | `int` | No | Episode number |
| `languages` | `string` | No | Comma-separated ISO-639-1/2 codes (e.g. `en,ar,es,fr,de,it,pt,ru,ja,ko,zh,hu,pl,nl,el,ro,cs,sv,no,da,fi,he,hi`). Default: `en` |
| `providers` | `string` | No | Provider list (`opensubtitles,gestdown,subdl,subsource,yifysubs`) |

**Language Disambiguation Behavior:**
- Short language codes (e.g. `ar` for Arabic, `hu` for Hungarian, `es` for Spanish) are matched strictly against word boundaries and ISO code prefixes (`code === a || code.startsWith(a + '-')`).
- Prevents false-positive substring matches (e.g., prevents `Hungarian` or `Bulgarian` from appearing in Arabic search results).
- Multi-language subtitle packs and ZIP archives are automatically inspected via `select_zip_subtitle_member` to extract only matching tracks.

**Example Response (200 OK):**
```json
{
  "query": "Inception",
  "imdb_id": "tt1375666",
  "total_results": 18,
  "items": [
    {
      "id": "sub_1092847",
      "lang": "ar",
      "label": "Arabic (Standard)",
      "release_name": "Inception.2010.1080p.BluRay.x264-YTS",
      "format": "srt",
      "source": "opensubtitles",
      "download_url": "http://localhost:8009/api/v1/subtitles/download?url=https%3A%2F%2F...&lang=ar",
      "vtt_url": "http://localhost:8009/api/v1/subtitles/vtt?url=https%3A%2F%2F...&lang=ar",
      "rating": 9.4
    }
  ]
}
```

---

#### `GET /api/v1/subtitles/by-hash`
Precision hash matching using binary media file checksums (OpenSubtitles 64-bit uint64 and Shooter MD5).

---

#### `GET /api/v1/subtitles/download`
SSRF-protected subtitle download and ZIP extraction proxy.
- Unpacks compressed ZIP archives on-the-fly.
- Matches target language with `select_zip_subtitle_member`.
- Blocks intranet, private RFC1918, and loopback IP addresses.

---

#### `GET /api/v1/subtitles/vtt`
On-the-fly SubRip (`.srt`) to WebVTT (`.vtt`) format conversion with ASS/SSA drawing vector filtering.

---

### 2.4. Unified Media & Discovery (`/api/v1/media` & `/api/v1/discover`)

#### `GET /api/v1/media/lookup`
Fuses torrent search and subtitle synchronization into a single unified JSON payload.

**Query Parameters:**
- `query` (`string`): Search query
- `imdb_id` (`string`, optional): IMDb identifier
- `season` (`int`, optional): Season number
- `episode` (`int`, optional): Episode number
- `languages` (`string`, optional): Subtitle languages

---

#### `GET /api/v1/discover/catalog`
Fetches rich catalogs for `movie`, `series`, or `anime` with high-resolution jacket artwork and IMDb ratings from Cinemeta and Kitsu.

---

#### `GET /api/v1/discover/anime/category`
Fetches paginated anime categories from Kitsu (`trending`, `top-airing`, `popular`, `upcoming`).

---

#### `GET /api/v1/discover/anime/detail`
Fetches complete anime metadata and paginated episode lists (>20 episodes) from Kitsu.

---

### 2.5. Library / Watchlist (`/api/v1/library`)

Watchlist management backed by atomic file persistence (`data/library.json`).

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/v1/library/items` | List all saved library items |
| `POST` | `/api/v1/library/item` | Add or update an item with progress tracking |
| `DELETE` | `/api/v1/library/item/{item_id}` | Remove an item from the library |
| `GET` | `/api/v1/library/export` | Download complete library as JSON |
| `POST` | `/api/v1/library/import` | Import library items from JSON payload |

---

### 2.6. Diagnostics & Health (`/api/v1/health`)

#### `GET /api/v1/health`
System diagnostic health check.

**Example Response (200 OK):**
```json
{
  "status": "healthy",
  "version": "2.0.0",
  "uptime_seconds": 3600.5,
  "memory_rss_mb": 42.8,
  "active_circuit_breakers": 12,
  "open_circuits": []
}
```

#### `GET /api/v1/providers/status`
Operational snapshot of every indexer and subtitle provider with circuit breaker state, failure counts, and rolling average latency.

---

### 2.7. Stremio Addon Protocol v3 (/)

EvoScrapper is a fully compliant Stremio v3 Addon server. It can be installed directly into the Stremio desktop, mobile, and Android TV clients.

#### `GET /manifest.json`
Returns the official Stremio Addon manifest containing addon capabilities, catalogs, and supported resources.

#### `GET /catalog/{type}/{id}.json`
Explores popular and trending catalogs directly within Stremio.

#### `GET /stream/{type}/{id}.json`
Resolves high-speed streaming links for Stremio playback, querying local torrent indexers and enabled Debrid cloud unrestrictors.

---

### 2.8. CometNet P2P Metadata Mesh (/api/v1/cometnet)

Decentralized metadata and torrent discovery mesh inspired by the CometNet gossip protocol.

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/v1/cometnet/status` | Gossip node health, peer count, and cache statistics |
| `GET` | `/api/v1/cometnet/peers` | Active connected mesh peers |
| `POST` | `/api/v1/cometnet/announce` | Announce torrent info_hash and cache status with Ed25519 signature |
| `GET` | `/api/v1/cometnet/lookup/{info_hash}` | Query distributed swarm metadata across connected relay nodes |
