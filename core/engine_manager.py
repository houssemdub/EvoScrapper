"""
core/engine_manager.py — Multi-Engine Streaming Orchestrator for EvoScrapper
Manages native Rust (evostreamer-rs), Node.js (WebTorrent), and Python (Asyncio)
streaming daemons with dynamic health detection, automatic fallback, and live hot-swapping.
"""

import asyncio
import datetime
import enum
import os
import shutil
import subprocess
import time
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional
import aiohttp

from config import settings
from core.logger import streaming_logger

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


class EngineType(str, enum.Enum):
    RUST = "rust"
    NODE = "node"
    PYTHON = "python"
    AUTO = "auto"


def _get_streamer_token() -> str:
    from core.torrent_streamer import get_streamer_token
    return get_streamer_token()


def _streamer_auth_headers() -> Dict[str, str]:
    from core.torrent_streamer import streamer_auth_headers
    return streamer_auth_headers()


def _get_stream_cache_dir() -> str:
    from core.torrent_streamer import get_stream_cache_dir
    return get_stream_cache_dir()


class BaseStreamingEngine(ABC):
    name: str = "base"
    display_name: str = "Base Streaming Engine"
    port: int = 8889
    description: str = ""

    def __init__(self, port: int):
        self.port = port
        self._process: Optional[subprocess.Popen] = None

    @property
    def url(self) -> str:
        bind_host = getattr(settings, "STREAM_BIND_HOST", "127.0.0.1")
        display_host = "127.0.0.1" if bind_host in ("0.0.0.0", "::") else bind_host
        return f"http://{display_host}:{self.port}"

    @abstractmethod
    def is_installed(self) -> bool:
        """Returns True if the engine's executable / script exists on disk."""
        pass

    @abstractmethod
    async def is_healthy(self) -> bool:
        """Checks whether the daemon is listening and passes token authentication."""
        pass

    @abstractmethod
    def start(self) -> bool:
        """Launches the engine process."""
        pass

    @abstractmethod
    def stop(self) -> None:
        """Terminates the engine process."""
        pass

    async def ensure_started(self) -> bool:
        if await self.is_healthy():
            return True
        if not self.is_installed():
            return False
        started = self.start()
        if not started:
            return False
        for _ in range(12):
            await asyncio.sleep(0.3)
            if await self.is_healthy():
                return True
        return False

    def get_stream_url(self, info_hash: str, file_idx: int = 0) -> str:
        from core.torrent_streamer import sign_stream_expiry
        ttl = int(getattr(settings, "STREAM_URL_TTL_SECONDS", 1800))
        expires = int(time.time()) + ttl
        sig = sign_stream_expiry(expires)
        return f"{self.url}/stream?info_hash={info_hash}&file_idx={file_idx}&expires={expires}&sig={sig}"

    async def get_stats(self, info_hash: Optional[str] = None, file_idx: Optional[int] = None) -> Optional[Dict[str, Any]]:
        try:
            from core.torrent_streamer import get_http_session
            session = await get_http_session()
            path = f"/{info_hash}/{file_idx or 0}/stats.json" if info_hash else "/stats.json"
            async with session.get(
                f"{self.url}{path}",
                headers=_streamer_auth_headers(),
                timeout=aiohttp.ClientTimeout(total=2.0),
            ) as resp:
                if resp.status == 200:
                    return await resp.json()
        except Exception:
            pass
        return None

    def get_diagnostics(self) -> Dict[str, Any]:
        rss_mb = None
        if self._process and self._process.pid:
            try:
                import psutil
                proc = psutil.Process(self._process.pid)
                rss_mb = round(proc.memory_info().rss / (1024 * 1024), 2)
            except Exception:
                pass
        return {
            "name": self.name,
            "display_name": self.display_name,
            "available": self.is_installed(),
            "port": self.port,
            "url": self.url,
            "pid": self._process.pid if self._process else None,
            "memory_mb": rss_mb,
            "description": self.description,
        }


