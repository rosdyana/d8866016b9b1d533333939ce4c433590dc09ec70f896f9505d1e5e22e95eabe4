"""The MCP endpoint is mounted, so FastAPI's Depends() never runs for it.

Client(mcp) in test_mcp_server.py connects straight to the server object and
skips HTTP entirely, so it cannot see this at all.
"""

import httpx
import pytest

from app.auth.bearer import BearerTokenMiddleware

_RPC = {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}
_HEADERS = {"Accept": "application/json, text/event-stream"}


async def _ok(scope, receive, send):
    await send({"type": "http.response.start", "status": 200, "headers": []})
    await send({"type": "http.response.body", "body": b"reached"})


@pytest.fixture
def client():
    app = BearerTokenMiddleware(_ok, "secret-token")
    transport = httpx.ASGITransport(app=app)
    return httpx.AsyncClient(transport=transport, base_url="http://testserver")


async def test_missing_header_is_rejected(client):
    async with client as c:
        response = await c.post("/mcp", json=_RPC, headers=_HEADERS)
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"


async def test_wrong_token_is_rejected(client):
    async with client as c:
        response = await c.post(
            "/mcp", json=_RPC, headers={**_HEADERS, "Authorization": "Bearer wrong"}
        )
    assert response.status_code == 401


async def test_wrong_scheme_is_rejected(client):
    async with client as c:
        response = await c.post(
            "/mcp", json=_RPC, headers={**_HEADERS, "Authorization": "Basic secret-token"}
        )
    assert response.status_code == 401


async def test_correct_token_passes_through(client):
    async with client as c:
        response = await c.post(
            "/mcp", json=_RPC, headers={**_HEADERS, "Authorization": "Bearer secret-token"}
        )
    assert response.status_code == 200
    assert response.text == "reached"
