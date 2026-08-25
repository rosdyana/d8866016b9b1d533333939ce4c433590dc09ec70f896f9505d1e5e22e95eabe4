from __future__ import annotations

from pipeline.browser.context_pool import BrowserContextPool
from pipeline.proxy.provider import ProxyProvider
from pipeline.stages.base import FetchResult, Stage
from pipeline.stages.stage2_playwright import fetch_via_browser


class Stage3PlaywrightProxy(Stage):
    """Same rendering path as Stage 2, routed through a proxy - disabled by
    config until a real ProxyProvider is wired in (see PROXY_ENABLED)."""

    name = "stage3_playwright_proxy"

    def __init__(
        self,
        context_pool: BrowserContextPool,
        proxy_provider: ProxyProvider,
        user_agent: str,
        enabled: bool,
        timeout_seconds: float = 40.0,
    ) -> None:
        self._context_pool = context_pool
        self._proxy_provider = proxy_provider
        self._user_agent = user_agent
        self._enabled = enabled
        self.timeout_seconds = timeout_seconds

    async def fetch(self, url: str) -> FetchResult:
        if not self._enabled:
            raise RuntimeError("stage3_playwright_proxy is disabled (PROXY_ENABLED=false)")

        proxy = await self._proxy_provider.get_proxy()
        if proxy is None:
            raise RuntimeError("no proxy available from the configured ProxyProvider")

        return await fetch_via_browser(
            self._context_pool, url, self._user_agent, self.timeout_seconds, proxy=proxy
        )
