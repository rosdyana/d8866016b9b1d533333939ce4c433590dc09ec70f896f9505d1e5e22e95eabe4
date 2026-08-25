from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True)
class FetchResult:
    html: str
    status_code: int
    final_url: str
    # Populated only by stages that produce their own richer payload
    # (crawl4ai's markdown/fit_markdown) so extract/normalize.py can use it
    # instead of re-deriving markdown from raw HTML via trafilatura.
    extra: dict | None = None


class Stage(ABC):
    name: str
    timeout_seconds: float

    @abstractmethod
    async def fetch(self, url: str) -> FetchResult: ...
