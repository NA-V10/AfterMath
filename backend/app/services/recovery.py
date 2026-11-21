"""Recovery planning service: inventory, strategy generation (3 policies), validation, queries."""

from __future__ import annotations

import asyncio
import json
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import TypeAdapter
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ConflictError, InvalidInputError, NotFoundError
from app.database.models import Incident, RecoveryAction, RecoveryStrategy, ResourceInventory
from app.governance.rules.validator import ValidationReport, content_hash, validate_plan
from app.recovery.evaluate import impact_hours, run
from app.recovery.model import (
    PLANNING_HORIZON_MINUTES,
    Inventory,
    Plan,
    Policy,
    ResourceUse,
    ScheduledAction,
    StrategyMetrics,
    Unschedulable,
)
from app.recovery.scheduler import plan as make_plan
from app.schemas.recovery import (
    ActionOut,
    InventoryIn,
    InventoryOut,
    StrategyDetail,
    StrategyRound,
    StrategySummary,
)
from app.services.audit import append_audit
from app.services.scenarios import EVENTS_ADAPTER
from app.services.twin_store import LoadedTwin

OBJECTIVES = {
    Policy.CRITICAL_FIRST: (
        "Restore life-critical services (hospitals, emergency response, water) first."
    ),
    Policy.MAX_RESTORATION: "Restore the largest number of infrastructure assets per crew-hour.",
    Policy.BALANCED: "Balance criticality, population served, cost and resource scarcity.",
}
OPEN_STATUSES = ("DRAFT", "VALIDATED")
UNSCHEDULABLE = TypeAdapter(list[Unschedulable])


# ------------------------------------------------------------------ inventory
def _inventory_out(row: ResourceInventory) -> InventoryOut:
    return InventoryOut(
        version=row.version,
        renewables=row.renewables,
        consumables=row.consumables,
        reason=row.reason,
        created_by=row.created_by,
        created_at=row.created_at,
    )


async def current_inventory_row(session: AsyncSession) -> ResourceInventory:
    row = await session.scalar(select(ResourceInventory).where(ResourceInventory.is_current))
    if row is None:
        raise ConflictError("No resource inventory is loaded. Run `python -m app.cli seed`.")
    return row


async def get_inventory(session: AsyncSession) -> InventoryOut:
    return _inventory_out(await current_inventory_row(session))


async def inventory_by_version(session: AsyncSession, version: int) -> Inventory:
    row = await session.scalar(
        select(ResourceInventory).where(ResourceInventory.version == version)
    )
    if row is None:
        raise NotFoundError(f"Inventory version {version} does not exist.")
    return Inventory(version=row.version, renewables=row.renewables, consumables=row.consumables)


async def set_inventory(
    session: AsyncSession, body: InventoryIn, *, actor_id: str, initial: bool = False
) -> InventoryOut:
    if any(v < 0 for v in [*body.renewables.values(), *body.consumables.values()]):
        raise InvalidInputError("Inventory quantities must be non-negative.")
    latest = await session.scalar(select(func.max(ResourceInventory.version)))
    if initial and latest:
        return _inventory_out(await current_inventory_row(session))
    await session.execute(update(ResourceInventory).values(is_current=False))
    row = ResourceInventory(
        version=(latest or 0) + 1,
        renewables=body.renewables,
        consumables=body.consumables,
        reason=body.reason,
        created_by=actor_id,
        is_current=True,
    )
    session.add(row)
    await session.flush()
    await append_audit(
        session,
        actor_type="SYSTEM" if initial else "USER",
        actor_id=actor_id,
        action="inventory.updated",
        entity_type="resource_inventory",
        entity_id=str(row.version),
        after={"renewables": body.renewables, "consumables": body.consumables},
        details={"reason": body.reason},
    )
    await session.commit()
    return _inventory_out(row)


async def seed_inventory(session: AsyncSession, path: Path) -> InventoryOut:
    """Load the dataset's initial inventory once (version 1); later changes go through the API."""
    data = json.loads(await asyncio.to_thread(path.read_text, encoding="utf-8"))
    body = InventoryIn(
        renewables=data["renewables"],
        consumables=data["consumables"],
        reason="initial synthetic inventory",
    )
    return await set_inventory(session, body, actor_id="cli:seed", initial=True)


