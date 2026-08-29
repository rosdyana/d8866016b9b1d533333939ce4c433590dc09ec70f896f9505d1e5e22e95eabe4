from __future__ import annotations

from contextlib import asynccontextmanager

from arq import create_pool
from arq.connections import RedisSettings
from fastapi import FastAPI
from mcp.server.transport_security import TransportSecuritySettings
from redis.asyncio import Redis

from app.api.routes_health import router as health_router
from app.api.routes_jobs import router as jobs_router
from app.auth.bearer import BearerTokenMiddleware
from app.config import Settings, get_settings
from app.mcp_server.server import build_mcp_server
from common.logging import configure_logging


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    configure_logging()

    app.state.redis = Redis.from_url(settings.redis_url)
    app.state.arq_pool = await create_pool(RedisSettings.from_dsn(settings.redis_url))

    # A mounted sub-application's own lifespan never runs, so the session
    # manager the MCP transport depends on has to be entered here. Without
    # it the first request to /mcp fails with "Task group is not
    # initialized".
    async with app.state.mcp.session_manager.run():
        yield

    await app.state.arq_pool.close()
    await app.state.redis.aclose()


def _transport_security(settings: Settings) -> TransportSecuritySettings:
    hosts = [h.strip() for h in settings.mcp_allowed_hosts.split(",") if h.strip()]
    if not hosts:
        return TransportSecuritySettings(enable_dns_rebinding_protection=False)
    return TransportSecuritySettings(allowed_hosts=hosts)


def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(title="ccscraper", lifespan=lifespan)
    app.include_router(health_router)
    app.include_router(jobs_router)

    # Built here rather than in the lifespan because `session_manager` only
    # exists once streamable_http_app() has been called, and the lifespan
    # has to enter it. The tools read app.state.redis/arq_pool at call time,
    # so building before the lifespan sets them is fine.
    mcp = build_mcp_server(app.state)
    app.state.mcp = mcp

    # Mounted at "/" with the transport's own default path, so the endpoint
    # is exactly /mcp. Mounting at "/mcp" with streamable_http_path="/"
    # reads more naturally but leaves the sub-router with nothing to match
    # for the empty remainder, and every POST /mcp answers 307 to /mcp/.
    # Routes are included above so they still match first; only genuinely
    # unknown paths reach this mount, and they answer 401 rather than 404.
    app.mount(
        "/",
        BearerTokenMiddleware(
            mcp.streamable_http_app(transport_security=_transport_security(settings)),
            settings.auth_token,
        ),
    )
    return app


app = create_app()
