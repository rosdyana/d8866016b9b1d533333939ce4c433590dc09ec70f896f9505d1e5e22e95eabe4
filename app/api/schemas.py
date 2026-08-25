from __future__ import annotations

from pydantic import AnyHttpUrl, BaseModel

from app.jobs.models import ALL_FORMATS, OutputFormat


class JobCreateRequest(BaseModel):
    url: AnyHttpUrl
    formats: list[OutputFormat] = list(ALL_FORMATS)
