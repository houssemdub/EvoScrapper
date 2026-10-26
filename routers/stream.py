import asyncio
import aiohttp
import re
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.responses import StreamingResponse

from core.security import verify_api_key

from core.stream_resolver import resolve_streams
from core.torrent_streamer import (
    ensure_streaming_daemon,
    get_daemon_status,
    get_http_session,
    get_internal_stream_url,
    get_torrent_files,
    warm_torrent,
    warm_window,
)
from collections import deque
import os
from core.transmuxer import (
    extract_embedded_subtitle_vtt,
    extract_embedded_sup_stream,
    find_external_player,
    find_vlc,
    launch_external_player_process,
    launch_vlc_process,
    stream_hls_ts_segment,
    stream_transmuxed_video,
)
from core.logger import debrid_logger, streaming_logger
from models.stream import LaunchVlcRequest, StreamResolveResponse

router = APIRouter(prefix="/api/v1/stream", tags=["Streaming"], dependencies=[Depends(verify_api_key)])


@router.get("/resolve", response_model=StreamResolveResponse)
async def resolve_media_streams(
    title: str = Query(..., description="Title of the movie or series"),
    imdb_id: Optional[str] = Query(None, description="IMDb ID e.g. tt15239678"),
    year: Optional[str] = Query(None, description="Release year"),
    season: Optional[int] = Query(None, description="Season number (for series/anime)"),
    episode: Optional[int] = Query(None, description="Episode number (for series/anime)"),
    media_type: str = Query("movie", description="Media type: movie, series, or anime"),
    include_cdn: bool = Query(False, description="Whether to include third-party web CDN embed streams"),
):
    """
    Torrentio-style multi-tracker stream resolver.
    Queries 12+ providers, ranks streams by quality, seeds, audio/HDR tags.
    """
    return await resolve_streams(
        title=title,
        imdb_id=imdb_id,
        year=year,
        season=season,
        episode=episode,
        media_type=media_type.lower(),
        include_cdn=include_cdn,
    )


@router.get("/cdn")
async def get_web_cdn_streams(
    imdb_id: str = Query(..., description="IMDb ID e.g. tt1375666"),
    media_type: str = Query("movie", description="Media type: movie or series"),
    season: Optional[int] = Query(None, description="Season number"),
    episode: Optional[int] = Query(None, description="Episode number"),
):
    """
    Direct Web CDN / Embed video stream resolver for fallback browser playback.
    """
    from scrappers.web_cdn import get_web_cdn_scraper
    scraper = get_web_cdn_scraper()
    return await scraper.get_streams(
        imdb_id=imdb_id,
        media_type=media_type,
        season=season,
        episode=episode,
    )


@router.get("/files")
async def list_torrent_files(
    info_hash: str = Query(..., description="40-char SHA1 info hash or magnet link"),
    magnet: Optional[str] = Query(None, description="Optional original magnet link"),
):
    """
    Inspects torrent metadata to return list of files inside the torrent.
    """
    files = await get_torrent_files(info_hash, magnet=magnet)
    return {"info_hash": info_hash, "files": files, "total": len(files)}


@router.get("/warm")
async def warm_swarm_endpoint(
    info_hash: str = Query(..., description="Torrent info hash"),
    file_idx: int = Query(0, description="File index inside torrent"),
    magnet: Optional[str] = Query(None, description="Original magnet link with trackers"),
    season: Optional[int] = Query(None, description="Season number (for series/anime)"),
    episode: Optional[int] = Query(None, description="Episode number (for series/anime)"),
    buffer_mb: Optional[int] = Query(None, description="Buffer window size in MB"),
):
    """
    Pre-warms the torrent swarm and pre-buffers headers in background for instant playback.
    """
    data = await warm_torrent(info_hash, file_idx=file_idx, magnet=magnet, season=season, episode=episode)
    b_mb = buffer_mb if isinstance(buffer_mb, int) else None
    await warm_window(info_hash, file_idx=file_idx, byte_offset=0, buffer_mb=b_mb)
    if isinstance(data, dict):
        return data
    return {"status": "warming" if data else "failed", "info_hash": info_hash}


