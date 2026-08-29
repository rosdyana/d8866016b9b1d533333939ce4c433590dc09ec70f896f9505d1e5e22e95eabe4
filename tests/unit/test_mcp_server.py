import json

import pytest
from mcp import Client
from mcp.server.mcpserver.exceptions import ToolError
from starlette.datastructures import State

from app.jobs.models import Job
from app.jobs.store import JobStore
from app.mcp_server.server import _await_job, build_mcp_server
from extract.models import ExtractionOutput


class FakeRedis:
    def __init__(self) -> None:
        self._store: dict[str, bytes] = {}

    async def get(self, key: str):
        return self._store.get(key)

    async def set(self, key: str, value, ex=None):
        self._store[key] = value


class FakeArqPool:
    """Records enqueues; optionally finishes the job the way the worker would."""

    def __init__(self, redis: FakeRedis, finish_with: Job | None = None) -> None:
        self._redis = redis
        self._finish_with = finish_with
        self.calls: list[tuple] = []

    async def enqueue_job(self, *args):
        self.calls.append(args)
        if self._finish_with is not None:
            job_id = args[1]
            done = self._finish_with.model_copy(update={"id": job_id})
            await JobStore(self._redis, 60).create(done)


class FakeContext:
    def __init__(self) -> None:
        self.progress: list[float] = []

    async def report_progress(self, progress, total=None, message=None) -> None:
        self.progress.append(progress)


def _state(redis: FakeRedis, pool: FakeArqPool) -> State:
    return State({"redis": redis, "arq_pool": pool})


def _payload(result):
    return json.loads(result.content[0].text)


async def test_scrape_returns_llm_text_only_by_default():
    redis = FakeRedis()
    finished = Job(
        id="placeholder",
        url="https://example.com/",
        status="success",
        stage_won="stage1_curl_cffi",
        result=ExtractionOutput(llm_text="the page text"),
    )
    pool = FakeArqPool(redis, finish_with=finished)

    async with Client(build_mcp_server(_state(redis, pool))) as client:
        result = await client.call_tool("scrape", {"url": "https://example.com/"})

    payload = _payload(result)
    assert payload["status"] == "success"
    assert payload["llm_text"] == "the page text"
    assert payload["stage_won"] == "stage1_curl_cffi"
    assert payload["raw_html"] is None

    # ("run_scrape_job", job_id, url, formats, robotstxt)
    assert len(pool.calls) == 1
    assert pool.calls[0][0] == "run_scrape_job"
    assert pool.calls[0][2] == "https://example.com/"
    assert pool.calls[0][3] == ["llm_text"]
    assert pool.calls[0][4] is True


async def test_robotstxt_false_reaches_the_queue():
    redis = FakeRedis()
    finished = Job(id="placeholder", url="https://example.com/", status="blocked")
    pool = FakeArqPool(redis, finish_with=finished)

    async with Client(build_mcp_server(_state(redis, pool))) as client:
        await client.call_tool(
            "scrape",
            {"url": "https://example.com/", "robotstxt": False, "formats": ["markdown"]},
        )

    assert pool.calls[0][3] == ["markdown"]
    assert pool.calls[0][4] is False


async def test_terminal_failure_comes_back_as_data_not_a_tool_error():
    redis = FakeRedis()
    finished = Job(
        id="placeholder",
        url="https://example.com/",
        status="robots_disallowed",
        error="robots.txt disallows https://example.com/",
    )
    pool = FakeArqPool(redis, finish_with=finished)

    async with Client(build_mcp_server(_state(redis, pool))) as client:
        result = await client.call_tool("scrape", {"url": "https://example.com/"})

    assert result.is_error is not True
    payload = _payload(result)
    assert payload["status"] == "robots_disallowed"
    assert payload["error"] == "robots.txt disallows https://example.com/"


async def test_unfinished_job_hands_back_the_job_id():
    redis = FakeRedis()
    store = JobStore(redis, 60)
    await store.create(Job(id="abc123", url="https://example.com/", status="running"))

    ctx = FakeContext()
    result = await _await_job(store, "abc123", wait_seconds=0.6, ctx=ctx)

    assert result.status == "running"
    assert result.job_id == "abc123"
    assert result.llm_text is None
    # Progress is reported while waiting, and the spec requires it to increase.
    assert ctx.progress == sorted(ctx.progress)
    assert len(ctx.progress) >= 1


async def test_get_scrape_result_collects_a_finished_job():
    redis = FakeRedis()
    store = JobStore(redis, 60)
    await store.create(
        Job(
            id="abc123",
            url="https://example.com/",
            status="success",
            stage_won="stage2_camoufox",
            result=ExtractionOutput(llm_text="late text"),
        )
    )
    pool = FakeArqPool(redis)

    async with Client(build_mcp_server(_state(redis, pool))) as client:
        result = await client.call_tool("get_scrape_result", {"job_id": "abc123"})

    payload = _payload(result)
    assert payload["status"] == "success"
    assert payload["llm_text"] == "late text"


async def test_unknown_job_id_is_a_tool_error():
    store = JobStore(FakeRedis(), 60)
    with pytest.raises(ToolError):
        await _await_job(store, "nope", wait_seconds=5.0, ctx=FakeContext())
