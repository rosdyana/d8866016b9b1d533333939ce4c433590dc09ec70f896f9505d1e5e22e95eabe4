"""The non-HTML guard, shared by every stage that can see a Content-Type.

`UnsupportedContentType` is terminal for the whole pipeline (see
`pipeline/orchestrator.py`) - escalating a PDF to a browser can't turn it
into HTML either. Stage 1 reads the header off the response; Stage 2 reads
it off Playwright's navigation response, so both must agree on the rule.
"""

from __future__ import annotations

from common.errors import UnsupportedContentType

_HTML_CONTENT_TYPES = ("text/html", "application/xhtml+xml")


def guard_html_content_type(content_type: str | None) -> None:
    normalized = (content_type or "").split(";")[0].strip().lower()
    if normalized and not normalized.startswith(_HTML_CONTENT_TYPES):
        raise UnsupportedContentType(normalized)
