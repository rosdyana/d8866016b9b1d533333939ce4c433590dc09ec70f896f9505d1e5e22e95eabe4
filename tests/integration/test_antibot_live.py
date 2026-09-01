"""Live anti-bot verification. Deselected by default; run with `-m live`.

Every other test in this suite proves the pipeline's plumbing. Nothing but
this proves the premise the pipeline exists for - that these stages are not
detected - so it hits the real endpoints on purpose. It needs network, and
stages 2-4 need their browsers fetched (`python -m camoufox fetch` and
`python -m playwright install chromium`).
"""

from __future__ import annotations

import sys

import pytest
from curl_cffi import AsyncSession

from extract.html_cleaner import clean_html
from pipeline.browser.slots import BrowserSlots
from pipeline.quality import is_good_enough
from pipeline.stages.stage1_curl_cffi import Stage1CurlCffi
from pipeline.stages.stage2_crawl4ai import Stage2Crawl4ai
from pipeline.stages.stage3_camoufox import Stage3Camoufox
from pipeline.stages.stage4_seleniumbase import Stage4SeleniumBase

pytestmark = pytest.mark.live

# Fingerprint/automation checks. Stage 1 is a plain HTTP client and cannot
# pass a JS-driven check, so it is only asserted against the TLS-layer
# targets below.
BOT_CHECKS = [
    "https://bot.sannysoft.com/",
    "https://www.browserscan.net/bot-detection",
]

# Sites that reject a non-browser TLS/HTTP2 fingerprint outright, verified
# 2026-08-29: plain curl gets HTTP/2 INTERNAL_ERROR or an HTTP/1.1 hang
# delivering zero bytes, while curl_cffi gets a normal 200.
TLS_BLOCKED = [
    "https://www.hp.com/us-en/shop/",
    "https://www.acer.com/us-en/laptops",
]

# Stage 4 runs under Xvfb in production because headless *Chromium* is
# trivially detectable; a virtual display is Linux-only, so locally on
# macOS/Windows it falls back to headless and a passing run here is the
# weaker configuration. Stage 3 is headless everywhere on purpose - see
# settings.stage3_use_xvfb for the measurement.

_DETECTION_MARKERS = ("headlesschrome", "webdriver detected", "you are a bot", "bot detected")


def _assert_not_flagged(html: str) -> None:
    # Scan the script-stripped text, never raw HTML: bot.sannysoft.com's own
    # detector source contains `if (/HeadlessChrome/.test(...))`, so a raw
    # substring scan reports a detection on a page that actually passed.
    # Same trap `pipeline/quality.py` documents for its text counting.
    lowered = clean_html(html).lower()
    for marker in _DETECTION_MARKERS:
        assert marker not in lowered, f"detected as automation: {marker!r}"


@pytest.mark.asyncio
@pytest.mark.parametrize("url", TLS_BLOCKED)
async def test_stage1_passes_tls_fingerprint_blocks(url):
    async with AsyncSession() as session:
        result = await Stage1CurlCffi(session).fetch(url)
    assert result.status_code == 200
    assert is_good_enough(result.status_code, result.html).passed, "fetched, but judged low quality"


@pytest.mark.asyncio
@pytest.mark.parametrize("url", BOT_CHECKS)
async def test_stage3_camoufox_is_not_detected(url):
    stage = Stage3Camoufox(BrowserSlots(1), headless=True)
    result = await stage.fetch(url)
    assert result.status_code < 400
    _assert_not_flagged(result.html)


@pytest.mark.asyncio
@pytest.mark.parametrize("url", BOT_CHECKS)
async def test_stage4_seleniumbase_is_not_detected(url):
    stage = Stage4SeleniumBase(BrowserSlots(1), use_xvfb=sys.platform.startswith("linux"))
    result = await stage.fetch(url)
    assert result.status_code < 400
    _assert_not_flagged(result.html)


