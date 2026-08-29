"""Waits for a client-rendered page to finish filling itself in.

A fixed sleep after navigation is a coin flip on these sites. Measured on
store.acer.com 2026-08-29, the document grew 2.6KB -> 7.5KB -> 313KB ->
573KB -> 578KB over roughly five seconds; sampling at a fixed one second
returned a 32-character shell, which the quality gate then (correctly)
rejected as a failed fetch. Sampling until the document stops growing gets
the full page without making every fast page pay the slow page's budget.

Size stability alone is not enough to say a page is *done*, though, and
`is_settled` is why. A bot-challenge interstitial is a static document by
construction: store.acer.com's Akamai sensor page holds a byte-identical
2,615-byte body for ~4.5s while its JavaScript runs, then replaces it with
the real 595KB page. Two stable polls is 1.0s, so a pure size check hands
back the 32-character challenge every time and all three stages "fail"
with text_too_short on a page that renders fine at t+9s. The predicate
gates only the *early* return: the budget is still the hard cap, and the
most recent HTML is still always what comes back.

No per-site selectors, and no second opinion about what good content is -
callers pass `pipeline/quality.py`'s own verdict, so there is exactly one
definition of "good enough" in the pipeline.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

_POLL_INTERVAL_SECONDS = 0.5
_STABLE_POLLS_REQUIRED = 2


async def settle_until_stable(
    get_html: Callable[[], Awaitable[str]],
    budget_seconds: float,
    *,
    is_settled: Callable[[str], bool] | None = None,
    poll_interval_seconds: float = _POLL_INTERVAL_SECONDS,
    stable_polls_required: int = _STABLE_POLLS_REQUIRED,
) -> str:
    """Poll until the document size holds steady, or the budget runs out.

    Always returns the most recent HTML - a page that never settles (an
    animating ticker, an endless carousel) still yields whatever it had
    when the budget expired, rather than raising.

    `is_settled` additionally has to accept the document before a stable
    size is allowed to end the wait early.
    """
    loop = asyncio.get_running_loop()
    deadline = loop.time() + budget_seconds

    html = await get_html()
    previous_length = len(html)
    stable_polls = 0

    while loop.time() < deadline:
        await asyncio.sleep(poll_interval_seconds)
        html = await get_html()

        if len(html) == previous_length:
            # Keep counting even when the predicate rejects the document:
            # once a challenge page is replaced, the size counter resets on
            # its own and the very next stable poll returns the real page.
            stable_polls += 1
            if stable_polls >= stable_polls_required and (is_settled is None or is_settled(html)):
                return html
        else:
            stable_polls = 0
            previous_length = len(html)

    return html
