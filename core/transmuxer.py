import asyncio
import hashlib
import os
import re
import shutil
import subprocess
import time
from typing import AsyncGenerator, List, Optional
import aiofiles
from fastapi import HTTPException
from core.logger import streaming_logger, subtitles_logger


def find_ffmpeg() -> Optional[str]:
    """Finds the ffmpeg binary on system path or standard Windows install locations."""
    path = shutil.which("ffmpeg")
    if path:
        return path

    candidates = [
        os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\WinGet\Packages\Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe\ffmpeg-9.0.2-full_build\bin\ffmpeg.exe"),
        os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\WinGet\Packages\Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe\ffmpeg-8.1-full_build\bin\ffmpeg.exe"),
        r"C:\ffmpeg\bin\ffmpeg.exe",
        r"C:\Program Files\ffmpeg\bin\ffmpeg.exe",
    ]
    for c in candidates:
        if os.path.isfile(c):
            return c
    return None


def find_vlc() -> Optional[str]:
    """Finds the VLC media player binary on Windows."""
    candidates = [
        r"C:\Program Files\VideoLAN\VLC\vlc.exe",
        r"C:\Program Files (x86)\VideoLAN\VLC\vlc.exe",
        shutil.which("vlc"),
    ]
    for c in candidates:
        if c and os.path.isfile(c):
            return c
    return None


_FFMPEG_SUPPORTS_FPS_MODE: Optional[bool] = None


