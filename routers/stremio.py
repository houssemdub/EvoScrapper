"""
routers/stremio.py — Stremio Addon Ecosystem & Native Addon Server
Provides full compliance with the Stremio Addon Protocol v3:
- /manifest.json (and /stremio/manifest.json)
- /stream/{type}/{item_id}.json (and /stremio/stream/{type}/{item_id}.json)
Also allows querying external community Stremio addons via /api/v1/addons/*.
"""

from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse

from core.media_meta import fetch_media_details
from core.security import verify_api_key
from core.stream_resolver import resolve_streams
from core.stremio_addon import fetch_addon_manifest, fetch_addon_streams

router = APIRouter(tags=["Stremio Addon Engine"])


# ==============================================================================
# Native Stremio Addon V3 Server Endpoints
# ==============================================================================

@router.get("/manifest.json")
@router.get("/stremio/manifest.json")
async def get_stremio_manifest() -> Dict[str, Any]:
    """
    Official Stremio Addon v3 Manifest.
    Allows EvoScrapper to be installed directly into official Stremio apps on
    Android TV, FireStick, Desktop, and Web as a custom streaming addon.
    """
    return {
        "id": "org.evoscrapper.addon",
        "version": "3.0.0",
        "name": "EvoScrapper Streams",
        "description": "Decentralized Multi-Indexer Torrent & 6-Provider Multi-Debrid Streaming Gateway",
        "resources": ["stream", "subtitles"],
        "types": ["movie", "series", "anime"],
        "catalogs": [],
        "idPrefixes": ["tt", "kitsu:"],
        "background": "https://images.metahub.space/background/medium/tt1375666/img",
        "logo": "/static/logo.png",
        "behaviorHints": {
            "configurable": True,
            "configurationRequired": False,
        },
    }


