"""Response cache keyed on the canonical scrape request body.

A repeat request for a body already fetched answers from Redis instead of
re-running the pipeline, which for a bot-protected vendor page means a
browser launch measured in tens of seconds plus one of the few browser
slots. Only successes are ever stored: `blocked`/`timeout` are usually
transient, and freezing one for the cache TTL would poison that URL for a
month.

Each entry is two keys - metadata and body - written with the same TTL, so
listing the cache does not have to pull megabytes of `raw_html` per row.
They expire together; a half-present pair reads as a miss.
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from datetime import datetime, timezone

import orjson
from pydantic import BaseModel
from redis.asyncio import Redis

from app.jobs.models import OutputFormat
from extract.models import ExtractionOutput

_META_PREFIX = "scrape_cache:meta:"
_BODY_PREFIX = "scrape_cache:body:"

_CLEAR_SCAN_BATCH = 500


def cache_key(url: str, formats: Sequence[str], robotstxt: bool) -> str:
    """Derive the cache key for a scrape request body.

    `url` must be the post-validation string (`str(payload.url)`): AnyHttpUrl
    lowercases the scheme/host and appends the trailing slash, so hashing the
    raw input would file `https://example.com` and `https://example.com/`
    as two entries. `formats` is sorted because it is a set of outputs, not
    a sequence - asking for markdown+llm_text in either order is one request.
    """
    canonical = orjson.dumps(
        {"url": url, "formats": sorted(formats), "robotstxt": robotstxt}
    )
    return hashlib.sha256(canonical).hexdigest()


class CacheEntryMeta(BaseModel):
    key: str
    url: str
    formats: list[OutputFormat]
    robotstxt: bool
    stage_won: str | None = None
    job_id: str
    size_bytes: int
    created_at: datetime


class CacheEntry(BaseModel):
    meta: CacheEntryMeta
    result: ExtractionOutput


def _as_str(key: bytes | str) -> str:
    return key.decode("utf-8") if isinstance(key, bytes) else key


class ScrapeCache:
    def __init__(self, redis: Redis, ttl_seconds: int) -> None:
        self._redis = redis
        self._ttl = ttl_seconds

    async def get(self, key: str) -> CacheEntry | None:
        meta_raw, body_raw = await self._redis.mget(
            _META_PREFIX + key, _BODY_PREFIX + key
        )
        if meta_raw is None or body_raw is None:
            return None
        return CacheEntry(
            meta=CacheEntryMeta.model_validate(orjson.loads(meta_raw)),
            result=ExtractionOutput.model_validate(orjson.loads(body_raw)),
        )

    async def set(
        self,
        key: str,
        *,
        url: str,
        formats: Sequence[str],
        robotstxt: bool,
        stage_won: str | None,
        job_id: str,
        result: ExtractionOutput,
        max_bytes: int | None = None,
    ) -> bool:
        """Store a result under `key`. Returns False if it was too large.

        The size cap lives here because this is the only place that knows the
        serialized size, and Redis runs with no maxmemory - one pathological
        page must not be pinned for the whole TTL.
        """
        body = orjson.dumps(result.model_dump(mode="json"))
        if max_bytes is not None and len(body) > max_bytes:
            return False

        meta = CacheEntryMeta(
            key=key,
            url=url,
            formats=list(formats),
            robotstxt=robotstxt,
            stage_won=stage_won,
            job_id=job_id,
            size_bytes=len(body),
            created_at=datetime.now(timezone.utc),
        )

        pipe = self._redis.pipeline()
        pipe.set(
            _META_PREFIX + key,
            orjson.dumps(meta.model_dump(mode="json")),
            ex=self._ttl,
        )
        pipe.set(_BODY_PREFIX + key, body, ex=self._ttl)
        await pipe.execute()
        return True

    async def delete(self, key: str) -> bool:
        pipe = self._redis.pipeline()
        pipe.delete(_META_PREFIX + key)
        pipe.delete(_BODY_PREFIX + key)
        meta_removed, _ = await pipe.execute()
        return bool(meta_removed)

    async def list(
        self, cursor: int = 0, limit: int = 100
    ) -> tuple[list[CacheEntryMeta], int]:
        """One page of entry metadata, plus the cursor to resume from (0 = end).

        `limit` is a page-size hint, not a cap: SCAN's COUNT is itself only a
        hint, and truncating an oversized batch would drop keys the cursor has
        already moved past.
        """
        keys: list[str] = []
        while True:
            cursor, batch = await self._redis.scan(
                cursor, match=_META_PREFIX + "*", count=limit
            )
            keys.extend(_as_str(key) for key in batch)
            if cursor == 0 or len(keys) >= limit:
                break

        if not keys:
            return [], cursor

        values = await self._redis.mget(*keys)
        return [
            CacheEntryMeta.model_validate(orjson.loads(value))
            for value in values
            if value is not None
        ], cursor

    async def clear(self) -> int:
        """Delete every cache entry, returning how many were removed.

        Prefix-scoped SCAN + DEL, never FLUSHDB: arq's queue and the `job:`,
        `robots:` and `domain_memory:` keys all share this database.

        Keys are collected before anything is deleted, so the cursor walks an
        unmodified keyspace. That costs only the key names, and avoids relying
        on how a cursor behaves over a table being emptied underneath it.
        """
        removed = 0
        for prefix in (_META_PREFIX, _BODY_PREFIX):
            keys: list[str] = []
            cursor = 0
            while True:
                cursor, batch = await self._redis.scan(
                    cursor, match=prefix + "*", count=_CLEAR_SCAN_BATCH
                )
                keys.extend(_as_str(key) for key in batch)
                if cursor == 0:
                    break

            for start in range(0, len(keys), _CLEAR_SCAN_BATCH):
                deleted = await self._redis.delete(*keys[start : start + _CLEAR_SCAN_BATCH])
                if prefix == _META_PREFIX:
                    removed += deleted
        return removed