def get_passthrough_fps_flag() -> List[str]:
    """
    Returns the appropriate passthrough framerate flag:
    Modern FFmpeg (>=5.1, including 6, 7, 8, 9) uses ['-fps_mode', 'passthrough'].
    Deprecated legacy FFmpeg (<5.1) used ['-vsync', 'passthrough'].
    """
    global _FFMPEG_SUPPORTS_FPS_MODE
    if _FFMPEG_SUPPORTS_FPS_MODE is None:
        try:
            ffmpeg_bin = find_ffmpeg() or "ffmpeg"
            proc = subprocess.run(
                [ffmpeg_bin, "-version"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=2,
            )
            out = proc.stdout.decode("utf-8", errors="ignore")
            m = re.search(r"version\s+(\d+)", out)
            major = int(m.group(1)) if m else 7
            _FFMPEG_SUPPORTS_FPS_MODE = (major >= 5)
        except Exception:
            _FFMPEG_SUPPORTS_FPS_MODE = True
    return ["-fps_mode", "passthrough"] if _FFMPEG_SUPPORTS_FPS_MODE else ["-vsync", "passthrough"]


def find_ffprobe() -> Optional[str]:
    """Finds the ffprobe binary on system path or standard Windows install locations."""
    path = shutil.which("ffprobe")
    if path:
        return path
    ffmpeg_bin = find_ffmpeg()
    if ffmpeg_bin:
        cand = os.path.join(os.path.dirname(ffmpeg_bin), "ffprobe.exe")
        if os.path.isfile(cand):
            return cand
    candidates = [
        os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\WinGet\Packages\Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe\ffmpeg-9.0.2-full_build\bin\ffprobe.exe"),
        os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\WinGet\Packages\Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe\ffmpeg-8.1-full_build\bin\ffprobe.exe"),
        r"C:\ffmpeg\bin\ffprobe.exe",
        r"C:\Program Files\ffmpeg\bin\ffprobe.exe",
    ]
    for c in candidates:
        if os.path.isfile(c):
            return c
    return None


_HW_ENCODERS_CACHE = None


def detect_hw_encoders() -> dict:
    """
    Detects available hardware-accelerated video encoders (NVENC, QSV, AMF, VAAPI, VideoToolbox).
    Caches the capability map in memory to eliminate repeated subprocess overhead.
    """
    global _HW_ENCODERS_CACHE
    if _HW_ENCODERS_CACHE is not None:
        return _HW_ENCODERS_CACHE

    result = {
        "nvenc": False,
        "qsv": False,
        "amf": False,
        "vaapi": False,
        "videotoolbox": False,
        "software": True,
    }

    ffmpeg_bin = find_ffmpeg() or "ffmpeg"
    try:
        proc = subprocess.run(
            [ffmpeg_bin, "-encoders"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=3,
        )
        output = (proc.stdout or "").lower()
        if "h264_nvenc" in output:
            result["nvenc"] = True
        if "h264_qsv" in output:
            result["qsv"] = True
        if "h264_amf" in output:
            result["amf"] = True
        if "h264_vaapi" in output:
            result["vaapi"] = True
        if "h264_videotoolbox" in output:
            result["videotoolbox"] = True
    except Exception:
        pass

    _HW_ENCODERS_CACHE = result
    return result


def get_video_encoder(hw_accel: bool = True) -> tuple:
    """
    Selects the optimal H.264 video encoder:
    Uses hardware acceleration (NVENC, QSV, AMF, VideoToolbox) when available,
    falling back cleanly to CPU libx264.
    Returns (codec_name, extra_args_list).
    """
    if hw_accel:
        caps = detect_hw_encoders()
        if caps.get("nvenc"):
            return "h264_nvenc", ["-preset", "p1", "-tune", "ll", "-pix_fmt", "yuv420p"]
        elif caps.get("qsv"):
            return "h264_qsv", ["-preset", "veryfast", "-pix_fmt", "nv12"]
        elif caps.get("amf"):
            return "h264_amf", ["-quality", "speed", "-pix_fmt", "yuv420p"]
        elif caps.get("videotoolbox"):
            return "h264_videotoolbox", ["-realtime", "1", "-pix_fmt", "yuv420p"]

    return "libx264", [
        "-preset", "ultrafast",
        "-tune", "zerolatency",
        "-pix_fmt", "yuv420p",
        "-crf", "22",
    ]


async def probe_media_stream(source_url_or_path: str) -> dict:
    """
    Rapidly probes the media stream using ffprobe (2MB probe, 2s analyze).
    Returns total duration in seconds, video/audio codecs, audio tracks, and embedded subtitles.
    """
    import json
    ffprobe_bin = find_ffprobe() or "ffprobe"

    cmd = [
        ffprobe_bin,
        "-v", "error",
        "-probesize", "262144",
        "-analyzeduration", "500000",
    ]

    if source_url_or_path.startswith("http"):
        cmd.extend([
            "-reconnect", "1",
            "-reconnect_at_eof", "1",
            "-reconnect_streamed", "1",
            "-reconnect_delay_max", "4",
        ])

    cmd.extend([
        "-show_entries", "format=duration,size,bit_rate:stream=index,codec_name,codec_type,channels,channel_layout,disposition:stream_tags=language,title",
        "-of", "json",
        source_url_or_path,
    ])

    proc = None
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=15.0)
        data = json.loads(stdout.decode("utf-8", errors="replace"))

        if proc.returncode != 0 or (not data.get("streams") and not data.get("format")):
            return {
                "success": False,
                "error": f"ffprobe exited with code {proc.returncode}",
                "duration": 0.0,
                "size": 0,
                "bit_rate": 0,
                "video_codec": "unknown",
                "audio_codec": "unknown",
                "audio_tracks": [],
                "subtitle_tracks": [],
            }

        fmt = data.get("format", {})
        raw_duration = fmt.get("duration")
        duration = float(raw_duration) if raw_duration else 0.0

        audio_tracks = []
        subtitle_tracks = []
        video_codec = "h264"
        audio_codec = "aac"
        has_primary_video = False
        first_video_codec = None

        for s in data.get("streams", []):
            stype = s.get("codec_type")
            cname = (s.get("codec_name") or "").lower()
            tags = s.get("tags") or {}
            disp = s.get("disposition") or {}
            lang = tags.get("language") or "und"
            title = tags.get("title") or ""
            is_attached_pic = bool(disp.get("attached_pic"))

            if stype == "video":
                if not first_video_codec:
                    first_video_codec = cname
                # Exclude attached pictures (embedded cover art / poster thumbnails e.g. mjpeg/png)
                if is_attached_pic or cname in ("mjpeg", "png", "bmp", "jpeg"):
                    continue
                if not has_primary_video:
                    video_codec = cname
                    has_primary_video = True
            elif stype == "audio":
                audio_tracks.append({
                    "track_idx": len(audio_tracks),
                    "stream_idx": s.get("index"),
                    "codec": cname,
                    "channels": s.get("channels", 2),
                    "channel_layout": s.get("channel_layout", "stereo"),
                    "language": lang,
                    "title": title or f"Track {len(audio_tracks) + 1} ({lang.upper()})",
                })
                if len(audio_tracks) == 1:
                    audio_codec = cname
            elif stype == "subtitle":
                is_bitmap = any(k in cname.lower() for k in ("pgs", "dvd", "vobsub", "xsub", "dvb_subtitle"))
                subtitle_tracks.append({
                    "sub_idx": len(subtitle_tracks),
                    "stream_idx": s.get("index"),
                    "codec": cname,
                    "is_bitmap": is_bitmap,
                    "language": lang,
                    "title": title or f"Sub {len(subtitle_tracks) + 1} ({lang.upper()})",
                })

        if not has_primary_video and first_video_codec:
            video_codec = first_video_codec

        return {
            "success": True,
            "duration": round(duration, 2),
            "size": int(fmt.get("size") or 0),
            "bit_rate": int(fmt.get("bit_rate") or 0),
            "video_codec": video_codec,
            "audio_codec": audio_codec,
            "audio_tracks": audio_tracks,
            "subtitle_tracks": subtitle_tracks,
        }
    except Exception as e:
        if proc and proc.returncode is None:
            try:
                proc.kill()
            except Exception:
                pass
        return {
            "success": False,
            "error": str(e),
            "duration": 0.0,
            "size": 0,
            "bit_rate": 0,
            "video_codec": "unknown",
            "audio_codec": "unknown",
            "audio_tracks": [],
            "subtitle_tracks": [],
        }



def get_ffmpeg_max_concurrency() -> int:
    env_val = os.getenv("EVO_MAX_CONCURRENT_FFMPEG")
    if env_val:
        try:
            return max(1, int(env_val))
        except ValueError:
            pass
    cpu = os.cpu_count() or 4
    return min(8, max(2, cpu // 2))


_FFMPEG_SEMAPHORE = asyncio.Semaphore(get_ffmpeg_max_concurrency())


async def stream_transmuxed_video(
    source_url_or_path: str,
    start_seconds: float = 0.0,
    duration_seconds: Optional[float] = None,
    transcode_video: bool = False,
    burn_sub_idx: Optional[int] = None,
    audio_track: int = 0,
    audio_boost: float = 1.25,
    chunk_size: int = 65536,
    channels: Optional[int] = None,
) -> AsyncGenerator[bytes, None]:
    """
    Spawns an ultra-low latency FFmpeg pipeline that losslessly transmuxes video into
    fragmented MP4 and converts any audio codec (AC3, EAC3, DTS, TrueHD, 5.1/7.1)
    to crystal-clear 2-channel stereo AAC with perfect sync and dialogue boost.
    Supports real-time PGS/ASS subtitle burn-in via burn_sub_idx with zero-latency overlay.
    Enforces optional duration clamping and bounds concurrent processes via semaphore.
    """
    ffmpeg_bin = find_ffmpeg() or "ffmpeg"

    cmd: List[str] = [
        ffmpeg_bin,
        "-hide_banner",
        "-loglevel", "warning",
    ]

    # For streaming HTTP sources, robust reconnect parameters prevent buffer drops
    if source_url_or_path.startswith("http"):
        cmd.extend([
            "-reconnect", "1",
            "-reconnect_at_eof", "1",
            "-reconnect_streamed", "1",
            "-reconnect_on_network_error", "1",
            "-reconnect_delay_max", "15",
        ])

    cmd.extend([
        "-probesize", "524288",         # 512KB probe for ultra-low latency playback initiation
        "-analyzeduration", "1000000",  # 1s header analysis for multi-track streams
        "-fflags", "+genpts+discardcorrupt",
    ])

    # Input-seek (-ss before -i) allows instant seek without reading preceding stream bytes
    if start_seconds and start_seconds > 0:
        cmd.extend(["-ss", f"{start_seconds:.2f}"])

    if duration_seconds and duration_seconds > 0:
        cmd.extend(["-t", f"{duration_seconds:.2f}"])

    cmd.append("-i")
    cmd.append(source_url_or_path)

    if burn_sub_idx is not None:
        transcode_video = True
        cmd.extend([
            "-filter_complex", f"[0:V:0][0:s:{burn_sub_idx}]overlay[v]",
            "-map", "[v]",
        ])
    else:
        cmd.extend([
            "-map", "0:V:0?",               # Primary video stream (excludes attached pictures/thumbnails)
        ])

    # Map target audio track (with fallback to first audio stream)
    if audio_track > 0:
        cmd.extend(["-map", f"0:a:{audio_track}?"])
    else:
        cmd.extend(["-map", "0:a:0?"])

    if transcode_video:
        codec, extra_args = get_video_encoder(hw_accel=True)
        cmd.extend(["-c:v", codec])
        cmd.extend(extra_args)
    else:
        cmd.extend([
            "-c:v", "copy",
            *get_passthrough_fps_flag(),       # Preserve original video PTS (avoids A/V drift from copy)
        ])
        if start_seconds and start_seconds > 0:
            cmd.append("-copyts")

    # Build audio filter chain with ITU-R BS.775 downmix and timestamp correction:
    # 1. aresample=async=1:first_pts=0 dynamically synchronizes audio clock to video stream
    # 2. ITU-R BS.775 downmix pan matrix for surround audio (> 2 channels)
    # 3. volume boost restores center channel dialogue
    af_filters = ["aresample=async=1:first_pts=0:min_hard_comp=0.100000"]
    if channels is not None and channels > 2:
        af_filters.append("pan=stereo|FL=0.5*c0+0.7071*c2+0.7071*c4|FR=0.5*c1+0.7071*c2+0.7071*c5")
    if audio_boost and audio_boost > 0:
        af_filters.append(f"volume={audio_boost:.2f}")

    cmd.extend([
        "-c:a", "aac",
        "-b:a", "192k",
        "-ac", "2",                     # Downmix to 2-channel stereo for 100% browser compatibility
        "-af", ",".join(af_filters),
        "-sn",                          # Strip embedded subtitles to prevent MP4 container muxing errors
        "-dn",                          # Strip data streams
        "-avoid_negative_ts", "make_zero",  # Fix negative PTS timestamps from seek operations
        "-max_muxing_queue_size", "2048",   # Prevent queue starvation on multi-track streams
        "-movflags", "frag_keyframe+empty_moov+default_base_moof+negative_cts_offsets",
        "-flush_packets", "1",
        "-f", "mp4",
        "pipe:1",
    ])

    async with _FFMPEG_SEMAPHORE:
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        bytes_yielded = 0
        stderr_lines: List[str] = []

        async def _drain_stderr():
            try:
                while True:
                    line = await process.stderr.readline()
                    if not line:
                        break
                    decoded = line.decode("utf-8", errors="replace").strip()
                    if decoded:
                        stderr_lines.append(decoded)
                        if len(stderr_lines) > 50:
                            stderr_lines.pop(0)
            except Exception:
                pass

        drain_task = asyncio.create_task(_drain_stderr())

        try:
            while True:
                chunk = await process.stdout.read(chunk_size)
                if not chunk:
                    break
                bytes_yielded += len(chunk)
                yield chunk
        except (asyncio.CancelledError, GeneratorExit):
            pass
        finally:
            try:
                if process.returncode is None:
                    process.terminate()
                    try:
                        await asyncio.wait_for(process.wait(), timeout=1.0)
                    except (asyncio.TimeoutError, TimeoutError):
                        process.kill()
                        await process.wait()
            except Exception:
                pass
            if not drain_task.done():
                drain_task.cancel()

        if bytes_yielded == 0 and process.returncode is not None and process.returncode != 0:
            stderr_snippet = " ".join(stderr_lines[-5:]).strip()
            streaming_logger.error(
                f"[Transmuxer] FFmpeg exited with code {process.returncode} before yielding any bytes: {stderr_snippet}"
            )
            raise HTTPException(
                status_code=502,
                detail=f"Transmuxer failed to start: {stderr_snippet or 'premature exit'}"
            )


_HLS_SEMAPHORE = asyncio.Semaphore(max(1, int(os.getenv("EVO_HLS_MAX_CONCURRENCY", "3"))))


class HlsSegmentCache:
    """
    Persistent disk cache for virtual HLS TS segments.
    Single-flight deduplication prevents redundant FFmpeg spawns for duplicate segment requests.
    Enforces TTL (default 30m) and LRU cache eviction at max_mb threshold (default 2GB).
    """

    def __init__(self, cache_dir: Optional[str] = None, max_mb: Optional[int] = None, ttl_sec: int = 1800):
        if cache_dir is None:
            cache_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "data", "hls_cache"))
        self.cache_dir = cache_dir
        self.max_bytes = (max_mb or int(os.getenv("EVO_HLS_CACHE_MAX_MB", "2048"))) * 1024 * 1024
        self.ttl_sec = ttl_sec
        self._in_flight: dict[str, asyncio.Future] = {}
        self._lock = asyncio.Lock()
        os.makedirs(self.cache_dir, exist_ok=True)

    def get_cache_key(self, source_url: str, start: float, duration: float) -> str:
        m_hash = re.search(r"info_hash=([0-9a-fA-F]{40})", source_url)
        m_idx = re.search(r"file_idx=(\d+)", source_url)
        start_ms = int(round(start * 1000))
        dur_ms = int(round(duration * 1000))
        if m_hash:
            h = m_hash.group(1).lower()
            idx = m_idx.group(1) if m_idx else "0"
            return f"{h}_{idx}_{start_ms}_{dur_ms}"
        raw = f"{source_url}_{start_ms}_{dur_ms}"
        return hashlib.sha1(raw.encode("utf-8")).hexdigest()

    def get_file_path(self, key: str) -> str:
        return os.path.join(self.cache_dir, f"{key}.ts")

    def has(self, key: str) -> bool:
        ts_path = self.get_file_path(key)
        done_path = f"{ts_path}.done"
        if os.path.isfile(ts_path) and os.path.isfile(done_path):
            try:
                if time.time() - os.path.getmtime(done_path) < self.ttl_sec:
                    return True
            except OSError:
                pass
        return False

    async def get_cached_chunks(self, key: str, chunk_size: int = 65536) -> AsyncGenerator[bytes, None]:
        ts_path = self.get_file_path(key)
        try:
            now = time.time()
            os.utime(ts_path, (now, now))
        except OSError:
            pass
        async with aiofiles.open(ts_path, "rb") as f:
            while True:
                chunk = await f.read(chunk_size)
                if not chunk:
                    break
                yield chunk

    async def evict_lru_if_needed(self):
        try:
            total_size = 0
            files = []
            for entry in os.scandir(self.cache_dir):
                if entry.name.endswith(".ts"):
                    try:
                        stat = entry.stat()
                        total_size += stat.st_size
                        files.append((stat.st_mtime, stat.st_size, entry.path))
                    except OSError:
                        pass
            if total_size > self.max_bytes:
                files.sort(key=lambda x: x[0])
                for _, size, path in files:
                    try:
                        os.remove(path)
                        done = f"{path}.done"
                        if os.path.isfile(done):
                            os.remove(done)
                        total_size -= size
                        if total_size <= self.max_bytes * 0.8:
                            break
                    except OSError:
                        pass
        except Exception:
            pass


_hls_cache = HlsSegmentCache()


async def _spawn_ts_segment(
    source_url_or_path: str,
    start_seconds: float = 0.0,
    duration_seconds: float = 6.0,
    chunk_size: int = 65536,
) -> AsyncGenerator[bytes, None]:
    """Spawns an FFmpeg process to slice an individual MPEG-TS segment through the bounded HLS semaphore."""
    async with _HLS_SEMAPHORE:
        ffmpeg_bin = find_ffmpeg() or "ffmpeg"
        cmd: List[str] = [
            ffmpeg_bin,
            "-hide_banner",
            "-loglevel", "error",
        ]

        if source_url_or_path.startswith("http"):
            cmd.extend([
                "-reconnect", "1",
                "-reconnect_at_eof", "1",
                "-reconnect_streamed", "1",
                "-reconnect_on_network_error", "1",
                "-reconnect_delay_max", "15",
            ])

        cmd.extend([
            "-ss", f"{start_seconds:.3f}",
            "-t", f"{duration_seconds:.3f}",
            "-i", source_url_or_path,
            "-map", "0:V:0?",
            "-map", "0:a:0?",
            "-c:v", "copy",
            "-c:a", "aac",
            "-b:a", "192k",
            "-ac", "2",
            "-af", "aresample=async=1:first_pts=0",
            "-sn",
            "-dn",
            "-f", "mpegts",
            "-mpegts_copyts", "1",
            "-output_ts_offset", f"{start_seconds:.3f}",
            "pipe:1",
        ])

        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )

        try:
            while True:
                chunk = await process.stdout.read(chunk_size)
                if not chunk:
                    break
                yield chunk
        except (asyncio.CancelledError, GeneratorExit):
            pass
        finally:
            try:
                if process.returncode is None:
                    process.terminate()
                    await process.wait()
            except Exception:
                pass


