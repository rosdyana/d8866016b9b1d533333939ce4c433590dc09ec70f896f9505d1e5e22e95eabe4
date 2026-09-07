from __future__ import annotations

from pydantic import AnyHttpUrl, BaseModel

from app.jobs.models import DEFAULT_FORMATS, OutputFormat


class JobCreateRequest(BaseModel):
    url: AnyHttpUrl
    formats: list[OutputFormat] = list(DEFAULT_FORMATS)
    # Explicit per-request opt-out for a trusted, authenticated caller.
    # Defaults to True (respect robots.txt) - existing callers that omit
    # this field see no behavior change.
    robotstxt: bool = True
    # Skip the response cache and fetch again. The fresh result replaces the
    # cached one on success; a failed refetch leaves the old entry in place.
    refresh: bool = False
    # Skip the normal escalation chain and run exactly this stage - e.g.
    # "stage5_firecrawl" to spend the per-call cost deliberately instead of
    # only as a last resort. Bypasses the response cache (read and write)
    # and the domain-memory shortcut in both directions, so a one-off
    # forced fetch neither serves a result another stage produced nor
    # becomes the remembered stage for future, unforced requests to this
    # host. An unknown name (or a stage that exists but isn't configured,
    # like stage5 with no Firecrawl key) fails the job with status "error"
    # rather than rejecting the request, since validating the name needs
    # the worker's stage list. Valid names: stage1_curl_cffi,
    # stage2_crawl4ai, stage3_camoufox, stage4_seleniumbase,
    # stage5_firecrawl.
    force_stage: str | None = None
