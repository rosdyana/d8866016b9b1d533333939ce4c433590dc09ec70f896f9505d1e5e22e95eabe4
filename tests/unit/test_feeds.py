"""RSS/Atom feeds pass through Stage 1 as raw XML instead of being rejected
as an unsupported content type.

Stage 1 runs against a real loopback server for the same reason as
test_stage1_content_type.py: respx cannot intercept curl_cffi.
"""

from __future__ import annotations

import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest
from curl_cffi import AsyncSession

import worker.tasks as tasks
from app.config import Settings
from app.jobs.models import Job
from app.jobs.store import JobStore
from common.errors import UnsupportedContentType
from common.rate_limit import PerDomainConcurrencyLimiter
from pipeline.orchestrator import PipelineResult, run_pipeline
from pipeline.robots.gate import RobotsDecision
from pipeline.stages.base import FetchResult, Stage
from pipeline.stages.content_type import is_feed
from pipeline.stages.stage1_curl_cffi import Stage1CurlCffi
from tests.unit.fakes import FakeRedis

RSS = (
    '<?xml version="1.0" encoding="utf-8"?>\n'
    '<rss version="2.0"><channel><title>Forum</title>'
    "<item><title>Zenbook thread</title><link>https://example.com/t/1</link></item>"
    "</channel></rss>"
)
ATOM = '<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom"><title>x</title></feed>'
SITEMAP = '<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"></urlset>'


def _serve(content_type: str, body: str, status: int = 200):
    payload = body.encode("utf-8")

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802 - BaseHTTPRequestHandler's API
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, *args):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://127.0.0.1:{server.server_port}/feed"


@pytest.mark.parametrize(
    ("content_type", "body", "expected"),
    [
        ("application/rss+xml; charset=utf-8", RSS, True),
        ("application/atom+xml", ATOM, True),
        ("text/xml", RSS, True),
        # Generic XML that isn't a feed must still be rejected.
        ("application/xml", SITEMAP, False),
        # A feed root in an HTML response is just a page that mentions one.
        ("text/html", RSS, False),
        ("application/pdf", "%PDF-1.7", False),
    ],
)
def test_is_feed(content_type, body, expected):
    assert is_feed(content_type, body) is expected


@pytest.mark.asyncio
async def test_stage1_returns_a_feed_verbatim():
    server, url = _serve("application/rss+xml; charset=utf-8", RSS)
    try:
        async with AsyncSession() as session:
            result = await Stage1CurlCffi(session).fetch(url)
    finally:
        server.shutdown()
    assert result.feed == RSS
    assert result.html == ""


@pytest.mark.asyncio
async def test_stage1_still_rejects_xml_that_is_not_a_feed():
    server, url = _serve("application/xml", SITEMAP)
    try:
        async with AsyncSession() as session:
            with pytest.raises(UnsupportedContentType):
                await Stage1CurlCffi(session).fetch(url)
    finally:
        server.shutdown()


class _AllowAll:
    async def check(self, url: str) -> RobotsDecision:
        return RobotsDecision(allowed=True, crawl_delay=None)


class _FeedStage(Stage):
    name = "stage1_curl_cffi"
    timeout_seconds = 5.0

    def __init__(self, status_code: int = 200) -> None:
        self.status_code = status_code

    async def fetch(self, url: str) -> FetchResult:
        return FetchResult(html="", status_code=self.status_code, final_url=url, feed=RSS)


class _RecordingMemory:
    def __init__(self) -> None:
        self.recorded: list[tuple[str, str]] = []

    async def get_last_successful_stage(self, host: str):
        return None

    async def record_success(self, host: str, stage: str) -> None:
        self.recorded.append((host, stage))

    async def forget(self, host: str) -> None:
        pass


@pytest.mark.asyncio
async def test_a_feed_skips_the_html_quality_check_and_domain_memory():
    memory = _RecordingMemory()
    result = await run_pipeline("https://example.com/feed", _AllowAll(), [_FeedStage()], domain_memory=memory)
    # is_good_enough would call an empty html "text_too_short" and escalate.
    assert result.feed == RSS
    assert result.stage_won == "stage1_curl_cffi"
    assert memory.recorded == []


@pytest.mark.asyncio
async def test_a_feed_with_an_error_status_is_a_failure():
    from common.errors import AllStagesFailed

    with pytest.raises(AllStagesFailed, match="error_status_404"):
        await run_pipeline("https://example.com/feed", _AllowAll(), [_FeedStage(status_code=404)])


async def test_the_worker_returns_the_feed_and_never_caches_it(monkeypatch):
    redis = FakeRedis()
    settings = Settings(auth_token="t")
    url = "https://example.com/feed"

    monkeypatch.setattr(tasks, "_build_stages", lambda ctx, s: [])

    def no_conversion(*args, **kwargs):
        raise AssertionError("a feed has no HTML to convert")

    monkeypatch.setattr(tasks, "build_from_html", no_conversion)

    async def fake_pipeline(*args, **kwargs):
        return PipelineResult(stage_won="stage1_curl_cffi", html="", final_url=url, feed=RSS)

    monkeypatch.setattr(tasks, "run_pipeline", fake_pipeline)

    class RecordingCache:
        def __init__(self) -> None:
            self.writes = 0

        async def set(self, *args, **kwargs):
            self.writes += 1
            return True

    cache = RecordingCache()
    ctx = {
        "settings": settings,
        "redis": redis,
        "scrape_cache": cache,
        "robots_gate": None,
        "domain_memory": None,
        "rate_limiter": PerDomainConcurrencyLimiter(2),
    }
    await JobStore(redis, 60).create(Job(id="j1", url=url, formats=["markdown"]))
    await tasks.run_scrape_job(ctx, "j1", url, ["markdown"])

    job = await JobStore(redis, 60).get("j1")
    assert job.status == "success"
    assert job.result.feed == RSS
    assert job.result.markdown is None
    assert cache.writes == 0
