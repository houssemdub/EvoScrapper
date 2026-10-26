from config import settings

from .yts import YtsProvider
from .pirate_bay import PirateBayProvider
from .eztv import EztvProvider
from .nyaa import NyaaProvider
from .tokyotosho import TokyoToshoProvider
from .subsplease import SubsPleaseProvider
from .comando import ComandoProvider
from .bludv import BluDVProvider
from .rutor import RutorProvider
from .torrent_galaxy import TorrentGalaxyProvider
from .torlock import TorlockProvider
from .x1337 import X1337Provider
from .jackett import JackettProvider

TORRENT_PROVIDERS = {
    "yts": YtsProvider(),
    "thepiratebay": PirateBayProvider(),
    "eztv": EztvProvider(),
    "nyaa": NyaaProvider(),
    "tokyotosho": TokyoToshoProvider(),
    "subsplease": SubsPleaseProvider(),
    "comando": ComandoProvider(),
    "bludv": BluDVProvider(),
    "rutor": RutorProvider(),
    "torrentgalaxy": TorrentGalaxyProvider(),
    "torlock": TorlockProvider(),
    "1337x": X1337Provider(),
}

# T4.5: Jackett/Prowlarr passthrough joins the pool only when configured.
if settings.JACKETT_URL and settings.JACKETT_API_KEY:
    TORRENT_PROVIDERS["jackett"] = JackettProvider(
        base_url=settings.JACKETT_URL, api_key=settings.JACKETT_API_KEY
    )

__all__ = [
    "YtsProvider",
    "JackettProvider",
    "PirateBayProvider",
    "EztvProvider",
    "NyaaProvider",
    "TokyoToshoProvider",
    "SubsPleaseProvider",
    "ComandoProvider",
    "BluDVProvider",
    "RutorProvider",
    "TorrentGalaxyProvider",
    "TorlockProvider",
    "X1337Provider",
    "TORRENT_PROVIDERS",
]
