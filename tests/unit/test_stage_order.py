"""The escalation chain is the list `_build_stages` returns, in order.

`pipeline/orchestrator.py` iterates that list as given and has no notion of
cost or priority, so the ordering lives entirely in this one function - and
nothing else asserted it. The names also matter beyond ordering: they are
persisted per-domain in Redis for 7 days, so a rename silently invalidates
every shortcut.
"""

from __future__ import annotations

from types import SimpleNamespace

import worker.tasks as tasks
from pipeline.browser.slots import BrowserSlots

LOCAL_STAGES = [
    "stage1_curl_cffi",
    "stage2_crawl4ai",
    "stage3_camoufox",
    "stage4_seleniumbase",
]


def _ctx(firecrawl=None) -> dict:
    return {
        "curl_session": object(),
        "browser_slots": BrowserSlots(1),
        "firecrawl": firecrawl,
    }


def _settings() -> SimpleNamespace:
    return SimpleNamespace(
        curl_impersonate_target="chrome",
        stage1_timeout_seconds=15.0,
        stage2_timeout_seconds=45.0,
        stage3_timeout_seconds=45.0,
        stage4_timeout_seconds=90.0,
        stage5_timeout_seconds=90.0,
        stage2_headless=True,
        stage3_use_xvfb=False,
        stage4_use_xvfb=True,
        firecrawl_max_age_ms=172_800_000,
    )


def test_chain_is_cheapest_first_without_a_firecrawl_key():
    stages = tasks._build_stages(_ctx(firecrawl=None), _settings())
    assert [stage.name for stage in stages] == LOCAL_STAGES


def test_firecrawl_is_appended_last_when_a_client_exists():
    stages = tasks._build_stages(_ctx(firecrawl=object()), _settings())
    assert [stage.name for stage in stages] == [*LOCAL_STAGES, "stage5_firecrawl"]


def test_budgets_fit_inside_the_job_timeout():
    # A cold, hard URL runs every stage. If the budgets outgrow the job
    # timeout the last stages become unreachable and the job reports
    # `timeout` instead of `blocked`.
    from app.config import Settings

    settings = Settings(auth_token="x", firecrawl_api_key="k")
    total = sum(
        getattr(settings, f"stage{n}_timeout_seconds") for n in range(1, 6)
    )
    assert total < settings.job_timeout_seconds
