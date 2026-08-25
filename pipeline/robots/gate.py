"""Stage 0: robots.txt permission gate.

robots.txt governs *what a declared user-agent may crawl and how fast* — it
says nothing about transport (plain HTTP vs. a rendered browser) or IP
source (direct vs. proxy). This gate therefore runs once, before whichever
stage ends up doing the actual fetch, and every stage is subject to the
same decision.
"""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlparse

import httpx
from protego import Protego

from common.errors import RobotsFetchFailed
from pipeline.robots.cache import RobotsCache


@dataclass(frozen=True)
class RobotsDecision:
    allowed: bool
    crawl_delay: float | None


class RobotsGate:
    def __init__(
        self,
        http_client: httpx.AsyncClient,
        cache: RobotsCache,
        user_agent: str,
        fetch_timeout_seconds: float = 5.0,
    ) -> None:
        self._http_client = http_client
        self._cache = cache
        self._user_agent = user_agent
        self._fetch_timeout = fetch_timeout_seconds

    async def check(self, url: str) -> RobotsDecision:
        parsed = urlparse(url)
        host = parsed.netloc
        robots_txt = await self._get_robots_txt(f"{parsed.scheme}://{host}", host)

        parser = Protego.parse(robots_txt)
        allowed = parser.can_fetch(url, self._user_agent)
        crawl_delay = parser.crawl_delay(self._user_agent)
        return RobotsDecision(allowed=allowed, crawl_delay=crawl_delay)

    async def _get_robots_txt(self, origin: str, host: str) -> str:
        cached = await self._cache.get(host)
        if cached is not None:
            return cached

        robots_url = f"{origin}/robots.txt"
        try:
            response = await self._http_client.get(
                robots_url,
                timeout=self._fetch_timeout,
                headers={"User-Agent": self._user_agent},
            )
        except httpx.HTTPError as exc:
            # Fail CLOSED: we couldn't verify permission, so treat this
            # request as disallowed rather than assuming it's fine.
            raise RobotsFetchFailed(f"robots.txt fetch failed for {host}: {exc}") from exc

        if response.status_code == 404:
            robots_txt = ""  # no robots.txt => allow-all, per spec default
        elif response.status_code >= 400:
            raise RobotsFetchFailed(
                f"robots.txt returned {response.status_code} for {host}"
            )
        else:
            robots_txt = response.text

        await self._cache.set(host, robots_txt)
        return robots_txt
