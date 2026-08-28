"""Canonical formatting layer, decoupled from which pipeline stage won.

Every stage hands back plain HTML, which trafilatura turns into prose. On a
product catalogue the fields worth having - sku, price, availability - live
in ld+json, which trafilatura ignores and `clean_html()` strips, so
`extract/structured.py` recovers them and they are prepended to the text
formats here.
"""

from __future__ import annotations

from extract.html_cleaner import clean_html
from extract.llm_text import to_llm_text
from extract.markdown import to_markdown
from extract.models import ExtractionOutput
from extract.structured import extract_products, products_to_markdown

DEFAULT_FORMATS = ("raw_html", "markdown", "llm_text")


def _prepend(table: str, body: str | None) -> str | None:
    if not table:
        return body
    return f"{table}\n\n{body}" if body else table


def build_from_html(
    html: str,
    url: str,
    formats: tuple[str, ...] = DEFAULT_FORMATS,
) -> ExtractionOutput:
    """Build requested output formats from raw HTML."""
    output = ExtractionOutput()
    needs_text = "markdown" in formats or "llm_text" in formats
    product_table = products_to_markdown(extract_products(html)) if needs_text else ""

    if "raw_html" in formats:
        output.raw_html = clean_html(html)
    if "markdown" in formats:
        output.markdown = _prepend(product_table, to_markdown(html, url=url))
    if "llm_text" in formats:
        output.llm_text = _prepend(product_table, to_llm_text(html, url=url))
    return output
