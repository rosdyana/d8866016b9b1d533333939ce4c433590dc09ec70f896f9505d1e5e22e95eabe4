"""Per-domain politeness limiter.

Independent of robots.txt Crawl-delay: robots.txt may specify no delay at
all, but several concurrent internal jobs hitting one host in parallel can
still get the service's IP blocked. This caps concurrent in-flight fetches
per host within a single worker process.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections import defaultdict


class PerDomainConcurrencyLimiter:
    def __init__(self, max_concurrent_per_domain: int = 2) -> None:
        self._max = max_concurrent_per_domain
        self._semaphores: dict[str, asyncio.Semaphore] = defaultdict(
            lambda: asyncio.Semaphore(self._max)
        )

    @contextlib.asynccontextmanager
    async def slot(self, host: str):
        sem = self._semaphores[host]
        async with sem:
            yield