@router.get("/play")
async def stream_raw_torrent(
    request: Request,
    info_hash: str = Query(..., description="Torrent info hash"),
    file_idx: int = Query(0, description="File index inside torrent"),
    magnet: Optional[str] = Query(None, description="Original magnet link with trackers"),
    season: Optional[int] = Query(None, description="Season number (for series/anime)"),
    episode: Optional[int] = Query(None, description="Episode number (for series/anime)"),
    duration: Optional[float] = Query(None, description="Known media duration in seconds"),
    buffer_mb: Optional[int] = Query(None, description="Buffer window size in MB"),
):
    """
    Direct HTTP 206 Partial Content video stream proxying the P2P engine.
    Supports seek, range requests, auto-retries, and unthrottled streaming.
    """
    await ensure_streaming_daemon()
    b_mb = buffer_mb if isinstance(buffer_mb, int) else None
    target_url = get_internal_stream_url(info_hash, file_idx, magnet=magnet, season=season, episode=episode, buffer_mb=b_mb)

    # Direct-daemon 307 redirect for localhost clients [Phase 4]
    client_host = request.client.host if request.client else ""
    req_host = request.headers.get("host", "").split(":")[0].lower()
    is_localhost = client_host in ("127.0.0.1", "::1", "localhost", "testclient") or req_host in ("127.0.0.1", "localhost")
    if is_localhost and os.getenv("EVO_DIRECT_RANGE", "false").lower() in ("1", "true", "yes"):
        from fastapi.responses import RedirectResponse
        return RedirectResponse(url=target_url, status_code=307)

    req_headers = {}
    range_header = request.headers.get("Range")
    if range_header:
        req_headers["Range"] = range_header

    session = await get_http_session()

    # Retry loop with exponential backoff if daemon is buffering
    upstream_resp = None
    last_err = None
    for attempt in range(4):
        try:
            upstream_resp = await session.get(
                target_url,
                headers=req_headers,
                timeout=aiohttp.ClientTimeout(total=None, sock_connect=10.0, sock_read=45.0),
            )
            # If 503 (swarm buffering with Retry-After), wait briefly and retry
            if upstream_resp.status == 503 and attempt < 3:
                upstream_resp.close()
                await asyncio.sleep(1.5)
                continue
            break
        except Exception as e:
            last_err = e
            if attempt < 3:
                await ensure_streaming_daemon()
                await asyncio.sleep(1.0)
            else:
                raise HTTPException(status_code=502, detail=f"Failed to connect to streaming engine: {last_err}")

    if not upstream_resp:
        raise HTTPException(status_code=502, detail="Streaming engine unavailable")

    resp_headers = {}
    for key in ("Content-Range", "Accept-Ranges", "Content-Length", "Content-Type", "X-EvoStream-File", "X-EvoStream-Path", "X-EvoStream-Idx", "X-Content-Duration", "Content-Duration"):
        val = upstream_resp.headers.get(key)
        if val:
            resp_headers[key] = val
    if "Accept-Ranges" not in resp_headers:
        resp_headers["Accept-Ranges"] = "bytes"
    resp_headers["X-Evo-Buffer-State"] = "healthy"
    if duration and isinstance(duration, (int, float)) and duration > 0:
        resp_headers["X-Content-Duration"] = str(round(duration, 2))
        resp_headers["Content-Duration"] = str(round(duration, 2))

    async def stream_generator():
        try:
            async for chunk in upstream_resp.content.iter_chunked(262144):
                yield chunk
        except (asyncio.CancelledError, GeneratorExit):
            pass
        finally:
            upstream_resp.close()

    return StreamingResponse(
        stream_generator(),
        status_code=upstream_resp.status,
        headers=resp_headers,
        media_type=resp_headers.get("Content-Type", "video/mp4"),
    )


