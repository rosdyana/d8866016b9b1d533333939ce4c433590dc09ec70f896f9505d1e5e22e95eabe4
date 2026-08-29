"""Single entry point for turning a scrape request into a Job.

The REST route and the MCP `scrape` tool submit identical work. They already
duplicated the create/store/enqueue block verbatim; adding the cache lookup
to both would have made it a third copy free to drift.
"""

from __future__ import annotations

import uuid

from arq.connections import ArqRedis
from redis.asyncio import Redis

from app.config import Settings
from app.jobs.cache import ScrapeCache, cache_key
from app.jobs.models import Job, OutputFormat
from app.jobs.store import JobStore


async def submit_scrape(
    redis: Redis,
    arq_pool: ArqRedis,
    settings: Settings,
    *,
    url: str,
    formats: list[OutputFormat],
    robotstxt: bool,
    refresh: bool = False,
) -> Job:
    key = cache_key(url, formats, robotstxt)
    store = JobStore(redis, settings.job_result_ttl_seconds)

    if settings.scrape_cache_enabled and not refresh:
        cache = ScrapeCache(redis, settings.scrape_cache_ttl_seconds)
        entry = await cache.get(key)
        if entry is not None:
            # Written as a real job record even though nothing runs, so a
            # caller that ignores the 202 body and polls GET /jobs/{id} -
            # the documented flow - still finds its result.
            job = Job(
                id=uuid.uuid4().hex,
                url=url,
                formats=formats,
                robotstxt=robotstxt,
                status="success",
                stage_won=entry.meta.stage_won,
                result=entry.result,
                cache_key=key,
                cached=True,
            )
            await store.create(job)
            return job

    job = Job(
        id=uuid.uuid4().hex,
        url=url,
        formats=formats,
        robotstxt=robotstxt,
        cache_key=key,
    )
    await store.create(job)
    # `refresh` deliberately does not travel to the worker: it only suppresses
    # the read above. The worker overwrites the entry on success either way,
    # and pre-deleting would throw away a usable result if the refetch fails.
    await arq_pool.enqueue_job(
        "run_scrape_job", job.id, job.url, job.formats, job.robotstxt
    )
    return job