def _trigger_hls_prefetch(source_url_or_path: str, current_start: float, duration_seconds: float):
    """Enqueues background muxing of the next 1-3 segments through the bounded semaphore."""
    async def _prefetch_worker():
        for i in range(1, 4):
            next_start = current_start + (i * duration_seconds)
            next_key = _hls_cache.get_cache_key(source_url_or_path, next_start, duration_seconds)
            if _hls_cache.has(next_key):
                continue
            try:
                ts_path = _hls_cache.get_file_path(next_key)
                tmp_path = f"{ts_path}.tmp.{os.getpid()}.{time.time_ns()}"
                async with aiofiles.open(tmp_path, "wb") as f:
                    async for chunk in _spawn_ts_segment(source_url_or_path, next_start, duration_seconds):
                        await f.write(chunk)
                if os.path.isfile(tmp_path) and os.path.getsize(tmp_path) > 0:
                    os.replace(tmp_path, ts_path)
                    with open(f"{ts_path}.done", "w") as df:
                        df.write("1")
            except Exception:
                pass

    try:
        asyncio.create_task(_prefetch_worker())
    except RuntimeError:
        pass


async def stream_hls_ts_segment(
    source_url_or_path: str,
    start_seconds: float = 0.0,
    duration_seconds: float = 6.0,
    chunk_size: int = 65536,
    prefetch: bool = True,
) -> AsyncGenerator[bytes, None]:
    """
    Extracts an individual MPEG-TS segment for HLS streaming with persistent disk cache,
    single-flight deduplication, and bounded FFmpeg concurrency [STRM-HIGH-04].
    """
    key = _hls_cache.get_cache_key(source_url_or_path, start_seconds, duration_seconds)

    # 1. Cache hit: serve directly from disk with ZERO ffmpeg spawns
    if _hls_cache.has(key):
        async for chunk in _hls_cache.get_cached_chunks(key, chunk_size=chunk_size):
            yield chunk
        if prefetch:
            _trigger_hls_prefetch(source_url_or_path, start_seconds, duration_seconds)
        return

    # 2. Single-flight lock: if another request is currently generating this exact segment, wait for it
    fut = None
    is_initiator = False
    async with _hls_cache._lock:
        if key in _hls_cache._in_flight:
            fut = _hls_cache._in_flight[key]
        else:
            loop = asyncio.get_running_loop()
            fut = loop.create_future()
            _hls_cache._in_flight[key] = fut
            is_initiator = True

    if not is_initiator:
        try:
            await asyncio.wait_for(asyncio.shield(fut), timeout=30.0)
        except Exception:
            pass
        if _hls_cache.has(key):
            async for chunk in _hls_cache.get_cached_chunks(key, chunk_size=chunk_size):
                yield chunk
            return

    # 3. Cache miss initiator: spawn bounded FFmpeg, stream chunks to caller, and write to cache
    ts_path = _hls_cache.get_file_path(key)
    tmp_path = f"{ts_path}.tmp.{os.getpid()}.{time.time_ns()}"
    out_f = None
    try:
        out_f = await aiofiles.open(tmp_path, "wb")
        async for chunk in _spawn_ts_segment(source_url_or_path, start_seconds, duration_seconds, chunk_size):
            await out_f.write(chunk)
            yield chunk
        await out_f.close()
        out_f = None

        if os.path.isfile(tmp_path) and os.path.getsize(tmp_path) > 0:
            os.replace(tmp_path, ts_path)
            done_path = f"{ts_path}.done"
            with open(done_path, "w") as df:
                df.write("1")
            await _hls_cache.evict_lru_if_needed()
        if not fut.done():
            fut.set_result(True)
    except Exception as e:
        if not fut.done():
            fut.set_exception(e)
        raise
    finally:
        if out_f:
            try:
                await out_f.close()
            except Exception:
                pass
        if os.path.isfile(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass
        async with _hls_cache._lock:
            _hls_cache._in_flight.pop(key, None)

    # 4. Trigger background prefetch for subsequent segments
    if prefetch:
        _trigger_hls_prefetch(source_url_or_path, start_seconds, duration_seconds)


_TRACKED_VLC_PIDS: set[int] = set()


def launch_vlc_process(stream_url_or_path: str, title: Optional[str] = None) -> bool:
    """
    Launches native desktop VLC media player in an interactive GUI window on the host machine.
    Terminates any previously tracked EvoScrapper background instances, generates an instant .m3u playlist,
    and brings the window directly to the topmost centered interactive foreground.
    """
    import os
    import threading
    import ctypes
    import tempfile

    vlc_bin = find_vlc()
    if not vlc_bin:
        return False

    clean_title = (title or "EvoStream").replace('"', "").replace("'", "")

    # 1. Terminate only previously tracked EvoScrapper VLC instances (never global taskkill)
    dead_pids = set()
    for pid in list(_TRACKED_VLC_PIDS):
        try:
            if os.name == "nt":
                subprocess.run(
                    ["taskkill", "/F", "/PID", str(pid)],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=1.0,
                )
            else:
                os.kill(pid, 9)
        except Exception:
            pass
        dead_pids.add(pid)
    _TRACKED_VLC_PIDS.difference_update(dead_pids)

    # 2. Generate temporary M3U playlist file for guaranteed VLC queueing and header detection
    temp_m3u = os.path.join(tempfile.gettempdir(), "EvoStream_Playback.m3u")
    try:
        with open(temp_m3u, "w", encoding="utf-8") as f:
            f.write(f"#EXTM3U\n#EXTINF:-1,{clean_title}\n{stream_url_or_path}\n")
    except Exception:
        pass

    args = [
        vlc_bin,
        "--intf=qt",
        "--started-from-file",
        "--no-one-instance",
        "--video-on-top",
        "--network-caching=2000",
        "--file-caching=2000",
        "--clock-jitter=500",
        "--clock-synchro=0",
        "--no-video-title-show",
        f"--meta-title={clean_title}",
        temp_m3u if os.path.isfile(temp_m3u) else stream_url_or_path,
    ]

    try:
        startupinfo = None
        creationflags = 0
        if os.name == "nt":
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startupinfo.wShowWindow = 1  # SW_SHOWNORMAL
            creationflags = subprocess.CREATE_NEW_PROCESS_GROUP

        proc = subprocess.Popen(
            args,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
            startupinfo=startupinfo,
            creationflags=creationflags,
        )

        if proc.pid:
            _TRACKED_VLC_PIDS.add(proc.pid)

        # 3. Bring VLC window directly to topmost centered foreground
        if proc.pid and os.name == "nt":
            def _bring_front_worker(pid: int):
                import time
                user32 = ctypes.windll.user32
                kernel32 = ctypes.windll.kernel32

                found_hwnd = None
                for _ in range(60):
                    time.sleep(0.1)
                    hwnds = []
                    def _cb(hwnd, _):
                        p = ctypes.c_ulong()
                        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(p))
                        if p.value == pid:
                            cbuf = ctypes.create_unicode_buffer(256)
                            user32.GetClassNameW(hwnd, cbuf, 256)
                            # Match Qt GUI main window
                            if "Qt" in cbuf.value or user32.IsWindowVisible(hwnd):
                                hwnds.append(hwnd)
                        return True

                    WNDENUM = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
                    user32.EnumWindows(WNDENUM(_cb), 0)
                    if hwnds:
                        found_hwnd = hwnds[0]
                        break

                if found_hwnd:
                    # Calculate center coordinates at 85% screen size
                    screen_w = user32.GetSystemMetrics(0)  # SM_CXSCREEN
                    screen_h = user32.GetSystemMetrics(1)  # SM_CYSCREEN
                    target_w = min(1440, int(screen_w * 0.85))
                    target_h = min(900, int(screen_h * 0.85))
                    center_x = max(0, (screen_w - target_w) // 2)
                    center_y = max(0, (screen_h - target_h) // 2)

                    # Restore & Show window
                    user32.ShowWindow(found_hwnd, 9)  # SW_RESTORE
                    user32.ShowWindow(found_hwnd, 5)  # SW_SHOW

                    # AttachThreadInput trick to bypass Windows foreground locks
                    cur_thread = kernel32.GetCurrentThreadId()
                    target_thread = user32.GetWindowThreadProcessId(found_hwnd, None)
                    user32.AttachThreadInput(cur_thread, target_thread, True)

                    HWND_TOPMOST = -1
                    HWND_NOTOPMOST = -2
                    SWP_SHOWWINDOW = 0x0040
                    user32.SetWindowPos(found_hwnd, HWND_TOPMOST, center_x, center_y, target_w, target_h, SWP_SHOWWINDOW)
                    user32.BringWindowToTop(found_hwnd)
                    user32.SetForegroundWindow(found_hwnd)
                    user32.SetWindowPos(found_hwnd, HWND_NOTOPMOST, center_x, center_y, target_w, target_h, SWP_SHOWWINDOW)

                    user32.AttachThreadInput(cur_thread, target_thread, False)

            threading.Thread(target=_bring_front_worker, args=(proc.pid,), daemon=True).start()

        return True
    except Exception as e:
        print(f"[TorrentStreamer] VLC direct launch error: {e}")
        # Secondary fallback: use Windows ShellExecute
        if os.name == "nt" and os.path.isfile(temp_m3u):
            try:
                os.startfile(temp_m3u)
                return True
            except Exception:
                pass
        return False


KEYFRAMES_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "data", "keyframes"))


