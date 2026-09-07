"""Scrolls a settled-looking page to trigger IntersectionObserver-gated
lazy content before the settle loop's quality check runs.

Lenovo product pages ship several sections (`ofp-fe-techSpecs`,
`ofp-fe-portsAndSlots`, `ofp-fe-compatibleAccessories`,
`ofp-fe-similarProducts`, `ofp-fe-reviews`, and unlabelled `tag="fragment"`
blocks) as `<div class="comp_lazyload" ...></div>` placeholders that only
fetch their real content once scrolled into view. The above-the-fold
content renders and passes `is_good_enough` well before that happens, so
`settle_until_stable` exits early on a page that looks "good enough" but
still has unresolved fragments below the fold.
"""

from __future__ import annotations

import asyncio
import re

from playwright.async_api import Error as PlaywrightError
from playwright.async_api import Page

# Anchored on emptiness, not a bare substring match on the class name: if
# the site's lazyload JS fills the div in place rather than replacing it
# outright, a substring check would still see "comp_lazyload" in the
# resolved page and report it as unresolved forever. Attribute order
# (`class` vs `tag` vs `file` first) is not assumed.
_LAZYLOAD_PLACEHOLDER_RE = re.compile(
    r'<div\b[^>]*\bclass="[^"]*\bcomp_lazyload\b[^"]*"[^>]*>\s*</div>',
    re.IGNORECASE,
)

_SCROLL_STEP_PAUSE_SECONDS = 0.3


def has_unresolved_lazy_content(html: str) -> bool:
    """True if a `comp_lazyload` placeholder is still empty.

    Matched against raw HTML, not `clean_html()`'s visible text - this is a
    structural markup signal, not natural-language content, so it stays a
    different category of check than `pipeline/quality.py`'s challenge
    markers and never touches the single shared "good enough" definition.
    """
    return bool(_LAZYLOAD_PLACEHOLDER_RE.search(html))


async def scroll_full_page(page: Page, budget_seconds: float) -> None:
    """Best-effort: scroll top to bottom so every IntersectionObserver-gated
    fragment gets a chance to fire, then return to the top so a virtualized
    list that unmounts off-screen rows (if any) re-renders what was there
    at load. Never raises - a page this couldn't scroll just gets extracted
    as whatever `settle_until_stable` already has.

    One top-to-bottom pass, not a scroll on every settle poll: once every
    position has been visited, fragments land on their own async timing and
    `settle_until_stable`'s existing poll loop is exactly what already
    waits out that kind of growth (it does the same for Akamai's
    challenge-to-real-page swap). `budget_seconds` is independent of the
    settle budget - the orchestrator wraps this whole stage in one
    `asyncio.wait_for` (`pipeline/orchestrator.py`), so an infinite-scroll
    page must not spend that shared ceiling scrolling forever.
    """
    loop = asyncio.get_running_loop()
    deadline = loop.time() + budget_seconds
    try:
        viewport_height = await page.evaluate("() => window.innerHeight") or 800
        position = 0
        while loop.time() < deadline:
            scroll_height = await page.evaluate("() => document.body.scrollHeight")
            if position >= scroll_height:
                break
            position = min(position + viewport_height, scroll_height)
            await page.evaluate("(y) => window.scrollTo(0, y)", position)
            await asyncio.sleep(_SCROLL_STEP_PAUSE_SECONDS)
        await page.evaluate("() => window.scrollTo(0, 0)")
    except PlaywrightError:
        pass
