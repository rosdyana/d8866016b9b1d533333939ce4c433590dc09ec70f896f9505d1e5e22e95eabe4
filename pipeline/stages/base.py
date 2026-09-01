from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True)
class FetchResult:
    html: str
    status_code: int
    final_url: str
    # Set only by a stage whose upstream already produced better Markdown
    # than `extract/markdown.py` would from the HTML - today that is Stage 5
    # alone, which asks Firecrawl for main-content Markdown directly. None
    # everywhere else, meaning "convert the HTML the normal way".
    markdown: str | None = None


class Stage(ABC):
    name: str
    timeout_seconds: float

    @abstractmethod
    async def fetch(self, url: str) -> FetchResult: ...