def get_keyframes_cache_path(info_hash: str, file_idx: int = 0) -> str:
    """Returns the persistent keyframe cache file path for a torrent file [Phase 7 STRM-HIGH-05]."""
    os.makedirs(KEYFRAMES_DIR, exist_ok=True)
    return os.path.join(KEYFRAMES_DIR, f"{info_hash.lower()}_{file_idx}.json")


def load_cached_keyframes(info_hash: str, file_idx: int = 0) -> Optional[List[float]]:
    """Loads cached keyframe timestamps if available on disk."""
    path = get_keyframes_cache_path(info_hash, file_idx)
    if os.path.isfile(path):
        try:
            import json
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, list) and data:
                    return sorted([float(x) for x in data])
        except Exception:
            pass
    return None


def save_cached_keyframes(info_hash: str, file_idx: int, keyframes: List[float]):
    """Persists probed keyframe timestamps to disk."""
    path = get_keyframes_cache_path(info_hash, file_idx)
    try:
        import json
        with open(path, "w", encoding="utf-8") as f:
            json.dump(sorted(keyframes), f)
    except Exception:
        pass


async def probe_keyframes(source_url: str, info_hash: str, file_idx: int = 0, timeout: float = 8.0) -> List[float]:
    """Probes source video keyframes using ffprobe and caches results [Phase 7 STRM-HIGH-05]."""
    cached = load_cached_keyframes(info_hash, file_idx)
    if cached is not None:
        return cached

    ffprobe = shutil.which("ffprobe") or "ffprobe"
    cmd = [
        ffprobe,
        "-v", "quiet",
        "-select_streams", "v:0",
        "-show_frames",
        "-show_entries", "frame=pkt_pts_time,pict_type",
        "-of", "csv",
        source_url
    ]
    keyframes = [0.0]
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        for line in stdout.decode("utf-8", errors="replace").splitlines():
            parts = line.strip().split(",")
            if len(parts) >= 3 and parts[2] == "I":
                try:
                    pts = float(parts[1])
                    if pts > 0 and pts not in keyframes:
                        keyframes.append(round(pts, 3))
                except ValueError:
                    pass
        keyframes.sort()
        if len(keyframes) > 1:
            save_cached_keyframes(info_hash, file_idx, keyframes)
    except Exception:
        pass
    return keyframes


