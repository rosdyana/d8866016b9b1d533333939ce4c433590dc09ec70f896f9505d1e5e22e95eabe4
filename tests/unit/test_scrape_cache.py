import orjson
import pytest

from app.jobs.cache import ScrapeCache, cache_key
from extract.models import ExtractionOutput
from tests.unit.fakes import FakeRedis

_TTL = 2592000


async def _store(cache: ScrapeCache, url: str, *, formats=("llm_text",), text="body") -> str:
    key = cache_key(url, formats, True)
    await cache.set(
        key,
        url=url,
        formats=list(formats),
        robotstxt=True,
        stage_won="stage1_curl_cffi",
        job_id="job-" + key[:6],
        result=ExtractionOutput(llm_text=text),
    )
    return key


def test_format_order_does_not_change_the_key():
    assert cache_key("https://x.com/", ["markdown", "llm_text"], True) == cache_key(
        "https://x.com/", ["llm_text", "markdown"], True
    )


def test_url_formats_and_robotstxt_each_change_the_key():
    base = cache_key("https://x.com/", ["llm_text"], True)
    assert cache_key("https://y.com/", ["llm_text"], True) != base
    assert cache_key("https://x.com/", ["markdown"], True) != base
    assert cache_key("https://x.com/", ["llm_text"], False) != base


def test_a_subset_of_formats_is_a_different_entry():
    """Body-keyed caching: an llm_text entry must not serve a markdown request."""
    assert cache_key("https://x.com/", ["llm_text"], True) != cache_key(
        "https://x.com/", ["llm_text", "markdown"], True
    )


async def test_missing_key_is_a_miss():
    cache = ScrapeCache(FakeRedis(), _TTL)
    assert await cache.get("nope") is None


async def test_round_trip_preserves_result_and_metadata():
    redis = FakeRedis()
    cache = ScrapeCache(redis, _TTL)
    key = await _store(cache, "https://x.com/", text="the page text")

    entry = await cache.get(key)
    assert entry is not None
    assert entry.result.llm_text == "the page text"
    assert entry.meta.url == "https://x.com/"
    assert entry.meta.stage_won == "stage1_curl_cffi"
    assert entry.meta.formats == ["llm_text"]
    assert entry.meta.size_bytes == len(
        orjson.dumps(ExtractionOutput(llm_text="the page text").model_dump(mode="json"))
    )


async def test_both_keys_carry_the_ttl():
    redis = FakeRedis()
    key = await _store(ScrapeCache(redis, _TTL), "https://x.com/")
    assert redis.ttls[f"scrape_cache:meta:{key}"] == _TTL
    assert redis.ttls[f"scrape_cache:body:{key}"] == _TTL


async def test_oversize_result_is_not_stored():
    redis = FakeRedis()
    cache = ScrapeCache(redis, _TTL)
    key = cache_key("https://x.com/", ["raw_html"], True)

    stored = await cache.set(
        key,
        url="https://x.com/",
        formats=["raw_html"],
        robotstxt=True,
        stage_won="stage1_curl_cffi",
        job_id="j1",
        result=ExtractionOutput(raw_html="x" * 5000),
        max_bytes=1000,
    )

    assert stored is False
    assert await cache.get(key) is None
    assert redis._store == {}


async def test_a_half_expired_pair_reads_as_a_miss():
    redis = FakeRedis()
    cache = ScrapeCache(redis, _TTL)
    key = await _store(cache, "https://x.com/")

    await redis.delete(f"scrape_cache:body:{key}")

    assert await cache.get(key) is None


async def test_delete_removes_both_keys_and_reports_whether_it_existed():
    redis = FakeRedis()
    cache = ScrapeCache(redis, _TTL)
    key = await _store(cache, "https://x.com/")

    assert await cache.delete(key) is True
    assert redis._store == {}
    assert await cache.delete(key) is False


async def test_list_returns_metadata_only_and_ends_with_cursor_zero():
    cache = ScrapeCache(FakeRedis(), _TTL)
    await _store(cache, "https://a.com/")
    await _store(cache, "https://b.com/")

    items, cursor = await cache.list()

    assert cursor == 0
    assert sorted(item.url for item in items) == ["https://a.com/", "https://b.com/"]


async def test_list_resumes_from_the_returned_cursor():
    cache = ScrapeCache(FakeRedis(scan_batch_size=1), _TTL)
    for n in range(5):
        await _store(cache, f"https://{n}.com/")

    seen = []
    cursor = 0
    while True:
        items, cursor = await cache.list(cursor=cursor, limit=2)
        seen.extend(item.url for item in items)
        if cursor == 0:
            break

    assert sorted(seen) == [f"https://{n}.com/" for n in range(5)]


async def test_clear_removes_every_entry_and_counts_them():
    redis = FakeRedis(scan_batch_size=2)
    cache = ScrapeCache(redis, _TTL)
    for n in range(5):
        await _store(cache, f"https://{n}.com/")

    assert await cache.clear() == 5
    assert redis._store == {}


async def test_clear_leaves_other_keyspaces_alone():
    """arq's queue and the job:/robots: keys share this database - a clear
    that reached them would destroy in-flight work."""
    redis = FakeRedis()
    cache = ScrapeCache(redis, _TTL)
    await _store(cache, "https://x.com/")
    await redis.set("job:abc", b"{}")
    await redis.set("arq:queue", b"[]")
    await redis.set("domain_memory:x.com", b"stage1_curl_cffi")

    assert await cache.clear() == 1
    assert sorted(redis._store) == ["arq:queue", "domain_memory:x.com", "job:abc"]
