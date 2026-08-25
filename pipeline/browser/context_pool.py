"""Owns one long-lived Chromium process for the whole worker. Each fetch
gets its own isolated BrowserContext (so cookies/local storage never leak
between different sites) under a concurrency semaphore that bounds total
browser memory use - launching a fresh Browser per request would be far
more expensive than the contexts it hands out.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

from playwright.async_api import Browser, Playwright, async_playwright


class BrowserContextPool:
    def __init__(self, max_concurrent_contexts: int = 4) -> None:
        self._max_concurrent_contexts = max_concurrent_contexts
        self._playwright: Playwright | None = None
        self._browser: Browser | None = None
        self._semaphore = asyncio.Semaphore(max_concurrent_contexts)

    async def start(self) -> None:
        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(headless=True)

    async def stop(self) -> None:
        if self._browser is not None:
            await self._browser.close()
        if self._playwright is not None:
            await self._playwright.stop()

    @asynccontextmanager
    async def new_context(self, **kwargs):
        if self._browser is None:
            raise RuntimeError("BrowserContextPool.start() was not called")
        async with self._semaphore:
            context = await self._browser.new_context(**kwargs)
            try:
                yield context
            finally:
                await context.close()
