"""The agents as LangGraph nodes. Each node: deterministic tools -> (optional) LLM step ->
validated output -> recorded execution. See docs/AGENT_DESIGN.md §3."""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from typing import Any

from langchain_core.runnables import RunnableConfig
from langgraph.types import interrupt

from app.agents.assessment import apply_clarification, assess_report
from app.agents.explain import (
    CARTOGRAPHER_SYSTEM,
    ORACLE_SYSTEM,
    explain,
    extract,
)
from app.agents.recorder import Recorder
from app.agents.schemas import (
    AssetMatch,
    BackupDeadline,
    Briefing,
    DependencyAnalysis,
    DownstreamAsset,
    FailureChain,
    Grounding,
    IncidentAssessment,
    Narrative,
    RedundancyEffect,
    SimulationSummary,
    SinglePointOfFailure,
)
from app.core.events import EventBus
from app.database.session import Database
from app.graph.model import AssetCategory, PhysicalCondition, TwinSnapshot
from app.llm.chain import LLMClient
from app.schemas.simulation import SimulationDetail, SimulationRequest
from app.services import analysis_cache
from app.services import incidents as incident_service
from app.services import simulations as simulation_service
from app.services import workflows as wf
from app.services.scenarios import EVENTS_ADAPTER
from app.services.twin_store import LoadedTwin, TwinStore
from app.simulation.engine import flooded_assets
from app.simulation.evaluator import DependencyIndex
from app.simulation.model import AreaFloodEvent, AssetFailureEvent, EventKind, FunctionalStatus

CRITICAL_THRESHOLD = 80


@dataclass(frozen=True)
class Deps:
    db: Database
    twin_store: TwinStore
    llm: LLMClient
    bus: EventBus


def run_id_of(config: RunnableConfig) -> uuid.UUID:
    return uuid.UUID(config["configurable"]["thread_id"])


async def _twin(deps: Deps) -> LoadedTwin:
    async with deps.db.sessionmaker() as s:
        return await deps.twin_store.current(s)


# ------------------------------------------------------------------ SENTINEL
def structured_assessment(incident: Any, snapshot: TwinSnapshot) -> IncidentAssessment:
    """Structured incidents were validated at intake; SENTINEL only normalises them."""
    events = EVENTS_ADAPTER.validate_python(incident.initiating_events)
    matches: list[AssetMatch] = []
    for e in events:
        if isinstance(e, AssetFailureEvent):
            codes, condition = [e.asset_code], e.condition.value
        elif isinstance(e, AreaFloodEvent):
            codes, condition = flooded_assets(snapshot, e), PhysicalCondition.DAMAGED.value
        else:
            continue
        for code in codes:
            matches.append(
                AssetMatch(
                    code=code, name=snapshot.asset(code).name, quote="(structured payload)",
                    method="code", score=1.0, role="damaged", condition=condition,
                )
            )  # fmt: skip
    return IncidentAssessment(
        source="STRUCTURED",
        incident_type=incident.incident_type,
        severity=incident.severity,
        affected_assets=matches,
        initiating_events=events,
        confidence=1.0,
        evidence=[],
        missing_information=[],
        reported_consequences=[],
        needs_clarification=False,
        extraction_provider="structured",
    )


async def sentinel(state: dict[str, Any], config: RunnableConfig, *, deps: Deps) -> dict[str, Any]:
    run_id = run_id_of(config)
    rec = Recorder(deps.db, deps.bus, run_id)
    started = time.perf_counter()
    twin = await _twin(deps)
    async with deps.db.sessionmaker() as s:
        incident = await incident_service.get_incident_row(s, uuid.UUID(state["incident_id"]))
    clarification = state.get("clarification")
    async with rec.execution(
        "SENTINEL",
        {"incident": incident.reference, "source": incident.source, "clarification": clarification},
    ) as ctx:
        if clarification and state.get("assessment"):
            previous = IncidentAssessment.model_validate(state["assessment"])
            assessment = await ctx.tool(
                "apply_operator_clarification", clarification,
                lambda: _async(apply_clarification(previous, twin.snapshot, **clarification)),
            )  # fmt: skip
        elif incident.source == "STRUCTURED":
            assessment = await ctx.tool(
                "normalise_structured_incident", {"reference": incident.reference},
                lambda: _async(structured_assessment(incident, twin.snapshot)),
            )  # fmt: skip
        else:
            report = incident.raw_report or ""
            extraction, provider = await extract(
                deps.llm, ctx, report=report, snapshot=twin.snapshot
            )
            assessment = await ctx.tool(
                "resolve_and_validate", {"mentions": len(extraction.asset_mentions)},
                lambda: _async(assess_report(report, extraction, twin.snapshot, provider=provider)),
            )  # fmt: skip
        if not assessment.needs_clarification:
            async with deps.db.sessionmaker() as s:
                await wf.save_assessment(
                    s, incident.id, assessment.model_dump(mode="json"),
                    run_id=run_id, execution_id=ctx.execution_id,
                )  # fmt: skip
        damaged = [m.code for m in assessment.affected_assets if m.role == "damaged"]
        summary = (
            f"{assessment.incident_type} ({assessment.severity}); damaged: "
            f"{', '.join(damaged) or 'none identified'}; confidence {assessment.confidence:.2f}"
            + ("; operator clarification required" if assessment.needs_clarification else "")
        )
        await rec.complete(ctx, output=assessment, summary=summary, started=started)
    return {"assessment": assessment.model_dump(mode="json"), "clarification": None}


