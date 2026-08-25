from __future__ import annotations

import httpx

from common.errors import UnsupportedContentType
from common.http_headers import build_headers
from pipeline.stages.base import FetchResult, Stage

_HTML_CONTENT_TYPES = ("text/html", "application/xhtml+xml")


class Stage1Http(Stage):
    """Fast path: a plain HTTP GET, no browser. Wins for the large share of
    sites that aren't JS-rendered or actively anti-bot protected."""

    name = "stage1_http"

    def __init__(
        self,
        http_client: httpx.AsyncClient,
        user_agent: str,
        timeout_seconds: float = 10.0,
    ) -> None:
        self._http_client = http_client
        self._user_agent = user_agent
        self.timeout_seconds = timeout_seconds

    async def fetch(self, url: str) -> FetchResult:
        response = await self._http_client.get(
            url,
            headers=build_headers(self._user_agent),
            timeout=self.timeout_seconds,
            follow_redirects=True,
        )

        content_type = response.headers.get("content-type", "").split(";")[0].strip().lower()
        if content_type and not content_type.startswith(_HTML_CONTENT_TYPES):
            raise UnsupportedContentType(content_type)

        return FetchResult(
            html=response.text,
            status_code=response.status_code,
            final_url=str(response.url),
        )
