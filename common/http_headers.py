"""Realistic, honest request headers.

The User-Agent identifies this bot (see USER_AGENT in config) rather than
impersonating a real browser — robots.txt matching and any operator who
inspects logs both depend on that being true.
"""

from __future__ import annotations


def build_headers(user_agent: str) -> dict[str, str]:
    return {
        "User-Agent": user_agent,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        # No "br": httpx can only auto-decompress it with the optional
        # brotli/brotlicffi package installed, and without that the
        # response body silently comes back as undecoded compressed bytes.
        "Accept-Encoding": "gzip, deflate",
        "Connection": "keep-alive",
    }
