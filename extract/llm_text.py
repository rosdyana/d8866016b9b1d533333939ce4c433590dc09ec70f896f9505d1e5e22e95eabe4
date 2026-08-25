from __future__ import annotations

import trafilatura


def to_llm_text(html: str, url: str | None = None) -> str | None:
    """Boilerplate-pruned main content, plain text — meant for LLM/RAG ingestion."""
    return trafilatura.extract(
        html,
        url=url,
        output_format="txt",
        include_comments=False,
        include_tables=False,
        favor_precision=True,
    )