async def _async[T](value: T) -> T:
    return value


def route_after_sentinel(state: dict[str, Any]) -> str:
    return "clarify" if state["assessment"]["needs_clarification"] else "cartographer"


def clarify(state: dict[str, Any]) -> dict[str, Any]:
    """Human-in-the-loop: pause until an operator confirms the damaged assets."""
    a = state["assessment"]
    answer = interrupt(
        {
            "message": "SENTINEL could not identify the damaged assets with enough confidence. "
            "Confirm which facilities are damaged.",
            "missing_information": a["missing_information"],
            "candidates": [
                {"code": m["code"], "name": m["name"], "quote": m["quote"], "score": m["score"]}
                for m in a["affected_assets"]
            ],
            "incident_type": a["incident_type"],
            "severity": a["severity"],
        }
    )
    return {"clarification": answer}


# ------------------------------------------------------------------ CARTOGRAPHER
def dependency_facts(twin: LoadedTwin, focus: list[str], criticality: list[Any]) -> dict[str, Any]:
    depth: dict[str, int] = {}
    for code in focus:
        for hit in twin.graph.downstream(code):
            if hit.code not in focus:
                depth[hit.code] = min(depth.get(hit.code, hit.depth), hit.depth)
    spofs = [
        SinglePointOfFailure(code=e.code, critical_failed=list(e.critical_failed))
        for e in criticality
        if e.code in focus and e.single_point_of_failure
    ]
    effects: list[RedundancyEffect] = []
    index = DependencyIndex(twin.snapshot)
    for dependent, groups in sorted(index.groups.items()):
        if dependent in focus:
            continue
        for g in groups:
            lost = [p for p in g.providers if p in focus]
            if not lost:
                continue
            remaining = len(g.providers) - len(lost)
            effects.append(
                RedundancyEffect(
                    dependent=dependent, group=g.name, service_type=g.service_type.value,
                    providers_lost=lost, providers_remaining=remaining, required=g.k,
                    effect="REQUIREMENT_LOST" if remaining < g.k else "REDUNDANCY_REDUCED",
                )
            )  # fmt: skip
    return {
        "focus_assets": focus,
        "downstream": [
            DownstreamAsset(code=c, depth=d).model_dump()
            for c, d in sorted(depth.items(), key=lambda x: (x[1], x[0]))
        ],
        "single_points_of_failure": [s.model_dump() for s in spofs],
        "redundancy_effects": [e.model_dump() for e in effects],
    }


async def cartographer(
    state: dict[str, Any], config: RunnableConfig, *, deps: Deps
) -> dict[str, Any]:
    rec = Recorder(deps.db, deps.bus, run_id_of(config))
    started = time.perf_counter()
    twin = await _twin(deps)
    assessment = IncidentAssessment.model_validate(state["assessment"])
    focus = sorted({m.code for m in assessment.affected_assets if m.role == "damaged"})
    async with rec.execution("CARTOGRAPHER", {"focus_assets": focus}) as ctx:
        criticality = await ctx.tool(
            "structural_criticality", {}, lambda: analysis_cache.criticality(twin.snapshot)
        )
        facts = await ctx.tool(
            "dependency_analysis", {"focus": focus},
            lambda: _async(dependency_facts(twin, focus, criticality)),
        )  # fmt: skip
        allowed = set(focus) | {d["code"] for d in facts["downstream"]}
        for s in facts["single_points_of_failure"]:
            allowed |= {s["code"], *s["critical_failed"]}
        for r in facts["redundancy_effects"]:
            allowed |= {r["dependent"], *r["providers_lost"]}
        text, source, grounding = await explain(
            deps.llm, ctx, task="cartographer.briefing", schema=Briefing,
            system=CARTOGRAPHER_SYSTEM, facts=facts, allowed_codes=allowed,
            allowed_numbers=[len(facts["downstream"])],
        )  # fmt: skip
        analysis = DependencyAnalysis(
            **facts, briefing=text, briefing_source=source, grounding=grounding
        )
        summary = (
            f"{len(analysis.downstream)} downstream assets; "
            f"{len(analysis.single_points_of_failure)} single point(s) of failure; "
            f"{sum(r.effect == 'REQUIREMENT_LOST' for r in analysis.redundancy_effects)} "
            "requirements lost"
        )
        await rec.complete(
            ctx, output=analysis, summary=summary,
            grounding=grounding.model_dump(), started=started,
        )  # fmt: skip
    return {"dependency_analysis": analysis.model_dump(mode="json")}


