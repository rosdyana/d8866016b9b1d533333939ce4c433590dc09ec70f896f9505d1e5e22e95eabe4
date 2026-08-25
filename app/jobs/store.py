from __future__ import annotations

from datetime import datetime, timezone

import orjson
from redis.asyncio import Redis

from app.jobs.models import Job

_KEY_PREFIX = "job:"


class JobStore:
    def __init__(self, redis: Redis, ttl_seconds: int) -> None:
        self._redis = redis
        self._ttl = ttl_seconds

    async def create(self, job: Job) -> None:
        await self._redis.set(
            _KEY_PREFIX + job.id,
            orjson.dumps(job.model_dump(mode="json")),
            ex=self._ttl,
        )

    async def get(self, job_id: str) -> Job | None:
        raw = await self._redis.get(_KEY_PREFIX + job_id)
        if raw is None:
            return None
        return Job.model_validate(orjson.loads(raw))

    async def update(self, job_id: str, **fields: object) -> None:
        job = await self.get(job_id)
        if job is None:
            return
        updated = job.model_copy(update={**fields, "updated_at": datetime.now(timezone.utc)})
        await self._redis.set(
            _KEY_PREFIX + job_id,
            orjson.dumps(updated.model_dump(mode="json")),
            ex=self._ttl,
        )
