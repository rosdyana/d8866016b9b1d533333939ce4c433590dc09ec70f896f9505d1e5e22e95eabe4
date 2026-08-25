"""Last-resort escalation tier: crawl4ai's own Docker/FastAPI sidecar
brings its own 40+-CMP consent/overlay auto-dismiss, which is why it's only
invoked after Stages 1-3 have already failed.

`magic` and `simulate_user` are deliberately NOT sent here: since crawl4ai
0.9.0, its Docker server hard-rejects both with HTTP 400 when set in a
per-request crawler_config (they're in its UNTRUSTED_FORBIDDEN_FIELDS list -
verified against deploy/docker and crawl4ai/async_configs.py source, not
just docs). They're only usable as operator-set defaults in the server's
own config.yml, not from a caller. `remove_overlay_elements` and
`remove_consent_popups` are separately allowlisted and do work per-request,
so those two carry the actual popup/cookie-consent dismissal here.
"""

from __future__ import annotations

import httpx

from pipeline.stages.base import FetchResult, Stage


class Stage4Crawl4AI(Stage):
    name = "stage4_crawl4ai"

    def __init__(
        self,
        http_client: httpx.AsyncClient,
        base_url: str,
        api_token: str,
        timeout_seconds: float = 55.0,
    ) -> None:
        self._http_client = http_client
        self._base_url = base_url.rstrip("/")
        self._api_token = api_token
        self.timeout_seconds = timeout_seconds

    async def fetch(self, url: str) -> FetchResult:
        headers = {"Authorization": f"Bearer {self._api_token}"} if self._api_token else {}
        response = await self._http_client.post(
            f"{self._base_url}/crawl",
            json={
                "urls": [url],
                "crawler_config": {
                    "remove_overlay_elements": True,
                    "remove_consent_popups": True,
                },
            },
            headers=headers,
            timeout=self.timeout_seconds,
        )
        response.raise_for_status()
        payload = response.json()

        # crawl4ai's /crawl response wraps one result per requested URL in
        # a "results" list; re-validate this shape whenever the pinned
        # crawl4ai image tag (docker-compose.yml) is bumped.
        result = payload["results"][0] if isinstance(payload, dict) and "results" in payload else payload

        html = result.get("cleaned_html") or result.get("html") or ""
        status_code = result.get("status_code") or 200
        final_url = result.get("url") or url

        return FetchResult(
            html=html,
            status_code=status_code,
            final_url=final_url,
            extra=result,
        )
