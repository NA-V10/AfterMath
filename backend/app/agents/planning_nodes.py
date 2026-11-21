"""STRATEGIST and GUARDIAN as LangGraph nodes (Phase 4). docs/AGENT_DESIGN.md §3."""

from __future__ import annotations

import time
import uuid
from typing import Any

from langchain_core.runnables import RunnableConfig

from app.agents.explain import STRATEGIST_SYSTEM, explain
from app.agents.nodes import Deps, _twin, run_id_of
from app.agents.recorder import Recorder
from app.agents.schemas import (
    GovernanceReport,
    Grounding,
    Rationale,
    StrategyComparisonRow,
    StrategyProposal,
    StrategyVerdict,
)
from app.schemas.recovery import StrategyDetail
from app.services import recovery as recovery_service

RECOMMENDATION_RULE = (
    "Among strategies that passed every rule: lowest impact-hours, then lowest risk, then policy."
)


def _facts(
    st: StrategyDetail, others: list[StrategyDetail]
) -> tuple[dict[str, Any], set[str], list[float | int]]:
    facts = {
        "policy": st.policy,
        "objective": st.objective,
        "actions": [
            {
                "seq": a.seq,
                "type": a.action_type,
                "asset": a.target_asset_code,
                "start_minutes": a.start_minutes,
                "end_minutes": a.end_minutes,
            }
            for a in st.actions
        ],
        "impact_hours": st.impact_hours,
        "makespan_minutes": st.makespan_minutes,
        "time_to_critical_services_minutes": st.time_to_critical_services_minutes,
        "risk_score": st.risk_score,
        "total_cost": st.total_cost,
        "benefits": st.benefits,
        "limitations": st.limitations,
        "other_strategies": [
            {"policy": o.policy, "impact_hours": o.impact_hours, "risk_score": o.risk_score}
            for o in others
        ],
    }
    codes = {a.target_asset_code for a in st.actions} | set(st.metrics.unrestored_assets)
    codes |= set(st.metrics.backup_exhausted_before_restoration) | {
        u.asset_code for u in st.unschedulable
    }
    numbers: list[float | int] = [
        st.impact_hours,
        st.makespan_minutes,
        st.risk_score,
        st.total_cost,
        *(a.start_minutes for a in st.actions),
        *(a.end_minutes for a in st.actions),
        *(o.impact_hours for o in others),
        *(o.risk_score for o in others),
        *(o.total_cost for o in others),
    ]
    if st.time_to_critical_services_minutes is not None:
        numbers.append(st.time_to_critical_services_minutes)
    return facts, codes, numbers


