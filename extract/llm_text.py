"""Boilerplate-pruned main content, plain text — meant for LLM/RAG ingestion.

trafilatura is an *article* extractor: it looks for prose and prunes
everything else as boilerplate. That is right for a news page and wrong for
a product detail page, where the content worth having *is* the spec table.

Measured 2026-08-29 on an HP ZBook product page whose visible text carries
the full spec sheet ("Processor AMD Ryzen 5 8645HS ... Memory 16 GB DDR5
... 1 TB PCIe Gen4 NVMe SSD"), trafilatura returned 503 characters - 8% of
the visible text, containing zero spec terms, mostly promo banners. No
combination of favor_precision/favor_recall/include_tables recovered them
(best case 16%, still zero spec terms). On a genuine article page every
setting returned ~97% of visible text.

That gap is the signal: when trafilatura keeps only a small fraction of
what a reader would see, it has misjudged the page type, and the visible
text is the better answer.
"""

from __future__ import annotations

import html as html_module
import re

import trafilatura

from extract.html_cleaner import clean_html

_TAG_RE = re.compile(r"<[^>]+>")
_WHITESPACE_RE = re.compile(r"\s+")

# Article pages land at ~97%, product pages at 8-16%. Anything under this
# means trafilatura pruned away the substance of the page.
_MIN_KEPT_RATIO = 0.35


def _visible_text(html: str) -> str:
    text = _TAG_RE.sub(" ", clean_html(html))
    # Twice: sites double-encode (&amp;quot; for a quote inside an attribute
    # that was itself escaped), and one pass leaves &quot; in the output.
    # trafilatura does this for its own path; the fallback must match.
    text = html_module.unescape(html_module.unescape(text))
    return _WHITESPACE_RE.sub(" ", text).strip()


def to_llm_text(html: str, url: str | None = None) -> str | None:
    extracted = trafilatura.extract(
        html,
        url=url,
        output_format="txt",
        include_comments=False,
        include_tables=True,
        favor_precision=True,
    )

    visible = _visible_text(html)
    if not visible:
        return extracted
    if extracted and len(extracted) / len(visible) >= _MIN_KEPT_RATIO:
        return extracted
    return visible or extracted
