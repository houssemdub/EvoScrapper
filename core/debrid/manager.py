import asyncio
import time
from typing import Any, Dict, List, Optional

from core.debrid.base import DebridClient, DebridStreamResult
from core.debrid.realdebrid import RealDebridClient
from core.debrid.alldebrid import AllDebridClient
from core.debrid.torbox import TorboxClient
from core.debrid.debridlink import DebridLinkClient
from core.debrid.premiumize import PremiumizeClient
from core.debrid.pikpak import PikPakClient
from core.logger import debrid_logger


class _SplitBreaker:
    """
    T0.3: independent circuit breakers per operation kind (availability probe
    vs stream resolve), torrentio-style. A broken resolve endpoint must not
    disable cache checks on the same provider, and vice versa.
    """

    def __init__(self, threshold: int = 3, cooldown: float = 90.0):
        self.failures = 0
        self.opened_at = 0.0
        self.threshold = threshold
        self.cooldown = cooldown

    def is_open(self) -> bool:
        return self.failures >= self.threshold and (time.time() - self.opened_at) < self.cooldown

    def record_success(self) -> None:
        self.failures = 0

    def record_failure(self) -> None:
        self.failures += 1
        if self.failures >= self.threshold:
            self.opened_at = time.time()


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
        self._availability_breakers: Dict[str, _SplitBreaker] = {}
        self._resolve_breakers: Dict[str, _SplitBreaker] = {}

    def _breaker(self, kind: str, provider_name: str) -> _SplitBreaker:
        registry = self._availability_breakers if kind == "availability" else self._resolve_breakers
        key = provider_name.lower()
        if key not in registry:
            registry[key] = _SplitBreaker()
        return registry[key]

    def _availability_breaker_open(self, provider_name: str) -> bool:
        return provider_name.lower() in self._availability_breakers and self._availability_breakers[provider_name.lower()].is_open()

    def _resolve_breaker_open(self, provider_name: str) -> bool:
        return provider_name.lower() in self._resolve_breakers and self._resolve_breakers[provider_name.lower()].is_open()

    def _record_resolve_success(self, provider_name: str) -> None:
        self._breaker("resolve", provider_name).record_success()

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
        Providers whose availability breaker is open are skipped.
        """
        active = [p for p in self.active_providers if not self._availability_breaker_open(p.provider_name)]
        if not active or not info_hashes:
            return {}

        tasks = [p.check_cache(info_hashes) for p in active]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        cached_map: Dict[str, Dict[str, bool]] = {}
        for p, res in zip(active, results):
            prov = p.provider_name.lower()
            if isinstance(res, dict):
                self._breaker("availability", prov).record_success()
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
            else:
                self._breaker("availability", prov).record_failure()
                debrid_logger.warning(f"[DebridManager] Availability probe failed for {prov}: {res}")

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
        or any available active Debrid provider. Providers that already have the
        torrent cached are tried first: resolving from an uncached provider
        would trigger a server-side download instead of instant playback.
        """
        active = [p for p in self.active_providers if not self._resolve_breaker_open(p.provider_name)]
        if not active:
            return None

        clean_hash = info_hash.strip().lower()
        cached_map: Dict[str, bool] = {}
        try:
            # P2: mesh-fed coverage hints order the attempts before any live
            # probe; the live probe below still confirms before streaming.
            from core.swarm_intelligence import get_coverage_index
            for hint in get_coverage_index().providers_for(clean_hash):
                cached_map.setdefault(hint["provider"], True)
        except Exception:
            pass
        try:
            cache_probe = await self.check_cache([clean_hash])
            for prov_name, hash_dict in cache_probe.items():
                if hash_dict.get(clean_hash):
                    cached_map[prov_name] = True
        except Exception:
            cached_map = {}

        pref = (preferred_provider or "").lower()

        def _order(p: DebridClient) -> tuple:
            name = p.provider_name.lower()
            return (0 if cached_map.get(name) else 1, 0 if name == pref else 1)

        active = sorted(active, key=_order)

        for provider in active:
            try:
                res = await provider.resolve_stream(info_hash, file_idx=file_idx, magnet=magnet, season=season, episode=episode)
                if res and res.url:
                    self._record_resolve_success(provider.provider_name)
                    return res
                self._breaker("resolve", provider.provider_name).record_failure()
            except Exception as e:
                self._breaker("resolve", provider.provider_name).record_failure()
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