def generate_hls_manifest(
    info_hash: str,
    total_duration_sec: float = 7200.0,
    segment_duration_sec: float = 6.0,
    file_idx: int = 0,
    magnet: Optional[str] = None,
    season: Optional[int] = None,
    episode: Optional[int] = None,
    keyframes: Optional[List[float]] = None,
    prefer_fmp4: bool = False,
) -> str:
    """Generates an RFC 8216 compliant HLS VOD playlist with virtual segment references and keyframe snapping."""
    import urllib.parse
    import math

    if keyframes is None:
        keyframes = load_cached_keyframes(info_hash, file_idx)

    segments: List[tuple[float, float]] = []

    if keyframes and len(keyframes) > 1:
        sorted_kf = sorted([k for k in keyframes if 0.0 <= k <= total_duration_sec])
        if 0.0 not in sorted_kf:
            sorted_kf.insert(0, 0.0)

        cur_start = 0.0
        while cur_start < total_duration_sec:
            target_next = cur_start + segment_duration_sec
            if target_next >= total_duration_sec:
                seg_dur = max(0.1, total_duration_sec - cur_start)
                segments.append((cur_start, seg_dur))
                break

            candidates = [k for k in sorted_kf if k > cur_start + 0.5]
            if candidates:
                best_kf = min(candidates, key=lambda k: abs(k - target_next))
                if abs(best_kf - target_next) <= (segment_duration_sec * 0.7):
                    next_start = best_kf
                else:
                    next_start = target_next
            else:
                next_start = target_next

            next_start = min(total_duration_sec, next_start)
            seg_dur = round(next_start - cur_start, 3)
            segments.append((cur_start, seg_dur))
            cur_start = next_start
    else:
        total_segments = max(1, int(total_duration_sec / segment_duration_sec))
        for i in range(total_segments):
            start_time = i * segment_duration_sec
            seg_dur = min(segment_duration_sec, total_duration_sec - start_time) if total_duration_sec > start_time else segment_duration_sec
            segments.append((start_time, seg_dur))

    max_seg_dur = max([s[1] for s in segments], default=segment_duration_sec)
    target_duration = max(int(segment_duration_sec), int(math.ceil(max_seg_dur)))

    lines = [
        "#EXTM3U",
        f"#EXT-X-VERSION:{7 if prefer_fmp4 else 3}",
        f"#EXT-X-TARGETDURATION:{target_duration}",
        "#EXT-X-MEDIA-SEQUENCE:0",
        "#EXT-X-PLAYLIST-TYPE:VOD",
    ]

    if prefer_fmp4:
        init_url = f"/api/v1/stream/hls/init.mp4?info_hash={info_hash}&file_idx={file_idx}"
        if magnet:
            init_url += f"&magnet={urllib.parse.quote(magnet)}"
        lines.append(f'#EXT-X-MAP:URI="{init_url}"')

    for i, (start_time, seg_dur) in enumerate(segments):
        lines.append(f"#EXTINF:{seg_dur:.1f},")
        seg_url = f"/api/v1/stream/hls/segment?info_hash={info_hash}&file_idx={file_idx}&segment_idx={i}&duration={seg_dur:.2f}&start={start_time:.2f}"
        if prefer_fmp4:
            seg_url += "&format=fmp4"
        if magnet:
            seg_url += f"&magnet={urllib.parse.quote(magnet)}"
        if season is not None:
            seg_url += f"&season={season}"
        if episode is not None:
            seg_url += f"&episode={episode}"
        lines.append(seg_url)

    lines.append("#EXT-X-ENDLIST")
    return "\n".join(lines)


