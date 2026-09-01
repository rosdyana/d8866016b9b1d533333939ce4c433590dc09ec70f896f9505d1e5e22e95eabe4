from __future__ import annotations

from arq.connections import RedisSettings
from curl_cffi import AsyncSession
from firecrawl import AsyncFirecrawl

from app.config import get_settings
from app.jobs.cache import ScrapeCache
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

    # One impersonating session for everything that talks to a target host,
    # robots.txt included: the block on acer.com/hp.com is at the TLS layer,
    # so a plain client cannot read robots.txt either - and that failure is
    # fail-closed, which turned an allow-all robots.txt into a hard
    # robots_disallowed for the whole host.
    ctx["curl_session"] = AsyncSession()
    ctx["robots_gate"] = RobotsGate(
        session=ctx["curl_session"],
        cache=RobotsCache(ctx["redis"], settings.robots_cache_ttl_seconds),
        user_agent=settings.user_agent,
        impersonate=settings.curl_impersonate_target,
    )
    ctx["browser_slots"] = BrowserSlots(max_concurrent_browsers=settings.max_concurrent_browsers)
    ctx["domain_memory"] = DomainMemory(ctx["redis"], settings.domain_memory_ttl_seconds)
    ctx["scrape_cache"] = ScrapeCache(ctx["redis"], settings.scrape_cache_ttl_seconds)
    ctx["rate_limiter"] = PerDomainConcurrencyLimiter(settings.per_domain_max_concurrency)
    # None when no key is configured, which is how Stage 5 stays out of the
    # chain entirely (see `worker/tasks.py:_build_stages`). AsyncFirecrawl
    # exposes no close() and no async-context-manager; its internal httpx
    # client is built with max_keepalive_connections=0, so it holds no idle
    # sockets and needs no shutdown hook.
    ctx["firecrawl"] = (
        AsyncFirecrawl(api_key=settings.firecrawl_api_key) if settings.firecrawl_api_key else None
    )


async def shutdown(ctx: dict) -> None:
    await ctx["curl_session"].close()


class WorkerSettings:
    functions = [run_scrape_job]
    on_startup = startup
    on_shutdown = shutdown
    redis_settings = RedisSettings.from_dsn(get_settings().redis_url)
