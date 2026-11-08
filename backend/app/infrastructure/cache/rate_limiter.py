"""Fixed-window counters for rate limiting. Redis in production, in-memory fallback in dev."""

from __future__ import annotations

import asyncio
import time
from typing import Protocol

from redis.asyncio import Redis


class RateLimiter(Protocol):
    backend_name: str

    async def hit(self, key: str, window_seconds: int) -> tuple[int, int]:
        """Increment ``key``; return (count in current window, seconds until reset)."""

    async def peek(self, key: str) -> tuple[int, int]:
        """Return (count, seconds until reset) without incrementing."""

    async def reset(self, key: str) -> None: ...


class RedisRateLimiter:
    backend_name = "redis"

    def __init__(self, client: Redis, prefix: str = "tp:rl:") -> None:
        self._client = client
        self._prefix = prefix

    async def hit(self, key: str, window_seconds: int) -> tuple[int, int]:
        full_key = self._prefix + key
        async with self._client.pipeline(transaction=True) as pipe:
            pipe.incr(full_key)
            pipe.expire(full_key, window_seconds, nx=True)
            pipe.ttl(full_key)
            count, _, ttl = await pipe.execute()
        return int(count), max(int(ttl), 0)

    async def peek(self, key: str) -> tuple[int, int]:
        full_key = self._prefix + key
        async with self._client.pipeline(transaction=False) as pipe:
            pipe.get(full_key)
            pipe.ttl(full_key)
            raw, ttl = await pipe.execute()
        return (int(raw) if raw else 0), max(int(ttl), 0)

    async def reset(self, key: str) -> None:
        await self._client.delete(self._prefix + key)


class InMemoryRateLimiter:
    """Single-process fallback for local development and tests only."""

    backend_name = "in_memory"

    def __init__(self) -> None:
        self._buckets: dict[str, tuple[int, float]] = {}
        self._lock = asyncio.Lock()

    def _current(self, key: str, now: float) -> tuple[int, float] | None:
        bucket = self._buckets.get(key)
        if bucket is None or bucket[1] <= now:
            self._buckets.pop(key, None)
            return None
        return bucket

    async def hit(self, key: str, window_seconds: int) -> tuple[int, int]:
        async with self._lock:
            now = time.monotonic()
            bucket = self._current(key, now)
            count, expires = (bucket[0] + 1, bucket[1]) if bucket else (1, now + window_seconds)
            self._buckets[key] = (count, expires)
            return count, int(expires - now)

    async def peek(self, key: str) -> tuple[int, int]:
        async with self._lock:
            now = time.monotonic()
            bucket = self._current(key, now)
            return (bucket[0], int(bucket[1] - now)) if bucket else (0, 0)

    async def reset(self, key: str) -> None:
        async with self._lock:
            self._buckets.pop(key, None)
