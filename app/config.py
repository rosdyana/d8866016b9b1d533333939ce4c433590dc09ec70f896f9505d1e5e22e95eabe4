from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    auth_token: str
    redis_url: str = "redis://redis:6379/0"

    # Consumed only by RobotsGate, for matching robots.txt directives - no
    # stage sends it. Each stage presents the coherent identity its own
    # impersonation layer generates, and overriding that with a string set
    # here is exactly what would break the fingerprint.
    user_agent: str = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36"
    )

    # Version-less alias: tracks curl_cffi's newest fingerprint as the
    # library updates, instead of pinning to one that ages out.
    curl_impersonate_target: str = "chrome"

    stage1_timeout_seconds: float = 15.0
    stage2_timeout_seconds: float = 45.0
    stage3_timeout_seconds: float = 90.0
    job_timeout_seconds: float = 180.0

    robots_cache_ttl_seconds: int = 86400
    job_result_ttl_seconds: int = 259200

    # Each slot is a whole browser process, not a context off a shared one.
    max_concurrent_browsers: int = 2
    # Stage 2/3 run a virtual display rather than true headless, which is
    # trivially detectable. Xvfb is Linux-only; off for local macOS dev.
    browser_use_xvfb: bool = True
    per_domain_max_concurrency: int = 2

    domain_memory_enabled: bool = True
    domain_memory_ttl_seconds: int = 604800


@lru_cache
def get_settings() -> Settings:
    return Settings()
