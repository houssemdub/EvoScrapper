import asyncio
import os
import sys
import time
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from core.circuit_breaker import CircuitBreaker
from models.common import CircuitState


async def test_circuit_breaker_lifecycle():
    cb = CircuitBreaker(name="test_provider", fail_threshold=2, recovery_time=0.2)

    # Initial state should be CLOSED
    assert cb.state == CircuitState.CLOSED
    assert await cb.can_execute() is True

    # Record failure 1
    await cb.record_failure("Connection timeout")
    assert cb.state == CircuitState.CLOSED

    # Record failure 2 -> should trip to OPEN
    await cb.record_failure("Connection timeout")
    assert cb.state == CircuitState.OPEN
    assert await cb.can_execute() is False

    # Wait for recovery time (0.25s)
    await asyncio.sleep(0.25)

    # Should transition to HALF_OPEN to probe
    assert await cb.can_execute() is True
    assert cb.state == CircuitState.HALF_OPEN

    # Probe succeeds -> should reset to CLOSED
    await cb.record_success(latency_ms=45.0)
    assert cb.state == CircuitState.CLOSED
    assert cb.failure_count == 0

    health = cb.get_health()
    assert health.status == CircuitState.CLOSED
    assert health.successful_calls == 1
    assert health.total_calls == 3


if __name__ == "__main__":
    asyncio.run(test_circuit_breaker_lifecycle())
    print("[+] Circuit Breaker lifecycle tests passed!")