# Stage 2 is deliberately absent from the two probes below. crawl4ai's
# stealth is JavaScript-injected, and sannysoft dumps the *source* of the
# overridden getters: instead of `function get userAgent() { [native code]
# }` it renders crawl4ai's `current_ua.replace("HeadlessChrome/",
# "Chrome/")` as page text. Measured 2026-09-02 - the override is visible
# to any page that looks, which is exactly the class of tell Camoufox's
# in-Gecko patching exists to avoid. Stage 2 is not there to beat
# fingerprint checks; it is a cheap real browser for the majority of pages,
# and anything that detects it escalates to Stage 3. Asserting otherwise
# here would be asserting something untrue.
@pytest.mark.asyncio
@pytest.mark.parametrize(
    "stage_factory",
    [
        lambda: Stage3Camoufox(BrowserSlots(1), headless=True),
        lambda: Stage4SeleniumBase(BrowserSlots(1), use_xvfb=sys.platform.startswith("linux")),
    ],
    ids=["camoufox", "seleniumbase"],
)
async def test_browser_stages_pass_sannysoft_webdriver_probe(stage_factory):
    # A positive assertion, not just absence of markers: sannysoft renders
    # "missing (passed)" in the WebDriver row only when navigator.webdriver
    # is genuinely absent.
    result = await stage_factory().fetch("https://bot.sannysoft.com/")
    assert "missing (passed)" in clean_html(result.html).lower()


# The reason Stage 2 is in the chain at all. reddit.com answers Stage 1
# with a "Prove your humanity" interstitial at HTTP 200, and reads the
# request User-Agent to decide what to serve a browser: measured 2026-09-02
# over 3 trials each, the HeadlessChrome header Playwright sends by default
# got a 190KB shell every time, while the same engine's UA with the token
# removed got 850KB of real content (see `_coherent_user_agent`).
@pytest.mark.asyncio
async def test_stage2_crawl4ai_gets_past_reddits_interstitial():
    result = await Stage2Crawl4ai(BrowserSlots(1), headless=True).fetch(
        "https://www.reddit.com/r/programming/"
    )
    verdict = is_good_enough(result.status_code, result.html)
    assert verdict.passed, f"reddit served a shell: {verdict.reason}"


@pytest.mark.asyncio
async def test_stage2_crawl4ai_announces_one_coherent_identity():
    # The header UA, Sec-Ch-Ua and navigator.userAgent must agree, and none
    # may say Headless. crawl4ai's default is a malformed Chrome 116 Linux
    # string that contradicts all three.
    from pipeline.stages.stage2_crawl4ai import _coherent_user_agent

    user_agent = await _coherent_user_agent()
    assert "Headless" not in user_agent
    assert "(KHTML, like Gecko)" in user_agent
    assert "Chrome/" in user_agent


@pytest.mark.asyncio
async def test_stage4_clears_cloudflare_turnstile():
    stage = Stage4SeleniumBase(BrowserSlots(1), use_xvfb=sys.platform.startswith("linux"))
    result = await stage.fetch("https://seleniumbase.io/apps/turnstile")
    assert "success" in result.html.lower() or "verified" in result.html.lower()


# Akamai Bot Manager answers with a *static* 2.6KB interstitial at HTTP 200
# and only serves the real page once its sensor JS has run - measured
# 2026-08-29 the challenge held byte-identical for ~4.5s, then the document
# grew to 595KB / ~17.7k characters at t+9s. This is the regression case
# for pipeline/browser/settle.py: a size-stability check alone settles on
# the challenge, and every stage reports text_too_short on a page that
# renders perfectly well.
AKAMAI_INTERSTITIAL = "https://store.acer.com/en-us/nitro-v-16-gaming-laptop-anv16-72-70f4"


@pytest.mark.asyncio
async def test_stage3_waits_out_the_akamai_interstitial():
    stage = Stage3Camoufox(BrowserSlots(1), headless=True)
    result = await stage.fetch(AKAMAI_INTERSTITIAL)
    verdict = is_good_enough(result.status_code, result.html)
    assert verdict.passed, f"settled on the challenge page instead: {verdict.reason}"
