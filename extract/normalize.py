"""Canonical formatting layer, decoupled from which pipeline stage won.

Stage 4 (crawl4ai) produces its own markdown/fit_markdown; every other stage
hands back plain HTML that we run through trafilatura ourselves. Either way
this module is the single place that reconciles those shapes into one
ExtractionOutput.
"""

from __future__ import annotations

from extract.html_cleaner import clean_html
from extract.llm_text import to_llm_text
from extract.markdown import to_markdown
from extract.models import ExtractionOutput

DEFAULT_FORMATS = ("raw_html", "markdown", "llm_text")


def build_from_html(
    html: str,
    url: str,
    formats: tuple[str, ...] = DEFAULT_FORMATS,
) -> ExtractionOutput:
    """Build requested output formats from raw HTML (Stages 1-3 path)."""
    output = ExtractionOutput()
    if "raw_html" in formats:
        output.raw_html = clean_html(html)
    if "markdown" in formats:
        output.markdown = to_markdown(html, url=url)
    if "llm_text" in formats:
        output.llm_text = to_llm_text(html, url=url)
    return output


def build_from_crawl4ai(
    payload: dict,
    formats: tuple[str, ...] = DEFAULT_FORMATS,
) -> ExtractionOutput:
    """Reconcile crawl4ai's /crawl response shape into ExtractionOutput.

    crawl4ai's result envelope (as of the pinned 0.7.x line) nests markdown
    generation results under result["markdown"], with `raw_markdown` and
    `fit_markdown` fields, and the rendered page HTML under result["html"]/
    result["cleaned_html"]. Re-validate this mapping whenever the pinned
    crawl4ai image tag is bumped.
    """
    result = payload.get("results", [payload])[0] if "results" in payload else payload
    html = result.get("cleaned_html") or result.get("html") or ""
    markdown_field = result.get("markdown")
    if isinstance(markdown_field, dict):
        raw_markdown = markdown_field.get("raw_markdown")
        fit_markdown = markdown_field.get("fit_markdown") or raw_markdown
    else:
        raw_markdown = markdown_field
        fit_markdown = markdown_field

    output = ExtractionOutput()
    if "raw_html" in formats:
        output.raw_html = clean_html(html) if html else None
    if "markdown" in formats:
        output.markdown = raw_markdown
    if "llm_text" in formats:
        output.llm_text = fit_markdown
    return output
