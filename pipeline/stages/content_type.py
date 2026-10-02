"""The non-HTML guard, shared by every stage that can see a Content-Type.

`UnsupportedContentType` is terminal for the whole pipeline (see
`pipeline/orchestrator.py`) - escalating a PDF to a browser can't turn it
into HTML either. Stage 1 reads the header off the response; Stage 2 off crawl4ai's, Stage
3 off Playwright's navigation response, so they must agree on the rule.

RSS/Atom feeds are the one non-HTML type that is passed through instead of
rejected, and only by Stage 1 (see `is_feed`).
"""

from __future__ import annotations

import re

from common.errors import UnsupportedContentType

_HTML_CONTENT_TYPES = ("text/html", "application/xhtml+xml")

_FEED_CONTENT_TYPES = (
    "application/rss+xml",
    "application/atom+xml",
    "application/rdf+xml",
    "application/xml",
    "text/xml",
)

# The generic XML types also carry sitemaps, SOAP and plain data documents,
# so the header alone doesn't make a response a feed - its root element has to.
_FEED_ROOT_RE = re.compile(r"<(?:rss|feed|rdf:RDF)[\s>]")
_FEED_SNIFF_CHARS = 2048


def _normalize(content_type: str | None) -> str:
    return (content_type or "").split(";")[0].strip().lower()


def guard_html_content_type(content_type: str | None) -> None:
    normalized = _normalize(content_type)
    if normalized and not normalized.startswith(_HTML_CONTENT_TYPES):
        raise UnsupportedContentType(normalized)


def is_feed(content_type: str | None, body: str) -> bool:
    """A feed has nothing to render or convert - the XML itself is what the
    caller wants, so it is handed back verbatim.

    Only Stage 1 asks this. It is the stage that gets through fingerprint
    checks on feed URLs without a browser (verified 2026-10-02:
    forums.anandtech.com's feed answers plain curl with a "Checking your
    browser" page and curl_cffi with the real application/rss+xml), and a
    browser stage that had to run a challenge first no longer holds the
    feed's own response, so it couldn't return the raw XML anyway.
    """
    return _normalize(content_type).startswith(_FEED_CONTENT_TYPES) and bool(
        _FEED_ROOT_RE.search(body[:_FEED_SNIFF_CHARS])
    )