@router.get("/transmux")
async def stream_transmuxed_torrent(
    info_hash: str = Query(..., description="Torrent info hash"),
    file_idx: int = Query(0, description="File index inside torrent"),
    magnet: Optional[str] = Query(None, description="Original magnet link with trackers"),
    start_time: float = Query(0.0, description="Start playback offset in seconds"),
    duration_slice: Optional[float] = Query(None, description="Optional maximum chunk duration in seconds"),
    transcode_video: bool = Query(False, description="Whether to re-encode video or lossless copy"),
    burn_sub_idx: Optional[int] = Query(None, description="Subtitle stream index to burn into video frames (e.g. Blu-ray PGS)"),
    audio_track: int = Query(0, description="Audio track index (0 = primary audio)"),
    audio_boost: float = Query(1.25, description="Audio volume boost multiplier"),
    season: Optional[int] = Query(None, description="Season number (for series/anime)"),
    episode: Optional[int] = Query(None, description="Episode number (for series/anime)"),
    duration: Optional[float] = Query(None, description="Known media duration in seconds"),
    buffer_mb: Optional[int] = Query(None, description="Buffer window size in MB"),
    channels: Optional[int] = Query(None, description="Audio channels for BS.775 downmix"),
):
    """
    Real-time FFmpeg transmuxing pipeline.
    Losslessly copies video (-c:v copy) or transcodes HEVC to 8-bit H.264 (-c:v libx264 -pix_fmt yuv420p)
    and remuxes audio to 2-channel AAC with dialogue boost and timestamp sync.
    Supports real-time PGS/ASS subtitle burn-in via burn_sub_idx.
    """
    await ensure_streaming_daemon()
    b_mb = buffer_mb if isinstance(buffer_mb, int) else None
    source_url = get_internal_stream_url(info_hash, file_idx, magnet=magnet, season=season, episode=episode, buffer_mb=b_mb)
    snapped_start = start_time
    if start_time and start_time > 0:
        from core.transmuxer import load_cached_keyframes
        cached_kfs = load_cached_keyframes(info_hash, file_idx)
        if cached_kfs:
            preceding = [k for k in cached_kfs if k <= start_time]
            if preceding:
                snapped_start = preceding[-1]

    if snapped_start and snapped_start > 0:
        dur_val = duration if (duration and isinstance(duration, (int, float)) and duration > 0) else None
        asyncio.create_task(
            warm_window(
                info_hash,
                file_idx=file_idx,
                start_time=snapped_start,
                duration=dur_val,
                buffer_mb=b_mb,
            )
        )

    generator = stream_transmuxed_video(
        source_url_or_path=source_url,
        start_seconds=snapped_start,
        duration_seconds=duration_slice,
        transcode_video=transcode_video or (burn_sub_idx is not None),
        burn_sub_idx=burn_sub_idx,
        audio_track=audio_track,
        audio_boost=audio_boost,
        channels=channels if isinstance(channels, int) else None,
    )

    resp_hdrs = {
        "Content-Type": "video/mp4",
        "Accept-Ranges": "none",
        "X-EvoStream-Audio": f"track_{audio_track}_boost_{audio_boost}",
        "X-Evo-Buffer-State": "healthy",
    }
    if burn_sub_idx is not None:
        resp_hdrs["X-Evo-BurnWarn"] = "1"
    if snapped_start and snapped_start > 0:
        resp_hdrs["X-Evo-Seek-Keyframe"] = str(round(snapped_start, 3))
    if duration and isinstance(duration, (int, float)) and duration > 0:
        resp_hdrs["X-Content-Duration"] = str(round(duration, 2))
        resp_hdrs["Content-Duration"] = str(round(duration, 2))

    return StreamingResponse(
        generator,
        status_code=200,
        media_type="video/mp4",
        headers=resp_hdrs,
    )


@router.get("/probe")
async def probe_stream_metadata(
    info_hash: str = Query(..., description="Torrent info hash"),
    file_idx: int = Query(0, description="File index inside torrent"),
    magnet: Optional[str] = Query(None, description="Magnet link"),
    season: Optional[int] = Query(None, description="Season number"),
    episode: Optional[int] = Query(None, description="Episode number"),
):
    """
    Rapidly probes the video stream using ffprobe to detect total duration,
    video/audio codecs, audio tracks (languages/titles), and embedded subtitles.
    Enables full-duration timeline rendering in the browser player.
    """
    await ensure_streaming_daemon()
    source_url = get_internal_stream_url(info_hash, file_idx, magnet=magnet, season=season, episode=episode)
    from core.transmuxer import probe_media_stream
    return await probe_media_stream(source_url)


@router.post("/launch-vlc")
async def launch_vlc_player(req: LaunchVlcRequest, request: Request):
    """
    Launches native desktop VLC media player with Qt GUI interface on the host machine.
    """
    vlc_path = find_vlc()
    if not vlc_path:
        raise HTTPException(
            status_code=404,
            detail="VLC media player executable not found on host machine. Please ensure VLC is installed.",
        )

    # Ensure daemon is up and pre-warm swarm
    await ensure_streaming_daemon()
    if req.info_hash:
        try:
            await asyncio.wait_for(
                warm_torrent(req.info_hash, req.file_idx, req.magnet, season=req.season, episode=req.episode),
                timeout=3.0,
            )
        except Exception:
            pass

    if req.info_hash:
        target_url = get_internal_stream_url(req.info_hash, req.file_idx, magnet=req.magnet, season=req.season, episode=req.episode)
    elif req.stream_url:
        target_url = req.stream_url
    else:
        raise HTTPException(status_code=400, detail="Must provide either stream_url or info_hash")

    success = launch_vlc_process(target_url, title=req.title)
    if not success:
        raise HTTPException(status_code=500, detail="Failed to launch VLC process")

    return {
        "success": True,
        "message": "VLC Media Player launched successfully",
        "vlc_path": vlc_path,
        "stream_url": target_url,
    }


