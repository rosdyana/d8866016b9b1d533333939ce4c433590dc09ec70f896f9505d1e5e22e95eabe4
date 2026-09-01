"""Canonical formatting layer, decoupled from which pipeline stage won.

Stages hand back plain HTML, which `extract/converter.py` turns into
Markdown. On a product catalogue the fields worth having - sku, price,
availability - live in ld+json, which the converter drops and
`clean_html()` strips, so `extract/structured.py` recovers them and they
are prepended to the text formats here.

One stage is exempt from the conversion: Stage 5 asks Firecrawl for
main-content Markdown directly, and that is better than anything we would
render from the same page's HTML. It arrives as the `markdown` argument and
is used verbatim. `llm_text` and `raw_html` still come from the HTML, so a
caller asking for those gets the same shape from every stage.
"""

from __future__ import annotations

from extract.html_cleaner import clean_html
from extract.llm_text import to_llm_text
from extract.markdown import to_markdown
from extract.models import ExtractionOutput
from extract.structured import extract_products, products_to_markdown

# Markdown only. A `raw_html` body is routinely megabytes and usually ends
# up in a model's context; a caller that genuinely wants the HTML asks for
# it. The full set still lives in `app/jobs/models.ALL_FORMATS`.
DEFAULT_FORMATS = ("markdown",)


def _prepend(table: str, body: str | None) -> str | None:
    if not table:
        return body
    return f"{table}\n\n{body}" if body else table


def build_from_html(
    html: str,
    url: str,
    formats: tuple[str, ...] = DEFAULT_FORMATS,
    markdown: str | None = None,
) -> ExtractionOutput:
    """Build requested output formats from raw HTML.

    `markdown`, when given, is Markdown the winning stage's upstream already
    produced (Stage 5 / Firecrawl) and is used instead of converting the
    HTML ourselves.
    """
    output = ExtractionOutput()
    needs_text = "markdown" in formats or "llm_text" in formats
    product_table = products_to_markdown(extract_products(html)) if needs_text else ""

    if "raw_html" in formats:
        output.raw_html = clean_html(html)
    if "markdown" in formats:
        body = markdown if markdown is not None else to_markdown(html, url=url)
        output.markdown = _prepend(product_table, body)
    if "llm_text" in formats:
        output.llm_text = _prepend(product_table, to_llm_text(html, url=url))
    return output
