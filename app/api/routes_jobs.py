from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status

from app.api.schemas import JobCreateRequest
from app.auth.bearer import require_bearer_token
from app.config import Settings, get_settings
from app.jobs.models import Job
from app.jobs.store import JobStore
from app.jobs.submit import submit_scrape

router = APIRouter(tags=["jobs"], dependencies=[Depends(require_bearer_token)])


@router.post("/jobs", response_model=Job, status_code=status.HTTP_202_ACCEPTED)
async def create_job(
    payload: JobCreateRequest,
    request: Request,
    settings: Settings = Depends(get_settings),
) -> Job:
    # Still 202 on a cache hit, so the status code never varies per request -
    # the body says `cached: true` with `status: "success"`, and an existing
    # poller finishes on its first GET.
    return await submit_scrape(
        request.app.state.redis,
        request.app.state.arq_pool,
        settings,
        url=str(payload.url),
        formats=payload.formats,
        robotstxt=payload.robotstxt,
        refresh=payload.refresh,
    )


@router.get("/jobs/{job_id}", response_model=Job)
async def get_job(
    job_id: str,
    request: Request,
    settings: Settings = Depends(get_settings),
) -> Job:
    store = JobStore(request.app.state.redis, settings.job_result_ttl_seconds)
    job = await store.get(job_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="job not found")
    return job
