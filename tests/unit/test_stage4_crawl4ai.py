import json

import httpx
import pytest
import respx

from extract.normalize import build_from_crawl4ai
from pipeline.stages.stage4_crawl4ai import Stage4Crawl4AI

# Shape based on crawl4ai's documented /crawl response envelope: a
# "results" list, each with cleaned_html/html and a nested markdown object
# carrying raw_markdown/fit_markdown. Re-validate against the real service
# whenever the pinned image tag in docker-compose.yml is bumped.
SAMPLE_CRAWL4AI_PAYLOAD = {
    "results": [
        {
            "url": "https://example.com/",
            "status_code": 200,
            "html": "<html><body><script>x()</script><h1>Hi</h1></body></html>",
            "cleaned_html": "<html><body><h1>Hi</h1></body></html>",
            "markdown": {
                "raw_markdown": "# Hi\n\nFull content.",
                "fit_markdown": "# Hi",
            },
        }
    ]
}


@pytest.mark.asyncio
async def test_stage4_parses_crawl4ai_envelope():
    async with httpx.AsyncClient() as client:
        with respx.mock(assert_all_called=False) as mock:
            mock.post("http://crawl4ai.internal/crawl").mock(
                return_value=httpx.Response(200, json=SAMPLE_CRAWL4AI_PAYLOAD)
            )
            stage = Stage4Crawl4AI(
                client, base_url="http://crawl4ai.internal", api_token="secret"
            )
            result = await stage.fetch("https://example.com/")

    assert result.status_code == 200
    assert result.final_url == "https://example.com/"
    assert "<h1>Hi</h1>" in result.html
    assert result.extra == SAMPLE_CRAWL4AI_PAYLOAD["results"][0]


# crawl4ai >=0.9.0 hard-rejects these two fields with HTTP 400 when set in a
# per-request crawler_config (verified against its actual
# UNTRUSTED_FORBIDDEN_FIELDS source, not just docs) - regression guard so a
# future edit can't silently reintroduce a call that always 400s.
_FORBIDDEN_CRAWLER_CONFIG_FIELDS = {"magic", "simulate_user"}


@pytest.mark.asyncio
async def test_stage4_never_sends_fields_crawl4ai_rejects_over_the_network():
    async with httpx.AsyncClient() as client:
        with respx.mock(assert_all_called=False) as mock:
            route = mock.post("http://crawl4ai.internal/crawl").mock(
                return_value=httpx.Response(200, json=SAMPLE_CRAWL4AI_PAYLOAD)
            )
            stage = Stage4Crawl4AI(
                client, base_url="http://crawl4ai.internal", api_token="secret"
            )
            await stage.fetch("https://example.com/")

    sent_body = json.loads(route.calls.last.request.content)
    crawler_config = sent_body["crawler_config"]
    assert not (_FORBIDDEN_CRAWLER_CONFIG_FIELDS & crawler_config.keys())


def test_build_from_crawl4ai_uses_fit_markdown_for_llm_text():
    output = build_from_crawl4ai(SAMPLE_CRAWL4AI_PAYLOAD)
    assert output.markdown == "# Hi\n\nFull content."
    assert output.llm_text == "# Hi"
    assert "<script>" not in (output.raw_html or "")
    assert "<h1>Hi</h1>" in (output.raw_html or "")


def test_build_from_crawl4ai_accepts_already_unwrapped_result():
    # This is the actual runtime shape: worker/tasks.py passes
    # FetchResult.extra, which Stage4Crawl4AI already unwrapped from the
    # "results" envelope - not the raw payload as returned by crawl4ai.
    unwrapped = SAMPLE_CRAWL4AI_PAYLOAD["results"][0]
    output = build_from_crawl4ai(unwrapped)
    assert output.markdown == "# Hi\n\nFull content."
    assert output.llm_text == "# Hi"
