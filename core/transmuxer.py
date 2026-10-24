import asyncio
import os
import re
import shutil
import subprocess
from typing import AsyncGenerator, List, Optional


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
                is_bitmap = cname.lower() in ("hdmv_pgs_subtitle", "dvd_subtitle", "pgssub", "vobsub")
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



_FFMPEG_SEMAPHORE = asyncio.Semaphore(4)


async def stream_transmuxed_video(
    source_url_or_path: str,
    start_seconds: float = 0.0,
    duration_seconds: Optional[float] = None,
    transcode_video: bool = False,
    burn_sub_idx: Optional[int] = None,
    audio_track: int = 0,
    audio_boost: float = 1.25,
    chunk_size: int = 65536,
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
            "-reconnect_delay_max", "5",
        ])

    cmd.extend([
        "-probesize", "262144",        # 256KB probe for ultra-fast stream startup
        "-analyzeduration", "500000",  # 0.5s header analysis
    ])

    if start_seconds > 0:
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

    cmd.extend([
        "-c:v", "libx264" if transcode_video else "copy",
    ])

    if transcode_video:
        cmd.extend([
            "-preset", "ultrafast",
            "-tune", "zerolatency",
            "-pix_fmt", "yuv420p",
            "-crf", "22",
        ])

    # Build audio filter chain:
    # 1. aresample=async=1000 locks audio timestamps to video frames to prevent drift/silence
    # 2. volume boost restores center channel dialogue lost during 5.1/7.1 downmix
    af_filters = ["aresample=async=1000"]
    if audio_boost and audio_boost > 0:
        af_filters.append(f"volume={audio_boost:.2f}")

    cmd.extend([
        "-c:a", "aac",
        "-b:a", "192k",
        "-ac", "2",                     # Downmix to 2-channel stereo for 100% browser compatibility
        "-af", ",".join(af_filters),
        "-sn",                          # Strip embedded subtitles to prevent MP4 container muxing errors
        "-dn",                          # Strip data streams
        "-movflags", "frag_keyframe+default_base_moof",
        "-flush_packets", "1",
        "-f", "mp4",
        "pipe:1",
    ])

    async with _FFMPEG_SEMAPHORE:
        # Use DEVNULL for stderr to prevent pipe buffer deadlocks (which hang ffmpeg when logging warnings)
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


async def stream_hls_ts_segment(
    source_url_or_path: str,
    start_seconds: float = 0.0,
    duration_seconds: float = 6.0,
    chunk_size: int = 65536,
) -> AsyncGenerator[bytes, None]:
    """
    Extracts an individual MPEG-TS segment for HLS streaming.
    Constrains processing strictly to duration_seconds using -ss and -t with -f mpegts.
    """
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
            "-reconnect_delay_max", "5",
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


def generate_hls_manifest(
    info_hash: str,
    total_duration_sec: float = 7200.0,
    segment_duration_sec: float = 6.0,
    file_idx: int = 0,
    magnet: Optional[str] = None,
    season: Optional[int] = None,
    episode: Optional[int] = None,
) -> str:
    """Generates an RFC 8216 compliant HLS VOD playlist with virtual segment references."""
    import urllib.parse
    target_duration = int(segment_duration_sec)
    total_segments = max(1, int(total_duration_sec / segment_duration_sec))

    lines = [
        "#EXTM3U",
        "#EXT-X-VERSION:3",
        f"#EXT-X-TARGETDURATION:{target_duration}",
        "#EXT-X-MEDIA-SEQUENCE:0",
        "#EXT-X-PLAYLIST-TYPE:VOD",
    ]

    for i in range(total_segments):
        start_time = i * segment_duration_sec
        seg_dur = min(segment_duration_sec, total_duration_sec - start_time) if total_duration_sec > start_time else segment_duration_sec
        lines.append(f"#EXTINF:{seg_dur:.1f},")
        seg_url = f"/api/v1/stream/hls/segment?info_hash={info_hash}&file_idx={file_idx}&segment_idx={i}&duration={seg_dur}&start={start_time:.2f}"
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
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=20.0)
        text = stdout.decode("utf-8", errors="replace")
        err_text = stderr.decode("utf-8", errors="replace").lower()
        if text.strip():
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
