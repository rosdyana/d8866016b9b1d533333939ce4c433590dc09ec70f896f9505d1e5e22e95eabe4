from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, Field

from extract.models import ExtractionOutput

JobStatus = Literal[
    "queued",
    "running",
    "success",
    "blocked",
    "robots_disallowed",
    "unsupported_content_type",
    "timeout",
    "error",
]

OutputFormat = Literal["raw_html", "markdown", "llm_text"]

ALL_FORMATS: tuple[OutputFormat, ...] = ("raw_html", "markdown", "llm_text")


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Job(BaseModel):
    id: str
    url: str
    formats: list[OutputFormat] = Field(default_factory=lambda: list(ALL_FORMATS))
    robotstxt: bool = True
    status: JobStatus = "queued"
    stage_won: str | None = None
    result: ExtractionOutput | None = None
    error: str | None = None
    # The response cache entry this request maps to - returned so a caller
    # can inspect or drop its own entry via /cache/{key} without having to
    # re-derive the hash.
    cache_key: str | None = None
    cached: bool = False
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)
