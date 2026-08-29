"""Stage 0's robots.txt gate.

Runs against a real loopback HTTP server rather than a mocked transport:
the gate fetches with curl_cffi, which drives libcurl directly, so respx
(which patches httpx's transport) cannot intercept it. Same reason
`test_stage1_content_type.py` does this.
"""

from __future__ import annotations

import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest
from curl_cffi import AsyncSession

from common.errors import RobotsFetchFailed
from pipeline.robots.gate import RobotsGate


class FakeCache:
    """Matches pipeline.robots.cache.RobotsCache's interface without Redis."""

    def __init__(self) -> None:
        self._store: dict[str, str] = {}

    async def get(self, host: str):
        return self._store.get(host)

    async def set(self, host: str, robots_txt: str) -> None:
        self._store[host] = robots_txt


def _make_server(status: int, body: str):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802 - BaseHTTPRequestHandler's API
            payload = body.encode()
            self.send_response(status)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, *args):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://127.0.0.1:{server.server_port}"


@pytest.fixture
def serve():
    servers = []

    def _serve(body: str, status: int = 200):
        server, origin = _make_server(status, body)
        servers.append(server)
        return origin

    yield _serve
    for server in servers:
        server.shutdown()


@pytest.fixture
async def gate():
    async with AsyncSession() as session:
        yield RobotsGate(session, FakeCache(), user_agent="ccscraper-test")


@pytest.mark.asyncio
async def test_allows_when_robots_txt_permits(serve, gate):
    origin = serve("User-agent: *\nAllow: /\n")
    decision = await gate.check(f"{origin}/page")
    assert decision.allowed is True


@pytest.mark.asyncio
async def test_disallows_matching_path(serve, gate):
    origin = serve("User-agent: *\nDisallow: /private\n")
    decision = await gate.check(f"{origin}/private/page")
    assert decision.allowed is False


@pytest.mark.asyncio
async def test_missing_robots_txt_allows_all(serve, gate):
    origin = serve("", status=404)
    decision = await gate.check(f"{origin}/anything")
    assert decision.allowed is True


@pytest.mark.asyncio
async def test_server_error_fails_closed(serve, gate):
    origin = serve("nope", status=503)
    with pytest.raises(RobotsFetchFailed):
        await gate.check(f"{origin}/anything")


@pytest.mark.asyncio
async def test_unreachable_robots_txt_fails_closed(gate):
    # A port nothing is listening on: the transport error must become a
    # RobotsFetchFailed (which subclasses RobotsDisallowed), never a bare
    # exception that would surface as job status "error".
    with pytest.raises(RobotsFetchFailed):
        await gate.check("http://127.0.0.1:1/anything")