# ------------------------------------------------------------------ mapping
def _actions(rows: list[RecoveryAction]) -> list[ScheduledAction]:
    return [
        ScheduledAction(
            seq=r.seq,
            key=r.key,
            type=r.action_type,
            asset_code=r.target_asset_code,
            start_minutes=r.start_minutes,
            end_minutes=r.end_minutes,
            resources=tuple(ResourceUse.model_validate(x) for x in r.resources),
            consumables=r.consumables,
            cost=r.cost,
            supplies_minutes=r.supplies_minutes,
            trade=r.trade,
            crew_size=r.crew_size,
            prerequisites=tuple(r.prerequisite_seqs),
            rationale=r.rationale,
        )
        for r in sorted(rows, key=lambda r: r.seq)
    ]


async def _action_rows(session: AsyncSession, strategy_id: uuid.UUID) -> list[RecoveryAction]:
    return list(
        (
            await session.scalars(
                select(RecoveryAction).where(RecoveryAction.strategy_id == strategy_id)
            )
        ).all()
    )


def _summary(row: RecoveryStrategy, n_actions: int) -> StrategySummary:
    m = row.metrics
    return StrategySummary(
        id=row.id,
        incident_id=row.incident_id,
        planning_round=row.planning_round,
        policy=row.policy,
        status=row.status,
        recommended=row.recommended,
        objective=row.objective,
        impact_hours=m["impact_hours"],
        time_to_critical_services_minutes=m["time_to_critical_services_minutes"],
        time_to_90pct_operational_minutes=m["time_to_90pct_operational_minutes"],
        makespan_minutes=m["makespan_minutes"],
        total_cost=m["total_cost"],
        risk_score=row.risk_score,
        actions_count=n_actions,
        unschedulable_count=len(row.unschedulable),
        content_hash=row.content_hash,
        created_at=row.created_at,
    )


def _signature(actions: list[RecoveryAction]) -> tuple[Any, ...]:
    return tuple((a.key, a.start_minutes) for a in sorted(actions, key=lambda a: a.seq))


async def _detail(
    session: AsyncSession, row: RecoveryStrategy, siblings: list[RecoveryStrategy] | None = None
) -> StrategyDetail:
    actions = await _action_rows(session, row.id)
    identical = []
    for other in siblings or []:
        if other.id != row.id and _signature(await _action_rows(session, other.id)) == _signature(
            actions
        ):
            identical.append(other.policy)
    return StrategyDetail(
        **_summary(row, len(actions)).model_dump(),
        inventory_version=row.inventory_version,
        horizon_minutes=row.horizon_minutes,
        rationale=row.rationale,
        rationale_source=row.rationale_source,
        metrics=StrategyMetrics.model_validate(row.metrics),
        risk_components=row.risk_components,
        benefits=row.benefits,
        limitations=row.limitations,
        unschedulable=UNSCHEDULABLE.validate_python(row.unschedulable),
        expected_result_hash=row.expected_result_hash,
        validation_report=ValidationReport.model_validate(row.validation_report)
        if row.validation_report
        else None,
        validated_at=row.validated_at,
        actions=[
            ActionOut(
                seq=a.seq,
                key=a.key,
                action_type=a.action_type,
                target_asset_code=a.target_asset_code,
                start_minutes=a.start_minutes,
                end_minutes=a.end_minutes,
                trade=a.trade,
                crew_size=a.crew_size,
                resources=a.resources,
                consumables=a.consumables,
                cost=a.cost,
                supplies_minutes=a.supplies_minutes,
                prerequisite_seqs=a.prerequisite_seqs,
                rationale=a.rationale,
            )
            for a in sorted(actions, key=lambda a: a.seq)
        ],
        identical_to=sorted(identical),
    )


# ------------------------------------------------------------------ comparison text
def _fmt_minutes(m: int | None) -> str:
    if m is None:
        return "not within the horizon"
    return f"T+{m // 60}h{m % 60:02d}" if m % 60 else f"T+{m // 60}h"


