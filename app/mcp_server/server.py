from __future__ import annotations

import asyncio
from typing import Annotated

from mcp.server import MCPServer
from mcp.server.mcpserver import Context
from mcp.server.mcpserver.exceptions import ToolError
from pydantic import AnyHttpUrl, Field
from starlette.datastructures import State

from app.config import get_settings
from app.jobs.models import Job, OutputFormat
from app.jobs.store import JobStore
from app.jobs.submit import submit_scrape
from app.mcp_server.models import ScrapeResult

_PENDING = ("queued", "running")

_POLL_MIN_SECONDS = 0.25
_POLL_MAX_SECONDS = 2.0

_INSTRUCTIONS = """\
Fetch a web page and get back clean, boilerplate-stripped text.

Requests go through a staged fallback pipeline that escalates from a plain
HTTP client to a real browser only when the cheaper stage is blocked, so
bot-protected pages work but can take tens of seconds. Call `scrape` first;
if it hands back a job_id with status queued or running, collect the result
with `get_scrape_result`.
"""


def _to_result(job: Job) -> ScrapeResult:
    output = job.result
    return ScrapeResult(
        job_id=job.id,
        url=job.url,
        status=job.status,
        stage_won=job.stage_won,
        llm_text=output.llm_text if output else None,
        markdown=output.markdown if output else None,
        raw_html=output.raw_html if output else None,
        error=job.error,
    )


async def _await_job(store: JobStore, job_id: str, wait_seconds: float, ctx: Context) -> ScrapeResult:
    loop = asyncio.get_running_loop()
    started = loop.time()
    delay = _POLL_MIN_SECONDS
    job: Job | None = None

    while True:
        job = await store.get(job_id)
        if job is None:
            raise ToolError(f"job {job_id} not found - it may have expired")
        if job.status not in _PENDING:
            return _to_result(job)

        elapsed = loop.time() - started
        if elapsed >= wait_seconds:
            return _to_result(job)

        # report_progress is a no-op when the caller passed no progress
        # callback, so it is called unconditionally. Elapsed time is used as
        # the progress value because the spec requires it to strictly
        # increase and there is no countable unit of work here.
        await ctx.report_progress(elapsed, total=wait_seconds, message=job.status)

        await asyncio.sleep(min(delay, wait_seconds - elapsed))
        delay = min(delay * 2, _POLL_MAX_SECONDS)


def build_mcp_server(state: State) -> MCPServer:
    """Build the MCP server over the API tier's Redis and arq pool.

    `state` is the FastAPI `app.state`; its `redis`/`arq_pool` attributes are
    only set later, in the app's lifespan, so the tools read them at call
    time rather than the factory capturing their values here.
    """
    mcp = MCPServer("ccscraper", instructions=_INSTRUCTIONS, version="0.1.0")

    @mcp.tool()
    async def scrape(
        url: Annotated[AnyHttpUrl, Field(description="Absolute http(s) URL of the page to fetch.")],
        ctx: Context,
        formats: Annotated[
            list[OutputFormat],
            Field(
                description=(
                    "Output formats to produce. llm_text is boilerplate-stripped plain text "
                    "and the right default for reading a page; raw_html can be megabytes."
                )
            ),
        ] = ["llm_text"],
        robotstxt: Annotated[
            bool,
            Field(description="Respect the site's robots.txt. Set false only to deliberately override it."),
        ] = True,
        refresh: Annotated[
            bool,
            Field(
                description=(
                    "Fetch again instead of serving a cached result. Use only when the page "
                    "is expected to have changed - a normal call is already up to date enough."
                )
            ),
        ] = False,
        wait_seconds: Annotated[
            float,
            Field(ge=5, le=300, description="How long to wait for the content before handing back a job_id."),
        ] = 45.0,
    ) -> ScrapeResult:
        """Fetch a web page and return its content.

        Escalates through a plain HTTP client, then two real browsers, so
        bot-protected pages resolve but may take tens of seconds. Waits up to
        `wait_seconds` for the content.

        `status` is one of: success (content is in the requested format
        fields); blocked (every stage was detected or refused);
        robots_disallowed (robots.txt forbids this URL - retry with
        robotstxt=false only if you are meant to override it);
        unsupported_content_type (the URL is a PDF or image, not a page -
        do not retry); timeout; error; or queued/running, meaning the wait
        budget expired - call get_scrape_result with the returned job_id.

        A page fetched recently comes back from cache immediately; pass
        refresh=true to bypass that and fetch again.
        """
        settings = get_settings()
        job = await submit_scrape(
            state.redis,
            state.arq_pool,
            settings,
            url=str(url),
            formats=formats,
            robotstxt=robotstxt,
            refresh=refresh,
        )

        store = JobStore(state.redis, settings.job_result_ttl_seconds)
        return await _await_job(store, job.id, wait_seconds, ctx)

    @mcp.tool()
    async def get_scrape_result(
        job_id: Annotated[str, Field(description="The job_id returned by an unfinished scrape call.")],
        ctx: Context,
        wait_seconds: Annotated[
            float,
            Field(ge=5, le=300, description="How long to keep waiting before handing the job_id back again."),
        ] = 45.0,
    ) -> ScrapeResult:
        """Collect the result of a scrape that had not finished yet.

        Returns the same shape as `scrape`. A status of queued or running
        means it is still going and the job_id is still good.
        """
        settings = get_settings()
        store = JobStore(state.redis, settings.job_result_ttl_seconds)
        return await _await_job(store, job_id, wait_seconds, ctx)

    return mcp
