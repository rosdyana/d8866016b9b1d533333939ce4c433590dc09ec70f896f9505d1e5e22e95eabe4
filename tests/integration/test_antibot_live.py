"""Live anti-bot verification. Deselected by default; run with `-m live`.

Every other test in this suite proves the pipeline's plumbing. Nothing but
this proves the premise the pipeline exists for - that these stages are not
detected - so it hits the real endpoints on purpose. It needs network, and
stages 2 and 3 need their browsers fetched (`python -m camoufox fetch`).
"""

from __future__ import annotations

import sys

import pytest
from curl_cffi import AsyncSession

from extract.html_cleaner import clean_html
from pipeline.browser.slots import BrowserSlots
from pipeline.quality import is_good_enough
from pipeline.stages.stage1_curl_cffi import Stage1CurlCffi
from pipeline.stages.stage2_camoufox import Stage2Camoufox
from pipeline.stages.stage3_seleniumbase import Stage3SeleniumBase

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

# Stage 3 runs under Xvfb in production because headless *Chromium* is
# trivially detectable; a virtual display is Linux-only, so locally on
# macOS/Windows it falls back to headless and a passing run here is the
# weaker configuration. Stage 2 is headless everywhere on purpose - see
# settings.stage2_use_xvfb for the measurement.

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
async def test_stage2_camoufox_is_not_detected(url):
    stage = Stage2Camoufox(BrowserSlots(1), headless=True)
    result = await stage.fetch(url)
    assert result.status_code < 400
    _assert_not_flagged(result.html)


@pytest.mark.asyncio
@pytest.mark.parametrize("url", BOT_CHECKS)
async def test_stage3_seleniumbase_is_not_detected(url):
    stage = Stage3SeleniumBase(BrowserSlots(1), use_xvfb=sys.platform.startswith("linux"))
    result = await stage.fetch(url)
    assert result.status_code < 400
    _assert_not_flagged(result.html)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "stage_factory",
    [
        lambda: Stage2Camoufox(BrowserSlots(1), headless=True),
        lambda: Stage3SeleniumBase(BrowserSlots(1), use_xvfb=sys.platform.startswith("linux")),
    ],
    ids=["camoufox", "seleniumbase"],
)
async def test_browser_stages_pass_sannysoft_webdriver_probe(stage_factory):
    # A positive assertion, not just absence of markers: sannysoft renders
    # "missing (passed)" in the WebDriver row only when navigator.webdriver
    # is genuinely absent.
    result = await stage_factory().fetch("https://bot.sannysoft.com/")
    assert "missing (passed)" in clean_html(result.html).lower()


@pytest.mark.asyncio
async def test_stage3_clears_cloudflare_turnstile():
    stage = Stage3SeleniumBase(BrowserSlots(1), use_xvfb=sys.platform.startswith("linux"))
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
async def test_stage2_waits_out_the_akamai_interstitial():
    stage = Stage2Camoufox(BrowserSlots(1), headless=True)
    result = await stage.fetch(AKAMAI_INTERSTITIAL)
    verdict = is_good_enough(result.status_code, result.html)
    assert verdict.passed, f"settled on the challenge page instead: {verdict.reason}"
