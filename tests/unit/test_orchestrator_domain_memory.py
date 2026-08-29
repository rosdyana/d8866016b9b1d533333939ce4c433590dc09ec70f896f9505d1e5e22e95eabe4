import pytest

from common.errors import AllStagesFailed
from pipeline.domain_memory import DomainMemory
from pipeline.orchestrator import run_pipeline
from pipeline.stages.base import FetchResult, Stage
from pipeline.robots.gate import RobotsDecision


class FakeRedis:
    def __init__(self) -> None:
        self._store: dict[str, str] = {}

    async def get(self, key: str):
        value = self._store.get(key)
        return value.encode("utf-8") if value is not None else None

    async def set(self, key: str, value, ex=None):
        self._store[key] = value

    async def delete(self, key: str) -> None:
        self._store.pop(key, None)


class FakeRobotsGate:
    async def check(self, url: str) -> RobotsDecision:
        return RobotsDecision(allowed=True, crawl_delay=None)


GOOD_HTML = "<html><body>" + ("<p>Real content. </p>" * 30) + "</body></html>"


class RecordingStage(Stage):
    def __init__(self, name: str, html: str = GOOD_HTML, timeout_seconds: float = 5.0):
        self.name = name
        self.timeout_seconds = timeout_seconds
        self.html = html
        self.called = False

    async def fetch(self, url: str) -> FetchResult:
        self.called = True
        return FetchResult(html=self.html, status_code=200, final_url=url)


class FailingStage(Stage):
    def __init__(self, name: str, timeout_seconds: float = 5.0):
        self.name = name
        self.timeout_seconds = timeout_seconds
        self.called = False

    async def fetch(self, url: str) -> FetchResult:
        self.called = True
        raise RuntimeError("boom")


@pytest.mark.asyncio
async def test_skips_earlier_stages_when_domain_memory_recalls_success():
    memory = DomainMemory(FakeRedis(), ttl_seconds=3600)
    await memory.record_success("example.com", "stage2")

    stage1 = FailingStage("stage1")
    stage2 = RecordingStage("stage2")
    result = await run_pipeline(
        "http://example.com/page", FakeRobotsGate(), [stage1, stage2], domain_memory=memory
    )

    assert stage1.called is False  # skipped entirely, per remembered stage
    assert stage2.called is True
    assert result.stage_won == "stage2"


@pytest.mark.asyncio
async def test_falls_back_to_full_chain_when_remembered_stage_unknown():
    memory = DomainMemory(FakeRedis(), ttl_seconds=3600)
    await memory.record_success("example.com", "stage_that_no_longer_exists")

    stage1 = RecordingStage("stage1")
    result = await run_pipeline(
        "http://example.com/page", FakeRobotsGate(), [stage1], domain_memory=memory
    )

    assert stage1.called is True
    assert result.stage_won == "stage1"


@pytest.mark.asyncio
async def test_records_success_for_future_requests():
    memory = DomainMemory(FakeRedis(), ttl_seconds=3600)
    stage1 = RecordingStage("stage1")

    await run_pipeline("http://example.com/page", FakeRobotsGate(), [stage1], domain_memory=memory)

    assert await memory.get_last_successful_stage("example.com") == "stage1"


@pytest.mark.asyncio
async def test_retries_the_skipped_stages_when_the_remembered_one_fails():
    # Regression, store.acer.com: one Stage 3 success pinned the host to
    # Stage 3 for the 7-day TTL, so when Stage 3 started failing the
    # earlier stage that could still fetch the page never ran again.
    memory = DomainMemory(FakeRedis(), ttl_seconds=3600)
    await memory.record_success("example.com", "stage2")

    stage1 = RecordingStage("stage1")
    stage2 = FailingStage("stage2")
    result = await run_pipeline(
        "http://example.com/page", FakeRobotsGate(), [stage1, stage2], domain_memory=memory
    )

    assert stage2.called is True  # the shortcut is still tried first
    assert stage1.called is True  # ...but is no longer a dead end
    assert result.stage_won == "stage1"


@pytest.mark.asyncio
async def test_forgets_a_shortcut_that_no_longer_works():
    memory = DomainMemory(FakeRedis(), ttl_seconds=3600)
    await memory.record_success("example.com", "stage2")

    with pytest.raises(AllStagesFailed):
        await run_pipeline(
            "http://example.com/page",
            FakeRobotsGate(),
            [FailingStage("stage1"), FailingStage("stage2")],
            domain_memory=memory,
        )

    assert await memory.get_last_successful_stage("example.com") is None


@pytest.mark.asyncio
async def test_every_stage_tried_is_named_in_the_failure():
    memory = DomainMemory(FakeRedis(), ttl_seconds=3600)
    await memory.record_success("example.com", "stage2")

    with pytest.raises(AllStagesFailed) as exc:
        await run_pipeline(
            "http://example.com/page",
            FakeRobotsGate(),
            [FailingStage("stage1"), FailingStage("stage2")],
            domain_memory=memory,
        )

    assert "stage1:RuntimeError" in str(exc.value)
    assert "stage2:RuntimeError" in str(exc.value)
