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

from pipeline.browser.lazyload import has_unresolved_lazy_content
from pipeline.browser.slots import BrowserSlots
from pipeline.stages.base import FetchResult, Stage
from pipeline.stages.content_type import guard_html_content_type

_user_agent: str | None = None
_user_agent_lock = asyncio.Lock()

# Share of the stage budget crawl4ai's own `wait_for` may spend polling for
# lazyload fragments (see pipeline/browser/lazyload.py) to resolve after
# `scan_full_page` has scrolled. A JS-mode `wait_for` never raises on its
# own timeout - it just gives up quietly (`crawl4ai/async_crawler_strategy.py`
# `csp_compliant_wait` returns `False`, and the caller discards that return
# value) - so this bounds how long that quiet wait can run, not whether it
# can fail the stage.
_LAZYLOAD_WAIT_TIMEOUT_RATIO = 0.2

# `comp_lazyload` placeholders are literally empty until their fragment
# lands - matches `pipeline/browser/lazyload.py::has_unresolved_lazy_content`'s
# emptiness anchor, expressed in-page since this runs inside the browser.
_LAZYLOAD_RESOLVED_JS = (
    "() => !Array.from(document.querySelectorAll('.comp_lazyload'))"
    ".some(el => el.innerHTML.trim() === '')"
)


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
            # Lenovo PDPs defer several sections behind IntersectionObserver
            # -gated `comp_lazyload` placeholders (see
            # pipeline/browser/lazyload.py) that never fire without a
            # scroll. `max_scroll_steps` is bumped from crawl4ai's default
            # of 10: at its default 600px viewport that only reaches
            # ~6,600px, short of a full Lenovo PDP's height. `scroll_delay`
            # matches Stage 3's own per-step pause.
            scan_full_page=True,
            scroll_delay=0.3,
            max_scroll_steps=30,
            # Best-effort extra wait for a fragment's fetch to land after
            # scan_full_page's scroll - see _LAZYLOAD_WAIT_TIMEOUT_RATIO for
            # why this alone cannot be trusted to force escalation.
            wait_for=f"js:{_LAZYLOAD_RESOLVED_JS}",
            wait_for_timeout=int(self.timeout_seconds * 1000 * _LAZYLOAD_WAIT_TIMEOUT_RATIO),
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

        if has_unresolved_lazy_content(result.html):
            # scan_full_page scrolled and wait_for gave the fragment fetch
            # extra time, but wait_for's JS mode gives up quietly rather
            # than raising (see _LAZYLOAD_WAIT_TIMEOUT_RATIO above) - so
            # this is the only thing that actually forces escalation.
            # Stage 3 has the same check wired into a real poll loop
            # (`settle_until_stable`), which is what resolves it.
            raise RuntimeError("unresolved lazyload content")

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
