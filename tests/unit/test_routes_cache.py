import httpx

from app.jobs.cache import ScrapeCache, cache_key
from extract.models import ExtractionOutput

_TTL = 2592000


async def _seed(api, url: str, *, text: str = "cached text") -> str:
    key = cache_key(url, ["llm_text"], True)
    await ScrapeCache(api.redis, _TTL).set(
        key,
        url=url,
        formats=["llm_text"],
        robotstxt=True,
        stage_won="stage1_curl_cffi",
        job_id="j-" + key[:6],
        result=ExtractionOutput(llm_text=text),
    )
    return key


async def test_every_cache_route_needs_a_token(api):
    transport = httpx.ASGITransport(app=api.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as anon:
        for method, path in (
            ("GET", "/cache"),
            ("DELETE", "/cache"),
            ("GET", "/cache/abc"),
            ("DELETE", "/cache/abc"),
        ):
            response = await anon.request(method, path)
            assert response.status_code == 401, (method, path)


async def test_list_returns_metadata_without_bodies(api):
    await _seed(api, "https://a.com/", text="AAA-page-body")
    await _seed(api, "https://b.com/", text="BBB-page-body")

    response = await api.client.get("/cache")

    assert response.status_code == 200
    body = response.json()
    assert body["cursor"] == 0
    assert sorted(item["url"] for item in body["items"]) == [
        "https://a.com/",
        "https://b.com/",
    ]
    # The whole point of the meta/body split: the bodies never ride along.
    assert "AAA-page-body" not in response.text
    assert "BBB-page-body" not in response.text
    assert all(item["size_bytes"] > 0 for item in body["items"])


async def test_list_of_an_empty_cache(api):
    response = await api.client.get("/cache")
    assert response.status_code == 200
    assert response.json() == {"items": [], "cursor": 0}


async def test_get_one_entry_returns_the_full_result(api):
    key = await _seed(api, "https://a.com/", text="the page text")

    response = await api.client.get(f"/cache/{key}")

    assert response.status_code == 200
    body = response.json()
    assert body["meta"]["key"] == key
    assert body["result"]["llm_text"] == "the page text"


async def test_get_unknown_entry_is_404(api):
    response = await api.client.get("/cache/deadbeef")
    assert response.status_code == 404
    assert response.json()["detail"] == "cache entry not found"


async def test_delete_one_entry(api):
    key = await _seed(api, "https://a.com/")

    assert (await api.client.delete(f"/cache/{key}")).status_code == 204
    assert (await api.client.get(f"/cache/{key}")).status_code == 404
    assert (await api.client.delete(f"/cache/{key}")).status_code == 404


async def test_clear_reports_how_many_were_removed(api):
    await _seed(api, "https://a.com/")
    await _seed(api, "https://b.com/")

    response = await api.client.delete("/cache")

    assert response.status_code == 200
    assert response.json() == {"deleted": 2}
    assert (await api.client.get("/cache")).json()["items"] == []


async def test_clear_does_not_touch_job_records_or_the_arq_queue(api):
    await _seed(api, "https://a.com/")
    await api.redis.set("job:abc", b'{"id": "abc"}')
    await api.redis.set("arq:queue", b"[]")

    await api.client.delete("/cache")

    assert await api.redis.get("job:abc") == b'{"id": "abc"}'
    assert await api.redis.get("arq:queue") == b"[]"
