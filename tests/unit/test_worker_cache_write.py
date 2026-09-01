import pytest

import worker.tasks as tasks
from app.config import Settings
from app.jobs.cache import ScrapeCache, cache_key
from app.jobs.models import Job
from app.jobs.store import JobStore
from common.errors import AllStagesFailed
from common.rate_limit import PerDomainConcurrencyLimiter
from extract.models import ExtractionOutput
from pipeline.orchestrator import PipelineResult
from tests.unit.fakes import FakeRedis

_URL = "https://example.com/"
_FORMATS = ["llm_text"]


def _settings(**overrides) -> Settings:
    return Settings(auth_token="t", **overrides)


async def _run(
    monkeypatch,
    redis: FakeRedis,
    settings: Settings,
    *,
    output: ExtractionOutput,
    raises: Exception | None = None,
    robotstxt: bool = True,
) -> None:
    monkeypatch.setattr(tasks, "_build_stages", lambda ctx, s: [])
    monkeypatch.setattr(tasks, "build_from_html", lambda html, url, formats, markdown=None: output)

    async def fake_pipeline(*args, **kwargs):
        if raises is not None:
            raise raises
        return PipelineResult(stage_won="stage3_camoufox", html="<html></html>", final_url=_URL)

    monkeypatch.setattr(tasks, "run_pipeline", fake_pipeline)

    ctx = {
        "settings": settings,
        "redis": redis,
        "scrape_cache": ScrapeCache(redis, settings.scrape_cache_ttl_seconds),
        "robots_gate": None,
        "domain_memory": None,
        "rate_limiter": PerDomainConcurrencyLimiter(2),
    }
    await JobStore(redis, 60).create(Job(id="j1", url=_URL, formats=_FORMATS))
    await tasks.run_scrape_job(ctx, "j1", _URL, _FORMATS, robotstxt)


async def test_a_success_populates_the_cache(monkeypatch):
    redis = FakeRedis()
    settings = _settings()
    await _run(monkeypatch, redis, settings, output=ExtractionOutput(llm_text="the page text"))

    entry = await ScrapeCache(redis, 60).get(cache_key(_URL, _FORMATS, True))
    assert entry is not None
    assert entry.result.llm_text == "the page text"
    assert entry.meta.stage_won == "stage3_camoufox"
    assert entry.meta.job_id == "j1"


async def test_the_worker_derives_the_same_key_the_api_does(monkeypatch):
    """No cache key travels through arq - both sides recompute it."""
    redis = FakeRedis()
    await _run(monkeypatch, redis, _settings(), output=ExtractionOutput(llm_text="x"))

    key = cache_key(_URL, _FORMATS, True)
    assert f"scrape_cache:meta:{key}" in redis._store


async def test_a_blocked_job_caches_nothing(monkeypatch):
    redis = FakeRedis()
    await _run(
        monkeypatch,
        redis,
        _settings(),
        output=ExtractionOutput(),
        raises=AllStagesFailed("all stages failed"),
    )

    assert await JobStore(redis, 60).get("j1") is not None
    assert [k for k in redis._store if k.startswith("scrape_cache:")] == []


async def test_an_oversize_result_is_not_cached_but_the_job_still_succeeds(monkeypatch):
    redis = FakeRedis()
    await _run(
        monkeypatch,
        redis,
        _settings(scrape_cache_max_entry_bytes=100),
        output=ExtractionOutput(raw_html="x" * 5000),
    )

    job = await JobStore(redis, 60).get("j1")
    assert job.status == "success"
    assert [k for k in redis._store if k.startswith("scrape_cache:")] == []


async def test_the_feature_flag_turns_the_write_off(monkeypatch):
    redis = FakeRedis()
    await _run(
        monkeypatch,
        redis,
        _settings(scrape_cache_enabled=False),
        output=ExtractionOutput(llm_text="x"),
    )

    assert [k for k in redis._store if k.startswith("scrape_cache:")] == []


async def test_a_cache_write_failure_does_not_fail_the_job(monkeypatch):
    """The job is already recorded as succeeded by the time the write runs."""
    redis = FakeRedis()

    class Exploding:
        async def set(self, *args, **kwargs):
            raise RuntimeError("redis is down")

    monkeypatch.setattr(tasks, "_build_stages", lambda ctx, s: [])
    monkeypatch.setattr(
        tasks, "build_from_html", lambda html, url, formats, markdown=None: ExtractionOutput(llm_text="x")
    )

    async def fake_pipeline(*args, **kwargs):
        return PipelineResult(stage_won="stage1_curl_cffi", html="<html></html>", final_url=_URL)

    monkeypatch.setattr(tasks, "run_pipeline", fake_pipeline)

    ctx = {
        "settings": _settings(),
        "redis": redis,
        "scrape_cache": Exploding(),
        "robots_gate": None,
        "domain_memory": None,
        "rate_limiter": PerDomainConcurrencyLimiter(2),
    }
    await JobStore(redis, 60).create(Job(id="j1", url=_URL, formats=_FORMATS))
    await tasks.run_scrape_job(ctx, "j1", _URL, _FORMATS, True)

    job = await JobStore(redis, 60).get("j1")
    assert job.status == "success"
