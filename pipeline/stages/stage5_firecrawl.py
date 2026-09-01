"""Firecrawl: a hosted scraper with its own proxy and stealth
infrastructure, reached over HTTP rather than run locally.

Last resort by construction. Every earlier stage is free and runs on this
host; this one costs money per call and sends the target URL to a third
party, so it is only reached once all four local stages have been detected
or refused. It is also the only stage that is *optional* - the worker omits
it entirely when `FIRECRAWL_API_KEY` is unset (see `worker/tasks.py`).

Unlike every other stage, its upstream already produces good Markdown, so
this is the one stage that sets `FetchResult.markdown` instead of leaving
`extract/markdown.py` to convert the HTML. `rawHtml` is requested alongside
it because `pipeline/quality.py` judges HTML, and because the `raw_html`
and `llm_text` output formats still have to work when this stage wins.
"""

from __future__ import annotations

from firecrawl import AsyncFirecrawl

from pipeline.stages.base import FetchResult, Stage
from pipeline.stages.content_type import guard_html_content_type


class Stage5Firecrawl(Stage):
    name = "stage5_firecrawl"

    def __init__(
        self,
        client: AsyncFirecrawl,
        timeout_seconds: float = 90.0,
        max_age_ms: int = 172_800_000,
    ) -> None:
        self._client = client
        self.timeout_seconds = timeout_seconds
        self._max_age_ms = max_age_ms

    async def fetch(self, url: str) -> FetchResult:
        # No `BrowserSlots` acquisition: this launches no local browser, and
        # holding a slot would idle one of the two browser permits for the
        # length of a network round trip.
        document = await self._client.scrape(
            url,
            formats=["markdown", "rawHtml"],
            only_main_content=True,
            max_age=self._max_age_ms,
            timeout=int(self.timeout_seconds * 1000),
        )

        # `Document.metadata` can arrive as a plain dict; `metadata_typed`
        # always yields a DocumentMetadata, so the attribute reads below are
        # safe either way.
        metadata = document.metadata_typed
        guard_html_content_type(metadata.content_type)

        return FetchResult(
            html=document.raw_html or "",
            status_code=metadata.status_code or 200,
            final_url=metadata.url or metadata.source_url or url,
            markdown=document.markdown,
        )
