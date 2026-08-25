from __future__ import annotations

import httpx
from arq.connections import RedisSettings

from app.config import get_settings
from common.logging import configure_logging
from common.rate_limit import PerDomainConcurrencyLimiter
from pipeline.browser.context_pool import BrowserContextPool
from pipeline.domain_memory import DomainMemory
from pipeline.proxy.provider import NoopProxyProvider
from pipeline.robots.cache import RobotsCache
from pipeline.robots.gate import RobotsGate
from worker.tasks import run_scrape_job


async def startup(ctx: dict) -> None:
    configure_logging()
    settings = get_settings()
    ctx["settings"] = settings

    ctx["http_client"] = httpx.AsyncClient()
    ctx["robots_gate"] = RobotsGate(
        http_client=ctx["http_client"],
        cache=RobotsCache(ctx["redis"], settings.robots_cache_ttl_seconds),
        user_agent=settings.user_agent,
    )

    ctx["context_pool"] = BrowserContextPool(max_concurrent_contexts=settings.stage2_max_contexts)
    await ctx["context_pool"].start()

    ctx["proxy_provider"] = NoopProxyProvider()
    ctx["domain_memory"] = DomainMemory(ctx["redis"], settings.domain_memory_ttl_seconds)
    ctx["rate_limiter"] = PerDomainConcurrencyLimiter(settings.per_domain_max_concurrency)


async def shutdown(ctx: dict) -> None:
    await ctx["context_pool"].stop()
    await ctx["http_client"].aclose()


class WorkerSettings:
    functions = [run_scrape_job]
    on_startup = startup
    on_shutdown = shutdown
    redis_settings = RedisSettings.from_dsn(get_settings().redis_url)
