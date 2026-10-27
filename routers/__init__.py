from .torrents import router as torrents_router
from .subtitles import router as subtitles_router
from .media import router as media_router
from .health import router as health_router
from .discover import router as discover_router
from .stream import router as stream_router
from .stremio import router as stremio_router
from .library import router as library_router
from .cometnet import router as cometnet_router
from .auth import router as auth_router
from .profiles import router as profiles_router

__all__ = [
    "torrents_router",
    "subtitles_router",
    "media_router",
    "health_router",
    "discover_router",
    "stream_router",
    "stremio_router",
    "library_router",
    "cometnet_router",
    "auth_router",
    "profiles_router",
]
