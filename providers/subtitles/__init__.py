from .opensubtitles import OpenSubtitlesProvider
from .gestdown import GestdownProvider
from .yify_subs import YifySubtitlesProvider
from .subdl import SubdlProvider
from .subsource import SubSourceProvider
from .animetosho import AnimeToshoProvider
from .hash_matcher import compute_osdb_hash, compute_shooter_hash

SUBTITLE_PROVIDERS = {
    "opensubtitles": OpenSubtitlesProvider(),
    "gestdown": GestdownProvider(),
    "yifysubtitles": YifySubtitlesProvider(),
    "subdl": SubdlProvider(),
    "subsource": SubSourceProvider(),
    "animetosho": AnimeToshoProvider(),
}

__all__ = [
    "OpenSubtitlesProvider",
    "GestdownProvider",
    "YifySubtitlesProvider",
    "SubdlProvider",
    "SubSourceProvider",
    "AnimeToshoProvider",
    "compute_osdb_hash",
    "compute_shooter_hash",
    "SUBTITLE_PROVIDERS",
]
