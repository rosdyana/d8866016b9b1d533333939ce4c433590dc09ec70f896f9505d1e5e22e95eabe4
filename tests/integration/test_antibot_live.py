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

# A virtual display is Linux-only. In production both browser stages run
# under Xvfb (settings.browser_use_xvfb) because real headless is
# detectable; locally on macOS/Windows they fall back to headless, so a
# passing run here is the weaker of the two configurations.
_ON_LINUX = sys.platform.startswith("linux")

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
    stage = Stage2Camoufox(BrowserSlots(1), headless="virtual" if _ON_LINUX else True)
    result = await stage.fetch(url)
    assert result.status_code < 400
    _assert_not_flagged(result.html)


@pytest.mark.asyncio
@pytest.mark.parametrize("url", BOT_CHECKS)
async def test_stage3_seleniumbase_is_not_detected(url):
    stage = Stage3SeleniumBase(BrowserSlots(1), use_xvfb=_ON_LINUX)
    result = await stage.fetch(url)
    assert result.status_code < 400
    _assert_not_flagged(result.html)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "stage_factory",
    [
        lambda: Stage2Camoufox(BrowserSlots(1), headless="virtual" if _ON_LINUX else True),
        lambda: Stage3SeleniumBase(BrowserSlots(1), use_xvfb=_ON_LINUX),
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
    stage = Stage3SeleniumBase(BrowserSlots(1), use_xvfb=_ON_LINUX)
    result = await stage.fetch("https://seleniumbase.io/apps/turnstile")
    assert "success" in result.html.lower() or "verified" in result.html.lower()
