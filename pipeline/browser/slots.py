"""Bounds how many real browsers the browser stages (2, 3 and 4) may run
at once.

This replaced a pool that shared one long-lived Chromium and handed out
contexts. Camoufox injects its fingerprint at *launch*, so a shared browser
would give every job for a given host the same device identity - exactly
the correlation signal an Akamai/Cloudflare device check looks for. Each
job therefore launches its own browser, and all this needs to own is the
concurrency bound that keeps that affordable.
"""

from __future__ import annotations

import asyncio


class BrowserSlots:
    def __init__(self, max_concurrent_browsers: int = 2) -> None:
        self._semaphore = asyncio.Semaphore(max_concurrent_browsers)

    def acquire(self):
        return self._semaphore
