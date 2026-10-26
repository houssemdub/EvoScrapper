import os
import time
from contextlib import asynccontextmanager
import uvicorn
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from config import settings
from core.client import http_client
from core.logger import app_logger
from routers import (
    discover_router,
    health_router,
    library_router,
    media_router,
    stream_router,
    stremio_router,
    subtitles_router,
    torrents_router,
    cometnet_router,
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
    if not settings.API_KEY:
        print("  [!] Security Advisory: API_KEY is empty; server running in open mode.", flush=True)
    if settings.DEBRID_PROXY_SECRET == "evoscrapper-debrid-proxy-secret-key":
        print("  [!] Security Advisory: DEBRID_PROXY_SECRET is using default placeholder.", flush=True)
    print("=" * 58 + "\n", flush=True)
    app_logger.info(f"EvoScrapper v2.0 live on http://{host_display}:{settings.PORT}")

    # Start Node.js WebTorrent streaming micro-daemon
    try:
        from core.torrent_streamer import ensure_streaming_daemon
        daemon_ok = await ensure_streaming_daemon()
        if daemon_ok:
            app_logger.info("WebTorrent streaming daemon online at http://127.0.0.1:8889")
            print("[+] WebTorrent streaming daemon online at http://127.0.0.1:8889", flush=True)
        else:
            app_logger.warning("Streaming daemon not responding at startup")
            print("[!] Warning: Streaming daemon not responding at startup", flush=True)
    except Exception as e:
        app_logger.error(f"Streaming daemon startup notice: {e}")
        print(f"[!] Streaming daemon startup notice: {e}", flush=True)

    # Start CometNet P2P mesh networking node
    if getattr(settings, "COMETNET_ENABLED", False):
        try:
            from core.cometnet import get_cometnet_node
            await get_cometnet_node().start()
            app_logger.info("CometNet P2P metadata mesh listener started")
            print("[+] CometNet P2P metadata mesh listener started", flush=True)
        except Exception as e:
            app_logger.error(f"CometNet startup notice: {e}")
            print(f"[!] CometNet startup notice: {e}", flush=True)

    yield
    app_logger.info("EvoScrapper shutting down, closing connection pools...")
    print("[*] EvoScrapper shutting down, closing connection pools...")
    if getattr(settings, "COMETNET_ENABLED", False):
        try:
            from core.cometnet import get_cometnet_node
            await get_cometnet_node().stop()
        except Exception:
            pass

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
origins = settings.ALLOWED_ORIGINS
allow_creds = True
if "*" in origins and len(origins) == 1:
    allow_creds = False

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=allow_creds,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def request_logging_middleware(request: Request, call_next):
    start = time.perf_counter()
    try:
        response = await call_next(request)
        elapsed_ms = (time.perf_counter() - start) * 1000
        app_logger.info(f"{request.method} {request.url.path} - {response.status_code} ({elapsed_ms:.1f}ms)")
        return response
    except Exception as exc:
        elapsed_ms = (time.perf_counter() - start) * 1000
        app_logger.error(f"{request.method} {request.url.path} - Exception: {exc} ({elapsed_ms:.1f}ms)", exc_info=True)
        raise exc

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
app.include_router(cometnet_router)


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
