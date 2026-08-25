"""Proxy sourcing is intentionally stubbed for v1 - Stage 3 exists in the
pipeline shape but has no real proxy pool wired in yet. Implement a real
ProxyProvider (rotating residential/datacenter pool) later without touching
Stage 3 or the orchestrator - only this interface's implementation changes.
"""

from __future__ import annotations

from abc import ABC, abstractmethod


class ProxyProvider(ABC):
    @abstractmethod
    async def get_proxy(self) -> dict | None:
        """Return a Playwright-style proxy config (e.g. {"server": ...,
        "username": ..., "password": ...}), or None if none is available."""


class NoopProxyProvider(ProxyProvider):
    async def get_proxy(self) -> dict | None:
        return None