@router.post("/launch-external")
async def launch_external_player(req: LaunchVlcRequest, request: Request):
    """
    Launches external desktop player (VLC, MPV, MPC-HC, PotPlayer) with Qt/Native GUI.
    """
    player = (req.player or "vlc").lower()
    player_bin = find_external_player(player)
    if not player_bin:
        raise HTTPException(
            status_code=404,
            detail=f"{player.upper()} media player executable not found on host machine. Please ensure it is installed.",
        )

    await ensure_streaming_daemon()
    if req.info_hash:
        try:
            await asyncio.wait_for(
                warm_torrent(req.info_hash, req.file_idx, req.magnet, season=req.season, episode=req.episode),
                timeout=3.0,
            )
        except Exception:
            pass

    if req.info_hash:
        target_url = get_internal_stream_url(req.info_hash, req.file_idx, magnet=req.magnet, season=req.season, episode=req.episode)
    elif req.stream_url:
        target_url = req.stream_url
    else:
        raise HTTPException(status_code=400, detail="Must provide either stream_url or info_hash")

    success = launch_external_player_process(player, target_url, title=req.title or "EvoStream")
    if not success:
        raise HTTPException(status_code=500, detail=f"Failed to launch {player.upper()} process")

    return {
        "success": True,
        "message": f"{player.upper()} launched successfully",
        "player": player,
        "executable": player_bin,
        "stream_url": target_url,
    }


def _find_cached_media_path(info_hash: Optional[str] = None, episode: Optional[int] = None) -> Optional[str]:
    """
    Locates cached video files strictly scoped by torrent info_hash and target episode.
    Prevents cross-contamination between different series and movies.
    """
    if not info_hash or len(info_hash.strip()) != 40:
        return None

    clean_hash = info_hash.strip().lower()
    cache_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".stream_cache"))
    if not os.path.isdir(cache_dir):
        return None

    candidates = []
    for root, _, files in os.walk(cache_dir):
        for f in files:
            if f.lower().endswith((".mkv", ".mp4", ".avi", ".webm")):
                fp = os.path.join(root, f)
                try:
                    if os.path.getsize(fp) > 2 * 1024 * 1024:
                        candidates.append((fp, f.lower(), root.lower()))
                except OSError:
                    pass

    if not candidates:
        return None

    # Filter strictly by info_hash in directory path or filename
    hash_matched = [c for c in candidates if clean_hash in c[2] or clean_hash in c[1]]
    if not hash_matched:
        return None

    if episode is not None:
        patterns = [f"e{episode:02d}", f"e{episode:03d}", f" - {episode:02d}", f" - {episode:03d}", f"_{episode:02d}", f"_{episode:03d}"]
        for fp, fl, _ in hash_matched:
            if any(p in fl for p in patterns):
                return fp
        return None

    # If movie (episode is None)
    return hash_matched[0][0]


@router.get("/subtitles")
async def get_embedded_subtitles(
    info_hash: str = Query(..., description="Torrent info hash"),
    file_idx: int = Query(0, description="File index"),
    sub_index: int = Query(0, description="Subtitle stream index"),
    magnet: Optional[str] = Query(None),
    season: Optional[int] = Query(None),
    episode: Optional[int] = Query(None),
):
    """
    Extracts embedded Matroska/MP4 subtitles on the fly into WebVTT format using FFmpeg.
    """
    if info_hash.startswith("cdn_"):
        return Response(
            content="WEBVTT\n\nNOTE Web-CDN streams do not have embedded subtitles\n",
            media_type="text/vtt; charset=utf-8",
            headers={"Access-Control-Allow-Origin": "*", "Cache-Control": "public, max-age=3600"},
        )

    await ensure_streaming_daemon()
    source_url = get_internal_stream_url(info_hash, file_idx, magnet=magnet, season=season, episode=episode)
    local_file = _find_cached_media_path(info_hash=info_hash, episode=episode)
    target_source = local_file if local_file else source_url
    vtt = await extract_embedded_subtitle_vtt(target_source, sub_index)
    return Response(
        content=vtt,
        media_type="text/vtt; charset=utf-8",
        headers={"Access-Control-Allow-Origin": "*", "Cache-Control": "public, max-age=3600"},
    )


@router.get("/subtitles/sup")
async def get_embedded_sup_subtitles(
    info_hash: str = Query(..., description="Torrent info hash"),
    file_idx: int = Query(0, description="File index"),
    sub_index: int = Query(0, description="Subtitle stream index"),
    magnet: Optional[str] = Query(None),
    season: Optional[int] = Query(None),
    episode: Optional[int] = Query(None),
):
    """
    Streams raw binary Blu-ray PGS SUP packets extracted on the fly via FFmpeg.
    Enables zero-transcode client-side HTML5 canvas overlay rendering.
    """
    if info_hash.startswith("cdn_"):
        raise HTTPException(status_code=400, detail="Web CDN does not support embedded subtitles")

    await ensure_streaming_daemon()
    source_url = get_internal_stream_url(info_hash, file_idx, magnet=magnet, season=season, episode=episode)
    local_file = _find_cached_media_path(info_hash=info_hash, episode=episode)
    target_source = local_file if local_file else source_url

    generator = extract_embedded_sup_stream(target_source, sub_index)
    return StreamingResponse(
        generator,
        media_type="application/octet-stream",
        headers={
            "Access-Control-Allow-Origin": "*",
            "Content-Disposition": f'inline; filename="track_{sub_index}.sup"',
            "Cache-Control": "public, max-age=3600",
        },
    )


