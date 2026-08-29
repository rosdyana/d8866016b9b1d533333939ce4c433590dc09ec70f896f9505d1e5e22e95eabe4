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

    # Comma-separated Host allowlist for the mounted /mcp endpoint, e.g.
    # "scraper.example.com,scraper.example.com:*". The MCP SDK arms
    # DNS-rebinding protection with a localhost-only allowlist when this is
    # unset, which answers 421 Misdirected Request to every request Caddy
    # forwards under the public hostname - and only logs the reason
    # server-side. Empty turns the check off, the honest setting behind a
    # reverse proxy that already controls the Host header and the only one
    # that works with the loopback-only port mapping out of the box.
    mcp_allowed_hosts: str = ""

    robots_cache_ttl_seconds: int = 86400
    job_result_ttl_seconds: int = 259200

    scrape_cache_enabled: bool = True
    scrape_cache_ttl_seconds: int = 2592000
    # Redis runs with no maxmemory and the default noeviction policy, and
    # raw_html is routinely megabytes - without a cap one pathological page
    # stays pinned for the whole 30 days.
    scrape_cache_max_entry_bytes: int = 2_097_152

    # Each slot is a whole browser process, not a context off a shared one.
    max_concurrent_browsers: int = 2
    # The two engines measurably want opposite things, so they get separate
    # knobs rather than one "browser_use_xvfb".
    #
    # Camoufox must NOT run on a virtual display. Measured in the worker
    # container 2026-08-29, 3 interleaved trials each: under Xvfb the Akamai
    # challenge on store.acer.com never cleared (32 chars after 23s, 3/3),
    # while plain headless cleared it in ~5.5s (3/3). The reason is visible
    # in the fingerprint - under Xvfb, Camoufox's WebGL spoof advertises
    # `ANGLE (NVIDIA, NVIDIA GeForce GTX 980 ...)` while the container
    # software-renders it, and a GPU that claims a GTX 980 and draws like
    # llvmpipe is a contradiction. Headless exposes no WebGL at all, so
    # there is nothing to contradict. Neither mode is flagged by
    # bot.sannysoft.com or browserscan.net, so this costs no stealth.
    stage2_use_xvfb: bool = False
    # Stage 3 keeps it: headless *Chromium* is trivially detectable, and it
    # made no difference to Akamai either way (403 in both modes).
    # Xvfb is Linux-only; off for local macOS dev.
    stage3_use_xvfb: bool = True
    per_domain_max_concurrency: int = 2

    domain_memory_enabled: bool = True
    domain_memory_ttl_seconds: int = 604800


@lru_cache
def get_settings() -> Settings:
    return Settings()