async def strategist(
    state: dict[str, Any], config: RunnableConfig, *, deps: Deps
) -> dict[str, Any]:
    """Plans with the deterministic scheduler; the LLM only explains (grounding-checked)."""
    rec = Recorder(deps.db, deps.bus, run_id_of(config))
    started = time.perf_counter()
    twin = await _twin(deps)
    incident_id = uuid.UUID(state["incident_id"])
    async with rec.execution("STRATEGIST", {"incident_id": str(incident_id)}) as ctx:

        async def generate() -> list[uuid.UUID]:
            async with deps.db.sessionmaker() as s:
                return await recovery_service.generate_strategies(
                    s, twin, incident_id, actor_id="agent:STRATEGIST"
                )

        ids = await ctx.tool("generate_strategies", {"incident_id": str(incident_id)}, generate)

        async def load() -> list[StrategyDetail]:
            async with deps.db.sessionmaker() as s:
                return [await recovery_service.get_strategy(s, i) for i in ids]

        strategies = await ctx.tool(
            "compare_strategies", {"strategy_ids": [str(i) for i in ids]}, load
        )
        rationale: dict[str, str] = {}
        sources: dict[str, str] = {}
        groundings: dict[str, Grounding] = {}
        for st in strategies:
            facts, codes, numbers = _facts(st, [o for o in strategies if o.id != st.id])
            text, source, grounding = await explain(
                deps.llm,
                ctx,
                task="strategist.rationale",
                schema=Rationale,
                system=STRATEGIST_SYSTEM,
                facts=facts,
                allowed_codes=codes,
                allowed_numbers=numbers,
            )
            async with deps.db.sessionmaker() as s:
                await recovery_service.set_rationale(s, st.id, text, source)
            key = str(st.id)
            rationale[key], sources[key], groundings[key] = text, source, grounding
        proposal = StrategyProposal(
            planning_round=strategies[0].planning_round,
            comparison=[
                StrategyComparisonRow(
                    strategy_id=str(st.id),
                    policy=st.policy,
                    impact_hours=st.impact_hours,
                    time_to_critical_services_minutes=st.time_to_critical_services_minutes,
                    makespan_minutes=st.makespan_minutes,
                    total_cost=st.total_cost,
                    risk_score=st.risk_score,
                    actions=len(st.actions),
                )
                for st in strategies
            ],
            rationale=rationale,
            rationale_sources=sources,
            grounding=groundings,
        )
        best = min(proposal.comparison, key=lambda c: c.impact_hours)
        all_ok = all(g.ok for g in groundings.values())
        await rec.complete(
            ctx,
            output=proposal,
            summary=f"3 strategies (round {proposal.planning_round}); lowest impact: "
            f"{best.policy} ({best.impact_hours:.1f} impact-hours)",
            grounding={"checked": True, "ok": all_ok},
            started=started,
        )
    return {"strategy_proposal": proposal.model_dump(mode="json")}


async def guardian(state: dict[str, Any], config: RunnableConfig, *, deps: Deps) -> dict[str, Any]:
    """Deterministic governance: no LLM participates in any decision here."""
    rec = Recorder(deps.db, deps.bus, run_id_of(config))
    started = time.perf_counter()
    twin = await _twin(deps)
    proposal = state["strategy_proposal"]
    incident_id = uuid.UUID(state["incident_id"])
    ids = [c["strategy_id"] for c in proposal["comparison"]]
    async with rec.execution("GUARDIAN", {"strategies": ids}) as ctx:
        verdicts = []
        for row in proposal["comparison"]:
            sid = uuid.UUID(row["strategy_id"])

            async def check(sid: uuid.UUID = sid) -> Any:
                async with deps.db.sessionmaker() as s:
                    return await recovery_service.validate_strategy(
                        s, twin, sid, actor_id="agent:GUARDIAN"
                    )

            report = await ctx.tool("validate_strategy", {"strategy_id": str(sid)}, check)
            verdicts.append(
                StrategyVerdict(
                    strategy_id=str(sid),
                    policy=row["policy"],
                    status="VALIDATED" if report.passed else "VALIDATION_FAILED",
                    failed_rules=[r.rule for r in report.rules if not r.passed],
                )
            )

        async def pick() -> uuid.UUID | None:
            async with deps.db.sessionmaker() as s:
                return await recovery_service.recommend(s, incident_id, proposal["planning_round"])

        recommended = await ctx.tool("recommend_strategy", {"rule": RECOMMENDATION_RULE}, pick)
        report_out = GovernanceReport(
            verdicts=verdicts,
            recommended_strategy_id=str(recommended) if recommended else None,
            recommendation_rule=RECOMMENDATION_RULE,
            any_valid=any(v.status == "VALIDATED" for v in verdicts),
        )
        passed = sum(v.status == "VALIDATED" for v in verdicts)
        chosen = next(
            (v.policy for v in verdicts if v.strategy_id == report_out.recommended_strategy_id),
            None,
        )
        await rec.complete(
            ctx,
            output=report_out,
            summary=f"{passed}/{len(verdicts)} strategies passed V-001..V-009; "
            + (f"recommended {chosen}" if chosen else "no valid strategy"),
            started=started,
        )
    return {"governance_report": report_out.model_dump(mode="json")}
