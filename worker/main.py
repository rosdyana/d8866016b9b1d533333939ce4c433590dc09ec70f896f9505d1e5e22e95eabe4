from __future__ import annotations

import httpx
from arq.connections import RedisSettings
from curl_cffi import AsyncSession

from app.config import get_settings
from common.logging import configure_logging
from common.rate_limit import PerDomainConcurrencyLimiter
from pipeline.browser.slots import BrowserSlots
from pipeline.domain_memory import DomainMemory
from pipeline.robots.cache import RobotsCache
from pipeline.robots.gate import RobotsGate
from worker.tasks import run_scrape_job


async def startup(ctx: dict) -> None:
    configure_logging()
    settings = get_settings()
    ctx["settings"] = settings

    # httpx stays for robots.txt only - it is a small text file from a
    # well-known path, and fetching it is not what gets fingerprinted.
    ctx["http_client"] = httpx.AsyncClient()
    ctx["robots_gate"] = RobotsGate(
        http_client=ctx["http_client"],
        cache=RobotsCache(ctx["redis"], settings.robots_cache_ttl_seconds),
        user_agent=settings.user_agent,
    )

    ctx["curl_session"] = AsyncSession()
    ctx["browser_slots"] = BrowserSlots(max_concurrent_browsers=settings.max_concurrent_browsers)
    ctx["domain_memory"] = DomainMemory(ctx["redis"], settings.domain_memory_ttl_seconds)
    ctx["rate_limiter"] = PerDomainConcurrencyLimiter(settings.per_domain_max_concurrency)


async def shutdown(ctx: dict) -> None:
    await ctx["curl_session"].close()
    await ctx["http_client"].aclose()


class WorkerSettings:
    functions = [run_scrape_job]
    on_startup = startup
    on_shutdown = shutdown
    redis_settings = RedisSettings.from_dsn(get_settings().redis_url)
