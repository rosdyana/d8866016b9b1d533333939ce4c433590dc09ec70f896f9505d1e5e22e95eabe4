"""`run_scrape_job`'s `force_stage` override: run exactly one named stage,
bypassing both the domain-memory shortcut and the response cache in both
directions, so a one-off forced fetch cannot read another stage's cached
result and cannot become the remembered answer for future unforced requests.
"""

import pytest

import worker.tasks as tasks
from app.config import Settings
from app.jobs.cache import ScrapeCache
from app.jobs.models import Job
from app.jobs.store import JobStore
from common.rate_limit import PerDomainConcurrencyLimiter
from extract.models import ExtractionOutput
from pipeline.orchestrator import PipelineResult
from tests.unit.fakes import FakeRedis

_URL = "https://example.com/"
_FORMATS = ["llm_text"]


class _FakeStage:
    def __init__(self, name: str) -> None:
        self.name = name


def _settings(**overrides) -> Settings:
    return Settings(auth_token="t", **overrides)


def _ctx(redis: FakeRedis, settings: Settings) -> dict:
    return {
        "settings": settings,
        "redis": redis,
        "scrape_cache": ScrapeCache(redis, settings.scrape_cache_ttl_seconds),
        "robots_gate": None,
        # A real sentinel, not None - the assertions below check that a
        # forced stage never reaches run_pipeline, not just that it happens
        # to look empty.
        "domain_memory": object(),
        "rate_limiter": PerDomainConcurrencyLimiter(2),
    }


async def test_force_stage_runs_only_the_named_stage_and_bypasses_domain_memory(
    monkeypatch,
):
    redis = FakeRedis()
    settings = _settings(domain_memory_enabled=True)
    monkeypatch.setattr(
        tasks,
        "_build_stages",
        lambda ctx, s: [_FakeStage("stage1_curl_cffi"), _FakeStage("stage5_firecrawl")],
    )
    monkeypatch.setattr(
        tasks,
        "build_from_html",
        lambda html, url, formats, markdown=None: ExtractionOutput(llm_text="x"),
    )

    captured = {}

    async def fake_pipeline(url, robots_gate, stages, *, domain_memory=None, respect_robots=True):
        captured["stages"] = stages
        captured["domain_memory"] = domain_memory
        return PipelineResult(stage_won="stage5_firecrawl", html="<html></html>", final_url=_URL)

    monkeypatch.setattr(tasks, "run_pipeline", fake_pipeline)

    ctx = _ctx(redis, settings)
    await JobStore(redis, 60).create(Job(id="j1", url=_URL, formats=_FORMATS))
    await tasks.run_scrape_job(ctx, "j1", _URL, _FORMATS, True, "stage5_firecrawl")

    assert [s.name for s in captured["stages"]] == ["stage5_firecrawl"]
    assert captured["domain_memory"] is None

    job = await JobStore(redis, 60).get("j1")
    assert job.status == "success"
    assert job.stage_won == "stage5_firecrawl"


async def test_unknown_force_stage_fails_the_job_with_a_clear_error(monkeypatch):
    redis = FakeRedis()
    settings = _settings()
    monkeypatch.setattr(
        tasks, "_build_stages", lambda ctx, s: [_FakeStage("stage1_curl_cffi")]
    )

    ctx = _ctx(redis, settings)
    await JobStore(redis, 60).create(Job(id="j1", url=_URL, formats=_FORMATS))
    await tasks.run_scrape_job(ctx, "j1", _URL, _FORMATS, True, "stage9_does_not_exist")

    job = await JobStore(redis, 60).get("j1")
    assert job.status == "error"
    assert "stage9_does_not_exist" in job.error
    assert "stage1_curl_cffi" in job.error


async def test_force_stage_does_not_populate_the_response_cache(monkeypatch):
    redis = FakeRedis()
    settings = _settings()
    monkeypatch.setattr(
        tasks, "_build_stages", lambda ctx, s: [_FakeStage("stage5_firecrawl")]
    )
    monkeypatch.setattr(
        tasks,
        "build_from_html",
        lambda html, url, formats, markdown=None: ExtractionOutput(llm_text="x"),
    )

    async def fake_pipeline(*args, **kwargs):
        return PipelineResult(stage_won="stage5_firecrawl", html="<html></html>", final_url=_URL)

    monkeypatch.setattr(tasks, "run_pipeline", fake_pipeline)

    ctx = _ctx(redis, settings)
    await JobStore(redis, 60).create(Job(id="j1", url=_URL, formats=_FORMATS))
    await tasks.run_scrape_job(ctx, "j1", _URL, _FORMATS, True, "stage5_firecrawl")

    job = await JobStore(redis, 60).get("j1")
    assert job.status == "success"
    assert [k for k in redis._store if k.startswith("scrape_cache:")] == []


async def test_no_force_stage_is_unchanged_behavior(monkeypatch):
    """Omitting force_stage must run the full chain and use domain_memory,
    same as before this parameter existed."""
    redis = FakeRedis()
    settings = _settings(domain_memory_enabled=True)
    monkeypatch.setattr(
        tasks,
        "_build_stages",
        lambda ctx, s: [_FakeStage("stage1_curl_cffi"), _FakeStage("stage5_firecrawl")],
    )
    monkeypatch.setattr(
        tasks,
        "build_from_html",
        lambda html, url, formats, markdown=None: ExtractionOutput(llm_text="x"),
    )

    captured = {}

    async def fake_pipeline(url, robots_gate, stages, *, domain_memory=None, respect_robots=True):
        captured["stages"] = stages
        captured["domain_memory"] = domain_memory
        return PipelineResult(stage_won="stage1_curl_cffi", html="<html></html>", final_url=_URL)

    monkeypatch.setattr(tasks, "run_pipeline", fake_pipeline)

    ctx = _ctx(redis, settings)
    await JobStore(redis, 60).create(Job(id="j1", url=_URL, formats=_FORMATS))
    await tasks.run_scrape_job(ctx, "j1", _URL, _FORMATS, True, None)

    assert [s.name for s in captured["stages"]] == ["stage1_curl_cffi", "stage5_firecrawl"]
    assert captured["domain_memory"] is ctx["domain_memory"]
