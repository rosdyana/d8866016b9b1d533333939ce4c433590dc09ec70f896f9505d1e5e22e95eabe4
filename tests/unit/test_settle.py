"""Regression: a fixed post-navigation sleep is a coin flip on an SPA.

Measured on store.acer.com (2026-08-29) the document grew
2.6KB -> 7.5KB -> 313KB -> 573KB -> 578KB across roughly five seconds.
Sampling once after a fixed second returned a 32-character shell, which the
quality gate then rejected — the job came back "blocked" for a page that
renders perfectly well a few seconds later.
"""

import asyncio

import pytest

from pipeline.browser.settle import settle_until_stable


def _grower(sizes):
    """Yields each size once, then repeats the last forever."""
    remaining = list(sizes)

    async def get_html():
        value = remaining.pop(0) if remaining else sizes[-1]
        return "x" * value

    return get_html


@pytest.mark.asyncio
async def test_waits_through_growth_then_returns_settled_document():
    # The acer.com growth curve, scaled down.
    html = await settle_until_stable(
        _grower([2_600, 7_500, 313_000, 573_000, 578_000]),
        budget_seconds=5.0,
        poll_interval_seconds=0.01,
    )
    assert len(html) == 578_000, "returned before the document finished growing"


@pytest.mark.asyncio
async def test_returns_immediately_when_already_stable():
    # A fast, server-rendered page must not pay the slow page's budget.
    started = asyncio.get_running_loop().time()
    html = await settle_until_stable(
        _grower([5_000]), budget_seconds=30.0, poll_interval_seconds=0.01
    )
    assert len(html) == 5_000
    assert asyncio.get_running_loop().time() - started < 1.0


@pytest.mark.asyncio
async def test_never_exceeds_its_budget_on_a_page_that_never_settles():
    counter = {"n": 0}

    async def always_growing():
        counter["n"] += 1
        return "x" * (1000 * counter["n"])

    started = asyncio.get_running_loop().time()
    html = await settle_until_stable(
        always_growing, budget_seconds=0.3, poll_interval_seconds=0.01
    )
    elapsed = asyncio.get_running_loop().time() - started
    assert elapsed < 2.0, "blew through the budget"
    # Best effort, not an exception: whatever it had when time ran out.
    assert len(html) > 0
