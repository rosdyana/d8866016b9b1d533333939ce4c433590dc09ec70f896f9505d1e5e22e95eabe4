"""Stage 5 (optimization): remembers which stage last succeeded for a
domain, so a repeat request can skip straight past stages already known to
fail for it. A TTL keeps this from becoming permanent: if a site's anti-bot
posture changes, the memory expires and the pipeline re-probes from Stage 1.
"""

from __future__ import annotations

from redis.asyncio import Redis

_KEY_PREFIX = "domain_memory:"


class DomainMemory:
    def __init__(self, redis: Redis, ttl_seconds: int) -> None:
        self._redis = redis
        self._ttl = ttl_seconds

    async def get_last_successful_stage(self, host: str) -> str | None:
        value = await self._redis.get(_KEY_PREFIX + host)
        if value is None:
            return None
        return value.decode("utf-8") if isinstance(value, bytes) else value

    async def record_success(self, host: str, stage_name: str) -> None:
        await self._redis.set(_KEY_PREFIX + host, stage_name, ex=self._ttl)

    async def forget(self, host: str) -> None:
        """Drop a shortcut that has stopped working, so the next request
        re-probes from Stage 1 instead of waiting out the TTL."""
        await self._redis.delete(_KEY_PREFIX + host)
