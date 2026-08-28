"""Last resort: SeleniumBase CDP Mode - Chromium driven over the DevTools
Protocol with no WebDriver attached, plus captcha solving for the Turnstile
/ reCAPTCHA / hCaptcha interstitials that stop Stage 2.

Only the async `cdp_driver` surface is used here. SeleniumBase's sync
helpers (`sb_cdp.Chrome`, `SB()`) apply nest_asyncio to whatever loop is
running, which inside the arq worker would patch the worker's own event
loop - never import those in this process.
"""

from __future__ import annotations

from contextlib import suppress

import mycdp
from seleniumbase import cdp_driver

from pipeline.browser.settle import settle_until_stable
from pipeline.browser.slots import BrowserSlots
from pipeline.stages.base import FetchResult, Stage
from pipeline.stages.content_type import guard_html_content_type

# Share of the stage budget spent letting a client-rendered page fill in.
# The rest is reserved for launch, navigation and captcha solving.
_SETTLE_BUDGET_RATIO = 0.4


class _DocumentResponses:
    """`get_content()` returns HTML with no HTTP status, but
    `pipeline/quality.py` needs one to spot a 403/429 block. The CDP
    Network domain is the only place that status is available, so record
    every top-level document response and reconcile against the final URL
    afterwards.
    """

    def __init__(self) -> None:
        self.seen: list[tuple[str, int, str]] = []

    def handler(self, event) -> None:
        if event.type_ is not mycdp.network.ResourceType.DOCUMENT:
            return
        response = event.response
        self.seen.append((response.url, int(response.status), response.mime_type or ""))

    def resolve(self, final_url: str) -> tuple[int, str] | None:
        if not self.seen:
            return None
        for url, status, mime in reversed(self.seen):
            if url == final_url:
                return status, mime
        # An iframe document can land after the main frame's; falling back
        # to the first response keeps us on the top-level navigation.
        _, status, mime = self.seen[0]
        return status, mime


class Stage3SeleniumBase(Stage):
    name = "stage3_seleniumbase"

    def __init__(
        self,
        slots: BrowserSlots,
        timeout_seconds: float = 90.0,
        use_xvfb: bool = True,
    ) -> None:
        self._slots = slots
        self.timeout_seconds = timeout_seconds
        self._use_xvfb = use_xvfb

    async def fetch(self, url: str) -> FetchResult:
        async with self._slots.acquire():
            browser = await cdp_driver.start_async(
                # Real headless is trivially detectable; a virtual display
                # is the whole reason this stage can pass where Stage 2
                # failed. xvfb is Linux-only, hence configurable.
                xvfb=self._use_xvfb,
                incognito=True,
                ad_block=True,
            )
            try:
                page = await browser.get("about:blank")

                documents = _DocumentResponses()
                await page.send(mycdp.network.enable())
                page.add_handler(mycdp.network.ResponseReceived, documents.handler)

                await page.get(url)
                with suppress(Exception):
                    # Best-effort: no captcha present is the common case,
                    # and a solver failure must not lose the HTML we have.
                    await page.solve_captcha()

                html = await settle_until_stable(
                    page.get_content, self.timeout_seconds * _SETTLE_BUDGET_RATIO
                )
                final_url = await page.evaluate("window.location.href") or url

                resolved = documents.resolve(final_url)
                if resolved is None:
                    status_code, mime_type = 200, ""
                else:
                    status_code, mime_type = resolved
                guard_html_content_type(mime_type)
            finally:
                with suppress(Exception):
                    browser.stop()

        return FetchResult(html=html, status_code=status_code, final_url=str(final_url))