@router.get("/stats")
async def get_torrent_engine_stats():
    """
    Fetches real-time P2P swarm and daemon metrics (peers, speed, piece allocation).
    """
    status = await get_daemon_status()
    return status or {"status": "offline", "engine": "webtorrent-v3", "sessions": []}


@router.get("/cache/status")
async def get_streaming_cache_status():
    """
    Returns total disk usage and file count of cached torrent pieces in .stream_cache.
    """
    cache_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".stream_cache"))
    total_size = 0
    file_count = 0
    if os.path.exists(cache_dir):
        for root, _, files in os.walk(cache_dir):
            for f in files:
                fp = os.path.join(root, f)
                try:
                    total_size += os.path.getsize(fp)
                    file_count += 1
                except OSError:
                    pass
    return {
        "cache_dir": cache_dir,
        "total_bytes": total_size,
        "total_mb": round(total_size / (1024 * 1024), 2),
        "total_gb": round(total_size / (1024 * 1024 * 1024), 2),
        "file_count": file_count,
    }


@router.post("/cache/clear")
async def clear_streaming_cache():
    """
    Safely clears temporary streaming piece chunks from disk.
    """
    cache_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".stream_cache"))
    cleared_bytes = 0
    cleared_files = 0
    if os.path.exists(cache_dir):
        for root, dirs, files in os.walk(cache_dir, topdown=False):
            for f in files:
                fp = os.path.join(root, f)
                try:
                    cleared_bytes += os.path.getsize(fp)
                    os.remove(fp)
                    cleared_files += 1
                except OSError:
                    pass
            for d in dirs:
                dp = os.path.join(root, d)
                try:
                    os.rmdir(dp)
                except OSError:
                    pass
    return {
        "success": True,
        "cleared_files": cleared_files,
        "cleared_mb": round(cleared_bytes / (1024 * 1024), 2),
    }


@router.get("/playlist.m3u")
async def get_stream_m3u(
    info_hash: str = Query(..., description="Torrent info hash"),
    file_idx: int = Query(0, description="File index"),
    title: Optional[str] = Query("EvoStream", description="Playlist title"),
    magnet: Optional[str] = Query(None, description="Magnet link"),
    season: Optional[int] = Query(None, description="Season number"),
    episode: Optional[int] = Query(None, description="Episode number"),
    request: Request = None,
):
    """
    Generates a high-compatibility M3U playlist file for instant 1-click playback
    in desktop media players like VLC, MPC-HC, or MPV.
    """
    host = request.headers.get("host", "127.0.0.1:8009") if request else "127.0.0.1:8009"
    import urllib.parse
    stream_url = f"http://{host}/api/v1/stream/play?info_hash={info_hash}&file_idx={file_idx}"
    if magnet:
        stream_url += f"&magnet={urllib.parse.quote(magnet)}"
    if season is not None:
        stream_url += f"&season={season}"
    if episode is not None:
        stream_url += f"&episode={episode}"
    safe_title = re.sub(r'[\\/*?:"<>|]', "_", title or "EvoStream")
    m3u_text = f"#EXTM3U\n#EXTINF:-1,{safe_title}\n{stream_url}\n"
    return Response(
        content=m3u_text,
        media_type="audio/x-mpegurl",
        headers={"Content-Disposition": f'attachment; filename="{safe_title}.m3u"'},
    )


@router.get("/status")
async def get_streaming_status():
    """
    Returns current P2P streaming engine status and swarm stats.
    """
    return await get_daemon_status()


@router.post("/debrid/resolve")
async def resolve_debrid_stream(
    info_hash: str = Query(..., description="Torrent info hash"),
    file_idx: int = Query(0, description="File index inside torrent"),
    magnet: Optional[str] = Query(None, description="Original magnet link"),
    provider: Optional[str] = Query(None, description="Preferred Debrid provider"),
    season: Optional[int] = Query(None, description="Season number (for series/anime)"),
    episode: Optional[int] = Query(None, description="Episode number (for series/anime)"),
):
    """
    Resolves a cached torrent to an unthrottled 1Gbps HTTPS direct cloud streaming link
    via Real-Debrid, AllDebrid, or TorBox.
    """
    debrid_logger.info(f"Resolving Debrid stream info_hash={info_hash} file_idx={file_idx} provider={provider}")
    from core.debrid.manager import get_debrid_manager
    manager = get_debrid_manager()
    result = await manager.resolve_stream(
        info_hash=info_hash,
        file_idx=file_idx,
        magnet=magnet,
        preferred_provider=provider,
        season=season,
        episode=episode,
    )
    if not result:
        raise HTTPException(
            status_code=404,
            detail="Stream not cached or failed to resolve on configured Debrid providers",
        )

    from config import settings
    from core.debrid.proxy import get_debrid_proxy

    proxy = get_debrid_proxy()
    proxied_url = proxy.get_proxy_url(result.url, filename=result.filename)

    return {
        "success": True,
        "provider": result.provider,
        "stream_url": proxied_url if getattr(settings, "DEBRID_PROXY_ENABLED", True) else result.url,
        "direct_url": result.url,
        "proxied_url": proxied_url,
        "filename": result.filename,
        "size": result.size,
        "cached": result.cached,
    }