def compare_plans(
    plans: dict[Policy, Plan], inventory: Inventory
) -> dict[Policy, tuple[list[str], list[str]]]:
    """Deterministic benefits/limitations, stated relative to the other strategies."""
    out: dict[Policy, tuple[list[str], list[str]]] = {}

    def best(key: Any, lower: bool = True) -> set[Policy]:
        values = {p: key(plan) for p, plan in plans.items() if key(plan) is not None}
        if not values:
            return set()
        target = min(values.values()) if lower else max(values.values())
        winners = {p for p, v in values.items() if v == target}
        return winners if len(winners) < len(plans) else set()  # "best" only if it differs

    lowest_impact = best(lambda p: p.metrics.impact_hours)
    fastest_crit = best(lambda p: p.metrics.time_to_critical_services_minutes)
    fastest_90 = best(lambda p: p.metrics.time_to_90pct_operational_minutes)
    cheapest = best(lambda p: p.metrics.total_cost)
    safest = best(lambda p: p.risk_score)
    riskiest = best(lambda p: p.risk_score, lower=False)
    for policy, p in plans.items():
        m = p.metrics
        benefits: list[str] = []
        limitations: list[str] = []
        if policy in lowest_impact:
            benefits.append(f"Lowest total impact ({m.impact_hours:.1f} impact-hours).")
        if policy in fastest_crit:
            benefits.append(
                "Fastest restoration of life-critical services "
                f"({_fmt_minutes(m.time_to_critical_services_minutes)})."
            )
        if policy in fastest_90:
            benefits.append(
                "Fastest to 90% of assets operational "
                f"({_fmt_minutes(m.time_to_90pct_operational_minutes)})."
            )
        if policy in cheapest:
            benefits.append(f"Lowest cost ({m.total_cost:,}).")
        if policy in safest:
            benefits.append(f"Lowest execution risk ({p.risk_score:.1f}).")
        if m.time_to_critical_services_minutes is None:
            limitations.append("Life-critical services are not all restored within the horizon.")
        if m.backup_exhausted_before_restoration:
            limitations.append(
                "Backup power runs out before restoration at: "
                + ", ".join(m.backup_exhausted_before_restoration)
                + "."
            )
        if m.unrestored_assets:
            limitations.append(
                f"{len(m.unrestored_assets)} asset(s) still impaired at the horizon: "
                + ", ".join(m.unrestored_assets[:8])
                + ("…" if len(m.unrestored_assets) > 8 else "")
                + "."
            )
        repairs_dropped = [u for u in p.unschedulable if u.reason != "NO_BENEFIT"]
        if repairs_dropped:
            limitations.append(
                "Cannot schedule: "
                + ", ".join(
                    f"{u.key} ({u.reason.lower().replace('_', ' ')})" for u in repairs_dropped
                )
                + "."
            )
        exhausted = [k for k, v in m.remaining.items() if v == 0 and inventory.consumables.get(k)]
        if exhausted:
            limitations.append("Uses the last of: " + ", ".join(exhausted) + ".")
        if policy in riskiest:
            limitations.append(f"Highest execution risk ({p.risk_score:.1f}).")
        out[policy] = (benefits, limitations)
    return out


# ------------------------------------------------------------------ generation
async def _incident_events(
    session: AsyncSession, incident_id: uuid.UUID
) -> tuple[Incident, list[Any]]:
    incident = await session.get(Incident, incident_id)
    if incident is None:
        raise NotFoundError(f"Incident {incident_id} does not exist.")
    if incident.status in ("RECOVERING", "RECOVERED", "CLOSED"):
        raise ConflictError(f"Incident {incident.reference} is {incident.status}; cannot re-plan.")
    if not incident.initiating_events:
        raise ConflictError(
            f"Incident {incident.reference} has no validated initiating events; analyse it first."
        )
    return incident, EVENTS_ADAPTER.validate_python(incident.initiating_events)


def plan_all(twin: LoadedTwin, events: list[Any], inventory: Inventory) -> dict[Policy, Plan]:
    return {p: make_plan(twin.snapshot, events, inventory, p) for p in Policy}


