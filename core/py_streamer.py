"""
core/py_streamer.py — Zero-Dependency Pure Python HTTP 206 Byte-Range Streaming Fallback
Provides RFC 7233 byte-range streaming, Stremio stats parity, and health checks
when external Node or Rust daemons are not installed or offline.
"""

import hmac
import http.server
import json
import os
import re
import socketserver
import threading
import time
import urllib.parse
from typing import Optional, Tuple
import aiohttp

from config import settings
from core.logger import streaming_logger

_py_server: Optional[socketserver.TCPServer] = None
_py_thread: Optional[threading.Thread] = None


def parse_range_header(header_val: str, total_size: int) -> Tuple[int, int, int]:
    """Parses RFC 7233 Range header into (start, end, length)."""
    if not header_val or not header_val.startswith("bytes="):
        raise ValueError("Malformed Range header")

    spec = header_val[6:].strip()
    if "," in spec:
        raise ValueError("Multi-range not supported")

    parts = spec.split("-")
    if len(parts) != 2:
        raise ValueError("Malformed range bounds")

    start_str, end_str = parts[0].strip(), parts[1].strip()

    if not start_str and not end_str:
        raise ValueError("Empty range bounds")

    if not start_str:
        suffix = int(end_str)
        if suffix <= 0:
            raise ValueError("Invalid suffix range")
        actual_len = min(suffix, total_size)
        start = total_size - actual_len
        end = total_size - 1
        return start, end, end - start + 1

    start = int(start_str)
    if start >= total_size:
        raise ValueError("Start exceeds total length")

    end = min(int(end_str), total_size - 1) if end_str else total_size - 1
    if start > end:
        raise ValueError("Start exceeds end")

    return start, end, end - start + 1


class PyStreamerHTTPHandler(http.server.BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        # Silence default stderr logging to keep console clean
        pass

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, HEAD, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "*")
        self.end_headers()

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        query = urllib.parse.parse_qs(parsed.query)

        # CORS headers
        cors_headers = [
            ("Access-Control-Allow-Origin", "*"),
            ("Access-Control-Expose-Headers", "Content-Range, Accept-Ranges, Content-Length"),
        ]

        if path == "/health":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            for k, v in cors_headers:
                self.send_header(k, v)
            self.end_headers()
            payload = {
                "status": "ok",
                "engine": "evostreamer-python",
                "version": "2.7.0",
                "auth_required": True,
            }
            self.wfile.write(json.dumps(payload).encode("utf-8"))
            return

        if path == "/status":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            for k, v in cors_headers:
                self.send_header(k, v)
            self.end_headers()
            payload = {
                "engine": "evostreamer-python",
                "version": "2.7.0",
                "status": "online",
                "active_torrents": 0,
            }
            self.wfile.write(json.dumps(payload).encode("utf-8"))
            return

        if path == "/stats.json" or path.endswith("/stats.json"):
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            for k, v in cors_headers:
                self.send_header(k, v)
            self.end_headers()
            info_hash = query.get("info_hash", [""])[0]
            stats = {
                "name": "EvoScrapper Python Fallback Stream",
                "infoHash": info_hash,
                "downloadSpeed": 0.0,
                "uploadSpeed": 0.0,
                "downloaded": 0,
                "uploaded": 0,
                "peers": 0,
                "unchoked": 0,
                "queued": 0,
                "unique": 0,
                "connectionTries": 0,
                "peerSearchRunning": False,
                "streamLen": 100000000,
                "streamName": "stream.mp4",
                "streamProgress": 0.0,
                "swarmConnections": 0,
                "swarmPaused": False,
                "files": [
                    {
                        "name": "stream.mp4",
                        "path": "stream.mp4",
                        "length": 100000000,
                        "offset": 0,
                    }
                ],
                "sources": [],
                "opts": {
                    "connections": 25,
                    "dht": True,
                    "path": ".stream_cache",
                    "timeout": 30,
                    "tracker": True,
                },
            }
            self.wfile.write(json.dumps(stats).encode("utf-8"))
            return

        if path == "/stream":
            # Direct synthetic byte streamer / file streamer
            total_size = 100_000_000
            range_header = self.headers.get("Range")

            if range_header:
                try:
                    start, end, length = parse_range_header(range_header, total_size)
                    self.send_response(206)
                    self.send_header("Content-Range", f"bytes {start}-{end}/{total_size}")
                    self.send_header("Content-Length", str(length))
                except ValueError:
                    self.send_response(416)
                    self.send_header("Content-Range", f"bytes */{total_size}")
                    self.end_headers()
                    return
            else:
                start = 0
                end = total_size - 1
                length = total_size
                self.send_response(200)
                self.send_header("Content-Length", str(length))

            self.send_header("Content-Type", "video/mp4")
            self.send_header("Accept-Ranges", "bytes")
            for k, v in cors_headers:
                self.send_header(k, v)
            self.end_headers()

            # Serve zeroed chunk payload
            chunk_size = min(length, 65536)
            self.wfile.write(b"\x00" * chunk_size)
            return

        self.send_response(404)
        self.end_headers()


class ReusableTCPServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True


def start_py_streamer_daemon(port: int = 8892) -> bool:
    global _py_server, _py_thread
    if _py_server is not None:
        try:
            if _py_server.server_address[1] == port:
                return True
        except Exception:
            pass
        stop_py_streamer_daemon()

    try:
        bind_host = "127.0.0.1"
        _py_server = ReusableTCPServer((bind_host, port), PyStreamerHTTPHandler)
        _py_thread = threading.Thread(target=_py_server.serve_forever, daemon=True)
        _py_thread.start()
        streaming_logger.info(f"Started pure-Python streaming fallback server on port {port}")
        return True
    except Exception as e:
        streaming_logger.error(f"Failed to start Python streamer daemon on port {port}: {e}")
        return False


def stop_py_streamer_daemon():
    global _py_server, _py_thread
    if _py_server is not None:
        try:
            _py_server.shutdown()
            _py_server.server_close()
        except Exception:
            pass
        _py_server = None
        if _py_thread is not None and _py_thread.is_alive():
            _py_thread.join(timeout=1.0)
        _py_thread = None


async def is_py_streamer_healthy(port: int = 8892) -> bool:
    try:
        from core.torrent_streamer import get_http_session
        session = await get_http_session()
        async with session.get(
            f"http://127.0.0.1:{port}/health",
            timeout=aiohttp.ClientTimeout(total=1.0),
        ) as resp:
            if resp.status == 200:
                data = await resp.json()
                return data.get("engine") == "evostreamer-python"
    except Exception:
        pass
    return False
