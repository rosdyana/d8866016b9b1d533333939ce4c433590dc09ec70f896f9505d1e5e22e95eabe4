from app.config import get_settings
from app.jobs.cache import ScrapeCache, cache_key
from extract.models import ExtractionOutput

_BODY = {"url": "https://example.com/", "formats": ["llm_text"]}


async def _warm(api, *, formats=("llm_text",), robotstxt=True, text="cached text") -> str:
    key = cache_key("https://example.com/", formats, robotstxt)
    await ScrapeCache(api.redis, get_settings().scrape_cache_ttl_seconds).set(
        key,
        url="https://example.com/",
        formats=list(formats),
        robotstxt=robotstxt,
        stage_won="stage3_camoufox",
        job_id="earlier-job",
        result=ExtractionOutput(llm_text=text),
    )
    return key


async def test_a_cold_key_enqueues_and_returns_queued(api):
    response = await api.client.post("/jobs", json=_BODY)

    assert response.status_code == 202
    body = response.json()
    assert body["status"] == "queued"
    assert body["cached"] is False
    assert body["cache_key"] == cache_key("https://example.com/", ["llm_text"], True)
    assert len(api.pool.calls) == 1


async def test_a_warm_key_serves_the_result_without_enqueuing(api):
    key = await _warm(api, text="the page text")

    response = await api.client.post("/jobs", json=_BODY)

    assert response.status_code == 202
    body = response.json()
    assert body["status"] == "success"
    assert body["cached"] is True
    assert body["cache_key"] == key
    assert body["stage_won"] == "stage3_camoufox"
    assert body["result"]["llm_text"] == "the page text"
    assert api.pool.calls == []


async def test_a_cache_hit_is_still_pollable_through_get_jobs(api):
    """The documented flow is POST then poll - a hit must not break it."""
    await _warm(api, text="the page text")

    job_id = (await api.client.post("/jobs", json=_BODY)).json()["id"]
    response = await api.client.get(f"/jobs/{job_id}")

    assert response.status_code == 200
    assert response.json()["result"]["llm_text"] == "the page text"


async def test_refresh_true_enqueues_despite_a_warm_key(api):
    await _warm(api)

    response = await api.client.post("/jobs", json={**_BODY, "refresh": True})

    body = response.json()
    assert body["status"] == "queued"
    assert body["cached"] is False
    assert len(api.pool.calls) == 1


async def test_refresh_does_not_drop_the_existing_entry(api):
    """A failed refetch must leave the usable result in place."""
    key = await _warm(api, text="the page text")

    await api.client.post("/jobs", json={**_BODY, "refresh": True})

    entry = await ScrapeCache(api.redis, 1).get(key)
    assert entry is not None
    assert entry.result.llm_text == "the page text"


async def test_a_different_format_subset_is_a_miss(api):
    await _warm(api, formats=("llm_text",))

    response = await api.client.post(
        "/jobs", json={"url": "https://example.com/", "formats": ["markdown"]}
    )

    assert response.json()["status"] == "queued"
    assert len(api.pool.calls) == 1


async def test_a_robotstxt_bypass_is_not_served_from_a_respecting_entry(api):
    await _warm(api, robotstxt=True)

    response = await api.client.post("/jobs", json={**_BODY, "robotstxt": False})

    assert response.json()["status"] == "queued"
    assert len(api.pool.calls) == 1


async def test_the_enqueued_arg_list_is_unchanged(api):
    """`refresh` deliberately does not travel to the worker."""
    await api.client.post("/jobs", json={**_BODY, "refresh": True})

    call = api.pool.calls[0]
    assert call[0] == "run_scrape_job"
    assert call[2] == "https://example.com/"
    assert call[3] == ["llm_text"]
    assert call[4] is True
    assert len(call) == 5


async def test_url_normalisation_makes_a_bare_host_the_same_entry(api):
    key = cache_key("https://example.com/", ["llm_text"], True)
    await ScrapeCache(api.redis, 60).set(
        key,
        url="https://example.com/",
        formats=["llm_text"],
        robotstxt=True,
        stage_won="stage1_curl_cffi",
        job_id="earlier-job",
        result=ExtractionOutput(llm_text="the page text"),
    )

    response = await api.client.post(
        "/jobs", json={"url": "https://example.com", "formats": ["llm_text"]}
    )

    assert response.json()["cached"] is True
