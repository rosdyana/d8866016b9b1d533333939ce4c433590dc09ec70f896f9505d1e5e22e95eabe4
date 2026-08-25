from __future__ import annotations

from contextlib import asynccontextmanager

from arq import create_pool
from arq.connections import RedisSettings
from fastapi import FastAPI
from redis.asyncio import Redis

from app.api.routes_health import router as health_router
from app.api.routes_jobs import router as jobs_router
from app.config import get_settings
from common.logging import configure_logging


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    configure_logging()

    app.state.redis = Redis.from_url(settings.redis_url)
    app.state.arq_pool = await create_pool(RedisSettings.from_dsn(settings.redis_url))

    yield

    await app.state.arq_pool.close()
    await app.state.redis.aclose()


def create_app() -> FastAPI:
    app = FastAPI(title="ccscraper", lifespan=lifespan)
    app.include_router(health_router)
    app.include_router(jobs_router)
    return app


app = create_app()
