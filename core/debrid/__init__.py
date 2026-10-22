"""
Multi-Debrid Cloud Streaming Engine.
Provides instant 1Gbps unthrottled HTTPS streaming for cached torrents across
Real-Debrid, AllDebrid, TorBox, and Premiumize.
"""

from core.debrid.base import DebridClient, DebridStreamResult
from core.debrid.realdebrid import RealDebridClient
from core.debrid.alldebrid import AllDebridClient
from core.debrid.torbox import TorboxClient
from core.debrid.manager import get_debrid_manager

__all__ = [
    "DebridClient",
    "DebridStreamResult",
    "RealDebridClient",
    "AllDebridClient",
    "TorboxClient",
    "get_debrid_manager",
]
