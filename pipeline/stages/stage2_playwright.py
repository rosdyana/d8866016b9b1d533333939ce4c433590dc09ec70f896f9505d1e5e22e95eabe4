from __future__ import annotations

from pipeline.browser.context_pool import BrowserContextPool
from pipeline.consent.dismiss import attach_dialog_autodismiss, dismiss_consent_and_overlays
from pipeline.stages.base import FetchResult, Stage

_POST_DISMISS_SETTLE_MS = 300


async def fetch_via_browser(
    context_pool: BrowserContextPool,
    url: str,
    user_agent: str,
    timeout_seconds: float,
    proxy: dict | None = None,
) -> FetchResult:
    """Shared by Stage 2 (direct) and Stage 3 (via proxy) - identical
    rendering/consent-dismissal behavior, the only difference is whether a
    proxy config is passed to the browser context."""
    context_kwargs: dict = {"user_agent": user_agent}
    if proxy is not None:
        context_kwargs["proxy"] = proxy

    async with context_pool.new_context(**context_kwargs) as context:
        page = await context.new_page()
        attach_dialog_autodismiss(page)

        response = await page.goto(
            url, wait_until="domcontentloaded", timeout=timeout_seconds * 1000
        )
        await dismiss_consent_and_overlays(page)
        await page.wait_for_timeout(_POST_DISMISS_SETTLE_MS)

        html = await page.content()
        status_code = response.status if response is not None else 200
        final_url = page.url

    return FetchResult(html=html, status_code=status_code, final_url=final_url)


class Stage2Playwright(Stage):
    """Direct (no proxy) headless rendering - handles JS-rendered pages and
    dismisses cookie/popup overlays that Stage 1's plain HTTP fetch can't
    interact with at all."""

    name = "stage2_playwright"

    def __init__(
        self,
        context_pool: BrowserContextPool,
        user_agent: str,
        timeout_seconds: float = 40.0,
    ) -> None:
        self._context_pool = context_pool
        self._user_agent = user_agent
        self.timeout_seconds = timeout_seconds

    async def fetch(self, url: str) -> FetchResult:
        return await fetch_via_browser(
            self._context_pool, url, self._user_agent, self.timeout_seconds
        )
