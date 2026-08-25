"""Pydantic-only models — no trafilatura/lxml imports here.

Kept dependency-free so the lightweight `api` container can import this
module (for response typing) without pulling in the worker's heavier
extraction stack.
"""

from __future__ import annotations

from pydantic import BaseModel


class ExtractionOutput(BaseModel):
    raw_html: str | None = None
    markdown: str | None = None
    llm_text: str | None = None
