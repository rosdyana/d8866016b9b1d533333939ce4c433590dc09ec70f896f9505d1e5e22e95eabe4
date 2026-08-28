"""Waits for a client-rendered page to finish filling itself in.

A fixed sleep after navigation is a coin flip on these sites. Measured on
store.acer.com 2026-08-29, the document grew 2.6KB -> 7.5KB -> 313KB ->
573KB -> 578KB over roughly five seconds; sampling at a fixed one second
returned a 32-character shell, which the quality gate then (correctly)
rejected as a failed fetch. Sampling until the document stops growing gets
the full page without making every fast page pay the slow page's budget.

Deliberately a size-stability check and nothing else: no per-site selectors
to maintain, and no judgement about whether the content is *good* - that
stays the orchestrator's job via pipeline/quality.py.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

_POLL_INTERVAL_SECONDS = 0.5
_STABLE_POLLS_REQUIRED = 2


async def settle_until_stable(
    get_html: Callable[[], Awaitable[str]],
    budget_seconds: float,
    poll_interval_seconds: float = _POLL_INTERVAL_SECONDS,
    stable_polls_required: int = _STABLE_POLLS_REQUIRED,
) -> str:
    """Poll until the document size holds steady, or the budget runs out.

    Always returns the most recent HTML - a page that never settles (an
    animating ticker, an endless carousel) still yields whatever it had
    when the budget expired, rather than raising.
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
            stable_polls += 1
            if stable_polls >= stable_polls_required:
                return html
        else:
            stable_polls = 0
            previous_length = len(html)

    return html