def sanitize_webvtt_content(vtt_text: str) -> str:
    """
    Cleans WebVTT content converted from Matroska ASS/SSA subtitles.
    Strips ASS vector drawing paths (e.g. 'm -5 0 l -51 0...') and removes blank/redundant cues.
    Deduplicates karaoke repeats, reducing cue volume from ~100k down to pure dialogue lines (~500-2500),
    preventing browser UI freezes and rendering clean dialogue text.
    """
    if not vtt_text or not vtt_text.strip():
        return "WEBVTT\n\nNOTE Empty subtitle track\n"

    lines = vtt_text.splitlines()
    output = ["WEBVTT\n"]
    time_regex = re.compile(r"^\s*(?:(?:\d{1,2}:)?\d{2}:\d{2}[,.]\d{3})\s*-->\s*(?:(?:\d{1,2}:)?\d{2}:\d{2}[,.]\d{3})")
    drawing_regex = re.compile(r"^m\s+[-0-9\s]+[lbcsp]", re.IGNORECASE)
    drawing_pure = re.compile(r"^[m\s\-0-9lbcsp]+$", re.IGNORECASE)

    current_timestamp = None
    current_text = []
    last_text = None
    last_time = None

    for raw_line in lines:
        line = raw_line.strip()
        if not line or line.startswith("WEBVTT") or line.startswith("NOTE") or line.startswith("STYLE") or line.startswith("REGION"):
            continue

        if time_regex.match(line):
            if current_timestamp and current_text:
                dia = "\n".join(current_text).strip()
                if dia and not drawing_regex.match(dia) and not (drawing_pure.match(dia) and len(dia) > 20):
                    if dia != last_text or current_timestamp != last_time:
                        output.append(f"{current_timestamp}\n{dia}\n")
                        last_text = dia
                        last_time = current_timestamp
                current_text = []
            current_timestamp = line
        elif current_timestamp:
            if not re.match(r"^\d+$", line):
                clean_line = re.sub(r"\{[^}]*\}", "", line).strip()
                if clean_line:
                    current_text.append(clean_line)

    if current_timestamp and current_text:
        dia = "\n".join(current_text).strip()
        if dia and not drawing_regex.match(dia) and not (drawing_pure.match(dia) and len(dia) > 20):
            if dia != last_text:
                output.append(f"{current_timestamp}\n{dia}\n")

    return "\n".join(output)