@router.get("/debrid/proxy")
async def debrid_stream_proxy_endpoint(
    request: Request,
    token: str = Query(..., description="Signed proxy token"),
    filename: Optional[str] = Query(None, description="Optional filename for metadata"),
):
    """
    Debrid Multi-IP Stream Proxy Gateway endpoint.
    Passes through HTTP Range 206 requests so multiple client devices
    can stream simultaneously through the EvoScrapper server IP without
    triggering account bans on Real-Debrid / AllDebrid.
    """
    from core.debrid.proxy import get_debrid_proxy

    proxy = get_debrid_proxy()
    payload = proxy.verify_token(token)
    if not payload:
        raise HTTPException(status_code=403, detail="Invalid or expired proxy token")

    upstream_url = payload.get("url")
    if not upstream_url:
        raise HTTPException(status_code=400, detail="Missing upstream stream URL in token")

    try:
        stream_gen, status_code, headers = await proxy.create_upstream_stream(
            upstream_url,
            incoming_headers=dict(request.headers),
        )
        return StreamingResponse(stream_gen, status_code=status_code, headers=headers)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Upstream stream proxy error: {str(e)}")


@router.get("/debrid/status")
async def get_debrid_statuses():
    """
    Returns account and connection statuses for all configured Debrid providers.
    """
    debrid_logger.info("Fetching Debrid provider connection statuses")
    from core.debrid.manager import get_debrid_manager
    manager = get_debrid_manager()
    statuses = await manager.get_all_statuses()
    return {"providers": statuses}


@router.get("/hls/playlist.m3u8")
async def get_hls_playlist(
    info_hash: str = Query(..., description="Torrent info hash"),
    file_idx: int = Query(0, description="File index inside torrent"),
    magnet: Optional[str] = Query(None, description="Optional magnet URI"),
    duration: float = Query(7200.0, description="Total video duration in seconds"),
    segment_duration: float = Query(6.0, description="HLS chunk duration in seconds"),
    season: Optional[int] = Query(None, description="Season number"),
    episode: Optional[int] = Query(None, description="Episode number"),
    format: str = Query("ts", description="Segment format: 'ts' or 'fmp4'"),
):
    """
    Returns an RFC 8216 compliant HLS VOD playlist with virtual segment references.
    Powers the P2P Media Loader browser WebRTC mesh.
    """
    from core.transmuxer import generate_hls_manifest
    manifest = generate_hls_manifest(
        info_hash=info_hash,
        total_duration_sec=duration,
        segment_duration_sec=segment_duration,
        file_idx=file_idx,
        magnet=magnet,
        season=season,
        episode=episode,
        prefer_fmp4=(format == "fmp4"),
    )
    return Response(
        content=manifest,
        media_type="application/vnd.apple.mpegurl",
        headers={
            "Cache-Control": "no-cache",
            "Access-Control-Allow-Origin": "*",
        },
    )


@router.get("/hls/init.mp4")
async def get_hls_init_segment(
    info_hash: str = Query(..., description="Torrent info hash"),
    file_idx: int = Query(0, description="File index inside torrent"),
    magnet: Optional[str] = Query(None, description="Optional magnet URI"),
    season: Optional[int] = Query(None, description="Season number"),
    episode: Optional[int] = Query(None, description="Episode number"),
):
    """Generates the fMP4 initialization segment (ftyp + moov) for RFC 8216 EXT-X-MAP [Phase 7 STRM-HIGH-05]."""
    await ensure_streaming_daemon()
    source_url = get_internal_stream_url(info_hash, file_idx, magnet=magnet, season=season, episode=episode)
    generator = stream_transmuxed_video(
        source_url_or_path=source_url,
        start_seconds=0.0,
        duration_seconds=0.5,
        transcode_video=False,
    )
    return StreamingResponse(
        generator,
        media_type="video/mp4",
        headers={
            "Cache-Control": "public, max-age=3600, immutable",
            "Access-Control-Allow-Origin": "*",
        },
    )


