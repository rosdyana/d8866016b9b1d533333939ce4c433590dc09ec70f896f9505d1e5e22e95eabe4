from __future__ import annotations

import trafilatura


def to_markdown(html: str, url: str | None = None) -> str | None:
    return trafilatura.extract(
        html,
        url=url,
        output_format="markdown",
        include_links=True,
        include_images=True,
        include_tables=True,
        favor_recall=True,
    )
