"""Stage 0: robots.txt permission gate.

robots.txt governs *what a declared user-agent may crawl and how fast* — it
says nothing about transport (plain HTTP vs. a rendered browser) or IP
source (direct vs. proxy). This gate therefore runs once, before whichever
stage ends up doing the actual fetch, and every stage is subject to the
same decision.

It fetches over curl_cffi, not httpx, for the same reason Stage 1 does.
"robots.txt is a small well-known text file, so fetching it is not what
gets fingerprinted" sounds right and is false: the block on acer.com and
hp.com happens at the TLS/HTTP2 handshake, before the path is ever sent.
Measured 2026-08-29, httpx read-times-out on `store.acer.com/robots.txt`
and `www.acer.com/robots.txt` under every User-Agent, while curl_cffi gets
a normal 200. Because an unreachable robots.txt fails *closed*, an httpx
client turned a file that explicitly allows the URL into a permanent
`robots_disallowed` for the whole host.
"""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlparse

from curl_cffi import AsyncSession
from curl_cffi.requests.exceptions import RequestException
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
        session: AsyncSession,
        cache: RobotsCache,
        user_agent: str,
        impersonate: str = "chrome",
        fetch_timeout_seconds: float = 5.0,
    ) -> None:
        self._session = session
        self._cache = cache
        self._user_agent = user_agent
        self._impersonate = impersonate
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
            # No User-Agent header: `impersonate` installs a coherent one,
            # and `self._user_agent` is for matching directives, not for
            # announcing ourselves over a fingerprint that says otherwise.
            response = await self._session.get(
                robots_url,
                impersonate=self._impersonate,
                allow_redirects=True,
                timeout=self._fetch_timeout,
            )
        except RequestException as exc:
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
