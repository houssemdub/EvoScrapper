import asyncio
import base64
import datetime
import os
import re
import subprocess
import sys
import urllib.parse
from typing import Any, Dict, List, Optional
import aiohttp
from core.logger import get_logs_dir, streaming_logger

STREAM_PORT = 8889
TORRENT_PORT = 50000
DHT_PORT = 50001
DAEMON_URL = f"http://127.0.0.1:{STREAM_PORT}"
STREAMER_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "streamer"))
SERVER_SCRIPT = os.path.join(STREAMER_DIR, "server.js")

_daemon_process: Optional[subprocess.Popen] = None
_session: Optional[aiohttp.ClientSession] = None


def canonical_hash(magnet_or_hash: str) -> str:
    """Extracts standard 40-char lowercase hex info_hash from raw hash or magnet URI."""
    s = (magnet_or_hash or "").strip()
    if s.startswith("magnet:?"):
        m = re.search(r"xt=urn:btih:([0-9a-fA-F]{40})", s)
        if m:
            return m.group(1).lower()
        m32 = re.search(r"xt=urn:btih:([2-7A-Za-z]{32})", s)
        if m32:
            try:
                decoded = base64.b32decode(m32.group(1).upper())
                return decoded.hex().lower()
            except Exception:
                pass
    if len(s) == 40 and re.match(r"^[0-9a-fA-F]{40}$", s):
        return s.lower()
    if len(s) == 32 and re.match(r"^[2-7A-Za-z]{32}$", s):
        try:
            return base64.b32decode(s.upper()).hex().lower()
        except Exception:
            pass
    return None


def is_direct_streamable(filename_or_title: str) -> bool:
    """
    Evaluates whether a video stream can be directly played in the browser
    via HTTP 206 partial content without invoking the FFmpeg transmuxing pipeline.
    Browser-native codecs: MP4 (H.264/AAC/MP3) or WebM (VP8/VP9/AV1/Opus).
    Requires FFmpeg transmuxing: MKV, AVI, HEVC/x265, 10-bit, AC3, DTS, 5.1/7.1 audio.
    """
    if not filename_or_title:
        return False
    name = str(filename_or_title).lower()

    # MKV, AVI, TS containers require remuxing for standard HTML5 <video>
    if name.endswith('.mkv') or name.endswith('.avi') or name.endswith('.ts') or name.endswith('.mov'):
        return False
    if re.search(r'\b(mkv|matroska|avi|xvid|divx)\b', name):
        return False

    # Codecs unsupported directly in standard web browsers
    if re.search(r'\b(x265|hevc|h265|10-?bit|hi10p)\b', name):
        return False

    # Audio formats unsupported natively in HTML5 video elements
    if re.search(r'\b(ddp|eac-?3|ac-?3|dts|truehd|atmos|flac|[257]\.[01]|surround)\b', name):
        return False

    # Native WebM with VP8/VP9/AV1 + Opus/Vorbis
    if name.endswith('.webm') or re.search(r'\b(webm|vp8|vp9|opus)\b', name):
        return True

    # Native MP4 with H.264 / AV1 + AAC / MP3
    if name.endswith('.mp4') or name.endswith('.m4v') or re.search(r'\b(mp4|aac|mp3|yts|yify|x264|h264|avc)\b', name):
        return True

    return False


async def get_http_session() -> aiohttp.ClientSession:
    """Returns a module-level persistent aiohttp ClientSession."""
    global _session
    if _session is None or _session.closed:
        connector = aiohttp.TCPConnector(limit=100, keepalive_timeout=30)
        _session = aiohttp.ClientSession(connector=connector)
    return _session


async def is_daemon_healthy() -> bool:
    """Checks if the Node.js streaming micro-daemon is responding."""
    try:
        session = await get_http_session()
        async with session.get(f"{DAEMON_URL}/health", timeout=aiohttp.ClientTimeout(total=1.0)) as resp:
            return resp.status == 200
    except Exception:
        return False


def kill_stale_daemon():
    """Kills any stale or deadlocked process listening on the streamer (8889), torrent wire (50000), or DHT (50001) ports."""
    if os.name == "nt":
        for port in (STREAM_PORT, 50000, 50001):
            try:
                out = subprocess.check_output(f"netstat -ano | findstr :{port}", shell=True, text=True)
                for line in out.strip().splitlines():
                    if "LISTENING" in line:
                        parts = line.strip().split()
                        pid = int(parts[-1])
                        if pid > 0 and pid != os.getpid():
                            subprocess.run(f"taskkill /F /PID {pid}", shell=True, capture_output=True)
            except Exception:
                pass


