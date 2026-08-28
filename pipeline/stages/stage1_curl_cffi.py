"""Fast path: a plain HTTP GET carrying a real browser's TLS/JA3 and HTTP/2
fingerprint, no browser process.

This is not a stealth nicety - it is the difference between content and
nothing on the target sites. Probed 2026-08-29: hp.com and acer.com kill
the connection at the TLS/H2 layer (HTTP/2 INTERNAL_ERROR, or an HTTP/1.1
hang delivering zero bytes) for a plain httpx/curl client no matter what
User-Agent it sends, and return a normal 200 to the exact same request made
with curl_cffi's `impersonate`.
"""

from __future__ import annotations

from curl_cffi import AsyncSession

from pipeline.stages.base import FetchResult, Stage
from pipeline.stages.content_type import guard_html_content_type


class Stage1CurlCffi(Stage):
    name = "stage1_curl_cffi"

    def __init__(
        self,
        session: AsyncSession,
        impersonate: str = "chrome",
        timeout_seconds: float = 15.0,
    ) -> None:
        self._session = session
        self._impersonate = impersonate
        self.timeout_seconds = timeout_seconds

    async def fetch(self, url: str) -> FetchResult:
        # No explicit headers: `impersonate` installs a complete header set
        # in the order the real browser sends it, and any override here
        # desynchronises the headers from the TLS fingerprint - which is
        # itself a detection signal.
        response = await self._session.get(
            url,
            impersonate=self._impersonate,
            allow_redirects=True,
            timeout=self.timeout_seconds,
        )

        guard_html_content_type(response.headers.get("content-type"))

        return FetchResult(
            html=response.text,
            status_code=response.status_code,
            final_url=str(response.url),
        )
