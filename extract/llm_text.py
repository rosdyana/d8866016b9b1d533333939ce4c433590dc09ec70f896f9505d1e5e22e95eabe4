"""Boilerplate-pruned main content — meant for LLM/RAG ingestion.

The extractor changed (trafilatura -> crawl4ai's PruningContentFilter); the
reason for the guard below did not. Both are *boilerplate pruners*, and a
boilerplate pruner misjudges a product detail page, where the content worth
having *is* the spec table: short repeated label/value pairs, dense markup,
no prose - which to a scorer looks exactly like a nav block.

Measured 2026-08-29 on an HP ZBook product page whose visible text carries
the full spec sheet ("Processor AMD Ryzen 5 8645HS ... Memory 16 GB DDR5
... 1 TB PCIe Gen4 NVMe SSD"), trafilatura returned 503 characters - 8% of
the visible text, containing zero spec terms, mostly promo banners. No
combination of favor_precision/favor_recall/include_tables recovered them
(best case 16%, still zero spec terms). On a genuine article page every
setting returned ~97%.

PruningContentFilter can fail the same way, and has one extra route to it:
it decomposes <form>, <header>, <aside>, <nav>, <footer> and <iframe>
outright before any scoring runs, and on a configurable PDP the specs and
the price live inside the <form>. No threshold tuning reaches that - only
the fallback does.

The measurement is deliberately taken against `fit_html`, the HTML the
pruner kept, and not against the Markdown it produced. Markdown carries
inline `[text](url)` links and is therefore longer than the visible text it
came from, so a ratio taken on the Markdown is biased upward and the guard
would fire less often than it should.
"""

from __future__ import annotations

import html as html_module
import re

from extract.converter import render_pruned_markdown, to_cleaned_html
from extract.html_cleaner import clean_html

_TAG_RE = re.compile(r"<[^>]+>")
_WHITESPACE_RE = re.compile(r"\s+")

# Article pages land at ~97%, product pages at 8-16%. Anything under this
# means the pruner threw away the substance of the page.
_MIN_KEPT_RATIO = 0.35


def _visible_text(html: str) -> str:
    text = _TAG_RE.sub(" ", clean_html(html))
    # Twice: sites double-encode (&amp;quot; for a quote inside an attribute
    # that was itself escaped), and one pass leaves &quot; in the output.
    text = html_module.unescape(html_module.unescape(text))
    return _WHITESPACE_RE.sub(" ", text).strip()


def to_llm_text(html: str, url: str | None = None) -> str | None:
    pruned, kept_html = render_pruned_markdown(to_cleaned_html(html, url), url)

    visible = _visible_text(html)
    if not visible:
        return pruned or None
    if pruned and len(_visible_text(kept_html)) / len(visible) >= _MIN_KEPT_RATIO:
        return pruned
    return visible or pruned or None
