"""Running, persisting and querying simulations; the operational picture.

Simulation runs, their events and picture changes are immutable once written (DB triggers).
"""

from __future__ import annotations

import asyncio
import time
import uuid
from typing import Any

from pydantic import TypeAdapter
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError, ConflictError, NotFoundError
from app.core.logging import get_logger
from app.database.models import (
    Incident,
    OperationalPictureChange,
    SimulationEventRow,
    SimulationRun,
    SimulationScenario,
)
from app.schemas.simulation import (
    OperationalPicture,
    ReplayResult,
    SimulationComparison,
    SimulationDetail,
    SimulationRequest,
    SimulationSummary,
    StatusDifference,
)
from app.services import analysis_cache
from app.services.audit import append_audit
from app.services.scenarios import EVENTS_ADAPTER, check_events, get_scenario
from app.services.twin_store import LoadedTwin
from app.simulation.engine import simulate
from app.simulation.model import (
    ENGINE_VERSION,
    SCORING_VERSION,
    AssetState,
    FunctionalStatus,
    ImpactMetrics,
    InitiatingEvent,
    SimEvent,
    SimulationConfig,
    SimulationResult,
    TimelinePoint,
)

log = get_logger(__name__)
DEFAULT_HORIZON_MINUTES = 72 * 60
STATES_ADAPTER: TypeAdapter[list[AssetState]] = TypeAdapter(list[AssetState])
TIMELINE_ADAPTER: TypeAdapter[list[TimelinePoint]] = TypeAdapter(list[TimelinePoint])


class SimulationFailedError(AppError):
    status, slug, title = 500, "simulation-failed", "Simulation failed"


# ------------------------------------------------------------------ mapping
def _summary(run: SimulationRun, scenario_key: str | None) -> SimulationSummary:
    m = run.metrics or {}
    final = m.get("final") or {}
    return SimulationSummary(
        id=run.id,
        created_at=run.created_at,
        label=run.label,
        kind=run.kind,
        status=run.status,
        scenario_key=scenario_key,
        incident_id=run.incident_id,
        horizon_minutes=run.inputs["config"]["horizon_minutes"],
        impact_score=final.get("impact_score"),
        peak_impact_score=(m.get("peak") or {}).get("impact_score"),
        failed_count=(final.get("status_counts") or {}).get("FAILED"),
        affected_population=final.get("affected_population"),
        result_hash=run.result_hash,
        dataset_version=run.dataset_version,
        engine_version=run.engine_version,
        duration_ms=run.duration_ms,
    )


def _detail(run: SimulationRun, scenario_key: str | None) -> SimulationDetail:
    m = run.metrics or {}
    return SimulationDetail(
        **_summary(run, scenario_key).model_dump(),
        initiating_events=EVENTS_ADAPTER.validate_python(run.inputs["events"]),
        snapshot_hash=run.snapshot_hash,
        scoring_version=run.scoring_version,
        final_state=STATES_ADAPTER.validate_python(run.final_state or []),
        final_metrics=ImpactMetrics.model_validate(m["final"]) if m.get("final") else None,
        peak_metrics=ImpactMetrics.model_validate(m["peak"]) if m.get("peak") else None,
        timeline=TIMELINE_ADAPTER.validate_python(m.get("timeline", [])),
        error=run.error,
    )


async def _scenario_keys(session: AsyncSession, ids: set[uuid.UUID]) -> dict[uuid.UUID, str]:
    if not ids:
        return {}
    rows = await session.execute(
        select(SimulationScenario.id, SimulationScenario.key).where(SimulationScenario.id.in_(ids))
    )
    return {i: k for i, k in rows.all()}


async def _get_run(session: AsyncSession, run_id: uuid.UUID) -> SimulationRun:
    run = await session.get(SimulationRun, run_id)
    if run is None:
        raise NotFoundError(f"Simulation {run_id} does not exist.")
    return run