@router.get("/hls/segment")
async def get_hls_segment(
    info_hash: str = Query(..., description="Torrent info hash"),
    file_idx: int = Query(0, description="File index inside torrent"),
    start: float = Query(0.0, description="Segment start timestamp in seconds"),
    duration: float = Query(6.0, description="Segment duration in seconds"),
    magnet: Optional[str] = Query(None, description="Optional magnet URI"),
    season: Optional[int] = Query(None, description="Season number"),
    episode: Optional[int] = Query(None, description="Episode number"),
):
    """
    Generates an individual MPEG-TS/MP4 segment on-the-fly for Hls.js and P2P Media Loader.
    """
    source_url = get_internal_stream_url(info_hash, file_idx, magnet=magnet, season=season, episode=episode)
    return StreamingResponse(
        stream_hls_ts_segment(source_url, start_seconds=start, duration_seconds=duration),
        media_type="video/mp2t",
        headers={
            "Access-Control-Allow-Origin": "*",
            "Cache-Control": "public, max-age=300, immutable",
        },
    )


@router.get("/keyframes")
async def get_stream_keyframes(
    info_hash: str = Query(..., description="Torrent info hash"),
    file_idx: int = Query(0, description="File index inside torrent"),
    magnet: Optional[str] = Query(None, description="Optional magnet URI"),
):
    """
    Returns probed or cached video keyframe timestamps for seek-safe keyframe snapping [Phase 7 STRM-HIGH-05].
    """
    from core.transmuxer import load_cached_keyframes, probe_keyframes
    cached = load_cached_keyframes(info_hash, file_idx)
    if cached is not None:
        return {"info_hash": info_hash, "file_idx": file_idx, "keyframes": cached, "cached": True}
    source_url = get_internal_stream_url(info_hash, file_idx, magnet=magnet)
    kfs = await probe_keyframes(source_url, info_hash, file_idx)
    return {"info_hash": info_hash, "file_idx": file_idx, "keyframes": kfs, "cached": False}


_WATCHDOG_HISTORY: deque = deque(maxlen=100)


@router.get("/health-watch")
async def get_stream_health_watch(
    info_hash: str = Query(..., description="Torrent info hash"),
):
    """
    Real-time buffer health state monitoring endpoint from the torrent engine watchdog.
    """
    from core.torrent_streamer import DAEMON_URL
    try:
        session = await get_http_session()
        async with session.get(f"{DAEMON_URL}/health-watch?info_hash={info_hash}", timeout=aiohttp.ClientTimeout(total=2.0)) as resp:
            if resp.status == 200:
                data = await resp.json()
                import time
                data["timestamp"] = time.time()
                _WATCHDOG_HISTORY.append(data)
                return data
            raise HTTPException(status_code=resp.status, detail="Daemon health-watch failed")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Cannot connect to daemon: {str(e)}")


