from __future__ import annotations

import asyncio
from urllib.parse import urlparse

import structlog

from app.jobs.cache import cache_key
from app.jobs.store import JobStore
from common.errors import AllStagesFailed, RobotsDisallowed, UnsupportedContentType
from common.logging import get_logger
from extract.normalize import build_from_html
from pipeline.orchestrator import run_pipeline
from pipeline.stages.stage1_curl_cffi import Stage1CurlCffi
from pipeline.stages.stage2_camoufox import Stage2Camoufox
from pipeline.stages.stage3_seleniumbase import Stage3SeleniumBase

logger = get_logger(__name__)


async def _store_in_cache(
    ctx: dict,
    settings,
    *,
    job_id: str,
    url: str,
    formats: list[str],
    robotstxt: bool,
    stage_won: str,
    output,
) -> None:
    """Populate the response cache after a success.

    Never raises: the job is already recorded as succeeded by the time this
    runs, and a Redis hiccup here must not turn it back into a failure.
    """
    try:
        stored = await ctx["scrape_cache"].set(
            cache_key(url, formats, robotstxt),
            url=url,
            formats=formats,
            robotstxt=robotstxt,
            stage_won=stage_won,
            job_id=job_id,
            result=output,
            max_bytes=settings.scrape_cache_max_entry_bytes,
        )
        if not stored:
            logger.info(
                "scrape_cache_skipped_oversize",
                max_bytes=settings.scrape_cache_max_entry_bytes,
            )
    except Exception:  # noqa: BLE001 - see docstring
        logger.exception("scrape_cache_write_failed")


def _build_stages(ctx: dict, settings) -> list:
    return [
        Stage1CurlCffi(
            session=ctx["curl_session"],
            impersonate=settings.curl_impersonate_target,
            timeout_seconds=settings.stage1_timeout_seconds,
        ),
        Stage2Camoufox(
            slots=ctx["browser_slots"],
            timeout_seconds=settings.stage2_timeout_seconds,
            headless="virtual" if settings.stage2_use_xvfb else True,
        ),
        Stage3SeleniumBase(
            slots=ctx["browser_slots"],
            timeout_seconds=settings.stage3_timeout_seconds,
            use_xvfb=settings.stage3_use_xvfb,
        ),
    ]


async def run_scrape_job(
    ctx: dict, job_id: str, url: str, formats: list[str], robotstxt: bool = True
) -> None:
    settings = ctx["settings"]
    store = JobStore(ctx["redis"], settings.job_result_ttl_seconds)
    host = urlparse(url).netloc

    structlog.contextvars.bind_contextvars(job_id=job_id, url=url, host=host)
    try:
        await store.update(job_id, status="running")
        logger.info("job_started")
        if not robotstxt:
            # Explicit per-request opt-out by an authenticated caller - log
            # it distinctly, since it's a deliberate deviation from the
            # default "respect robots.txt" behavior worth being able to audit.
            logger.warning("robots_txt_bypassed")

        stages = _build_stages(ctx, settings)
        domain_memory = ctx["domain_memory"] if settings.domain_memory_enabled else None

        try:
            async with ctx["rate_limiter"].slot(host):
                result = await asyncio.wait_for(
                    run_pipeline(
                        url,
                        ctx["robots_gate"],
                        stages,
                        domain_memory=domain_memory,
                        respect_robots=robotstxt,
                    ),
                    timeout=settings.job_timeout_seconds,
                )
        except RobotsDisallowed as exc:
            logger.info("job_robots_disallowed", error=str(exc))
            await store.update(job_id, status="robots_disallowed", error=str(exc))
            return
        except UnsupportedContentType as exc:
            logger.info("job_unsupported_content_type", content_type=str(exc))
            await store.update(job_id, status="unsupported_content_type", error=str(exc))
            return
        except AllStagesFailed as exc:
            logger.info("job_blocked", error=str(exc))
            await store.update(job_id, status="blocked", error=str(exc))
            return
        except TimeoutError:
            logger.warning("job_timeout", budget_seconds=settings.job_timeout_seconds)
            await store.update(
                job_id,
                status="timeout",
                error=f"job exceeded {settings.job_timeout_seconds}s overall budget",
            )
            return
        except Exception as exc:  # noqa: BLE001 - surface any unexpected failure on the job, not the worker
            logger.exception("job_error")
            await store.update(job_id, status="error", error=str(exc))
            return

        output = build_from_html(result.html, result.final_url, tuple(formats))

        logger.info("job_succeeded", stage_won=result.stage_won)
        await store.update(job_id, status="success", stage_won=result.stage_won, result=output)

        # After the job is marked done, and only for a success: a transient
        # block or timeout cached for 30 days would poison the URL for a month.
        if settings.scrape_cache_enabled:
            await _store_in_cache(
                ctx,
                settings,
                job_id=job_id,
                url=url,
                formats=formats,
                robotstxt=robotstxt,
                stage_won=result.stage_won,
                output=output,
            )
    finally:
        structlog.contextvars.clear_contextvars()
