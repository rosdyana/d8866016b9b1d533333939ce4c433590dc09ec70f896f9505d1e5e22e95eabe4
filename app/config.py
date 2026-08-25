from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    auth_token: str
    redis_url: str = "redis://redis:6379/0"

    crawl4ai_base_url: str = "http://crawl4ai:11235"
    crawl4ai_api_token: str = ""

    proxy_enabled: bool = False

    user_agent: str = "ccscraper/0.1 (+https://example.invalid/bot)"

    stage1_timeout_seconds: float = 10.0
    stage2_timeout_seconds: float = 40.0
    stage4_timeout_seconds: float = 55.0
    job_timeout_seconds: float = 120.0

    robots_cache_ttl_seconds: int = 86400
    job_result_ttl_seconds: int = 259200

    stage2_max_contexts: int = 4
    per_domain_max_concurrency: int = 2

    domain_memory_enabled: bool = True
    domain_memory_ttl_seconds: int = 604800


@lru_cache
def get_settings() -> Settings:
    return Settings()
