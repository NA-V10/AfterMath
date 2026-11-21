"""LangGraph orchestration of the incident-analysis workflow and its background runner.

    START -> SENTINEL -(confident)-> CARTOGRAPHER -> ORACLE -> STRATEGIST -> GUARDIAN -> END
                     \\-(unsure)-> clarify (interrupt: human) -> SENTINEL

A completed run leaves the incident AWAITING_APPROVAL when GUARDIAN validated at least one
strategy; approval and execution are human actions (Phase 5). Runs survive restarts: state
is checkpointed in PostgreSQL after every node.
"""

from __future__ import annotations

import asyncio
import functools
import uuid
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, RetryPolicy

from app.agents.nodes import Deps, cartographer, clarify, oracle, route_after_sentinel, sentinel
from app.agents.planning_nodes import guardian, strategist
from app.core.logging import get_logger
from app.database.checkpointer import AsyncpgCheckpointSaver
from app.database.models import WorkflowRun
from app.services import workflows as wf
from app.services.audit import append_audit

log = get_logger(__name__)
WORKFLOW_TIMEOUT_S = 300
TRANSIENT = RetryPolicy(max_attempts=2, retry_on=(ConnectionError, TimeoutError))


class WorkflowState(TypedDict, total=False):
    incident_id: str
    assessment: dict[str, Any]
    clarification: dict[str, Any] | None
    dependency_analysis: dict[str, Any]
    simulation_summary: dict[str, Any]
    strategy_proposal: dict[str, Any]
    governance_report: dict[str, Any]


def build_graph(deps: Deps, checkpointer: AsyncpgCheckpointSaver) -> Any:
    # Nodes take the state as a plain dict (WorkflowState is a TypedDict over the same keys).
    g: Any = StateGraph(WorkflowState)
    g.add_node("sentinel", functools.partial(sentinel, deps=deps), retry_policy=TRANSIENT)
    g.add_node("clarify", clarify)
    g.add_node("cartographer", functools.partial(cartographer, deps=deps), retry_policy=TRANSIENT)
    g.add_node("oracle", functools.partial(oracle, deps=deps), retry_policy=TRANSIENT)
    g.add_edge(START, "sentinel")
    g.add_conditional_edges("sentinel", route_after_sentinel, ["clarify", "cartographer"])
    g.add_edge("clarify", "sentinel")
    g.add_edge("cartographer", "oracle")
    g.add_node("strategist", functools.partial(strategist, deps=deps), retry_policy=TRANSIENT)
    g.add_node("guardian", functools.partial(guardian, deps=deps), retry_policy=TRANSIENT)
    g.add_edge("oracle", "strategist")
    g.add_edge("strategist", "guardian")
    g.add_edge("guardian", END)
    return g.compile(checkpointer=checkpointer)


class WorkflowRunner:
    def __init__(self, deps: Deps) -> None:
        self.deps = deps
        self.graph = build_graph(deps, AsyncpgCheckpointSaver(deps.db.engine))
        self._tasks: set[asyncio.Task[None]] = set()

    def topic(self, run_id: uuid.UUID) -> str:
        return f"workflow:{run_id}"

    async def start(self, incident_id: uuid.UUID, *, actor_id: str) -> WorkflowRun:
        async with self.deps.db.sessionmaker() as s:
            run = await wf.create_run(
                s, incident_id, llm_mode=self.deps.llm.mode,
                llm_provider=self.deps.llm.description, actor_id=actor_id,
            )  # fmt: skip
        self._spawn(run.id, {"incident_id": str(incident_id)})
        return run

    async def clarify(self, run_id: uuid.UUID, answer: dict[str, Any], *, actor_id: str) -> None:
        async with self.deps.db.sessionmaker() as s:
            await wf.update_run(
                s, run_id, status="RUNNING", current_node="SENTINEL", pending_question=None
            )
            await append_audit(
                s, actor_type="USER", actor_id=actor_id, action="workflow.clarified",
                entity_type="workflow_run", entity_id=str(run_id), workflow_run_id=run_id,
                details=answer,
            )  # fmt: skip
            await s.commit()
        self._spawn(run_id, Command(resume=answer))

    async def resume_incomplete(self) -> int:
        """After a restart, continue every RUNNING workflow from its last checkpoint."""
        async with self.deps.db.sessionmaker() as s:
            runs = await wf.runs_with_status(s, "RUNNING")
        for run in runs:
            log.info("workflow_resumed", run_id=str(run.id))
            self._spawn(run.id, None)
        return len(runs)

    def _spawn(self, run_id: uuid.UUID, payload: Any) -> None:
        task = asyncio.create_task(self._execute(run_id, payload), name=f"workflow-{run_id}")
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _execute(self, run_id: uuid.UUID, payload: Any) -> None:
        config = {"configurable": {"thread_id": str(run_id)}}
        self.deps.bus.publish(self.topic(run_id))
        try:
            async with asyncio.timeout(WORKFLOW_TIMEOUT_S):
                await self.graph.ainvoke(payload, config)
            snapshot = await self.graph.aget_state(config)
            async with self.deps.db.sessionmaker() as s:
                if snapshot.next:
                    question: dict[str, Any] = next(
                        (i.value for t in snapshot.tasks for i in t.interrupts), {}
                    )
                    await wf.update_run(
                        s, run_id, status="AWAITING_CLARIFICATION", current_node="CLARIFICATION",
                        pending_question=question,
                    )  # fmt: skip
                else:
                    values = snapshot.values
                    governance = values.get("governance_report") or {}
                    # Human approval (Phase 5) is required before anything executes.
                    next_status = "AWAITING_APPROVAL" if governance.get("any_valid") else "ANALYZED"
                    await wf.finish_run(
                        s, run_id, status="COMPLETED", incident_status=next_status,
                        result={
                            "assessment": values.get("assessment"),
                            "dependency_analysis": values.get("dependency_analysis"),
                            "simulation_summary": values.get("simulation_summary"),
                            "strategy_proposal": values.get("strategy_proposal"),
                            "governance_report": governance or None,
                        },
                    )  # fmt: skip
        except Exception as exc:  # recorded, never silently discarded
            log.error("workflow_failed", run_id=str(run_id), exc_info=exc)
            async with self.deps.db.sessionmaker() as s:
                await wf.finish_run(
                    s, run_id, status="FAILED", incident_status="ANALYSIS_FAILED",
                    error={"type": type(exc).__name__, "message": str(exc)[:500]},
                )  # fmt: skip
        finally:
            self.deps.bus.publish(self.topic(run_id))

    async def wait_idle(self) -> None:
        """Test helper: wait for all in-flight workflows (callers bound it with a timeout)."""
        while self._tasks:
            await asyncio.gather(*list(self._tasks), return_exceptions=True)

    async def shutdown(self) -> None:
        for task in list(self._tasks):
            task.cancel()  # runs stay RUNNING and resume from their checkpoint next start
        await asyncio.gather(*self._tasks, return_exceptions=True)
