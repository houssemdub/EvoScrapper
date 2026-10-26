import asyncio
from typing import Any, Dict, List, Optional

from core.debrid.base import DebridClient, DebridStreamResult
from core.debrid.realdebrid import RealDebridClient
from core.debrid.alldebrid import AllDebridClient
from core.debrid.torbox import TorboxClient
from core.debrid.debridlink import DebridLinkClient
from core.debrid.premiumize import PremiumizeClient
from core.debrid.pikpak import PikPakClient
from core.logger import debrid_logger


class DebridManager:
    """
    Central Coordinator for Multi-Debrid cloud streaming.
    Manages active providers across Real-Debrid, AllDebrid, TorBox,
    Debrid-Link, Premiumize.me, and PikPak, batches cache availability probing,
    and resolves direct 1Gbps unthrottled cloud streaming links.
    """

    def __init__(self):
        self.providers: Dict[str, DebridClient] = {
            "realdebrid": RealDebridClient(),
            "alldebrid": AllDebridClient(),
            "torbox": TorboxClient(),
            "debridlink": DebridLinkClient(),
            "premiumize": PremiumizeClient(),
            "pikpak": PikPakClient(),
        }

    def set_key(self, provider_name: str, key: str):
        p = provider_name.lower()
        if p in self.providers:
            self.providers[p].api_key = key.strip()

    @property
    def active_providers(self) -> List[DebridClient]:
        return [p for p in self.providers.values() if p.is_configured]

    async def check_cache(self, info_hashes: List[str]) -> Dict[str, Dict[str, bool]]:
        """
        Queries all configured debrid providers concurrently.
        Returns a dict mapping provider_name -> { hash: is_cached }.
        """
        active = self.active_providers
        if not active or not info_hashes:
            return {}

        tasks = [p.check_cache(info_hashes) for p in active]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        cached_map: Dict[str, Dict[str, bool]] = {}
        for p, res in zip(active, results):
            if isinstance(res, dict):
                prov = p.provider_name.lower()
                cached_map[prov] = res
                # Broadcast positive cache hits to CometNet gossip
                try:
                    from core.cometnet import get_cometnet_node
                    node = get_cometnet_node()
                    for h, is_cached in res.items():
                        if is_cached:
                            node.announce_cache(h, prov, True)
                except Exception:
                    pass

        return cached_map

    async def is_any_cached(self, info_hash: str) -> Optional[str]:
        """
        Returns the first provider name where this torrent is cached, or None.
        Checks active providers and queries decentralized CometNet gossip network.
        """
        clean_hash = info_hash.strip().lower()
        res = await self.check_cache([clean_hash])
        for prov_name, hash_dict in res.items():
            if hash_dict.get(clean_hash):
                return prov_name

        # Query decentralized CometNet gossip cache
        try:
            from core.cometnet import get_cometnet_node
            gossip_cached = get_cometnet_node().lookup_cache(clean_hash)
            if gossip_cached:
                return next(iter(gossip_cached))
        except Exception:
            pass

        return None

    async def resolve_stream(
        self,
        info_hash: str,
        file_idx: int = 0,
        magnet: Optional[str] = None,
        preferred_provider: Optional[str] = None,
        season: Optional[int] = None,
        episode: Optional[int] = None,
    ) -> Optional[DebridStreamResult]:
        """
        Attempts to resolve an unthrottled direct HTTPS stream from the preferred
        or any available active Debrid provider.
        """
        active = self.active_providers
        if not active:
            return None

        # Sort with preferred provider first
        if preferred_provider:
            pref = preferred_provider.lower()
            active = sorted(active, key=lambda p: 0 if p.provider_name.lower() == pref else 1)

        for provider in active:
            try:
                res = await provider.resolve_stream(info_hash, file_idx=file_idx, magnet=magnet, season=season, episode=episode)
                if res and res.url:
                    return res
            except Exception as e:
                print(f"[DebridManager] Provider {provider.provider_name} resolve failed: {e}")

        return None

    async def get_all_statuses(self) -> List[Dict[str, Any]]:
        tasks = [p.get_user_info() for p in self.providers.values()]
        return await asyncio.gather(*tasks)


_debrid_manager_instance: Optional[DebridManager] = None


def get_debrid_manager() -> DebridManager:
    global _debrid_manager_instance
    if _debrid_manager_instance is None:
        _debrid_manager_instance = DebridManager()
    return _debrid_manager_instance