async def extract_embedded_subtitle_vtt(source_url: str, sub_stream_index: int = 0) -> str:
    """
    Extracts an embedded subtitle stream from MKV/MP4 using FFmpeg and converts it to WebVTT format on stdout.
    """
    ffmpeg_bin = find_ffmpeg()
    if not ffmpeg_bin:
        return "WEBVTT\n\nNOTE FFmpeg binary not found on host\n"

    cmd = [
        ffmpeg_bin,
        "-y",
        "-loglevel", "error",
    ]
    if source_url.startswith("http"):
        cmd.extend([
            "-reconnect", "1",
            "-reconnect_at_eof", "1",
            "-reconnect_streamed", "1",
            "-reconnect_on_network_error", "1",
            "-reconnect_delay_max", "5",
        ])
    cmd.extend([
        "-probesize", "1000000",
        "-analyzeduration", "1000000",
        "-i", source_url,
        "-vn", "-an",
        "-map", f"0:s:{sub_stream_index}",
        "-f", "webvtt",
        "-",
    ])

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=8.0)
        except asyncio.TimeoutError:
            try:
                proc.terminate()
            except Exception:
                pass
            stdout, stderr = await proc.communicate()

        text = stdout.decode("utf-8", errors="replace") if stdout else ""
        err_text = stderr.decode("utf-8", errors="replace").lower() if stderr else ""
        if text.strip() and ("-->" in text or "WEBVTT" in text):
            return sanitize_webvtt_content(text)
        if "bitmap" in err_text or "pgs" in err_text:
            return (
                "WEBVTT\n\n"
                "00:00:01.000 --> 00:00:08.000\n"
                "[Bitmap PGS Subtitle: Image-based track cannot be rendered in HTML5 video. Please select a text subtitle (SRT) from the drawer or launch in VLC/MPV]\n"
            )
        return "WEBVTT\n\nNOTE Empty or unsupported embedded subtitle track\n"
    except Exception as e:
        return f"WEBVTT\n\nNOTE Extraction error: {str(e)}\n"


