from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, status

from app.api.schemas import JobCreateRequest
from app.auth.bearer import require_bearer_token
from app.config import Settings, get_settings
from app.jobs.models import Job
from app.jobs.store import JobStore

router = APIRouter(tags=["jobs"], dependencies=[Depends(require_bearer_token)])


@router.post("/jobs", response_model=Job, status_code=status.HTTP_202_ACCEPTED)
async def create_job(
    payload: JobCreateRequest,
    request: Request,
    settings: Settings = Depends(get_settings),
) -> Job:
    job = Job(id=uuid.uuid4().hex, url=str(payload.url), formats=payload.formats)

    store = JobStore(request.app.state.redis, settings.job_result_ttl_seconds)
    await store.create(job)

    await request.app.state.arq_pool.enqueue_job(
        "run_scrape_job", job.id, job.url, job.formats
    )
    return job


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
