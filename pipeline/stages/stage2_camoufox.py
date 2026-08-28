"""Camoufox: a patched Firefox that spoofs its fingerprint inside Gecko's
C++ rather than by injecting JavaScript, so page scripts read the spoofed
values natively with no override object to detect.

Camoufox hands back an ordinary Playwright Browser, which is why
`pipeline/consent/dismiss.py` works here untouched.
"""

from __future__ import annotations

from camoufox.async_api import AsyncCamoufox
from playwright.async_api import Error as PlaywrightError

from common.errors import UnsupportedContentType
from pipeline.browser.settle import settle_until_stable
from pipeline.browser.slots import BrowserSlots
from pipeline.consent.dismiss import attach_dialog_autodismiss, dismiss_consent_and_overlays
from pipeline.stages.base import FetchResult, Stage
from pipeline.stages.content_type import guard_html_content_type

# Share of the stage budget spent letting a client-rendered page fill in
# after consent dismissal. The rest is reserved for launch and navigation.
_SETTLE_BUDGET_RATIO = 0.4


class Stage2Camoufox(Stage):
    name = "stage2_camoufox"

    def __init__(
        self,
        slots: BrowserSlots,
        timeout_seconds: float = 45.0,
        headless: str | bool = "virtual",
    ) -> None:
        self._slots = slots
        self.timeout_seconds = timeout_seconds
        self._headless = headless

    async def fetch(self, url: str) -> FetchResult:
        async with self._slots.acquire():
            # Launched per job, not pooled: the fingerprint is fixed at
            # launch, so reusing one browser would show a host the same
            # device for every request we ever make to it.
            async with AsyncCamoufox(
                headless=self._headless,
                os=["windows", "macos"],
                humanize=True,
                geoip=True,
                block_webrtc=True,
                enable_cache=True,
            ) as browser:
                page = await browser.new_page()
                attach_dialog_autodismiss(page)

                try:
                    response = await page.goto(
                        url, wait_until="domcontentloaded", timeout=self.timeout_seconds * 1000
                    )
                except PlaywrightError as exc:
                    # Firefox answers a non-renderable content type by
                    # starting a download instead of navigating. Match
                    # Stage 1 and terminate rather than escalating - Stage
                    # 3 can't turn a PDF into HTML either.
                    if "download" in str(exc).lower():
                        raise UnsupportedContentType("download") from exc
                    raise

                if response is not None:
                    guard_html_content_type(response.headers.get("content-type"))

                await dismiss_consent_and_overlays(page)

                html = await settle_until_stable(
                    page.content, self.timeout_seconds * _SETTLE_BUDGET_RATIO
                )
                status_code = response.status if response is not None else 200
                final_url = page.url

        return FetchResult(html=html, status_code=status_code, final_url=final_url)
