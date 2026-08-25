import httpx
import pytest
import respx

from common.errors import RobotsFetchFailed
from pipeline.robots.gate import RobotsGate


class FakeCache:
    """Matches pipeline.robots.cache.RobotsCache's interface without Redis."""

    def __init__(self) -> None:
        self._store: dict[str, str] = {}

    async def get(self, host: str):
        return self._store.get(host)

    async def set(self, host: str, robots_txt: str) -> None:
        self._store[host] = robots_txt


@pytest.mark.asyncio
async def test_allows_when_robots_txt_permits():
    async with httpx.AsyncClient() as client:
        with respx.mock(assert_all_called=False) as mock:
            mock.get("http://example.com/robots.txt").mock(
                return_value=httpx.Response(200, text="User-agent: *\nAllow: /\n")
            )
            gate = RobotsGate(client, FakeCache(), user_agent="ccscraper-test")
            decision = await gate.check("http://example.com/page")
            assert decision.allowed is True


@pytest.mark.asyncio
async def test_disallows_matching_path():
    async with httpx.AsyncClient() as client:
        with respx.mock(assert_all_called=False) as mock:
            mock.get("http://example.com/robots.txt").mock(
                return_value=httpx.Response(200, text="User-agent: *\nDisallow: /private\n")
            )
            gate = RobotsGate(client, FakeCache(), user_agent="ccscraper-test")
            decision = await gate.check("http://example.com/private/page")
            assert decision.allowed is False


@pytest.mark.asyncio
async def test_missing_robots_txt_allows_all():
    async with httpx.AsyncClient() as client:
        with respx.mock(assert_all_called=False) as mock:
            mock.get("http://example.com/robots.txt").mock(return_value=httpx.Response(404))
            gate = RobotsGate(client, FakeCache(), user_agent="ccscraper-test")
            decision = await gate.check("http://example.com/anything")
            assert decision.allowed is True


@pytest.mark.asyncio
async def test_unreachable_robots_txt_fails_closed():
    async with httpx.AsyncClient() as client:
        with respx.mock(assert_all_called=False) as mock:
            mock.get("http://example.com/robots.txt").mock(
                side_effect=httpx.ConnectTimeout("boom")
            )
            gate = RobotsGate(client, FakeCache(), user_agent="ccscraper-test")
            with pytest.raises(RobotsFetchFailed):
                await gate.check("http://example.com/anything")
