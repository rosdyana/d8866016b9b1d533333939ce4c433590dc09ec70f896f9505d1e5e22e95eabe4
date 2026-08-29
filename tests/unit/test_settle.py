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
from pipeline.quality import is_good_enough


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


@pytest.mark.asyncio
async def test_waits_out_a_static_bot_challenge_before_the_real_page():
    # Regression, store.acer.com 2026-08-29: Akamai's interstitial is a
    # byte-identical 2,615-byte document for ~4.5s while its sensor JS
    # runs, then it is replaced by the real 595KB page. Size stability
    # alone therefore "settles" on the challenge - all three stages came
    # back text_too_short on a page that renders fine at t+9s.
    challenge = "<html><body><div id='sec-if-cpt-container'></div></body></html>"
    real_page = "<html><body>" + ("<p>Nitro V 16 specifications. </p>" * 40) + "</body></html>"

    polls = {"n": 0}

    async def get_html():
        polls["n"] += 1
        return challenge if polls["n"] <= 9 else real_page

    html = await settle_until_stable(
        get_html,
        budget_seconds=5.0,
        is_settled=lambda candidate: is_good_enough(200, candidate).passed,
        poll_interval_seconds=0.01,
    )
    assert html == real_page, "settled on the bot-challenge page"


@pytest.mark.asyncio
async def test_without_the_predicate_the_same_sequence_settles_on_the_challenge():
    # Locks in what the predicate is actually for: the plateau is long
    # enough that plain size-stability cannot tell it from a finished page.
    challenge = "<html><body><div id='sec-if-cpt-container'></div></body></html>"

    async def get_html():
        return challenge

    html = await settle_until_stable(get_html, budget_seconds=5.0, poll_interval_seconds=0.01)
    assert html == challenge


@pytest.mark.asyncio
async def test_predicate_still_respects_the_budget():
    # A page that never satisfies the predicate must not hang - the budget
    # is still the hard cap, and whatever it had is still returned.
    async def get_html():
        return "<html><body></body></html>"

    started = asyncio.get_running_loop().time()
    html = await settle_until_stable(
        get_html,
        budget_seconds=0.3,
        is_settled=lambda candidate: is_good_enough(200, candidate).passed,
        poll_interval_seconds=0.01,
    )
    assert asyncio.get_running_loop().time() - started < 2.0
    assert html == "<html><body></body></html>"
