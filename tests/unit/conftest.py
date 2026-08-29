"""Fixtures for the app-tier REST tests.

These are the first tests to drive the FastAPI app itself. ASGITransport does
not run the lifespan - which is what would otherwise open a real Redis
connection and arq pool - so `app.state` is populated by hand here.
"""

from __future__ import annotations

from types import SimpleNamespace

import httpx
import pytest

from tests.unit.fakes import FakeArqPool, FakeRedis

TOKEN = "test-token"
AUTH = {"Authorization": f"Bearer {TOKEN}"}


@pytest.fixture
async def api(monkeypatch):
    monkeypatch.setenv("AUTH_TOKEN", TOKEN)

    # Imported inside the fixture, after the token is in the environment:
    # app/main.py builds an app at import time, which reads settings.
    from app.config import get_settings
    from app.main import create_app

    get_settings.cache_clear()
    app = create_app()

    redis = FakeRedis()
    app.state.redis = redis
    app.state.arq_pool = FakeArqPool(redis)

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://testserver", headers=AUTH
    ) as client:
        yield SimpleNamespace(
            app=app, client=client, redis=redis, pool=app.state.arq_pool
        )

    get_settings.cache_clear()