@router.get("/configure", response_class=HTMLResponse)
@router.get("/stremio/configure", response_class=HTMLResponse)
async def get_stremio_configure(request: Request) -> str:
    """
    T4.6: Responsive web-based configuration page for Stremio addon installation.
    Allows users to set stream preferences, preview manifest, and 1-click install.
    """
    html_content = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Configure EvoScrapper — Stremio Addon</title>
  <link rel="icon" type="image/x-icon" href="/static/favicon.ico">
  <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
  <style>
    :root {
      --bg: #0b0f19;
      --card-bg: rgba(18, 24, 38, 0.85);
      --accent: #6366f1;
      --accent-hover: #4f46e5;
      --cyan: #06b6d4;
      --text: #f3f4f6;
      --text-dim: #9ca3af;
      --border: rgba(255, 255, 255, 0.08);
      --border-focus: rgba(99, 102, 241, 0.5);
    }
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body {
      background: radial-gradient(circle at top, #1e1b4b 0%, var(--bg) 70%);
      color: var(--text);
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
      min-height: 100vh;
      display: flex;
      align-items: center;
      justify-content: center;
      padding: 1.5rem;
    }
    .config-card {
      background: var(--card-bg);
      backdrop-filter: blur(16px);
      border: 1px solid var(--border);
      border-radius: 1rem;
      max-width: 560px;
      width: 100%;
      padding: 2.25rem;
      box-shadow: 0 20px 40px -15px rgba(0, 0, 0, 0.7), 0 0 30px rgba(99, 102, 241, 0.15);
    }
    .header {
      display: flex;
      align-items: center;
      gap: 1rem;
      margin-bottom: 1.75rem;
      border-bottom: 1px solid var(--border);
      padding-bottom: 1.25rem;
    }
    .logo {
      width: 48px;
      height: 48px;
      border-radius: 0.75rem;
      background: linear-gradient(135deg, var(--accent), var(--cyan));
      display: flex;
      align-items: center;
      justify-content: center;
      font-size: 1.5rem;
      box-shadow: 0 4px 15px rgba(99, 102, 241, 0.4);
    }
    h1 { font-size: 1.4rem; font-weight: 700; letter-spacing: -0.02em; }
    p.subtitle { font-size: 0.85rem; color: var(--text-dim); margin-top: 0.2rem; }
    .form-group { margin-bottom: 1.25rem; }
    label { display: block; font-size: 0.825rem; font-weight: 600; text-transform: uppercase; letter-spacing: 0.05em; color: var(--text-dim); margin-bottom: 0.5rem; }
    select, input[type="text"] {
      width: 100%;
      background: rgba(10, 14, 23, 0.75);
      border: 1px solid var(--border);
      border-radius: 0.5rem;
      color: var(--text);
      padding: 0.75rem 1rem;
      font-size: 0.95rem;
      outline: none;
      transition: border-color 0.2s, box-shadow 0.2s;
    }
    select:focus, input[type="text"]:focus {
      border-color: var(--border-focus);
      box-shadow: 0 0 0 3px rgba(99, 102, 241, 0.2);
    }
    .features-list {
      background: rgba(0, 0, 0, 0.25);
      border-radius: 0.5rem;
      padding: 0.85rem 1rem;
      margin-bottom: 1.5rem;
      border: 1px dashed var(--border);
    }
    .feature-item {
      display: flex;
      align-items: center;
      gap: 0.6rem;
      font-size: 0.8rem;
      color: var(--text-dim);
      margin-bottom: 0.35rem;
    }
    .feature-item:last-child { margin-bottom: 0; }
    .feature-item i { color: #10b981; font-size: 0.85rem; }
    .btn-group { display: flex; flex-direction: column; gap: 0.75rem; margin-top: 1.5rem; }
    .btn {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      gap: 0.5rem;
      padding: 0.85rem 1.25rem;
      font-size: 0.95rem;
      font-weight: 600;
      border-radius: 0.5rem;
      cursor: pointer;
      text-decoration: none;
      transition: all 0.2s ease;
      border: none;
    }
    .btn-primary {
      background: linear-gradient(135deg, var(--accent), #4f46e5);
      color: #fff;
      box-shadow: 0 4px 15px rgba(79, 70, 229, 0.4);
    }
    .btn-primary:hover {
      background: linear-gradient(135deg, #4f46e5, #4338ca);
      transform: translateY(-1px);
    }
    .btn-secondary {
      background: rgba(255, 255, 255, 0.05);
      color: var(--text);
      border: 1px solid var(--border);
    }
    .btn-secondary:hover { background: rgba(255, 255, 255, 0.1); }
    .status-badge {
      display: inline-flex;
      align-items: center;
      gap: 0.4rem;
      font-size: 0.75rem;
      color: #10b981;
      background: rgba(16, 185, 129, 0.1);
      padding: 0.25rem 0.6rem;
      border-radius: 1rem;
      margin-top: 0.5rem;
    }
    .status-dot { width: 6px; height: 6px; border-radius: 50%; background: #10b981; }
  </style>
</head>
<body>
  <div class="config-card">
    <div class="header">
      <div class="logo">⚡</div>
      <div>
        <h1>EvoScrapper Addon</h1>
        <p class="subtitle">Decentralized P2P Swarm & 6-Provider Multi-Debrid Gateway</p>
        <div class="status-badge"><span class="status-dot"></span> Ready for Stremio v3</div>
      </div>
    </div>

    <div class="form-group">
      <label for="pref-lang">Preferred Audio/Subtitle Language</label>
      <select id="pref-lang">
        <option value="all" selected>All Languages (Ranked by quality & seeds)</option>
        <option value="eng">English (eng)</option>
        <option value="fre">French (fre)</option>
        <option value="ger">German (ger)</option>
        <option value="spa">Spanish (spa)</option>
        <option value="ita">Italian (ita)</option>
        <option value="jpn">Japanese (jpn)</option>
      </select>
    </div>

    <div class="form-group">
      <label for="max-streams">Max Streams Per Category</label>
      <select id="max-streams">
        <option value="10">Top 10 Streams</option>
        <option value="20" selected>Top 20 Streams (Recommended)</option>
        <option value="40">Top 40 Streams</option>
      </select>
    </div>

    <div class="features-list">
      <div class="feature-item"><i class="fa-solid fa-check"></i> Dual-Source Racing (Instant Debrid CDN vs. High-Seed P2P)</div>
      <div class="feature-item"><i class="fa-solid fa-check"></i> Collective Seek Forecasting & Crowd Skip Support</div>
      <div class="feature-item"><i class="fa-solid fa-check"></i> Automatic Subtitle Aggregator (5 sources)</div>
    </div>

    <div class="btn-group">
      <button class="btn btn-primary" id="btn-install">
        <i class="fa-solid fa-download"></i> Install to Stremio
      </button>
      <button class="btn btn-secondary" id="btn-copy">
        <i class="fa-regular fa-copy"></i> Copy Manifest URL
      </button>
    </div>
  </div>

  <script>
    function getManifestUrl() {
      const origin = window.location.origin;
      return `${origin}/manifest.json`;
    }
    document.getElementById('btn-install').addEventListener('click', () => {
      const manifestUrl = getManifestUrl().replace(/^https?:\\/\\//, '');
      window.location.href = `stremio://${manifestUrl}`;
    });
    document.getElementById('btn-copy').addEventListener('click', () => {
      const url = getManifestUrl();
      navigator.clipboard.writeText(url).then(() => {
        const btn = document.getElementById('btn-copy');
        const orig = btn.innerHTML;
        btn.innerHTML = '<i class="fa-solid fa-check"></i> Copied to Clipboard!';
        setTimeout(() => { btn.innerHTML = orig; }, 2000);
      });
    });
  </script>
</body>
</html>"""
    return html_content


@router.get("/stream/{type}/{item_id}.json")
@router.get("/stremio/stream/{type}/{item_id}.json")
async def get_stremio_stream(type: str, item_id: str) -> Dict[str, List[Dict[str, Any]]]:
    """
    Stremio Stream Resolver endpoint compliant with Stremio Addon v3 specs.
    Handles movies ('tt1375666'), TV series ('tt1528406:1:8'), and anime ('kitsu:1234:1:8').
    """
    # 1. Parse item_id and season/episode
    clean_id = item_id.replace(".json", "")
    season: Optional[int] = None
    episode: Optional[int] = None
    imdb_id: str = clean_id

    if clean_id.startswith("kitsu:"):
        parts = clean_id.split(":")
        if len(parts) >= 4:
            imdb_id = f"{parts[0]}:{parts[1]}"
            try:
                season = int(parts[2])
                episode = int(parts[3])
            except ValueError:
                pass
    elif ":" in clean_id:
        parts = clean_id.split(":")
        imdb_id = parts[0]
        if len(parts) >= 3:
            try:
                season = int(parts[1])
                episode = int(parts[2])
            except ValueError:
                pass

    # 2. Resolve title metadata
    title: Optional[str] = None
    year: Optional[str] = None
    try:
        meta = await fetch_media_details(imdb_id)
        if meta:
            title = meta.title
            year = meta.year
    except Exception:
        pass

    if not title:
        title = imdb_id

    # 3. Resolve streams across all indexers and debrid caches
    media_type = type.lower()
    if media_type not in ("movie", "series", "anime"):
        media_type = "movie"

    res = await resolve_streams(
        title=title,
        imdb_id=imdb_id,
        year=year,
        season=season,
        episode=episode,
        media_type=media_type,
        include_cdn=False,
    )

    # 4. Format into Stremio stream items
    stremio_streams: List[Dict[str, Any]] = []
    for s in res.streams:
        stream_entry: Dict[str, Any] = {
            "name": f"EvoScrapper\n{s.name}",
            "title": f"{s.title}\n💾 {s.size} 👥 {s.seeds} seeds | {s.tracker}",
        }
        if s.stream_url:
            stream_entry["url"] = s.stream_url
        else:
            stream_entry["infoHash"] = s.info_hash
            stream_entry["fileIdx"] = s.file_idx

        stremio_streams.append(stream_entry)

    return {"streams": stremio_streams}


# ==============================================================================
# External Addon Client Endpoints
# ==============================================================================

@router.get("/subtitles/{stype}/{item_id}.json")
@router.get("/stremio/subtitles/{stype}/{item_id}.json")
async def get_stremio_subtitles(
    stype: str,
    item_id: str,
    season: Optional[int] = None,
    episode: Optional[int] = None,
    language: Optional[str] = None,
) -> Dict[str, Any]:
    """
    T4.6 Stremio v3 subtitles resource: serves EvoScrapper's aggregated
    subtitle providers (OpenSubtitles, Gestdown, SubDL, SubSource, YIFY) to
    official Stremio apps.
    """
    clean_id = item_id.split(".")[0]
    import re as _re
    if not _re.match(r"^tt\d+$", clean_id, _re.I):
        return {"subtitles": []}

    from routers.subtitles import search_subtitles
    try:
        response = await search_subtitles(
            query=None,
            imdb_id=clean_id,
            season=season,
            episode=episode,
            language=language,
            info_hash=None,
            provider="all",
            limit=20,
        )
    except Exception:
        return {"subtitles": []}

    subtitles = []
    for sub in getattr(response, "data", []) or []:
        url = getattr(sub, "url", None) or getattr(sub, "download_url", None)
        if not url:
            continue
        subtitles.append({
            "id": str(getattr(sub, "id", "")) or f"evo:{len(subtitles)}",
            "url": url,
            "lang": str(getattr(sub, "language_code", "") or getattr(sub, "language", "") or "eng"),
        })
    return {"subtitles": subtitles}


@router.get("/api/v1/addons/manifest", dependencies=[Depends(verify_api_key)])
async def get_external_addon_manifest(
    url: str = Query(..., description="Stremio addon manifest URL or base URL"),
):
    """
    Fetches and parses a Stremio addon manifest from an external URL.
    """
    try:
        manifest = await fetch_addon_manifest(url)
        return {"success": True, "manifest": manifest}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/api/v1/addons/streams", dependencies=[Depends(verify_api_key)])
async def get_external_addon_streams(
    url: str = Query(..., description="Stremio addon base URL"),
    media_type: str = Query("movie", description="Media type: movie, series, or anime"),
    item_id: str = Query(..., description="IMDb ID e.g. tt15239678 or Kitsu ID"),
    season: Optional[int] = Query(None, description="Season number"),
    episode: Optional[int] = Query(None, description="Episode number"),
):
    """
    Fetches available streams for a movie or TV episode directly from an external Stremio addon.
    """
    streams = await fetch_addon_streams(
        addon_url=url,
        media_type=media_type,
        item_id=item_id,
        season=season,
        episode=episode,
    )
    return {
        "success": True,
        "addon_url": url,
        "total": len(streams),
        "streams": streams,
    }
