"""Stage 1's non-HTML guard.

curl_cffi drives libcurl directly, so respx (which patches httpx's
transport) cannot intercept it - these run against a real loopback HTTP
server instead of a mocked transport.
"""

from __future__ import annotations

import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest
from curl_cffi import AsyncSession

from common.errors import UnsupportedContentType
from pipeline.stages.stage1_curl_cffi import Stage1CurlCffi

BODY = b"<html><body><p>hello</p></body></html>"


def _make_server(content_type: str | None):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802 - BaseHTTPRequestHandler's API
            self.send_response(200)
            if content_type is not None:
                self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(BODY)))
            self.end_headers()
            self.wfile.write(BODY)

        def log_message(self, *args):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://127.0.0.1:{server.server_port}/"


@pytest.fixture
def serve():
    servers = []

    def _serve(content_type: str | None):
        server, url = _make_server(content_type)
        servers.append(server)
        return url

    yield _serve
    for server in servers:
        server.shutdown()


@pytest.mark.asyncio
async def test_rejects_non_html_content_type(serve):
    url = serve("application/pdf")
    async with AsyncSession() as session:
        stage = Stage1CurlCffi(session)
        with pytest.raises(UnsupportedContentType):
            await stage.fetch(url)


@pytest.mark.asyncio
async def test_allows_html_with_charset(serve):
    url = serve("text/html; charset=utf-8")
    async with AsyncSession() as session:
        result = await Stage1CurlCffi(session).fetch(url)
    assert result.status_code == 200
    assert "hello" in result.html


@pytest.mark.asyncio
async def test_allows_missing_content_type_header(serve):
    # A response with no Content-Type at all must not be treated as
    # unsupported - only an explicitly non-HTML type is terminal.
    url = serve(None)
    async with AsyncSession() as session:
        result = await Stage1CurlCffi(session).fetch(url)
    assert result.status_code == 200
