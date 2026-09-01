"""The one HTML -> Markdown path, shared by every stage that returns HTML.

Both output formats come from the same two crawl4ai components, so a page
reads the same whichever stage won:

  LXMLWebScrapingStrategy  strips script/style/empty nodes -> cleaned_html
  DefaultMarkdownGenerator renders it (a vendored html2text, body_width=0)

`markdown` takes the generator's `raw_markdown`; `llm_text` adds a
`PruningContentFilter` and takes its `fit_markdown`. Both calls are
synchronous and launch no browser - crawl4ai is a fetch stage *and* a
converter, and nothing here touches `AsyncWebCrawler`.

Two things about these APIs are load-bearing:

- **Neither call raises. Both return their error message as content.**
  `scrap()` hands back a `cleaned_html` that is literally a `<div
  id="crawl4ai_error_message">Crawl4AI Error: ...</div>` with
  `success=False`, and `generate_markdown()` returns "Error converting HTML
  to markdown: ..." as `raw_markdown`. Unchecked, either is served to the
  caller as the page. Every entry point here checks.
- **`scrap()` is not an article extractor.** It removes script/style/link/
  meta/noscript, childless elements with no text, and most attributes -
  nav, footer and the spec tables survive. So the *unpruned* path is
  bloated rather than lossy, which is the right way to be wrong for a
  product catalogue. Only the pruned path (`extract/llm_text.py`) needs a
  guard against losing content.

Worker-only. `docker/api.Dockerfile` copies just `extract/models.py` and
`extract/__init__.py`, so importing crawl4ai here cannot pull numpy,
pillow or playwright into the light api image. Note that `import crawl4ai`
also does an `os.makedirs` at module scope (its `async_database`), so the
process needs a writable `CRAWL4_AI_BASE_DIRECTORY` or `$HOME`.
"""

from __future__ import annotations

from crawl4ai.content_filter_strategy import PruningContentFilter
from crawl4ai.content_scraping_strategy import LXMLWebScrapingStrategy
from crawl4ai.markdown_generation_strategy import DefaultMarkdownGenerator

# crawl4ai's own swallowed-exception messages, pinned to crawl4ai 0.9.3.
_GENERATOR_ERRORS = (
    "Error converting HTML to markdown:",
    "Error in markdown generation:",
    "Error generating fit markdown:",
)


def to_cleaned_html(html: str, url: str | None = None) -> str:
    """Scripts, styles and empty nodes gone; everything visible kept.

    Returns "" for both "nothing to do" and "crawl4ai failed", so callers
    have one failure value instead of also having to recognise its error
    <div>.
    """
    if not html:
        return ""
    # Built per call rather than as a module singleton: `build_from_html`
    # runs on a worker thread (see `worker/tasks.py`), and these objects
    # are not documented as thread-safe.
    result = LXMLWebScrapingStrategy().scrap(url or "", html)
    if not result.success:
        return ""
    return result.cleaned_html or ""


def render_markdown(cleaned_html: str, url: str | None = None) -> str:
    """The whole cleaned document as Markdown."""
    if not cleaned_html:
        return ""
    result = DefaultMarkdownGenerator().generate_markdown(
        cleaned_html,
        base_url=url or "",
        # The citation rewrite is a whole-document regex pass whose output
        # (markdown_with_citations) nothing here reads.
        citations=False,
    )
    return _usable(result.raw_markdown)


def render_pruned_markdown(cleaned_html: str, url: str | None = None) -> tuple[str, str]:
    """Boilerplate-pruned Markdown, plus the HTML the pruner actually kept.

    The caller needs both: `fit_markdown` is what it wants, and `fit_html`
    is the only honest way to measure how much of the page survived. A
    length ratio taken against `fit_markdown` would be biased - Markdown
    carries inline `[text](url)` links, so it is longer than the visible
    text it came from, and the guard would fire less often than it should.
    """
    if not cleaned_html:
        return "", ""
    result = DefaultMarkdownGenerator(
        content_filter=PruningContentFilter()
    ).generate_markdown(cleaned_html, base_url=url or "", citations=False)
    return _usable(result.fit_markdown), result.fit_html or ""


def _usable(rendered: str | None) -> str:
    text = rendered or ""
    if text.startswith(_GENERATOR_ERRORS):
        return ""
    # html2text emits a bare newline for an empty document. Callers treat
    # the empty string as "nothing extracted" and turn it into None, so
    # whitespace-only output must not sneak through as content.
    return text if text.strip() else ""
