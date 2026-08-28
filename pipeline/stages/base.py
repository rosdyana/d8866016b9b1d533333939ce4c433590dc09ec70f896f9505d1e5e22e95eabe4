from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True)
class FetchResult:
    html: str
    status_code: int
    final_url: str


class Stage(ABC):
    name: str
    timeout_seconds: float

    @abstractmethod
    async def fetch(self, url: str) -> FetchResult: ...
