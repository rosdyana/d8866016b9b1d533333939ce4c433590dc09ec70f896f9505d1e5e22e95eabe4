import pytest

from pipeline.orchestrator import run_pipeline
from pipeline.robots.gate import RobotsDecision
from pipeline.stages.base import FetchResult, Stage

GOOD_HTML = "<html><body>" + ("<p>Real content. </p>" * 30) + "</body></html>"


class DenyingRobotsGate:
    """Always denies, and records whether it was ever consulted - proves a
    bypass truly skips the check rather than fetching robots.txt and
    ignoring an unfavorable result."""

    def __init__(self):
        self.check_call_count = 0

    async def check(self, url: str) -> RobotsDecision:
        self.check_call_count += 1
        return RobotsDecision(allowed=False, crawl_delay=None)


class SucceedingStage(Stage):
    name = "stage1"
    timeout_seconds = 5.0

    async def fetch(self, url: str) -> FetchResult:
        return FetchResult(html=GOOD_HTML, status_code=200, final_url=url)


@pytest.mark.asyncio
async def test_respects_robots_by_default():
    from common.errors import RobotsDisallowed

    gate = DenyingRobotsGate()
    with pytest.raises(RobotsDisallowed):
        await run_pipeline("http://example.com/page", gate, [SucceedingStage()])
    assert gate.check_call_count == 1


@pytest.mark.asyncio
async def test_bypasses_robots_when_respect_robots_is_false():
    gate = DenyingRobotsGate()
    result = await run_pipeline(
        "http://example.com/page", gate, [SucceedingStage()], respect_robots=False
    )
    assert result.stage_won == "stage1"
    # The whole point of a bypass is skipping the check, not fetching
    # robots.txt and then discarding an unfavorable answer.
    assert gate.check_call_count == 0