# ------------------------------------------------------------------ ORACLE
def simulation_facts(
    detail: SimulationDetail, events: list[Any], snapshot: TwinSnapshot
) -> dict[str, Any]:
    state = {s.code: s for s in detail.final_state}
    chains: list[FailureChain] = []
    for a in snapshot.assets:
        s = state[a.code]
        if (
            a.category is AssetCategory.DEMAND_ZONE
            or a.criticality < CRITICAL_THRESHOLD
            or s.status is FunctionalStatus.OPERATIONAL
        ):
            continue
        path = [a.code]
        cur = a.code
        for _ in range(10):
            causes = [c for c in state[cur].causes if c.providers]
            nxt = next((p for c in causes for p in c.providers if p not in path), None)
            if nxt is None:
                break
            path.append(nxt)
            cur = nxt
        chains.append(FailureChain(asset=a.code, status=s.status.value, chain=path))
    chains.sort(key=lambda c: (-snapshot.asset(c.asset).criticality, c.asset))

    exhausted = {e.asset_code for e in events if e.kind is EventKind.BACKUP_EXHAUSTED}
    deadlines = [
        BackupDeadline(
            asset=e.asset_code,
            exhausts_at_minutes=int(e.details["exhausts_at"]),
            exhausted_within_horizon=e.asset_code in exhausted,
        )
        for e in events
        if e.kind is EventKind.BACKUP_ENGAGED and e.asset_code
    ]
    m = detail.final_metrics
    assert m is not None
    assert detail.peak_metrics is not None
    assert detail.result_hash
    return {
        "simulation_id": str(detail.id),
        "result_hash": detail.result_hash,
        "horizon_minutes": detail.horizon_minutes,
        "impact_score": m.impact_score,
        "peak_impact_score": detail.peak_metrics.impact_score,
        "failed": m.status_counts[FunctionalStatus.FAILED],
        "on_backup": m.status_counts[FunctionalStatus.ON_BACKUP],
        "degraded": m.status_counts[FunctionalStatus.DEGRADED],
        "affected_population": m.affected_population,
        "key_chains": [c.model_dump() for c in chains],
        "deadlines": [
            d.model_dump()
            for d in sorted(deadlines, key=lambda d: (d.exhausts_at_minutes, d.asset))
        ],
    }


async def oracle(state: dict[str, Any], config: RunnableConfig, *, deps: Deps) -> dict[str, Any]:
    run_id = run_id_of(config)
    rec = Recorder(deps.db, deps.bus, run_id)
    started = time.perf_counter()
    twin = await _twin(deps)
    incident_id = uuid.UUID(state["incident_id"])
    async with rec.execution("ORACLE", {"incident_id": str(incident_id)}) as ctx:

        async def run() -> SimulationDetail:
            async with deps.db.sessionmaker() as s:
                incident = await incident_service.get_incident_row(s, incident_id)
                return await simulation_service.run_simulation(
                    s, twin,
                    SimulationRequest(
                        incident_id=incident_id, label=f"{incident.reference} · ORACLE",
                        apply_to_picture=True,
                    ),
                    actor_id="agent:ORACLE",
                )  # fmt: skip

        detail = await ctx.tool("run_simulation", {"incident_id": str(incident_id)}, run)

        async def load_events() -> list[Any]:
            async with deps.db.sessionmaker() as s:
                return await simulation_service.run_events(s, detail.id, None, None)

        events = await ctx.tool("simulation_events", {"simulation_id": str(detail.id)}, load_events)
        facts = simulation_facts(detail, events, twin.snapshot)
        allowed = {c for chain in facts["key_chains"] for c in chain["chain"]}
        allowed |= {d["asset"] for d in facts["deadlines"]}
        numbers: list[float | int] = [
            facts["impact_score"], facts["peak_impact_score"], facts["affected_population"],
            facts["failed"], facts["on_backup"], facts["degraded"], facts["horizon_minutes"],
            *(d["exhausts_at_minutes"] for d in facts["deadlines"]),
        ]  # fmt: skip
        text, source, grounding = await explain(
            deps.llm, ctx, task="oracle.narrative", schema=Narrative, system=ORACLE_SYSTEM,
            facts=facts, allowed_codes=allowed, allowed_numbers=numbers,
        )  # fmt: skip
        summary_out = SimulationSummary(
            **facts, narrative=text, narrative_source=source, grounding=grounding
        )
        await rec.complete(
            ctx, output=summary_out,
            summary=f"impact {facts['impact_score']:.2f}; {facts['failed']} failed; "
            f"{facts['affected_population']:,} people affected; result {facts['result_hash'][:12]}",
            grounding=grounding.model_dump(), started=started,
        )  # fmt: skip
    return {"simulation_summary": summary_out.model_dump(mode="json")}


__all__ = [
    "Deps",
    "Grounding",
    "cartographer",
    "clarify",
    "oracle",
    "route_after_sentinel",
    "sentinel",
]
