from __future__ import annotations

from redis.asyncio import Redis

_KEY_PREFIX = "robots:"


class RobotsCache:
    """Per-host robots.txt body cache, backed by Redis.

    Caches the raw text (empty string means "no robots.txt / allow all").
    Absence of the key (not merely an empty value) means "not cached yet".
    """

    def __init__(self, redis: Redis, ttl_seconds: int) -> None:
        self._redis = redis
        self._ttl = ttl_seconds

    async def get(self, host: str) -> str | None:
        value = await self._redis.get(_KEY_PREFIX + host)
        if value is None:
            return None
        return value.decode("utf-8") if isinstance(value, bytes) else value

    async def set(self, host: str, robots_txt: str) -> None:
        await self._redis.set(_KEY_PREFIX + host, robots_txt, ex=self._ttl)