# ------------------------------------------------------------------ run
async def _resolve(
    session: AsyncSession, req: SimulationRequest
) -> tuple[list[InitiatingEvent], int, uuid.UUID | None, uuid.UUID | None, dict[str, Any]]:
    if req.scenario_key is not None:
        sc = await get_scenario(session, req.scenario_key)
        events = EVENTS_ADAPTER.validate_python(sc.initiating_events)
        horizon = req.horizon_minutes or sc.horizon_minutes
        return (
            events,
            horizon,
            sc.id,
            None,
            {"type": "scenario", "key": sc.key, "version": sc.version},
        )
    if req.incident_id is not None:
        incident = await session.get(Incident, req.incident_id)
        if incident is None:
            raise NotFoundError(f"Incident {req.incident_id} does not exist.")
        if not incident.initiating_events:
            raise ConflictError(
                f"Incident {incident.reference} has no validated initiating events yet; "
                "free-text reports require SENTINEL analysis (Phase 3)."
            )
        events = EVENTS_ADAPTER.validate_python(incident.initiating_events)
        horizon = req.horizon_minutes or DEFAULT_HORIZON_MINUTES
        return events, horizon, incident.scenario_id, incident.id, {
            "type": "incident", "reference": incident.reference,
        }  # fmt: skip
    assert req.initiating_events is not None
    horizon = req.horizon_minutes or DEFAULT_HORIZON_MINUTES
    return list(req.initiating_events), horizon, None, None, {"type": "custom"}


async def persist_completed(
    session: AsyncSession,
    run: SimulationRun,
    result: SimulationResult,
    *,
    actor_id: str,
    source: dict[str, Any],
) -> SimulationRun:
    """Store a completed run with its events and audit it, in the caller's transaction."""
    run.engine_version, run.scoring_version = result.engine_version, result.scoring_version
    run.status, run.result_hash = "COMPLETED", result.result_hash
    run.final_state = [s.model_dump(mode="json") for s in result.final_state]
    run.metrics = {
        "final": result.final_metrics.model_dump(mode="json"),
        "peak": result.peak_metrics.model_dump(mode="json"),
        "timeline": [p.model_dump(mode="json") for p in result.timeline],
    }
    session.add(run)
    await session.flush()
    session.add_all(
        SimulationEventRow(
            run_id=run.id, seq=e.seq, t_minutes=e.t_minutes, wave=e.wave, event_type=e.kind.value,
            asset_code=e.asset_code,
            from_status=e.from_status.value if e.from_status else None,
            to_status=e.to_status.value if e.to_status else None,
            details=e.details,
        )
        for e in result.events
    )  # fmt: skip
    await append_audit(
        session, actor_type="USER", actor_id=actor_id, action="simulation.completed",
        entity_type="simulation_run", entity_id=str(run.id),
        details={"source": source, "result_hash": result.result_hash,
                 "impact_score": result.final_metrics.impact_score},
    )  # fmt: skip
    return run


async def apply_run_to_picture(
    session: AsyncSession, run_id: uuid.UUID, *, actor_id: str, reason: str | None
) -> None:
    """Promote a run to the operational picture in the caller's transaction."""
    await _apply_picture(session, run_id, actor_id=actor_id, reason=reason)


