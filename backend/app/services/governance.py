"""Approval, rejection, simulated execution and verification (docs/SECURITY.md §3, ADR-0008).

Every state change runs as authorise → check state → mutate → audit inside ONE transaction,
with the strategy row (and its incident) locked, so concurrent approve/reject/execute calls are
serialised and an audit failure rolls the change back. "Execution" replays the approved plan
through the simulation engine; nothing leaves this process.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime
from typing import Literal

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import (
    AppError,
    ConflictError,
    ContentHashMismatchError,
    ForbiddenError,
    InvalidTransitionError,
    NotFoundError,
    RevalidationFailedError,
    VersionConflictError,
)
from app.core.logging import get_logger
from app.database.models import (
    ApprovalRecord,
    Incident,
    RecoveryExecution,
    RecoveryStrategy,
    RecoveryVerification,
    ResourceInventory,
    SimulationRun,
)
from app.governance.rules.policies import (
    Decision,
    StrategyFacts,
    decide_approval,
    decide_execution,
    highest,
)
from app.governance.rules.state_machine import (
    CLOSABLE,
    SUPERSEDABLE,
    IncidentStatus,
    StrategyStatus,
    TransitionError,
    require_transition,
)
from app.governance.rules.validator import (
    ValidationReport,
    consumption,
    validate_execution,
    validate_plan,
)
from app.governance.rules.verification import VerificationResult, verify
from app.recovery.evaluate import recovery_events, run
from app.recovery.model import Inventory, ScheduledAction
from app.schemas.governance import ApprovalOut, RecoveryExecutionOut, VerificationOut
from app.services.audit import append_audit
from app.services.auth import Principal
from app.services.recovery import approval_out, inventory_by_version, plan_actions
from app.services.scenarios import EVENTS_ADAPTER
from app.services.simulations import apply_run_to_picture, persist_completed
from app.services.twin_store import LoadedTwin
from app.simulation.model import SimulationResult

log = get_logger(__name__)
GUARDIAN = "agent:GUARDIAN"


class ExecutionFailedError(AppError):
    status, slug, title = 500, "execution-failed", "Simulated execution failed"


def _raise(decision: Decision) -> None:
    if decision.allowed:
        return
    cls: type[AppError] = {
        "forbidden": ForbiddenError,
        "invalid-state-transition": InvalidTransitionError,
        "content-hash-mismatch": ContentHashMismatchError,
    }.get(decision.code or "", ConflictError)
    raise cls(decision.reason)


def _transition(row: RecoveryStrategy, target: StrategyStatus) -> str:
    before = row.status
    try:
        require_transition(row.status, target)
    except TransitionError as exc:
        raise InvalidTransitionError(str(exc)) from None
    row.status = target.value
    row.version += 1
    return before


async def _locked(
    session: AsyncSession, strategy_id: uuid.UUID
) -> tuple[RecoveryStrategy, Incident]:
    """Lock the incident first, then the strategy (one order everywhere: no deadlocks)."""
    incident_id = await session.scalar(
        select(RecoveryStrategy.incident_id).where(RecoveryStrategy.id == strategy_id)
    )
    if incident_id is None:
        raise NotFoundError(f"Strategy {strategy_id} does not exist.")
    incident = await session.scalar(
        select(Incident).where(Incident.id == incident_id).with_for_update()
    )
    row = await session.scalar(
        select(RecoveryStrategy).where(RecoveryStrategy.id == strategy_id).with_for_update()
    )
    if incident is None or row is None:  # deleted concurrently (FKs make this unexpected)
        raise NotFoundError(f"Strategy {strategy_id} does not exist.")
    return row, incident


async def _siblings(session: AsyncSession, row: RecoveryStrategy) -> list[RecoveryStrategy]:
    return list(
        (
            await session.scalars(
                select(RecoveryStrategy).where(
                    RecoveryStrategy.incident_id == row.incident_id,
                    RecoveryStrategy.id != row.id,
                )
            )
        ).all()
    )


def _facts(
    row: RecoveryStrategy, incident: Incident, siblings: list[RecoveryStrategy]
) -> StrategyFacts:
    return StrategyFacts(
        status=row.status,
        content_hash=row.content_hash,
        incident_status=incident.status,
        planned_by=row.requested_by or row.created_by,
        sibling_statuses=tuple(s.status for s in siblings),
    )


def _check_version(row: RecoveryStrategy, expected: int) -> None:
    if row.version != expected:
        raise VersionConflictError(
            f"The strategy changed since you loaded it (version {row.version}, you had "
            f"{expected}). Reload and review it again."
        )


# ------------------------------------------------------------------ approve / reject
async def decide(
    session: AsyncSession,
    strategy_id: uuid.UUID,
    principal: Principal,
    *,
    decision: Literal["APPROVE", "REJECT"],
    content_hash: str,
    expected_version: int,
    comment: str | None,
    separation_of_duties: bool,
) -> ApprovalOut:
    row, incident = await _locked(session, strategy_id)
    siblings = await _siblings(session, row)
    verdict = decide_approval(
        actor=principal.username, roles=principal.roles, facts=_facts(row, incident, siblings),
        submitted_hash=content_hash, decision=decision, comment=comment,
        separation_of_duties=separation_of_duties,
    )  # fmt: skip
    if not verdict.allowed:
        log.info(
            "decision_denied", security=True, username=principal.username,
            strategy_id=str(strategy_id), decision=decision, reason=verdict.reason,
        )  # fmt: skip
        await session.rollback()
        _raise(verdict)
    _check_version(row, expected_version)
    target = StrategyStatus.APPROVED if decision == "APPROVE" else StrategyStatus.REJECTED
    before = _transition(row, target)
    record = ApprovalRecord(
        strategy_id=row.id,
        decision=target.value,
        content_hash=row.content_hash,
        actor_id=principal.username,
        actor_role=highest(principal.roles).value,
        comment=(comment or "").strip() or None,
    )
    session.add(record)
    await session.flush()
    if decision == "REJECT":
        # Nothing left to decide in this round → the incident needs a new plan.
        undecided = (StrategyStatus.VALIDATED, StrategyStatus.APPROVED)
        open_left = [
            s for s in siblings if s.planning_round == row.planning_round and s.status in undecided
        ]
        if not open_left and incident.status == IncidentStatus.AWAITING_APPROVAL:
            incident.status = IncidentStatus.ANALYZED.value
    await append_audit(
        session, actor_type="USER", actor_id=principal.username,
        action="strategy.approved" if decision == "APPROVE" else "strategy.rejected",
        entity_type="recovery_strategy", entity_id=str(row.id),
        before={"status": before}, after={"status": row.status},
        details={"content_hash": row.content_hash, "comment": record.comment,
                 "role": record.actor_role, "approval_id": str(record.id),
                 "separation_of_duties": separation_of_duties},
    )  # fmt: skip
    await session.commit()
    await session.refresh(record)
    return approval_out(record)


# ------------------------------------------------------------------ execute
async def _existing(session: AsyncSession, key: str) -> RecoveryExecution | None:
    return await session.scalar(
        select(RecoveryExecution).where(RecoveryExecution.idempotency_key == key)
    )


async def _current_inventory(session: AsyncSession) -> ResourceInventory:
    row = await session.scalar(
        select(ResourceInventory).where(ResourceInventory.is_current).with_for_update()
    )
    if row is None:
        raise ConflictError("No resource inventory is loaded.")
    return row


def _simulate_execution(
    twin: LoadedTwin, row: RecoveryStrategy, actions: list[ScheduledAction]
) -> tuple[SimulationResult, SimulationResult, VerificationResult]:
    events = EVENTS_ADAPTER.validate_python(row.incident_events)
    executed = run(twin.snapshot, events, actions, row.horizon_minutes)
    without = run(twin.snapshot, events, [], row.horizon_minutes)
    result = verify(
        twin.snapshot, actions, without_recovery=without, executed=executed,
        expected_result_hash=row.expected_result_hash,
    )  # fmt: skip
    return executed, without, result


def _revalidate(
    twin: LoadedTwin,
    row: RecoveryStrategy,
    incident: Incident,
    actions: list[ScheduledAction],
    planned: Inventory,
    current: Inventory,
    siblings: list[RecoveryStrategy],
) -> ValidationReport:
    events = EVENTS_ADAPTER.validate_python(row.incident_events)
    report = validate_plan(
        twin.snapshot, events, planned, actions, horizon=row.horizon_minutes,
        expected_result_hash=row.expected_result_hash, stored_content_hash=row.content_hash,
        policy=row.policy,
    )  # fmt: skip
    return validate_execution(
        report, actions,
        current_snapshot_hash=twin.snapshot.content_hash, planned_snapshot_hash=row.snapshot_hash,
        planned_inventory_version=row.inventory_version, current_inventory=current,
        incident_matches=row.incident_id == incident.id, incident_status=incident.status,
        sibling_statuses=[s.status for s in siblings],
    )  # fmt: skip


async def execute(
    session: AsyncSession,
    twin: LoadedTwin,
    strategy_id: uuid.UUID,
    principal: Principal,
    *,
    idempotency_key: str,
) -> RecoveryExecutionOut:
    previous = await _existing(session, idempotency_key)
    if previous is not None:
        if previous.strategy_id != strategy_id:
            raise ConflictError("This Idempotency-Key was already used for another strategy.")
        out = await get_execution(session, previous.id)
        return out.model_copy(update={"replayed": True})

    row, incident = await _locked(session, strategy_id)
    siblings = await _siblings(session, row)
    verdict = decide_execution(roles=principal.roles, facts=_facts(row, incident, siblings))
    if not verdict.allowed:
        log.info(
            "execute_denied", security=True, username=principal.username,
            strategy_id=str(strategy_id), reason=verdict.reason,
        )  # fmt: skip
        await append_audit(
            session, actor_type="USER", actor_id=principal.username,
            action="strategy.execute_denied", entity_type="recovery_strategy",
            entity_id=str(row.id), details={"reason": verdict.reason, "status": row.status},
        )  # fmt: skip
        await session.commit()
        _raise(verdict)

    approval = await session.scalar(
        select(ApprovalRecord)
        .where(ApprovalRecord.strategy_id == row.id, ApprovalRecord.decision == "APPROVED")
        .order_by(ApprovalRecord.created_at.desc())
        .limit(1)
    )
    if approval is None:  # APPROVED without a record would be a defect; never execute it
        raise InvalidTransitionError("Strategy has no approval record; it cannot be executed.")

    actions = await plan_actions(session, row.id)
    planned = await inventory_by_version(session, row.inventory_version)
    inv_row = await _current_inventory(session)
    current = Inventory(
        version=inv_row.version, renewables=inv_row.renewables, consumables=inv_row.consumables
    )
    report = await asyncio.to_thread(
        _revalidate, twin, row, incident, actions, planned, current, siblings
    )
    hash_ok = approval.content_hash == row.content_hash
    if not (report.passed and hash_ok):
        failed = [r.rule for r in report.rules if not r.passed]
        if not hash_ok:
            failed.append("approval-hash")
        before = _transition(row, StrategyStatus.VALIDATION_FAILED)
        row.validation_report = report.model_dump(mode="json")
        row.validated_at = datetime.now(UTC)
        await append_audit(
            session, actor_type="AGENT", actor_id=GUARDIAN, action="strategy.revalidation_failed",
            entity_type="recovery_strategy", entity_id=str(row.id),
            before={"status": before}, after={"status": row.status},
            details={"failed_rules": failed, "requested_by": principal.username},
        )  # fmt: skip
        await session.commit()
        raise RevalidationFailedError(
            "GUARDIAN revalidation failed at execution time; the strategy is now "
            f"VALIDATION_FAILED and cannot run. Failed: {', '.join(failed)}.",
            extra={"failed_rules": failed},
        )

    started = datetime.now(UTC)
    before = _transition(row, StrategyStatus.EXECUTING)
    try:
        executed, _without, result = await asyncio.to_thread(
            _simulate_execution, twin, row, actions
        )
    except Exception as exc:  # an engine defect: record the failure, never pretend success
        log.error("execution_failed", strategy_id=str(row.id), exc_info=exc)
        _transition(row, StrategyStatus.EXECUTION_FAILED)
        failed_exec = RecoveryExecution(
            strategy_id=row.id, incident_id=incident.id, approval_id=approval.id,
            requested_by=principal.username, idempotency_key=idempotency_key, status="FAILED",
            revalidation=report.model_dump(mode="json"),
            error={"type": type(exc).__name__, "message": str(exc)[:500]},
            started_at=started, completed_at=datetime.now(UTC),
        )  # fmt: skip
        session.add(failed_exec)
        await append_audit(
            session, actor_type="USER", actor_id=principal.username,
            action="strategy.execution_failed", entity_type="recovery_strategy",
            entity_id=str(row.id), details=failed_exec.error,
        )  # fmt: skip
        await session.commit()
        raise ExecutionFailedError(
            "The simulated execution failed; the failure was recorded.",
            extra={"execution_id": str(failed_exec.id)},
        ) from None

    sim = SimulationRun(
        id=uuid.uuid4(), label=f"Recovery: {row.policy} ({incident.reference})", kind="RECOVERY",
        incident_id=incident.id,
        inputs={"events": [e.model_dump(mode="json") for e in
                           recovery_events(EVENTS_ADAPTER.validate_python(row.incident_events),
                                           actions)],
                "config": {"horizon_minutes": row.horizon_minutes},
                "source": {"type": "recovery", "strategy_id": str(row.id)}},
        snapshot_hash=twin.snapshot.content_hash, dataset_version=twin.snapshot.dataset_version,
        requested_by=principal.username,
    )  # fmt: skip
    await persist_completed(
        session, sim, executed, actor_id=principal.username,
        source={"type": "recovery", "strategy_id": str(row.id)},
    )  # fmt: skip
    await apply_run_to_picture(
        session, sim.id, actor_id=principal.username, reason=f"recovery executed: {row.policy}"
    )
    execution = RecoveryExecution(
        strategy_id=row.id, incident_id=incident.id, simulation_run_id=sim.id,
        approval_id=approval.id, requested_by=principal.username,
        idempotency_key=idempotency_key, status="COMPLETED",
        revalidation=report.model_dump(mode="json"), started_at=started,
        completed_at=datetime.now(UTC),
    )  # fmt: skip
    session.add(execution)
    _transition(row, StrategyStatus.EXECUTED)
    await session.flush()
    await append_audit(
        session, actor_type="USER", actor_id=principal.username, action="strategy.executed",
        entity_type="recovery_strategy", entity_id=str(row.id),
        before={"status": before}, after={"status": row.status},
        details={"execution_id": str(execution.id), "simulation_run_id": str(sim.id),
                 "approval_id": str(approval.id), "content_hash": row.content_hash,
                 "result_hash": executed.result_hash},
    )  # fmt: skip

    # Siblings can no longer be executed; open ones are superseded.
    for s in siblings:
        if s.status in SUPERSEDABLE:
            s.status, s.recommended, s.version = (
                StrategyStatus.SUPERSEDED.value,
                False,
                s.version + 1,
            )
    # Consumables are used up: the inventory moves to a new version (crews are renewable).
    used = consumption(actions)
    if any(used.values()):
        await session.execute(update(ResourceInventory).values(is_current=False))
        new_inv = ResourceInventory(
            version=inv_row.version + 1, renewables=inv_row.renewables,
            consumables={k: v - used.get(k, 0) for k, v in inv_row.consumables.items()},
            reason=f"consumed by recovery execution {execution.id}",
            created_by=principal.username, is_current=True,
        )  # fmt: skip
        session.add(new_inv)
        await append_audit(
            session, actor_type="USER", actor_id=principal.username, action="inventory.consumed",
            entity_type="resource_inventory", entity_id=str(new_inv.version),
            details={"execution_id": str(execution.id), "consumed": used},
        )  # fmt: skip

    # GUARDIAN verification (deterministic).
    verification = RecoveryVerification(
        execution_id=execution.id, outcome=result.outcome,
        matches_expectation=result.matches_expectation, result=result.model_dump(mode="json"),
        verified_by=GUARDIAN,
    )  # fmt: skip
    session.add(verification)
    _transition(row, StrategyStatus.VERIFIED)
    incident.status = IncidentStatus.RECOVERED.value
    await session.flush()
    if not result.matches_expectation:
        log.error(
            "verification_mismatch", strategy_id=str(row.id),
            expected=result.expected_result_hash, actual=result.actual_result_hash,
        )  # fmt: skip
    await append_audit(
        session, actor_type="AGENT", actor_id=GUARDIAN, action="recovery.verified",
        entity_type="recovery_execution", entity_id=str(execution.id),
        details={"outcome": result.outcome, "matches_expectation": result.matches_expectation,
                 "unresolved": [u.code for u in result.unresolved]},
    )  # fmt: skip
    await session.commit()
    return await get_execution(session, execution.id)


# ------------------------------------------------------------------ queries
def _verification_out(v: RecoveryVerification) -> VerificationOut:
    return VerificationOut(
        id=v.id, execution_id=v.execution_id, verified_by=v.verified_by, created_at=v.created_at,
        result=VerificationResult.model_validate(v.result),
    )  # fmt: skip


async def get_execution(session: AsyncSession, execution_id: uuid.UUID) -> RecoveryExecutionOut:
    e = await session.get(RecoveryExecution, execution_id)
    if e is None:
        raise NotFoundError(f"Execution {execution_id} does not exist.")
    v = await session.scalar(
        select(RecoveryVerification).where(RecoveryVerification.execution_id == e.id)
    )
    return RecoveryExecutionOut(
        id=e.id, strategy_id=e.strategy_id, incident_id=e.incident_id,
        simulation_run_id=e.simulation_run_id, approval_id=e.approval_id,
        requested_by=e.requested_by, status=e.status,
        revalidation=ValidationReport.model_validate(e.revalidation), error=e.error,
        started_at=e.started_at, completed_at=e.completed_at,
        verification=_verification_out(v) if v else None,
    )  # fmt: skip


async def get_verification(session: AsyncSession, execution_id: uuid.UUID) -> VerificationOut:
    v = await session.scalar(
        select(RecoveryVerification).where(RecoveryVerification.execution_id == execution_id)
    )
    if v is None:
        raise NotFoundError(f"No verification exists for execution {execution_id}.")
    return _verification_out(v)


# ------------------------------------------------------------------ incidents
async def close_incident(
    session: AsyncSession, incident_id: uuid.UUID, principal: Principal, reason: str
) -> None:
    incident = await session.scalar(
        select(Incident).where(Incident.id == incident_id).with_for_update()
    )
    if incident is None:
        raise NotFoundError(f"Incident {incident_id} does not exist.")
    if incident.status not in CLOSABLE:
        raise InvalidTransitionError(f"Incident is {incident.status}; it cannot be closed now.")
    before = incident.status
    incident.status = IncidentStatus.CLOSED.value
    await session.execute(
        update(RecoveryStrategy)
        .where(
            RecoveryStrategy.incident_id == incident_id,
            RecoveryStrategy.status.in_([s.value for s in SUPERSEDABLE]),
        )
        .values(status="SUPERSEDED", recommended=False, version=RecoveryStrategy.version + 1)
    )
    await append_audit(
        session, actor_type="USER", actor_id=principal.username, action="incident.closed",
        entity_type="incident", entity_id=str(incident_id),
        before={"status": before}, after={"status": incident.status}, details={"reason": reason},
    )  # fmt: skip
    await session.commit()
