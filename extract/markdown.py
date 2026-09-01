from __future__ import annotations

from extract.converter import render_markdown, to_cleaned_html


def to_markdown(html: str, url: str | None = None) -> str | None:
    return render_markdown(to_cleaned_html(html, url), url) or None