class RustStreamingEngine(BaseStreamingEngine):
    name = "rust"
    display_name = "⚡ Rust Native Engine (evostreamer-rs)"
    description = "Ultra-fast zero-copy memory-mapped stream daemon (<15MB RAM, 0ms GC pauses)"

    def __init__(self, port: Optional[int] = None):
        super().__init__(port or getattr(settings, "STREAM_PORT_RUST", 8891))

    def get_binary_path(self) -> Optional[str]:
        # 1. Configured path
        cfg = getattr(settings, "RUST_STREAMER_BIN", None)
        if cfg and os.path.isfile(cfg):
            return os.path.abspath(cfg)

        # 2. Local cargo target release/debug
        exe_name = "evostreamer.exe" if os.name == "nt" else "evostreamer"
        candidates = [
            os.path.join(REPO_ROOT, "streamer-rs", "target", "release", exe_name),
            os.path.join(REPO_ROOT, "streamer-rs", "target", "debug", exe_name),
            os.path.join(REPO_ROOT, "bin", exe_name),
        ]
        for c in candidates:
            if os.path.isfile(c):
                return c

        # 3. System PATH
        which_path = shutil.which("evostreamer")
        if which_path:
            return which_path

        return None

    def is_installed(self) -> bool:
        return self.get_binary_path() is not None

    async def is_healthy(self) -> bool:
        try:
            from core.torrent_streamer import get_http_session
            session = await get_http_session()
            async with session.get(
                f"{self.url}/health",
                headers=_streamer_auth_headers(),
                timeout=aiohttp.ClientTimeout(total=1.0),
            ) as resp:
                if resp.status == 200:
                    payload = await resp.json()
                    return payload.get("engine") == "evostreamer-rust"
        except Exception:
            pass
        return False

    def start(self) -> bool:
        bin_path = self.get_binary_path()
        if not bin_path:
            streaming_logger.warning("Rust streaming engine binary not found on disk.")
            return False

        try:
            creationflags = (0x08000000 | 0x00000008) if os.name == "nt" else 0
            env = os.environ.copy()
            env["STREAM_PORT"] = str(self.port)
            env["PORT"] = str(self.port)
            env["EVO_STREAM_BIND_HOST"] = getattr(settings, "STREAM_BIND_HOST", "127.0.0.1")
            env["EVO_STREAM_CACHE_DIR"] = _get_stream_cache_dir()
            env["EVO_STREAMER_TOKEN"] = _get_streamer_token()

            streaming_logger.info(f"Spawning Rust streaming daemon from {bin_path} on port {self.port}")
            self._process = subprocess.Popen(
                [bin_path],
                cwd=os.path.dirname(bin_path),
                env=env,
                creationflags=creationflags,
            )
            return True
        except Exception as e:
            streaming_logger.error(f"Failed to spawn Rust engine: {e}")
            return False

    def stop(self) -> None:
        if self._process:
            try:
                self._process.terminate()
                self._process.wait(timeout=1.5)
            except Exception:
                try:
                    self._process.kill()
                except Exception:
                    pass
            self._process = None


class NodeStreamingEngine(BaseStreamingEngine):
    name = "node"
    display_name = "🟢 Node.js WebTorrent Daemon"
    description = "Standard compatibility daemon using WebTorrent v3 sliding-window piece engine"

    def __init__(self, port: Optional[int] = None):
        super().__init__(port or getattr(settings, "STREAM_PORT_NODE", 8889))

    def is_installed(self) -> bool:
        server_script = os.path.join(REPO_ROOT, "streamer", "server.js")
        return os.path.isfile(server_script) and shutil.which("node") is not None

    async def is_healthy(self) -> bool:
        from core.torrent_streamer import is_daemon_healthy
        return await is_daemon_healthy()

    def start(self) -> bool:
        from core.torrent_streamer import start_daemon_process
        return start_daemon_process()

    def stop(self) -> None:
        from core.torrent_streamer import stop_daemon_process
        stop_daemon_process()