async def run_simulation(
    session: AsyncSession, twin: LoadedTwin, req: SimulationRequest, *, actor_id: str
) -> SimulationDetail:
    events, horizon, scenario_id, incident_id, source = await _resolve(session, req)
    check_events(twin.snapshot, events, horizon)
    config = SimulationConfig(horizon_minutes=horizon)
    inputs = {
        "events": [e.model_dump(mode="json") for e in events],
        "config": config.model_dump(mode="json"),
        "source": source,
    }
    run = SimulationRun(
        id=uuid.uuid4(), label=req.label, kind="IMPACT", incident_id=incident_id,
        scenario_id=scenario_id, inputs=inputs, snapshot_hash=twin.snapshot.content_hash,
        dataset_version=twin.snapshot.dataset_version, requested_by=actor_id,
    )  # fmt: skip
    started = time.perf_counter()
    try:
        result = await asyncio.to_thread(simulate, twin.snapshot, events, config)
    except Exception as exc:  # an engine bug: record it, never discard it
        log.error("simulation_failed", run_id=str(run.id), exc_info=exc)
        run.engine_version, run.scoring_version = ENGINE_VERSION, SCORING_VERSION
        run.status, run.error = "FAILED", {"type": type(exc).__name__, "message": str(exc)[:500]}
        run.duration_ms = round((time.perf_counter() - started) * 1000, 2)
        session.add(run)
        await append_audit(
            session, actor_type="USER", actor_id=actor_id, action="simulation.failed",
            entity_type="simulation_run", entity_id=str(run.id), details=run.error,
        )  # fmt: skip
        await session.commit()
        raise SimulationFailedError(
            "The simulation engine failed; the failure was recorded.",
            extra={"simulation_id": str(run.id)},
        ) from None

    run.duration_ms = round((time.perf_counter() - started) * 1000, 2)
    await persist_completed(session, run, result, actor_id=actor_id, source=source)
    if req.apply_to_picture:
        await _apply_picture(session, run.id, actor_id=actor_id, reason=req.label)
    await session.commit()
    await session.refresh(run)
    keys = await _scenario_keys(session, {scenario_id} if scenario_id else set())
    return _detail(run, keys.get(scenario_id) if scenario_id else None)


# ------------------------------------------------------------------ queries
async def list_runs(
    session: AsyncSession, *, limit: int, cursor: str | None, incident_id: uuid.UUID | None
) -> tuple[list[SimulationSummary], str | None]:
    stmt = select(SimulationRun).order_by(SimulationRun.created_at.desc(), SimulationRun.id.desc())
    if incident_id:
        stmt = stmt.where(SimulationRun.incident_id == incident_id)
    if cursor:
        anchor = await _get_run(session, uuid.UUID(cursor))
        stmt = stmt.where(
            (SimulationRun.created_at < anchor.created_at)
            | ((SimulationRun.created_at == anchor.created_at) & (SimulationRun.id < anchor.id))
        )
    rows = list((await session.scalars(stmt.limit(limit + 1))).all())
    page = rows[:limit]
    keys = await _scenario_keys(session, {r.scenario_id for r in page if r.scenario_id})
    items = [_summary(r, keys.get(r.scenario_id) if r.scenario_id else None) for r in page]
    return items, (str(page[-1].id) if len(rows) > limit else None)


async def get_run(session: AsyncSession, run_id: uuid.UUID) -> SimulationDetail:
    run = await _get_run(session, run_id)
    keys = await _scenario_keys(session, {run.scenario_id} if run.scenario_id else set())
    return _detail(run, keys.get(run.scenario_id) if run.scenario_id else None)


async def run_events(
    session: AsyncSession, run_id: uuid.UUID, from_t: int | None, to_t: int | None
) -> list[SimEvent]:
    await _get_run(session, run_id)
    stmt = select(SimulationEventRow).where(SimulationEventRow.run_id == run_id)
    if from_t is not None:
        stmt = stmt.where(SimulationEventRow.t_minutes >= from_t)
    if to_t is not None:
        stmt = stmt.where(SimulationEventRow.t_minutes <= to_t)
    rows = (await session.scalars(stmt.order_by(SimulationEventRow.seq))).all()
    return [
        SimEvent(
            seq=r.seq, t_minutes=r.t_minutes, wave=r.wave, kind=r.event_type,
            asset_code=r.asset_code, from_status=r.from_status,
            to_status=r.to_status, details=r.details,
        )
        for r in rows
    ]  # fmt: skip


