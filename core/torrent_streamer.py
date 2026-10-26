import asyncio
import base64
import datetime
import hashlib
import hmac
import os
import re
import secrets
import subprocess
import sys
import time
import urllib.parse
from typing import Any, Dict, List, Optional
import aiohttp
from core.logger import get_logs_dir, streaming_logger

from config import settings

STREAM_PORT = getattr(settings, "STREAM_PORT", 8889)
TORRENT_PORT = getattr(settings, "TORRENT_PORT", 50000)
DHT_PORT = getattr(settings, "DHT_PORT", 50001)
DAEMON_URL = f"http://127.0.0.1:{STREAM_PORT}"
REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
STREAMER_DIR = os.path.abspath(os.path.join(REPO_ROOT, "streamer"))
SERVER_SCRIPT = os.path.join(STREAMER_DIR, "server.js")
STREAM_URL_TTL_SECONDS = int(getattr(settings, "STREAM_URL_TTL_SECONDS", 1800))

_daemon_process: Optional[subprocess.Popen] = None
_session: Optional[aiohttp.ClientSession] = None
_streamer_token: Optional[str] = None
_anonymous_daemon_warned = False


def get_stream_cache_dir() -> str:
    """Resolves the shared Python/Node cache directory, honoring test overrides."""
    configured = os.environ.get("EVO_STREAM_CACHE_DIR") or getattr(
        settings, "STREAM_CACHE_DIR", ".stream_cache"
    )
    if os.path.isabs(configured):
        return configured
    return os.path.abspath(os.path.join(REPO_ROOT, configured))


