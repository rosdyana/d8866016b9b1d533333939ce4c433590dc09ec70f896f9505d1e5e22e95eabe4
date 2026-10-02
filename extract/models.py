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
    # The page's own title (og:title, else <title>), set whatever formats
    # were asked for. Callers used to guess it from the first Markdown
    # heading, which is often a nav or product-table header instead.
    title: str | None = None
    # A URL that turned out to be an RSS/Atom feed comes back as its raw XML
    # here, with the HTML-derived formats above left None - there is no page
    # to convert.
    feed: str | None = None
