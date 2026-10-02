from __future__ import annotations

from pydantic import BaseModel, Field

from app.jobs.models import JobStatus

# Flattened rather than nesting ExtractionOutput: the model calling the tool
# reads `llm_text` at the top level instead of digging through `result`.


class ScrapeResult(BaseModel):
    job_id: str = Field(description="Pass to get_scrape_result if status is queued or running.")
    url: str
    status: JobStatus
    stage_won: str | None = Field(
        default=None,
        description="Which fetch stage produced the content, once status is success.",
    )
    title: str | None = Field(default=None, description="The page's own title, once status is success.")
    llm_text: str | None = None
    markdown: str | None = None
    raw_html: str | None = None
    feed: str | None = Field(
        default=None,
        description=(
            "Raw RSS/Atom XML when the URL is a feed. The text formats are then empty, "
            "since a feed has no page to convert."
        ),
    )
    error: str | None = None