def start_daemon_process() -> bool:
    """Spawns the background Node.js P2P torrent streaming micro-daemon."""
    global _daemon_process
    if not os.path.isfile(SERVER_SCRIPT):
        return False

    kill_stale_daemon()

    try:
        creationflags = (0x08000000 | 0x00000008) if os.name == "nt" else 0  # CREATE_NO_WINDOW | DETACHED_PROCESS
        today = datetime.datetime.now().strftime("%Y-%m-%d")
        logs_dir = get_logs_dir()
        log_path = os.path.join(logs_dir, f"streaming_{today}.log")
        generic_path = os.path.join(logs_dir, "streaming.log")
        # Ensure daemon output is captured in both dated and primary streaming logs
        log_file = open(log_path, "a", encoding="utf-8")
        env = os.environ.copy()
        env["STREAM_PORT"] = str(STREAM_PORT)
        env["TORRENT_PORT"] = str(TORRENT_PORT)
        env["DHT_PORT"] = str(DHT_PORT)
        streaming_logger.info(
            f"Spawning Node.js streaming daemon (ports: stream={STREAM_PORT}, torrent={TORRENT_PORT}, dht={DHT_PORT})"
        )
        _daemon_process = subprocess.Popen(
            ["node", SERVER_SCRIPT],
            cwd=STREAMER_DIR,
            stdout=log_file,
            stderr=log_file,
            env=env,
            creationflags=creationflags,
        )
        return True
    except Exception as e:
        streaming_logger.error(f"Failed to spawn node daemon: {e}")
        print(f"[TorrentStreamer] Failed to spawn node daemon: {e}")
        return False


async def ensure_streaming_daemon() -> bool:
    """Guarantees that the streaming engine is up and running."""
    if await is_daemon_healthy():
        return True

    started = start_daemon_process()
    if not started:
        return False

    for _ in range(12):
        await asyncio.sleep(0.4)
        if await is_daemon_healthy():
            return True

    return False


def stop_daemon_process():
    """Cleanly stops the background Node.js streaming micro-daemon."""
    global _daemon_process
    if _daemon_process:
        try:
            _daemon_process.terminate()
            _daemon_process.wait(timeout=2.0)
        except Exception:
            try:
                _daemon_process.kill()
            except Exception:
                pass
        _daemon_process = None


async def warm_torrent(
    info_hash: str,
    file_idx: int = 0,
    magnet: Optional[str] = None,
    season: Optional[int] = None,
    episode: Optional[int] = None,
) -> Optional[Dict[str, Any]]:
    """Pre-warms the torrent swarm and pre-buffers headers in background."""
    if not info_hash or info_hash.startswith("cdn_"):
        return None
    await ensure_streaming_daemon()
    try:
        session = await get_http_session()
        params: Dict[str, Any] = {"info_hash": info_hash, "file_idx": file_idx}
        if magnet:
            params["magnet"] = magnet
        if season is not None:
            params["season"] = season
        if episode is not None:
            params["episode"] = episode
        async with session.get(f"{DAEMON_URL}/warm", params=params, timeout=aiohttp.ClientTimeout(total=4.0)) as resp:
            if resp.status == 200:
                return await resp.json()
            return None
    except Exception:
        return None


async def warm_window(
    info_hash: str,
    file_idx: int = 0,
    byte_offset: int = 0,
    buffer_mb: Optional[int] = None,
) -> bool:
    """Explicitly signals the torrent engine to align its sliding window around a seek offset [Phase 2]."""
    if not info_hash or info_hash.startswith("cdn_"):
        return False
    await ensure_streaming_daemon()
    try:
        session = await get_http_session()
        payload: Dict[str, Any] = {
            "hash": info_hash,
            "fileIdx": file_idx,
            "byteOffset": byte_offset,
        }
        if buffer_mb is not None:
            payload["bufferMb"] = buffer_mb
        async with session.post(f"{DAEMON_URL}/window", json=payload, timeout=aiohttp.ClientTimeout(total=3.0)) as resp:
            return resp.status == 200
    except Exception:
        return False


async def get_torrent_files(magnet_or_hash: str, magnet: Optional[str] = None) -> List[Dict[str, Any]]:
    """Resolves torrent metadata and returns the list of playable files."""
    if not magnet_or_hash or magnet_or_hash.startswith("cdn_"):
        return []
    await ensure_streaming_daemon()
    try:
        session = await get_http_session()
        params: Dict[str, Any] = {"info_hash": magnet_or_hash}
        if magnet:
            params["magnet"] = magnet
        async with session.get(f"{DAEMON_URL}/files", params=params, timeout=aiohttp.ClientTimeout(total=20.0)) as resp:
            if resp.status == 200:
                data = await resp.json()
                return data.get("files") or []
    except Exception:
        pass
    return []


async def get_daemon_status() -> Dict[str, Any]:
    """Returns streaming swarm stats, active torrents, speeds, and buffer status."""
    if not await is_daemon_healthy():
        return {"status": "offline", "active_torrents": 0, "sessions": []}
    try:
        session = await get_http_session()
        async with session.get(f"{DAEMON_URL}/status", timeout=aiohttp.ClientTimeout(total=2.0)) as resp:
            if resp.status == 200:
                return await resp.json()
    except Exception:
        pass
    return {"status": "error", "active_torrents": 0, "sessions": []}


def get_internal_stream_url(
    info_hash: str,
    file_idx: int = 0,
    magnet: Optional[str] = None,
    season: Optional[int] = None,
    episode: Optional[int] = None,
    buffer_mb: Optional[int] = None,
) -> str:
    """Generates the direct loopback streaming URL for the P2P engine."""
    url = f"{DAEMON_URL}/stream?info_hash={info_hash}&file_idx={file_idx}"
    if magnet and isinstance(magnet, str):
        url += f"&magnet={urllib.parse.quote(magnet)}"
    if season is not None:
        url += f"&season={season}"
    if episode is not None:
        url += f"&episode={episode}"
    if buffer_mb is not None and isinstance(buffer_mb, int):
        url += f"&buffer_mb={buffer_mb}"
    return url