async def generate_strategies(
    session: AsyncSession, twin: LoadedTwin, incident_id: uuid.UUID, *, actor_id: str
) -> list[uuid.UUID]:
    _incident, events = await _incident_events(session, incident_id)
    inv_row = await current_inventory_row(session)
    inventory = Inventory(
        version=inv_row.version, renewables=inv_row.renewables, consumables=inv_row.consumables
    )
    plans = await asyncio.to_thread(plan_all, twin, events, inventory)
    texts = compare_plans(plans, inventory)
    last = await session.scalar(
        select(func.max(RecoveryStrategy.planning_round)).where(
            RecoveryStrategy.incident_id == incident_id
        )
    )
    round_no = (last or 0) + 1
    await session.execute(
        update(RecoveryStrategy)
        .where(
            RecoveryStrategy.incident_id == incident_id, RecoveryStrategy.status.in_(OPEN_STATUSES)
        )
        .values(status="SUPERSEDED", recommended=False)
    )
    ids = []
    event_json = [e.model_dump(mode="json") for e in events]
    for policy, p in plans.items():
        sid = uuid.uuid4()
        benefits, limitations = texts[policy]
        session.add(
            RecoveryStrategy(
                id=sid,
                incident_id=incident_id,
                planning_round=round_no,
                policy=policy.value,
                status="DRAFT",
                inventory_version=inventory.version,
                snapshot_hash=twin.snapshot.content_hash,
                incident_events=event_json,
                horizon_minutes=p.horizon_minutes,
                objective=OBJECTIVES[policy],
                metrics=p.metrics.model_dump(mode="json"),
                risk_score=p.risk_score,
                risk_components=p.risk_components,
                benefits=benefits,
                limitations=limitations,
                unschedulable=[u.model_dump(mode="json") for u in p.unschedulable],
                expected_result_hash=p.expected_result_hash,
                content_hash=content_hash(
                    policy=policy.value,
                    inventory=inventory,
                    incident_events=events,
                    actions=p.actions,
                    horizon=p.horizon_minutes,
                    expected_result_hash=p.expected_result_hash,
                ),
                created_by=actor_id,
            )
        )
        await session.flush()
        for a in p.actions:
            session.add(
                RecoveryAction(
                    strategy_id=sid,
                    seq=a.seq,
                    key=a.key,
                    action_type=a.type.value,
                    target_asset_code=a.asset_code,
                    start_minutes=a.start_minutes,
                    end_minutes=a.end_minutes,
                    trade=a.trade,
                    crew_size=a.crew_size,
                    resources=[r.model_dump() for r in a.resources],
                    consumables=a.consumables,
                    cost=a.cost,
                    supplies_minutes=a.supplies_minutes,
                    prerequisite_seqs=list(a.prerequisites),
                    rationale=a.rationale,
                )
            )
        ids.append(sid)
    await append_audit(
        session,
        actor_type="AGENT" if actor_id.startswith("agent:") else "USER",
        actor_id=actor_id,
        action="strategies.generated",
        entity_type="incident",
        entity_id=str(incident_id),
        details={
            "planning_round": round_no,
            "inventory_version": inventory.version,
            "strategies": [str(i) for i in ids],
        },
    )
    await session.commit()
    return ids


async def set_rationale(
    session: AsyncSession, strategy_id: uuid.UUID, text: str, source: str
) -> None:
    row = await _row(session, strategy_id)
    row.rationale, row.rationale_source = text, source
    await session.commit()


# ------------------------------------------------------------------ validation
async def _row(session: AsyncSession, strategy_id: uuid.UUID) -> RecoveryStrategy:
    row = await session.get(RecoveryStrategy, strategy_id)
    if row is None:
        raise NotFoundError(f"Strategy {strategy_id} does not exist.")
    return row


async def validate_strategy(
    session: AsyncSession, twin: LoadedTwin, strategy_id: uuid.UUID, *, actor_id: str
) -> ValidationReport:
    row = await _row(session, strategy_id)
    if row.status not in OPEN_STATUSES and row.status != "VALIDATION_FAILED":
        raise ConflictError(
            f"Strategy is {row.status}; only draft or validated strategies are validated."
        )
    if row.status == "VALIDATION_FAILED":
        raise ConflictError(
            "Strategy failed validation; VALIDATION_FAILED is terminal. Re-plan instead."
        )
    inventory = await inventory_by_version(session, row.inventory_version)
    actions = _actions(await _action_rows(session, row.id))
    events = EVENTS_ADAPTER.validate_python(row.incident_events)
    report = await asyncio.to_thread(
        validate_plan,
        twin.snapshot,
        events,
        inventory,
        actions,
        horizon=row.horizon_minutes,
        expected_result_hash=row.expected_result_hash,
        stored_content_hash=row.content_hash,
        policy=row.policy,
    )
    if row.snapshot_hash != twin.snapshot.content_hash:
        report = report.model_copy(update={"passed": False})
    before = row.status
    row.status = "VALIDATED" if report.passed else "VALIDATION_FAILED"
    row.validation_report = report.model_dump(mode="json")
    row.validated_at = datetime.now(UTC)
    row.version += 1
    await append_audit(
        session,
        actor_type="AGENT" if actor_id.startswith("agent:") else "USER",
        actor_id=actor_id,
        action="strategy.validated" if report.passed else "strategy.validation_failed",
        entity_type="recovery_strategy",
        entity_id=str(row.id),
        before={"status": before},
        after={"status": row.status},
        details={
            "failed_rules": [r.rule for r in report.rules if not r.passed],
            "content_hash": row.content_hash,
        },
    )
    await session.commit()
    return report