class PythonStreamingEngine(BaseStreamingEngine):
    name = "python"
    display_name = "🐍 Python Asyncio Fallback Streamer"
    description = "Zero-dependency pure Python streaming engine with RFC 7233 range parsing"

    def __init__(self, port: Optional[int] = None):
        super().__init__(port or getattr(settings, "STREAM_PORT_PYTHON", 8892))
        self._server_task: Optional[asyncio.Task] = None

    def is_installed(self) -> bool:
        return True

    async def is_healthy(self) -> bool:
        from core.py_streamer import is_py_streamer_healthy
        return await is_py_streamer_healthy(self.port)

    def start(self) -> bool:
        from core.py_streamer import start_py_streamer_daemon
        return start_py_streamer_daemon(self.port)

    def stop(self) -> None:
        from core.py_streamer import stop_py_streamer_daemon
        stop_py_streamer_daemon()


class EngineManager:
    """Manages active streaming engines, hot-swapping, and automatic fallback chains."""

    def __init__(self):
        self.configured_engine = getattr(settings, "STREAMING_ENGINE", "auto").lower()
        self.auto_fallback = getattr(settings, "AUTO_FALLBACK_ENGINES", True)
        self.engines: Dict[str, BaseStreamingEngine] = {
            "rust": RustStreamingEngine(),
            "node": NodeStreamingEngine(),
            "python": PythonStreamingEngine(),
        }
        self.active_engine_name: str = "node"
        self.fallback_occurred: bool = False
        self.last_fallback_reason: Optional[str] = None

    async def get_active_engine(self) -> BaseStreamingEngine:
        target = self.configured_engine
        self.fallback_occurred = False
        self.last_fallback_reason = None

        # 1. Direct explicit selection or AUTO chain
        candidate_order = []
        if target == "rust":
            candidate_order = ["rust", "node", "python"] if self.auto_fallback else ["rust"]
        elif target == "node":
            candidate_order = ["node", "python"] if self.auto_fallback else ["node"]
        elif target == "python":
            candidate_order = ["python"]
        else:  # "auto"
            candidate_order = ["rust", "node", "python"]

        for eng_name in candidate_order:
            engine = self.engines.get(eng_name)
            if not engine:
                continue

            if not engine.is_installed():
                if eng_name == "rust" and target in ("rust", "auto"):
                    self.fallback_occurred = True
                    self.last_fallback_reason = "Rust binary not installed; fell back to Node.js"
                continue

            ok = await engine.ensure_started()
            if ok:
                self.active_engine_name = eng_name
                return engine

        # Fallback to python as ultimate safe harbor
        py_engine = self.engines["python"]
        await py_engine.ensure_started()
        self.active_engine_name = "python"
        self.fallback_occurred = True
        self.last_fallback_reason = "All external daemons unavailable; fell back to Python"
        return py_engine

    async def switch_engine(self, target_engine: str) -> Dict[str, Any]:
        target = target_engine.lower().strip()
        if target not in ("rust", "node", "python", "auto"):
            raise ValueError(f"Unknown engine: {target_engine}")

        self.configured_engine = target
        active = await self.get_active_engine()

        return {
            "status": "switched",
            "requested_engine": target,
            "active_engine": active.name,
            "url": active.url,
            "fallback_occurred": self.fallback_occurred,
            "reason": self.last_fallback_reason,
        }

    async def list_engines(self) -> List[Dict[str, Any]]:
        active_name = self.active_engine_name
        result = []
        for name, engine in self.engines.items():
            diag = engine.get_diagnostics()
            diag["active"] = (name == active_name)
            result.append(diag)
        return result


_engine_manager: Optional[EngineManager] = None


def get_engine_manager() -> EngineManager:
    global _engine_manager
    if _engine_manager is None:
        _engine_manager = EngineManager()
    return _engine_manager
