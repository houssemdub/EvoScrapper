import asyncio
import copy
import time
from typing import Any, Dict, Optional, Tuple


class MemoryCache:
    """
    Lightweight, thread-safe asynchronous in-memory cache with TTL expiration.
    Eliminates redundant upstream traffic for frequently searched titles.
    """

    def __init__(self, default_ttl: int = 900, max_size: int = 2000):
        self.default_ttl = default_ttl
        self.max_size = max_size
        self._store: Dict[str, Tuple[float, Any]] = {}  # key -> (expires_at, data)
        self._lock = asyncio.Lock()

    async def get(self, key: str) -> Optional[Any]:
        async with self._lock:
            entry = self._store.get(key)
            if not entry:
                return None
            expires_at, data = entry
            if time.time() > expires_at:
                del self._store[key]
                return None
            if hasattr(data, "model_copy"):
                return data.model_copy(deep=True)
            try:
                return copy.deepcopy(data)
            except Exception:
                return data

    async def set(self, key: str, value: Any, ttl: Optional[int] = None):
        async with self._lock:
            # Simple eviction if max capacity reached
            if len(self._store) >= self.max_size:
                # Remove expired keys first
                now = time.time()
                expired_keys = [k for k, (exp, _) in self._store.items() if now > exp]
                for k in expired_keys:
                    del self._store[k]
                
                # If still at max size, evict oldest 20%
                if len(self._store) >= self.max_size:
                    keys_to_remove = list(self._store.keys())[: self.max_size // 5]
                    for k in keys_to_remove:
                        del self._store[k]

            duration = ttl if ttl is not None else self.default_ttl
            self._store[key] = (time.time() + duration, value)

    async def clear(self):
        async with self._lock:
            self._store.clear()


# Global cache instance for search results
cache = MemoryCache()
