import abc
import time
from typing import Any, Dict, List, Optional
from core.circuit_breaker import CircuitBreaker
from models.common import ProviderHealth


class BaseProvider(abc.ABC):
    """
    Abstract Base Class for all Torrent and Subtitle providers.
    Enforces standardized execution, circuit breaker protection,
    metric tracking, and mirror failover.
    """

    def __init__(
        self,
        name: str,
        provider_type: str,
        base_urls: List[str],
        fail_threshold: int = 3,
        recovery_time: float = 90.0,
    ):
        self.name = name
        self.provider_type = provider_type
        self.base_urls = base_urls
        self.current_mirror_idx = 0
        self.circuit_breaker = CircuitBreaker(
            name=name,
            provider_type=provider_type,
            fail_threshold=fail_threshold,
            recovery_time=recovery_time,
        )

    @property
    def base_url(self) -> str:
        return self.base_urls[self.current_mirror_idx]

    def rotate_mirror(self):
        """Switches to the next mirror if multiple exist."""
        if len(self.base_urls) > 1:
            self.current_mirror_idx = (self.current_mirror_idx + 1) % len(self.base_urls)

    @abc.abstractmethod
    async def _do_search(self, query: str, **kwargs) -> List[Any]:
        """Internal search logic to be implemented by specific provider."""
        pass

    async def search(self, query: str, **kwargs) -> List[Any]:
        """
        Executes search protected by the provider's Circuit Breaker.
        Fails fast if circuit is OPEN, measures execution latency,
        and logs failures gracefully.
        """
        if not await self.circuit_breaker.can_execute():
            return []

        start = time.time()
        try:
            results = await self._do_search(query, **kwargs)
            latency_ms = (time.time() - start) * 1000
            await self.circuit_breaker.record_success(latency_ms)
            return results
        except Exception as e:
            latency_ms = (time.time() - start) * 1000
            await self.circuit_breaker.record_failure(str(e), latency_ms)
            self.rotate_mirror()
            return []

    async def trending(self, **kwargs) -> List[Any]:
        """
        Executes trending lookup protected by the provider's Circuit Breaker.
        Measures execution latency and records success/failure metrics.
        """
        if not await self.circuit_breaker.can_execute():
            return []

        start = time.time()
        try:
            results = await self._do_trending(**kwargs)
            latency_ms = (time.time() - start) * 1000
            await self.circuit_breaker.record_success(latency_ms)
            return results
        except Exception as e:
            latency_ms = (time.time() - start) * 1000
            await self.circuit_breaker.record_failure(str(e), latency_ms)
            self.rotate_mirror()
            return []

    async def _do_trending(self, **kwargs) -> List[Any]:
        """Default fallback for providers that do not support trending."""
        return []

    def get_health(self) -> ProviderHealth:
        return self.circuit_breaker.get_health()