@router.get("/diagnostics")
async def get_system_diagnostics():
    """
    Runs full comprehensive system diagnostics for the Settings Control Center:
    - Backend core status & Python/OS details
    - WebTorrent micro-daemon connection & latency
    - FFmpeg presence and version
    - External player paths (VLC, MPV, MPC-HC, PotPlayer)
    - Storage and disk usage
    - Cinemeta & Stremio API latency
    - Torrent tracker host DNS resolution
    """
    import platform
    import shutil
    import socket
    import subprocess
    import time
    from core.torrent_streamer import DAEMON_URL

    start_time = time.time()
    diag = {
        "timestamp": time.time(),
        "backend": {
            "status": "online",
            "version": "2.2.0",
            "python": platform.python_version(),
            "os": f"{platform.system()} {platform.release()}",
            "arch": platform.machine(),
            "port": 8009,
        },
        "daemon": {
            "status": "offline",
            "url": DAEMON_URL,
            "latency_ms": None,
            "engine": "webtorrent-v3",
            "active_torrents": 0,
        },
        "ffmpeg": {
            "available": False,
            "version": None,
            "path": shutil.which("ffmpeg"),
        },
        "players": {
            "vlc": find_external_player("vlc"),
            "mpv": find_external_player("mpv"),
            "mpc_hc": find_external_player("mpc-hc"),
            "potplayer": find_external_player("potplayer"),
        },
        "storage": {},
        "stremio": {
            "status": "untested",
            "latency_ms": None,
        },
        "trackers": [],
    }

    # 1. Daemon status
    d_start = time.time()
    try:
        session = await get_http_session()
        async with session.get(f"{DAEMON_URL}/status", timeout=aiohttp.ClientTimeout(total=2.0)) as resp:
            if resp.status == 200:
                data = await resp.json()
                diag["daemon"]["status"] = "online"
                diag["daemon"]["latency_ms"] = round((time.time() - d_start) * 1000, 1)
                diag["daemon"]["active_torrents"] = data.get("active_torrents", 0)
                diag["daemon"]["download_speed"] = data.get("clientDownloadSpeed", "0 KB/s")
                diag["daemon"]["upload_speed"] = data.get("clientUploadSpeed", "0 KB/s")
                diag["daemon"]["sessions"] = [
                    {
                        "hash": s.get("info_hash"),
                        "health_state": s.get("health_state", "healthy"),
                        "seconds_ahead": s.get("seconds_ahead", 0),
                        "deficit_ratio": s.get("deficit_ratio", 0),
                        "download_speed": s.get("downloadSpeed", "0 MB/s"),
                        "peers": s.get("numPeers", 0),
                    }
                    for s in data.get("sessions", [])
                ]
    except Exception as e:
        diag["daemon"]["error"] = str(e)

    # 2. FFmpeg detection
    if diag["ffmpeg"]["path"]:
        try:
            loop = asyncio.get_event_loop()
            res = await loop.run_in_executor(
                None,
                lambda: subprocess.run(["ffmpeg", "-version"], capture_output=True, text=True, timeout=1.5),
            )
            if res.returncode == 0:
                diag["ffmpeg"]["available"] = True
                diag["ffmpeg"]["version"] = res.stdout.split("\n")[0]
        except Exception:
            pass

    # 3. Storage
    try:
        total, used, free = shutil.disk_usage(".")
        cache_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".stream_cache"))
        cache_size = 0
        file_count = 0
        if os.path.exists(cache_dir):
            for root, _, files in os.walk(cache_dir):
                for f in files:
                    try:
                        cache_size += os.path.getsize(os.path.join(root, f))
                        file_count += 1
                    except OSError:
                        pass

        diag["storage"] = {
            "disk_total_gb": round(total / (1024**3), 2),
            "disk_free_gb": round(free / (1024**3), 2),
            "disk_used_percent": round((used / total) * 100, 1),
            "cache_dir": cache_dir,
            "cache_mb": round(cache_size / (1024 * 1024), 2),
            "cache_files": file_count,
        }
    except Exception as e:
        diag["storage"]["error"] = str(e)

    # 3.5 HLS Cache & Transmux Telemetry [Phase 11]
    try:
        from core.transmuxer import _hls_cache, get_ffmpeg_max_concurrency, _FFMPEG_SEMAPHORE
        diag["hls_cache"] = _hls_cache.get_stats()
        active_permits = 0
        if _FFMPEG_SEMAPHORE is not None:
            max_c = get_ffmpeg_max_concurrency()
            active_permits = max(0, max_c - _FFMPEG_SEMAPHORE._value)
        diag["transmux"] = {
            "max_concurrency": get_ffmpeg_max_concurrency(),
            "active_permits": active_permits,
        }
    except Exception:
        diag["hls_cache"] = {}
        diag["transmux"] = {}

    try:
        import core.debrid.proxy as db_proxy
        client = db_proxy._shared_client
        pool_stats = {}
        if client is not None and getattr(client, "_transport", None) and getattr(client._transport, "_pool", None):
            pool = client._transport._pool
            pool_stats["open_connections"] = len(getattr(pool, "_requests", []))
        diag["debrid_proxy"] = {
            "shared_client_active": bool(client and not client.is_closed),
            "max_keepalive_connections": 20,
            "max_connections": 50,
            **pool_stats,
        }
    except Exception as e:
        diag["debrid_proxy"] = {
            "shared_client_active": False,
            "max_keepalive_connections": 20,
            "max_connections": 50,
            "error": str(e),
        }

    diag["watchdog_history"] = list(_WATCHDOG_HISTORY)
    diag["mesh"] = {
        "supported": True,
        "default_enabled": False,
        "engine": "p2p-media-loader",
    }

    # 4. Stremio Cinemeta check
    s_start = time.time()
    try:
        session = await get_http_session()
        async with session.get("https://v3-cinemeta.strem.io/manifest.json", timeout=aiohttp.ClientTimeout(total=3.0)) as resp:
            if resp.status == 200:
                m_data = await resp.json()
                diag["stremio"]["status"] = "online"
                diag["stremio"]["latency_ms"] = round((time.time() - s_start) * 1000, 1)
                diag["stremio"]["name"] = m_data.get("name", "Cinemeta")
    except Exception as e:
        diag["stremio"]["status"] = "error"
        diag["stremio"]["error"] = str(e)

    # 5. Torrent Trackers DNS
    trackers = ["tracker.opentrackr.org", "tracker.torrent.eu.org", "open.stealth.si"]
    loop = asyncio.get_event_loop()
    for trk in trackers:
        t_start = time.time()
        try:
            ip = await loop.run_in_executor(None, socket.gethostbyname, trk)
            diag["trackers"].append({
                "host": trk,
                "status": "resolved",
                "ip": ip,
                "latency_ms": round((time.time() - t_start) * 1000, 1),
            })
        except Exception as e:
            diag["trackers"].append({
                "host": trk,
                "status": "failed",
                "error": str(e),
            })

    diag["total_elapsed_ms"] = round((time.time() - start_time) * 1000, 1)
    return diag



