from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from pydantic import BaseModel, Field

from app.auth.bearer import require_bearer_token
from app.config import Settings, get_settings
from app.jobs.cache import CacheEntry, CacheEntryMeta, ScrapeCache

router = APIRouter(
    prefix="/cache", tags=["cache"], dependencies=[Depends(require_bearer_token)]
)


class CacheListResponse(BaseModel):
    items: list[CacheEntryMeta]
    cursor: int = Field(description="Pass to the next call; 0 means the scan reached the end.")


class CacheClearResponse(BaseModel):
    deleted: int


def _cache(request: Request, settings: Settings) -> ScrapeCache:
    return ScrapeCache(request.app.state.redis, settings.scrape_cache_ttl_seconds)


@router.get("", response_model=CacheListResponse)
async def list_cache(
    request: Request,
    cursor: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    settings: Settings = Depends(get_settings),
) -> CacheListResponse:
    # Metadata only - a page of entries carrying their raw_html would be
    # hundreds of megabytes.
    items, next_cursor = await _cache(request, settings).list(cursor=cursor, limit=limit)
    return CacheListResponse(items=items, cursor=next_cursor)


@router.delete("", response_model=CacheClearResponse)
async def clear_cache(
    request: Request,
    settings: Settings = Depends(get_settings),
) -> CacheClearResponse:
    return CacheClearResponse(deleted=await _cache(request, settings).clear())


@router.get("/{key}", response_model=CacheEntry)
async def get_cache_entry(
    key: str,
    request: Request,
    settings: Settings = Depends(get_settings),
) -> CacheEntry:
    entry = await _cache(request, settings).get(key)
    if entry is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="cache entry not found"
        )
    return entry


@router.delete("/{key}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_cache_entry(
    key: str,
    request: Request,
    settings: Settings = Depends(get_settings),
) -> Response:
    if not await _cache(request, settings).delete(key):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="cache entry not found"
        )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
