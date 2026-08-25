import pytest

from pipeline.domain_memory import DomainMemory


class FakeRedis:
    def __init__(self) -> None:
        self._store: dict[str, str] = {}

    async def get(self, key: str):
        value = self._store.get(key)
        return value.encode("utf-8") if value is not None else None

    async def set(self, key: str, value, ex=None):
        self._store[key] = value


@pytest.mark.asyncio
async def test_returns_none_when_nothing_recorded():
    memory = DomainMemory(FakeRedis(), ttl_seconds=3600)
    assert await memory.get_last_successful_stage("example.com") is None


@pytest.mark.asyncio
async def test_records_and_recalls_successful_stage():
    memory = DomainMemory(FakeRedis(), ttl_seconds=3600)
    await memory.record_success("example.com", "stage2_playwright")
    assert await memory.get_last_successful_stage("example.com") == "stage2_playwright"


@pytest.mark.asyncio
async def test_domains_are_independent():
    memory = DomainMemory(FakeRedis(), ttl_seconds=3600)
    await memory.record_success("a.com", "stage1_http")
    await memory.record_success("b.com", "stage4_crawl4ai")
    assert await memory.get_last_successful_stage("a.com") == "stage1_http"
    assert await memory.get_last_successful_stage("b.com") == "stage4_crawl4ai"
