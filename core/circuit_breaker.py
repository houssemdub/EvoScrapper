import asyncio
import time
from typing import Optional
from models.common import CircuitState, ProviderHealth


class CircuitBreaker:
    """
    Asynchronous Circuit Breaker implementation per provider.
    Prevents cascading timeouts by failing fast when an upstream provider
    experiences repeated failures or downtime.
    """

    def __init__(
        self,
        name: str,
        provider_type: str = "torrent",
        fail_threshold: int = 3,
        recovery_time: float = 90.0,
    ):
        self.name = name
        self.provider_type = provider_type
        self.fail_threshold = fail_threshold
        self.recovery_time = recovery_time

        self.state: CircuitState = CircuitState.CLOSED
        self.failure_count: int = 0
        self.tripped_at: float = 0.0

        # Metrics
        self.total_calls: int = 0
        self.successful_calls: int = 0
        self.total_latency_ms: float = 0.0
        self.last_error: Optional[str] = None
        self._lock = asyncio.Lock()

    async def can_execute(self) -> bool:
        """Determines if a request can proceed under the circuit breaker state."""
        async with self._lock:
            now = time.time()
            if self.state == CircuitState.OPEN:
                if now - self.tripped_at >= self.recovery_time:
                    self.state = CircuitState.HALF_OPEN
                    return True
                return False
            return True

    async def record_success(self, latency_ms: float):
        """Records a successful execution, updating metrics and resetting circuit."""
        async with self._lock:
            self.total_calls += 1
            self.successful_calls += 1
            self.total_latency_ms += latency_ms
            self.failure_count = 0
            self.state = CircuitState.CLOSED

    async def record_failure(self, error_msg: str, latency_ms: float = 0.0):
        """Records an execution failure, potentially tripping the circuit open."""
        async with self._lock:
            self.total_calls += 1
            self.total_latency_ms += latency_ms
            self.failure_count += 1
            self.last_error = error_msg

            if self.failure_count >= self.fail_threshold:
                self.state = CircuitState.OPEN
                self.tripped_at = time.time()

    def get_health(self) -> ProviderHealth:
        """Returns the current operational snapshot for this provider."""
        avg_latency = (
            self.total_latency_ms / self.total_calls
            if self.total_calls > 0
            else 0.0
        )
        return ProviderHealth(
            name=self.name,
            type=self.provider_type,
            status=self.state,
            failure_count=self.failure_count,
            total_calls=self.total_calls,
            successful_calls=self.successful_calls,
            avg_latency_ms=round(avg_latency, 2),
            last_error=self.last_error,
        )