async def recommend(
    session: AsyncSession, incident_id: uuid.UUID, planning_round: int
) -> uuid.UUID | None:
    """Deterministic rule: among VALIDATED strategies of the round, lowest impact-hours, then
    lowest risk, then policy name."""
    rows = list(
        (
            await session.scalars(
                select(RecoveryStrategy).where(
                    RecoveryStrategy.incident_id == incident_id,
                    RecoveryStrategy.planning_round == planning_round,
                )
            )
        ).all()
    )
    for r in rows:
        r.recommended = False
    valid = [r for r in rows if r.status == "VALIDATED"]
    chosen = min(
        valid, key=lambda r: (r.metrics["impact_hours"], r.risk_score, r.policy), default=None
    )
    if chosen:
        chosen.recommended = True
    await session.commit()
    return chosen.id if chosen else None


# ------------------------------------------------------------------ queries
async def get_strategy(session: AsyncSession, strategy_id: uuid.UUID) -> StrategyDetail:
    row = await _row(session, strategy_id)
    siblings = list(
        (
            await session.scalars(
                select(RecoveryStrategy).where(
                    RecoveryStrategy.incident_id == row.incident_id,
                    RecoveryStrategy.planning_round == row.planning_round,
                )
            )
        ).all()
    )
    return await _detail(session, row, siblings)


async def list_strategies(
    session: AsyncSession, *, incident_id: uuid.UUID | None, status: str | None
) -> list[StrategySummary]:
    stmt = (
        select(RecoveryStrategy)
        .order_by(RecoveryStrategy.created_at.desc(), RecoveryStrategy.policy)
        .limit(100)
    )
    if incident_id:
        stmt = stmt.where(RecoveryStrategy.incident_id == incident_id)
    if status:
        stmt = stmt.where(RecoveryStrategy.status == status)
    rows = list((await session.scalars(stmt)).all())
    return [_summary(r, len(await _action_rows(session, r.id))) for r in rows]


async def latest_round(
    session: AsyncSession, twin: LoadedTwin, incident_id: uuid.UUID
) -> StrategyRound:
    round_no = await session.scalar(
        select(func.max(RecoveryStrategy.planning_round)).where(
            RecoveryStrategy.incident_id == incident_id
        )
    )
    if round_no is None:
        raise NotFoundError("No recovery strategies have been generated for this incident.")
    rows = list(
        (
            await session.scalars(
                select(RecoveryStrategy)
                .where(
                    RecoveryStrategy.incident_id == incident_id,
                    RecoveryStrategy.planning_round == round_no,
                )
                .order_by(RecoveryStrategy.policy)
            )
        ).all()
    )
    events = EVENTS_ADAPTER.validate_python(rows[0].incident_events)
    horizon = rows[0].horizon_minutes or PLANNING_HORIZON_MINUTES
    baseline = await asyncio.to_thread(run, twin.snapshot, events, [], horizon)
    order = {p.value: i for i, p in enumerate(Policy)}
    rows.sort(key=lambda r: order[r.policy])
    return StrategyRound(
        incident_id=incident_id,
        planning_round=round_no,
        recommended_strategy_id=next((r.id for r in rows if r.recommended), None),
        baseline_impact_hours=impact_hours(baseline, horizon),
        baseline_timeline=[p.model_dump(mode="json") for p in baseline.timeline],
        strategies=[await _detail(session, r, rows) for r in rows],
    )
