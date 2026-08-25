"""Walks the fetch stages in order, stopping at the first one whose result
passes the quality check. Stage escalation only happens on failure — each
stage is strictly more expensive than the last, so cheaper stages are always
tried first (Stage 0's robots.txt gate, when enabled, applies to all of them
equally). `respect_robots=False` is an explicit per-request opt-out for a
trusted, authenticated caller - it skips the gate entirely rather than
fetching robots.txt and ignoring the result.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from urllib.parse import urlparse

from common.errors import AllStagesFailed, RobotsDisallowed, UnsupportedContentType
from pipeline.domain_memory import DomainMemory
from pipeline.quality import is_good_enough
from pipeline.robots.gate import RobotsGate
from pipeline.stages.base import FetchResult, Stage


@dataclass(frozen=True)
class PipelineResult:
    stage_won: str
    html: str
    final_url: str
    extra: dict | None = None


def _ordered_from_memory(stages: list[Stage], last_successful: str | None) -> list[Stage]:
    """Skip stages that are known to fail for this domain, per Stage 5's
    memory - but never skip past a stage that no longer exists (renamed,
    removed) or wasn't recorded."""
    if last_successful is None:
        return stages
    names = [stage.name for stage in stages]
    if last_successful not in names:
        return stages
    return stages[names.index(last_successful) :]


async def run_pipeline(
    url: str,
    robots_gate: RobotsGate,
    stages: list[Stage],
    domain_memory: DomainMemory | None = None,
    respect_robots: bool = True,
) -> PipelineResult:
    if respect_robots:
        decision = await robots_gate.check(url)
        if not decision.allowed:
            raise RobotsDisallowed(f"robots.txt disallows fetching {url}")

    host = urlparse(url).netloc
    last_successful = await domain_memory.get_last_successful_stage(host) if domain_memory else None
    ordered_stages = _ordered_from_memory(stages, last_successful)

    failures: list[str] = []
    for stage in ordered_stages:
        try:
            result: FetchResult = await asyncio.wait_for(
                stage.fetch(url), timeout=stage.timeout_seconds
            )
        except UnsupportedContentType:
            # A browser or crawl4ai can't turn a PDF/image into HTML either -
            # escalating further would just waste the rest of the chain.
            raise
        except TimeoutError:
            # A slow stage just failed its budget - escalate to the next
            # stage rather than letting it hang the whole job.
            failures.append(f"{stage.name}:timeout")
            continue
        except Exception as exc:  # noqa: BLE001 - any stage failure escalates, by design
            failures.append(f"{stage.name}:{exc.__class__.__name__}")
            continue

        verdict = is_good_enough(result.status_code, result.html)
        if verdict.passed:
            if domain_memory is not None:
                await domain_memory.record_success(host, stage.name)
            return PipelineResult(
                stage_won=stage.name,
                html=result.html,
                final_url=result.final_url,
                extra=result.extra,
            )
        failures.append(f"{stage.name}:{verdict.reason}")

    raise AllStagesFailed(f"all stages failed for {url}: {', '.join(failures)}")
