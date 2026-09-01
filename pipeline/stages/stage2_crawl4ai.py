"""crawl4ai: a real Chromium under Playwright with crawl4ai's own stealth
patches, sitting between the plain HTTP client and the two heavyweight
browsers.

It earns the slot because it fetches pages the rest of the chain does not.
Verified on reddit.com, whose "Prove your humanity" interstitial Stage 1
cannot get past (see `pipeline/quality.py`'s `_CHALLENGE_MARKERS`) - and it
does so for less than Camoufox costs, which downloads and launches a
patched Firefox per job.

The same package supplies `extract/converter.py`'s HTML -> Markdown
conversion for every other stage too, so this dependency pays for itself
twice.
"""

from __future__ import annotations

import asyncio

from crawl4ai import AsyncWebCrawler, BrowserConfig, CacheMode, CrawlerRunConfig

from pipeline.browser.slots import BrowserSlots
from pipeline.stages.base import FetchResult, Stage
from pipeline.stages.content_type import guard_html_content_type

_user_agent: str | None = None
_user_agent_lock = asyncio.Lock()


async def _coherent_user_agent() -> str:
    """The bundled Chromium's own UA, minus the `Headless` token.

    Neither of the obvious options works. crawl4ai's default is a
    hardcoded, malformed "Mozilla/5.0 (X11; Linux x86_64)
    AppleWebKit/537.36 Chrome/116.0.0.0 Safari/537.36" - no
    `(KHTML, like Gecko)`, and Chrome 116 on Linux from an engine that is
    Chrome 148 on whatever the host is. Passing an empty string to get
    Playwright's real UA is worse: measured 2026-09-02 against
    httpbin.org/headers, the header then reads `HeadlessChrome/148...` with
    `Sec-Ch-Ua: "HeadlessChrome";v="148"`, while crawl4ai's stealth patch
    separately rewrites *navigator.userAgent* to `Chrome/148` - so the page
    and the request disagree, which is the exact tell we are avoiding.

    reddit.com reads the header and acts on it: 843KB of real content for
    the fake UA, a 190KB shell for the HeadlessChrome one (3/3 each,
    measured 2026-09-02). Taking the engine's own string and dropping the
    token gives one identity everywhere - right version, right platform,
    and crawl4ai derives matching Sec-Ch-Ua from it.

    Probed once per process behind a lock (~1s on the first job) rather
    than hardcoded, so it cannot drift when Playwright's Chromium updates.
    """
    global _user_agent
    if _user_agent is None:
        async with _user_agent_lock:
            if _user_agent is None:
                from playwright.async_api import async_playwright

                async with async_playwright() as playwright:
                    browser = await playwright.chromium.launch(headless=True)
                    try:
                        page = await browser.new_page()
                        raw = await page.evaluate("navigator.userAgent")
                    finally:
                        await browser.close()
                _user_agent = raw.replace("HeadlessChrome/", "Chrome/")
    return _user_agent


def _content_type(headers: dict | None) -> str | None:
    for key, value in (headers or {}).items():
        if key.lower() == "content-type":
            return value
    return None


class Stage2Crawl4ai(Stage):
    name = "stage2_crawl4ai"

    def __init__(
        self,
        slots: BrowserSlots,
        timeout_seconds: float = 45.0,
        headless: bool = True,
    ) -> None:
        self._slots = slots
        self.timeout_seconds = timeout_seconds
        self._headless = headless

    async def fetch(self, url: str) -> FetchResult:
        user_agent = await _coherent_user_agent()
        browser_config = BrowserConfig(
            browser_type="chromium",
            headless=self._headless,
            enable_stealth=True,
            verbose=False,
            # See `_coherent_user_agent` - crawl4ai's default is a
            # malformed Chrome 116 string that contradicts the engine.
            user_agent=user_agent,
        )
        run_config = CrawlerRunConfig(
            # This service has its own response cache (`app/jobs/cache.py`)
            # keyed on url+formats+robotstxt. A second cache underneath it
            # would serve stale HTML that never reaches those keys.
            cache_mode=CacheMode.BYPASS,
            # crawl4ai ships its own robots parser. Letting it run would
            # fetch robots.txt a second time with a different HTTP client,
            # and would re-impose the gate on a request that explicitly set
            # `robotstxt: false`. `pipeline/robots/gate.py` is the only
            # robots authority in this pipeline.
            check_robots_txt=False,
            # Measured 2026-09-02, 3 trials per cell against the quality
            # gate: `domcontentloaded` returns before reddit hydrates (1/3,
            # 3.4s) and `networkidle` never fires on lenovo.com, which polls
            # forever (0/3, timing out at 45.6s). `load` passed 3/3 on
            # reddit, lenovo and hp, and was the fastest of the three
            # overall (4.4s / 6.9s / 6.4s).
            wait_until="load",
            page_timeout=int(self.timeout_seconds * 1000),
            # crawl4ai's own overlay/consent handling, rather than wiring in
            # `pipeline/consent/dismiss.py` - that module is written and
            # tested against Playwright Firefox because Stage 3 is its only
            # production caller.
            remove_overlay_elements=True,
            remove_consent_popups=True,
            verbose=False,
        )

        async with self._slots.acquire():
            # Launched per job, not pooled: same reason as Stage 3. A shared
            # browser presents one identical device to a host for every
            # request we ever make to it, which is the correlation signal
            # these stages exist to defeat. `BrowserSlots` only bounds how
            # many may run at once.
            async with AsyncWebCrawler(config=browser_config) as crawler:
                result = await crawler.arun(url=url, config=run_config)

        if not result.success:
            raise RuntimeError(result.error_message or "crawl4ai reported failure")

        guard_html_content_type(_content_type(result.response_headers))

        # No settle loop here, unlike Stages 3 and 4. `settle_until_stable`
        # needs a repeatable `async () -> str`, and `arun()` is one-shot. A
        # page still running a challenge script (store.acer.com's Akamai
        # sensor) fails `is_good_enough` and escalates to Stage 3, which
        # does settle. A fixed `delay_before_return_html` is the wrong fix -
        # see `pipeline/browser/settle.py` for why a fixed sleep is a coin
        # flip on these sites.
        return FetchResult(
            html=result.html,
            # crawl4ai leaves status_code None on some navigations; the
            # quality gate needs an int and a 200 is the honest default
            # for "the page came back and we have its HTML".
            status_code=result.status_code or 200,
            final_url=result.redirected_url or result.url,
        )
