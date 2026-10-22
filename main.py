import os
from contextlib import asynccontextmanager
import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from config import settings
from core.client import http_client
from routers import (
    discover_router,
    health_router,
    library_router,
    media_router,
    stream_router,
    stremio_router,
    subtitles_router,
    torrents_router,
)

STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")


@asynccontextmanager
async def lifespan(app: FastAPI):
    host_display = "localhost" if settings.HOST in ("0.0.0.0", "127.0.0.1") else settings.HOST
    url = f"http://{host_display}:{settings.PORT}"
    print("\n" + "=" * 58, flush=True)
    print("  [+] EvoScrapper v2.0 is live!", flush=True)
    print(f"  -> Web UI:   {url}", flush=True)
    print(f"  -> API Docs: {url}/docs", flush=True)
    print("=" * 58 + "\n", flush=True)

    # Start Node.js WebTorrent streaming micro-daemon
    try:
        from core.torrent_streamer import ensure_streaming_daemon
        daemon_ok = await ensure_streaming_daemon()
        if daemon_ok:
            print("[+] WebTorrent streaming daemon online at http://127.0.0.1:8889", flush=True)
        else:
            print("[!] Warning: Streaming daemon not responding at startup", flush=True)
    except Exception as e:
        print(f"[!] Streaming daemon startup notice: {e}", flush=True)

    yield
    print("[*] EvoScrapper shutting down, closing connection pools...")
    await http_client.close()
    try:
        from core.torrent_streamer import stop_daemon_process
        stop_daemon_process()
    except Exception:
        pass


app = FastAPI(
    title="EvoScrapper API",
    version="2.0.0",
    description="Next-Generation Fault-Tolerant Torrent & Subtitle Scraping Engine",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

# CORS configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount Static Files
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

# Mount API Routers
app.include_router(torrents_router)
app.include_router(subtitles_router)
app.include_router(media_router)
app.include_router(health_router)
app.include_router(discover_router)
app.include_router(stream_router)
app.include_router(stremio_router)
app.include_router(library_router)


@app.get("/", tags=["Web UI"])
async def serve_ui():
    """Serves the modern EvoScrapper Web Application."""
    index_file = os.path.join(STATIC_DIR, "index.html")
    if os.path.exists(index_file):
        return FileResponse(index_file)
    return JSONResponse({"status": "EvoScrapper API running", "docs": "/docs"})


@app.get("/api", tags=["API Manifest"])
async def api_manifest():
    """Returns the REST API endpoint catalog."""
    return JSONResponse(
        {
            "name": "EvoScrapper API",
            "version": "2.0.0",
            "docs": "/docs",
            "redoc": "/redoc",
            "health": "/health",
            "endpoints": {
                "torrents_search": "/api/v1/torrents/search?query={q}",
                "torrents_combo": "/api/v1/torrents/combo?query={q}",
                "torrents_stream": "/api/v1/torrents/stream?query={q}",
                "torrents_trending": "/api/v1/torrents/trending",
                "subtitles_search": "/api/v1/subtitles/search?query={q}&imdb_id={imdb}",
                "subtitles_by_hash": "/api/v1/subtitles/by-hash?info_hash={hash}",
                "subtitles_download": "/api/v1/subtitles/download?url={url}",
                "media_lookup": "/api/v1/media/lookup?query={q}&imdb_id={imdb}",
                "discover_catalog": "/api/v1/discover/catalog?type={movie|series|anime}",
                "discover_meta": "/api/v1/discover/meta/{type}/{imdb_id}",
                "discover_search": "/api/v1/discover/search?query={q}",
                "stream_resolve": "/api/v1/stream/resolve?title={title}&imdb_id={imdb}&season={s}&episode={e}",
                "stream_play": "/api/v1/stream/play?info_hash={hash}&file_idx={idx}",
                "stream_transmux": "/api/v1/stream/transmux?info_hash={hash}&file_idx={idx}",
                "stream_launch_vlc": "/api/v1/stream/launch-vlc",
                "providers_status": "/api/v1/providers/status",
            },
        }
    )


if __name__ == "__main__":
    host_display = "localhost" if settings.HOST in ("0.0.0.0", "127.0.0.1") else settings.HOST
    url = f"http://{host_display}:{settings.PORT}"
    print("\n" + "=" * 58, flush=True)
    print("  [+] EvoScrapper Web Terminal", flush=True)
    print(f"  -> Web UI:   {url}", flush=True)
    print(f"  -> API Docs: {url}/docs", flush=True)
    print("=" * 58 + "\n", flush=True)
    uvicorn.run("main:app", host=settings.HOST, port=settings.PORT, reload=settings.DEBUG)