def get_streamer_token(force_reload: bool = False) -> str:
    """Returns the daemon shared secret, persisting a generated one for restarts."""
    global _streamer_token
    if _streamer_token and not force_reload:
        return _streamer_token

    env_token = os.environ.get("EVO_STREAMER_TOKEN") or os.environ.get("STREAMER_TOKEN")
    configured = env_token or getattr(settings, "STREAMER_TOKEN", None)
    if configured and str(configured).strip():
        _streamer_token = str(configured).strip()
        return _streamer_token

    cache_dir = get_stream_cache_dir()
    token_path = os.path.join(cache_dir, "streamer.token")
    token = ""
    try:
        if os.path.isfile(token_path):
            with open(token_path, "r", encoding="utf-8") as token_file:
                token = token_file.read().strip()
    except OSError:
        token = ""

    if not token:
        token = secrets.token_urlsafe(32)
        os.makedirs(cache_dir, exist_ok=True)
        try:
            fd = os.open(token_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as token_file:
                token_file.write(token)
        except FileExistsError:
            try:
                with open(token_path, "r", encoding="utf-8") as token_file:
                    token = token_file.read().strip() or token
            except OSError:
                pass

    _streamer_token = token
    return token


def streamer_auth_headers() -> Dict[str, str]:
    """Headers required by every daemon control-plane request."""
    return {"X-Evo-Streamer-Token": get_streamer_token()}


def sign_stream_expiry(expires: int, token: Optional[str] = None) -> str:
    """HMAC for the short-lived signed media URL accepted by the daemon."""
    secret = token if token is not None else get_streamer_token()
    return hmac.new(
        secret.encode("utf-8"),
        str(int(expires)).encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def verify_stream_signature(
    expires: int, signature: str, token: Optional[str] = None
) -> bool:
    """Validates a signed media URL expiry/signature pair."""
    try:
        expires_int = int(expires)
    except (TypeError, ValueError):
        return False
    if not signature or expires_int < int(time.time()):
        return False
    expected = sign_stream_expiry(expires_int, token=token)
    return hmac.compare_digest(expected, str(signature))


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
    """Checks liveness and authenticates against the daemon shared secret."""
    global _anonymous_daemon_warned
    try:
        session = await get_http_session()
        async with session.get(
            f"{DAEMON_URL}/health",
            headers=streamer_auth_headers(),
            timeout=aiohttp.ClientTimeout(total=1.0),
        ) as resp:
            if resp.status != 200:
                return False
            try:
                payload = await resp.json()
            except Exception:
                payload = {}
            if payload.get("auth_required") is not True:
                if not _anonymous_daemon_warned:
                    streaming_logger.warning(
                        "Streaming daemon is not enforcing shared-secret authentication; "
                        "restart it through EvoScrapper to enable the control-plane token."
                    )
                    _anonymous_daemon_warned = True
                return False
            return True
    except Exception:
        return False


def _normalized_process_path(value: Any) -> str:
    return os.path.normcase(os.path.normpath(str(value))).replace("\\", "/")


def is_node_streamer_pid(pid: int, expected_script: str = SERVER_SCRIPT) -> bool:
    """Verifies that a PID is this repository's Node.js streamer process.

    A bare `node` process is never sufficient: killing the wrong Node process
    would terminate unrelated user work. The command line must reference the
    expected script, or the process must have been launched with a relative
    `server.js` from the streamer directory.
    """
    try:
        import psutil

        proc = psutil.Process(pid)
        name = (proc.name() or "").lower()
        cmdline = [str(part) for part in (proc.cmdline() or [])]
        if not cmdline:
            return False
        executable = os.path.basename(cmdline[0]).lower()
        if "node" not in name and "node" not in executable:
            return False

        expected = _normalized_process_path(expected_script)
        if any(expected in _normalized_process_path(part) for part in cmdline):
            return True

        script_name = os.path.basename(expected_script).lower()
        if os.path.basename(cmdline[-1]).lower() == script_name:
            try:
                cwd = _normalized_process_path(proc.cwd())
            except Exception:
                cwd = ""
            return cwd == _normalized_process_path(STREAMER_DIR)
        return False
    except Exception:
        return False


def find_available_stream_port(preferred_port: int = 8889) -> int:
    """Finds an open loopback port in range preferred_port..preferred_port+9."""
    import socket
    for port in range(preferred_port, preferred_port + 10):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    return preferred_port


def kill_stale_daemon(target_port: Optional[int] = None):
    """Kills any stale process on stream port ONLY if it is verified to be a Node.js streaming daemon."""
    global STREAM_PORT, DAEMON_URL
    port_to_check = target_port or STREAM_PORT
    if os.name == "nt":
        for port in (port_to_check, TORRENT_PORT, DHT_PORT):
            try:
                out = subprocess.check_output(f"netstat -ano | findstr :{port}", shell=True, text=True)
                for line in out.strip().splitlines():
                    if "LISTENING" in line:
                        parts = line.strip().split()
                        pid = int(parts[-1])
                        if pid > 0 and pid != os.getpid():
                            if is_node_streamer_pid(pid):
                                subprocess.run(f"taskkill /F /PID {pid}", shell=True, capture_output=True)
                            else:
                                streaming_logger.warning(
                                    f"Port {port} is occupied by foreign process PID {pid}. Not killing. Selecting fallback port."
                                )
                                if port == port_to_check:
                                    fallback = find_available_stream_port(8890)
                                    STREAM_PORT = fallback
                                    DAEMON_URL = f"http://127.0.0.1:{STREAM_PORT}"
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
        env["PORT"] = str(STREAM_PORT)
        env["STREAM_PORT"] = str(STREAM_PORT)
        env["TORRENT_PORT"] = str(TORRENT_PORT)
        env["DHT_PORT"] = str(DHT_PORT)
        env["EVO_STREAM_BIND_HOST"] = getattr(settings, "STREAM_BIND_HOST", "127.0.0.1")
        env["EVO_STREAM_CACHE_DIR"] = get_stream_cache_dir()
        env["EVO_STREAMER_TOKEN"] = get_streamer_token()
        streaming_logger.info(
            f"Spawning Node.js streaming daemon (ports: stream={STREAM_PORT}, "
            f"torrent={TORRENT_PORT}, dht={DHT_PORT}, bind={env['EVO_STREAM_BIND_HOST']})"
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
    """Cleanly stops the background Node.js streaming micro-daemon we spawned."""
    global _daemon_process
    if _daemon_process:
        pid = getattr(_daemon_process, "pid", None)
        if pid and not is_node_streamer_pid(pid):
            streaming_logger.warning(
                f"Refusing to terminate PID {pid}: it is not the verified streamer process."
            )
            _daemon_process = None
            return
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
    duration: Optional[float] = None,
    stage_seconds: Optional[float] = None,
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
        if duration is not None and duration > 0:
            params["duration"] = duration
        if stage_seconds is not None and stage_seconds > 0:
            params["stage_seconds"] = stage_seconds
        async with session.get(
            f"{DAEMON_URL}/warm",
            params=params,
            headers=streamer_auth_headers(),
            timeout=aiohttp.ClientTimeout(total=4.0),
        ) as resp:
            if resp.status == 200:
                return await resp.json()
            return None
    except Exception:
        return None


async def push_stream_metadata(
    info_hash: str,
    file_idx: int = 0,
    duration: Optional[float] = None,
    bitrate_bps: Optional[int] = None,
) -> Optional[Dict[str, Any]]:
    """
    Feeds measured media metadata (ffprobe duration/bitrate) into the daemon
    scheduler session so piece windows are sized by the real bitrate.
    Metadata-only: the reader sliding windows are left untouched.
    """
    if not info_hash or info_hash.startswith("cdn_"):
        return None
    has_duration = duration is not None and duration > 0
    has_bitrate = bitrate_bps is not None and bitrate_bps > 0
    if not has_duration and not has_bitrate:
        return None
    await ensure_streaming_daemon()
    try:
        session = await get_http_session()
        payload: Dict[str, Any] = {"hash": info_hash, "fileIdx": file_idx, "metadataOnly": True}
        if has_duration:
            payload["duration"] = duration
        if has_bitrate:
            payload["avgBitrateBps"] = bitrate_bps
        async with session.post(
            f"{DAEMON_URL}/window",
            json=payload,
            headers=streamer_auth_headers(),
            timeout=aiohttp.ClientTimeout(total=3.0),
        ) as resp:
            if resp.status == 200:
                return await resp.json()
            return None
    except Exception:
        return None


async def warm_window(
    info_hash: str,
    file_idx: int = 0,
    byte_offset: int = 0,
    start_time: Optional[float] = None,
    duration: Optional[float] = None,
    buffer_mb: Optional[int] = None,
    stage_seconds: Optional[float] = None,
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
        if start_time is not None:
            payload["startTime"] = start_time
        if duration is not None:
            payload["duration"] = duration
        if buffer_mb is not None:
            payload["bufferMb"] = buffer_mb
        if stage_seconds is not None and stage_seconds > 0:
            payload["stageSeconds"] = stage_seconds
        async with session.post(
            f"{DAEMON_URL}/window",
            json=payload,
            headers=streamer_auth_headers(),
            timeout=aiohttp.ClientTimeout(total=3.0),
        ) as resp:
            return resp.status == 200
    except Exception:
        return False


async def push_seek_hints(info_hash: str, targets: List[float]) -> bool:
    """
    P1: feeds crowd-sourced seek hotspots (seconds) into the daemon session so
    the scheduler pre-selects low-priority pieces around them.
    """
    if not info_hash or info_hash.startswith("cdn_") or not targets:
        return False
    await ensure_streaming_daemon()
    try:
        session = await get_http_session()
        async with session.post(
            f"{DAEMON_URL}/seek-hints",
            json={"hash": info_hash, "targets": list(targets)[:4]},
            headers=streamer_auth_headers(),
            timeout=aiohttp.ClientTimeout(total=2.0),
        ) as resp:
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
        async with session.get(
            f"{DAEMON_URL}/files",
            params=params,
            headers=streamer_auth_headers(),
            timeout=aiohttp.ClientTimeout(total=20.0),
        ) as resp:
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
        async with session.get(
            f"{DAEMON_URL}/status",
            headers=streamer_auth_headers(),
            timeout=aiohttp.ClientTimeout(total=2.0),
        ) as resp:
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
    """Generates a short-lived signed loopback streaming URL for the P2P engine."""
    url = f"{DAEMON_URL}/stream?info_hash={info_hash}&file_idx={file_idx}"
    if magnet and isinstance(magnet, str):
        url += f"&magnet={urllib.parse.quote(magnet)}"
    if season is not None:
        url += f"&season={season}"
    if episode is not None:
        url += f"&episode={episode}"
    if buffer_mb is not None and isinstance(buffer_mb, int):
        url += f"&buffer_mb={buffer_mb}"
    expires = int(time.time()) + STREAM_URL_TTL_SECONDS
    url += f"&expires={expires}&sig={sign_stream_expiry(expires)}"
    return url
