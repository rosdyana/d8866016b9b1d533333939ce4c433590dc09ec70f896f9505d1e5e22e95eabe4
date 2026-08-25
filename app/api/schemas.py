from __future__ import annotations

from pydantic import AnyHttpUrl, BaseModel

from app.jobs.models import ALL_FORMATS, OutputFormat


class JobCreateRequest(BaseModel):
    url: AnyHttpUrl
    formats: list[OutputFormat] = list(ALL_FORMATS)
    # Explicit per-request opt-out for a trusted, authenticated caller.
    # Defaults to True (respect robots.txt) - existing callers that omit
    # this field see no behavior change.
    robotstxt: bool = True