async def extract_embedded_sup_stream(source_url: str, sub_stream_index: int = 0) -> AsyncGenerator[bytes, None]:
    """
    Extracts an embedded PGS bitmap stream into binary SUP format via direct stream copy.
    Enables low-overhead client-side decoding onto HTML5 Canvas without server re-encoding.
    """
    ffmpeg_bin = find_ffmpeg() or "ffmpeg"
    cmd = [
        ffmpeg_bin,
        "-y",
        "-loglevel", "error",
    ]
    if source_url.startswith("http"):
        cmd.extend([
            "-reconnect", "1",
            "-reconnect_at_eof", "1",
            "-reconnect_streamed", "1",
            "-reconnect_on_network_error", "1",
            "-reconnect_delay_max", "5",
        ])
    cmd.extend([
        "-probesize", "500000",
        "-analyzeduration", "1000000",
        "-i", source_url,
        "-vn", "-an",
        "-map", f"0:s:{sub_stream_index}",
        "-c:s", "copy",
        "-f", "sup",
        "pipe:1",
    ])

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
    )
    try:
        while True:
            chunk = await proc.stdout.read(65536)
            if not chunk:
                break
            yield chunk
    except (asyncio.CancelledError, GeneratorExit):
        pass
    finally:
        if proc.returncode is None:
            try:
                proc.kill()
            except Exception:
                pass


def find_external_player(player_name: str) -> Optional[str]:
    """Finds path for external player (vlc, mpv, mpc-hc, potplayer)."""
    name = (player_name or "").lower().strip()
    if name == "vlc":
        return find_vlc()
    elif name == "mpv":
        cands = [
            shutil.which("mpv"),
            r"C:\Program Files\mpv\mpv.exe",
            r"C:\Program Files (x86)\mpv\mpv.exe",
            os.path.expandvars(r"%LOCALAPPDATA%\Programs\mpv\mpv.exe"),
            os.path.expandvars(r"%APPDATA%\mpv\mpv.exe"),
        ]
        return next((c for c in cands if c and os.path.isfile(c)), None)
    elif name in ("mpc", "mpc-hc", "mpchc"):
        cands = [
            shutil.which("mpc-hc64"),
            shutil.which("mpc-hc"),
            r"C:\Program Files\MPC-HC\mpc-hc64.exe",
            r"C:\Program Files (x86)\MPC-HC\mpc-hc.exe",
            r"C:\Program Files\K-Lite Codec Pack\MPC-HC64\mpc-hc64.exe",
            r"C:\Program Files (x86)\K-Lite Codec Pack\MPC-HC\mpc-hc.exe",
        ]
        return next((c for c in cands if c and os.path.isfile(c)), None)
    elif name in ("potplayer", "pot"):
        cands = [
            shutil.which("PotPlayer64"),
            shutil.which("PotPlayer"),
            r"C:\Program Files\DAUM\PotPlayer\PotPlayer64.exe",
            r"C:\Program Files (x86)\DAUM\PotPlayer\PotPlayer.exe",
        ]
        return next((c for c in cands if c and os.path.isfile(c)), None)
    return None


def launch_external_player_process(player_name: str, stream_url: str, title: str = "EvoStream") -> bool:
    """Launches an external player process with stream URL and window title."""
    name = (player_name or "vlc").lower().strip()
    if name == "vlc":
        return launch_vlc_process(stream_url, title)

    player_bin = find_external_player(name)
    if not player_bin:
        return False

    import tempfile
    temp_dir = os.path.join(tempfile.gettempdir(), "evoscrapper")
    os.makedirs(temp_dir, exist_ok=True)
    safe_title = "".join(c for c in title if c.isalnum() or c in " ._-")[:40] or "EvoStream"
    temp_m3u = os.path.join(temp_dir, f"{safe_title}.m3u")
    try:
        with open(temp_m3u, "w", encoding="utf-8") as f:
            f.write(f"#EXTM3U\n#EXTINF:-1,{title}\n{stream_url}\n")
    except Exception:
        pass

    try:
        target = temp_m3u if os.path.isfile(temp_m3u) else stream_url
        if name == "mpv":
            cmd = [player_bin, f"--title={title}", target]
        elif name in ("mpc", "mpc-hc", "mpchc"):
            cmd = [player_bin, target]
        elif name in ("potplayer", "pot"):
            cmd = [player_bin, target]
        else:
            cmd = [player_bin, target]

        subprocess.Popen(
            cmd,
            creationflags=subprocess.DETACHED_PROCESS if os.name == "nt" else 0,
            close_fds=True,
        )
        return True
    except Exception as e:
        print(f"[TorrentStreamer] {player_name} launch error: {e}")
        return False