async def compare_runs(
    session: AsyncSession, a_id: uuid.UUID, b_id: uuid.UUID
) -> SimulationComparison:
    a, b = await get_run(session, a_id), await get_run(session, b_id)
    for run in (a, b):
        if run.status != "COMPLETED":
            raise ConflictError(f"Simulation {run.id} did not complete and cannot be compared.")
    sa = {s.code: s.status for s in a.final_state}
    sb = {s.code: s.status for s in b.final_state}
    failed_a = {c for c, s in sa.items() if s is FunctionalStatus.FAILED}
    failed_b = {c for c, s in sb.items() if s is FunctionalStatus.FAILED}
    assert a.final_metrics
    assert b.final_metrics
    return SimulationComparison(
        a=SimulationSummary.model_validate(a.model_dump()),
        b=SimulationSummary.model_validate(b.model_dump()),
        impact_delta=round(b.final_metrics.impact_score - a.final_metrics.impact_score, 2),
        affected_population_delta=b.final_metrics.affected_population
        - a.final_metrics.affected_population,
        failed_only_in_a=sorted(failed_a - failed_b),
        failed_only_in_b=sorted(failed_b - failed_a),
        failed_in_both=sorted(failed_a & failed_b),
        status_differences=[
            StatusDifference(code=c, a=sa[c], b=sb[c])
            for c in sorted(set(sa) & set(sb))
            if sa[c] is not sb[c]
        ],
    )


async def replay_run(session: AsyncSession, twin: LoadedTwin, run_id: uuid.UUID) -> ReplayResult:
    run = await _get_run(session, run_id)
    if run.status != "COMPLETED" or run.result_hash is None:
        raise ConflictError(f"Simulation {run_id} did not complete; nothing to replay.")
    events = EVENTS_ADAPTER.validate_python(run.inputs["events"])
    config = SimulationConfig.model_validate(run.inputs["config"])
    result = await asyncio.to_thread(simulate, twin.snapshot, events, config)
    return ReplayResult(
        simulation_id=run.id,
        original_hash=run.result_hash,
        replay_hash=result.result_hash,
        hash_matches=result.result_hash == run.result_hash,
        snapshot_matches=run.snapshot_hash == twin.snapshot.content_hash,
        engine_matches=run.engine_version == result.engine_version,
    )


# ------------------------------------------------------------------ operational picture
async def _apply_picture(
    session: AsyncSession, run_id: uuid.UUID, *, actor_id: str, reason: str | None
) -> None:
    session.add(
        OperationalPictureChange(
            kind="APPLY", simulation_run_id=run_id, actor_id=actor_id, reason=reason
        )
    )
    await append_audit(
        session, actor_type="USER", actor_id=actor_id, action="picture.applied",
        entity_type="operational_picture", entity_id=str(run_id), details={"reason": reason},
    )  # fmt: skip


async def apply_picture(session: AsyncSession, run_id: uuid.UUID, *, actor_id: str) -> None:
    run = await _get_run(session, run_id)
    if run.status != "COMPLETED":
        raise ConflictError("Only completed simulations can be applied to the operational picture.")
    await _apply_picture(session, run_id, actor_id=actor_id, reason=run.label)
    await session.commit()


async def reset_picture(session: AsyncSession, *, actor_id: str, reason: str | None) -> None:
    session.add(OperationalPictureChange(kind="RESET", actor_id=actor_id, reason=reason))
    await append_audit(
        session, actor_type="USER", actor_id=actor_id, action="picture.reset",
        entity_type="operational_picture", details={"reason": reason},
    )  # fmt: skip
    await session.commit()


async def current_picture(session: AsyncSession, twin: LoadedTwin) -> OperationalPicture:
    last = await session.scalar(
        select(OperationalPictureChange).order_by(OperationalPictureChange.id.desc()).limit(1)
    )
    if last is not None and last.kind == "APPLY" and last.simulation_run_id is not None:
        run = await _get_run(session, last.simulation_run_id)
        detail = _detail(run, None)
        assert detail.final_metrics is not None
        return OperationalPicture(
            source="simulation",
            simulation_id=run.id,
            label=run.label,
            changed_at=last.created_at,
            as_of_minutes=detail.horizon_minutes,
            stale=run.snapshot_hash != twin.snapshot.content_hash,
            states=detail.final_state,
            metrics=detail.final_metrics,
        )
    base = await analysis_cache.baseline(twin.snapshot)
    return OperationalPicture(
        source="baseline",
        simulation_id=None,
        label=None,
        changed_at=last.created_at if last else None,
        as_of_minutes=0,
        stale=False,
        states=list(base.final_state),
        metrics=base.final_metrics.model_copy(update={"t_minutes": 0}),
    )
