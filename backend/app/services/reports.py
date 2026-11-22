"""Incident recovery report (PRD VF-3): JSON, or Markdown rendered from the same data.

Every figure comes from stored records (simulation runs, strategies, decisions, verification);
nothing is recomputed or summarised by an LLM. Header and footer carry the simulation notice.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFoundError
from app.database.models import (
    ApprovalRecord,
    AuditLog,
    Incident,
    RecoveryAction,
    RecoveryExecution,
    RecoveryStrategy,
    RecoveryVerification,
    SimulationRun,
)

NOTICE = "SIMULATION ENVIRONMENT — NOT CONNECTED TO LIVE INFRASTRUCTURE. All data is synthetic."


class ReportStrategy(BaseModel):
    id: uuid.UUID
    planning_round: int
    policy: str
    status: str
    recommended: bool
    impact_hours: float
    risk_score: float
    actions: int
    content_hash: str


class ReportDecision(BaseModel):
    strategy_id: uuid.UUID
    decision: str
    actor_id: str
    actor_role: str
    comment: str | None
    content_hash: str
    created_at: datetime


class ReportAudit(BaseModel):
    occurred_at: datetime
    actor: str
    action: str
    entity: str


class IncidentReport(BaseModel):
    notice: str = NOTICE
    generated_at: datetime
    incident: dict[str, Any]
    impact: dict[str, Any] | None
    strategies: list[ReportStrategy]
    decisions: list[ReportDecision]
    execution: dict[str, Any] | None
    verification: dict[str, Any] | None
    audit_trail: list[ReportAudit]
    synthetic: Literal[True] = True


def _md_escape(text: object) -> str:
    """Neutralise Markdown/HTML control characters in stored free text."""
    s = str(text if text is not None else "—")
    for ch in "\\`*_{}[]<>#|":
        s = s.replace(ch, "\\" + ch)
    return s.replace("\n", " ")


def render_markdown(r: IncidentReport) -> str:
    inc = r.incident
    e = _md_escape
    events = (
        ", ".join(
            e(f"{ev.get('asset_code')} {ev.get('condition', ev.get('kind'))}")
            for ev in inc["initiating_events"]
        )
        or "—"
    )
    lines = [
        f"> **{NOTICE}**",
        "",
        f"# Recovery report — {e(inc['reference'])}",
        "",
        f"Generated {r.generated_at:%Y-%m-%d %H:%M} UTC.",
        "",
        "## Incident",
        "",
        "| Field | Value |",
        "|---|---|",
        f"| Title | {e(inc['title'])} |",
        f"| Type / severity | {e(inc['type'])} / {e(inc['severity'])} |",
        f"| Status | {e(inc['status'])} |",
        f"| Reported | {e(inc['reported_at'][:16].replace('T', ' '))} UTC |",
        f"| Initiating events | {events} |",
        "",
    ]
    if r.impact:
        lines += [
            "## Impact (no recovery)",
            "",
            f"- Impact score: **{r.impact['impact_score']}**",
            f"- Affected population: {r.impact['affected_population']}",
            f"- Simulation result hash: `{(r.impact['result_hash'] or '')[:16]}…`",
            "",
        ]
    if r.strategies:
        lines += [
            "## Strategies",
            "",
            "| Round | Policy | Status | Impact-hours | Risk | Actions | Recommended |",
            "|---|---|---|---|---|---|---|",
            *(
                f"| {s.planning_round} | {s.policy} | {s.status} | {s.impact_hours:.1f} | "
                f"{s.risk_score:.1f} | {s.actions} | {'yes' if s.recommended else ''} |"
                for s in r.strategies
            ),
            "",
        ]
    if r.decisions:
        lines += ["## Decisions", ""]
        for d in r.decisions:
            lines.append(
                f"- {d.created_at:%Y-%m-%d %H:%M} — **{d.decision}** by {e(d.actor_id)} "
                f"({d.actor_role}), hash `{d.content_hash[:12]}…`: {e(d.comment)}"
            )
        lines.append("")
    if r.execution:
        x = r.execution
        revalidation = "passed" if x["revalidation_passed"] else "failed"
        lines += [
            "## Simulated execution",
            "",
            f"- Status: **{x['status']}** (requested by {e(x['requested_by'])})",
            f"- Revalidation at execution time: {revalidation}",
            "",
        ]
    if r.verification:
        v = r.verification
        lines += [
            "## Verification (GUARDIAN)",
            "",
            f"- Outcome: **{v['outcome'].replace('_', ' ').lower()}**; "
            f"matches the plan's expectation: **{'yes' if v['matches_expectation'] else 'NO'}**",
            f"- Operational assets: {v['before']['by_count']}% without recovery → "
            f"{v['after']['by_count']}% after (criticality-weighted "
            f"{v['before']['by_criticality']}% → {v['after']['by_criticality']}%; population "
            f"{v['before']['by_population']}% → {v['after']['by_population']}%)",
            f"- Repaired: {', '.join(v['repaired_assets']) or '—'}",
            f"- Functionally restored: {', '.join(v['functionally_restored']) or '—'}",
        ]
        for u in v["repaired_not_functional"]:
            lines.append(f"- Repaired but not functional: {u['code']} — {e(u['reason'])}")
        if v["unresolved"]:
            lines += ["", "| Unresolved asset | Status | Reason |", "|---|---|---|"]
            lines += [
                f"| {u['code']} | {u['status']} | {e(u['reason'])} |" for u in v["unresolved"]
            ]
        lines.append("")
    lines += [
        "## Audit trail",
        "",
        "| Time (UTC) | Actor | Action | Entity |",
        "|---|---|---|---|",
        *(
            f"| {a.occurred_at:%Y-%m-%d %H:%M:%S} | {e(a.actor)} | {a.action} | {e(a.entity)} |"
            for a in r.audit_trail
        ),
        "",
        f"> **{NOTICE}**",
        "",
    ]
    return "\n".join(lines)


async def build_report(session: AsyncSession, incident_id: uuid.UUID) -> IncidentReport:
    inc = await session.get(Incident, incident_id)
    if inc is None:
        raise NotFoundError(f"Incident {incident_id} does not exist.")
    impact_run = await session.scalar(
        select(SimulationRun)
        .where(SimulationRun.incident_id == inc.id, SimulationRun.kind == "IMPACT",
               SimulationRun.status == "COMPLETED")
        .order_by(SimulationRun.created_at.desc()).limit(1)
    )  # fmt: skip
    strategies = list(
        (
            await session.scalars(
                select(RecoveryStrategy)
                .where(RecoveryStrategy.incident_id == inc.id)
                .order_by(RecoveryStrategy.planning_round, RecoveryStrategy.policy)
            )
        ).all()
    )
    ids = [s.id for s in strategies]
    count_rows = (
        await session.execute(
            select(RecoveryAction.strategy_id, func.count())
            .where(RecoveryAction.strategy_id.in_(ids))
            .group_by(RecoveryAction.strategy_id)
        )
    ).all()
    counts: dict[uuid.UUID, int] = {sid: n for sid, n in count_rows}
    decisions = list(
        (
            await session.scalars(
                select(ApprovalRecord)
                .where(ApprovalRecord.strategy_id.in_(ids))
                .order_by(ApprovalRecord.created_at)
            )
        ).all()
    ) if ids else []  # fmt: skip
    execution = await session.scalar(
        select(RecoveryExecution).where(RecoveryExecution.incident_id == inc.id)
    )
    verification = (
        await session.scalar(
            select(RecoveryVerification).where(RecoveryVerification.execution_id == execution.id)
        )
        if execution
        else None
    )
    entity_ids = [str(inc.id), *(str(i) for i in ids)] + ([str(execution.id)] if execution else [])
    audit = list(
        (
            await session.scalars(
                select(AuditLog)
                .where(AuditLog.entity_id.in_(entity_ids))
                .order_by(AuditLog.id)
                .limit(500)
            )
        ).all()
    )
    final = (impact_run.metrics or {}).get("final", {}) if impact_run else {}
    return IncidentReport(
        generated_at=datetime.now(UTC),
        incident={
            "id": str(inc.id), "reference": inc.reference, "title": inc.title,
            "type": inc.incident_type, "severity": inc.severity, "status": inc.status,
            "source": inc.source, "reported_at": inc.created_at.isoformat(),
            "initiating_events": inc.initiating_events or [],
        },
        impact=None if impact_run is None else {
            "simulation_id": str(impact_run.id), "result_hash": impact_run.result_hash,
            "impact_score": final.get("impact_score"),
            "affected_population": final.get("affected_population"),
            "status_counts": final.get("status_counts"),
        },
        strategies=[
            ReportStrategy(
                id=s.id, planning_round=s.planning_round, policy=s.policy, status=s.status,
                recommended=s.recommended, impact_hours=s.metrics["impact_hours"],
                risk_score=s.risk_score, actions=counts.get(s.id, 0),
                content_hash=s.content_hash,
            )
            for s in strategies
        ],
        decisions=[
            ReportDecision(
                strategy_id=d.strategy_id, decision=d.decision, actor_id=d.actor_id,
                actor_role=d.actor_role, comment=d.comment, content_hash=d.content_hash,
                created_at=d.created_at,
            )
            for d in decisions
        ],
        execution=None if execution is None else {
            "id": str(execution.id), "strategy_id": str(execution.strategy_id),
            "status": execution.status, "requested_by": execution.requested_by,
            "simulation_run_id": str(execution.simulation_run_id)
            if execution.simulation_run_id else None,
            "revalidation_passed": execution.revalidation.get("passed"),
            "completed_at": execution.completed_at.isoformat() if execution.completed_at else None,
        },
        verification=None if verification is None else verification.result,
        audit_trail=[
            ReportAudit(
                occurred_at=a.occurred_at, actor=f"{a.actor_type}:{a.actor_id}",
                action=a.action, entity=f"{a.entity_type}:{(a.entity_id or '')[:8]}",
            )
            for a in audit
        ],
    )  # fmt: skip
