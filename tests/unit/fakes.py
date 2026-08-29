"""Redis/arq doubles shared by the app-tier unit tests.

Same dict-backed shape as the per-file FakeRedis in the pipeline tests, but
with the commands the response cache needs - mget, delete, scan, pipeline -
and recorded TTLs so `ex=` is assertable. Lives in one module because five
test files need it; the two-method fakes elsewhere stay where they are.
"""

from __future__ import annotations

import fnmatch

from app.jobs.models import Job
from app.jobs.store import JobStore


class FakePipeline:
    def __init__(self, redis: FakeRedis) -> None:
        self._redis = redis
        self._queued: list[tuple] = []

    def set(self, key, value, ex=None):
        self._queued.append(("set", (key, value), {"ex": ex}))
        return self

    def delete(self, *keys):
        self._queued.append(("delete", keys, {}))
        return self

    async def execute(self) -> list:
        results = []
        for name, args, kwargs in self._queued:
            results.append(await getattr(self._redis, name)(*args, **kwargs))
        self._queued.clear()
        return results


class FakeRedis:
    """Returns bytes and ignores expiry timing, like the real client here."""

    def __init__(self, scan_batch_size: int = 1000) -> None:
        self._store: dict[str, bytes] = {}
        self.ttls: dict[str, int | None] = {}
        self.scan_batch_size = scan_batch_size

    async def get(self, key: str):
        return self._store.get(key)

    async def set(self, key: str, value, ex=None):
        self._store[key] = value if isinstance(value, bytes) else str(value).encode("utf-8")
        self.ttls[key] = ex
        return True

    async def mget(self, *keys):
        if len(keys) == 1 and isinstance(keys[0], (list, tuple)):
            keys = keys[0]
        return [self._store.get(key) for key in keys]

    async def delete(self, *keys) -> int:
        removed = 0
        for key in keys:
            if self._store.pop(key, None) is not None:
                self.ttls.pop(key, None)
                removed += 1
        return removed

    async def scan(self, cursor: int = 0, match: str | None = None, count: int | None = None):
        keys = sorted(self._store)
        if match is not None:
            keys = [key for key in keys if fnmatch.fnmatch(key, match)]

        batch = keys[cursor : cursor + self.scan_batch_size]
        next_cursor = cursor + self.scan_batch_size
        if next_cursor >= len(keys):
            next_cursor = 0
        return next_cursor, [key.encode("utf-8") for key in batch]

    def pipeline(self) -> FakePipeline:
        return FakePipeline(self)

    async def ping(self) -> bool:
        return True


class FakeArqPool:
    """Records enqueues; optionally finishes the job the way the worker would."""

    def __init__(self, redis: FakeRedis, finish_with: Job | None = None) -> None:
        self._redis = redis
        self._finish_with = finish_with
        self.calls: list[tuple] = []

    async def enqueue_job(self, *args):
        self.calls.append(args)
        if self._finish_with is not None:
            job_id = args[1]
            done = self._finish_with.model_copy(update={"id": job_id})
            await JobStore(self._redis, 60).create(done)
