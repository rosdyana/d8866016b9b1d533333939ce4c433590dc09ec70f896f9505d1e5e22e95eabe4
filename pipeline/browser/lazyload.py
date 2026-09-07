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

Shared by Stage 3 (a Playwright `Page`) and Stage 4 (SeleniumBase's CDP
`Tab`) - `_EvaluatingPage` only requires the one method both already
expose, and every JS call below is a single self-contained expression
string rather than Playwright's `evaluate(fn, arg)` two-argument form,
since the CDP side's `Tab.evaluate` (`cdp/tab.py`) takes only a raw
expression and has no argument-binding parameter.
"""

from __future__ import annotations

import asyncio
import re
from contextlib import suppress
from typing import Protocol


class _EvaluatingPage(Protocol):
    async def evaluate(self, expression: str) -> object: ...


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


async def scroll_full_page(page: _EvaluatingPage, budget_seconds: float) -> None:
    """Best-effort: scroll top to bottom so every IntersectionObserver-gated
    fragment gets a chance to fire, then return to the top so a virtualized
    list that unmounts off-screen rows (if any) re-renders what was there
    at load. Never raises - a page this couldn't scroll just gets extracted
    as whatever the caller's own settle/capture step already has. Exceptions
    are suppressed broadly (not a specific engine's error type) because this
    runs against either a Playwright `Page` or a CDP `Tab`.

    One top-to-bottom pass, not a scroll on every settle poll: once every
    position has been visited, fragments land on their own async timing and
    the caller's existing settle/poll loop is exactly what already waits
    out that kind of growth (Stage 3 does the same for Akamai's
    challenge-to-real-page swap). `budget_seconds` is independent of that
    settle budget - the orchestrator wraps the whole stage call in one
    `asyncio.wait_for` (`pipeline/orchestrator.py`), so an infinite-scroll
    page must not spend that shared ceiling scrolling forever.
    """
    loop = asyncio.get_running_loop()
    deadline = loop.time() + budget_seconds
    with suppress(Exception):
        viewport_height = await page.evaluate("window.innerHeight") or 800
        position = 0
        while loop.time() < deadline:
            scroll_height = await page.evaluate("document.body.scrollHeight")
            if position >= scroll_height:
                break
            position = min(position + viewport_height, scroll_height)
            await page.evaluate(f"window.scrollTo(0, {position})")
            await asyncio.sleep(_SCROLL_STEP_PAUSE_SECONDS)
        await page.evaluate("window.scrollTo(0, 0)")
