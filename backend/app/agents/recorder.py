"""Records every agent step (execution row, tool calls, LLM attempts) and publishes progress.

Failures are recorded and re-raised, never swallowed (docs/AGENT_DESIGN.md §2).
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import time
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel

from app.core.events import EventBus
from app.database.session import Database
from app.llm.base import LLMResult
from app.services import workflows as wf


def _digest(value: Any) -> str:
    text = json.dumps(value, sort_keys=True, default=str)
    return hashlib.sha256(text.encode()).hexdigest()[:16]


@dataclass
class ExecutionContext:
    execution_id: uuid.UUID
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    llm_calls: list[dict[str, Any]] = field(default_factory=list)
    tokens_in: int = 0
    tokens_out: int = 0
    fell_back: bool = False

    async def tool[R](self, name: str, args: dict[str, Any], fn: Callable[[], Awaitable[R]]) -> R:
        """Run a deterministic tool and record name, args, timing and a result digest."""
        t0 = time.perf_counter()
        try:
            result = await fn()
        except Exception as exc:
            self.tool_calls.append(
                {
                    "name": name,
                    "args": args,
                    "ok": False,
                    "error": f"{type(exc).__name__}: {exc}"[:300],
                    "ms": round((time.perf_counter() - t0) * 1000, 2),
                }
            )
            raise
        payload = result.model_dump(mode="json") if isinstance(result, BaseModel) else result
        self.tool_calls.append(
            {"name": name, "args": args, "ok": True, "result_digest": _digest(payload),
             "ms": round((time.perf_counter() - t0) * 1000, 2)}
        )  # fmt: skip
        return result

    def llm(self, task: str, result: LLMResult[Any]) -> None:
        self.llm_calls.append(
            {
                "task": task,
                "provider": result.provider,
                "model": result.model,
                "fell_back": result.fell_back,
                "latency_ms": result.latency_ms,
                "attempts": [dataclasses.asdict(a) for a in result.attempts],
            }
        )
        self.tokens_in += result.usage.input_tokens or 0
        self.tokens_out += result.usage.output_tokens or 0
        self.fell_back |= result.fell_back

    def note_fallback(self, task: str, reason: str) -> None:
        self.fell_back = True
        self.llm_calls.append({"task": task, "provider": "deterministic", "reason": reason})


class Recorder:
    def __init__(self, db: Database, bus: EventBus, run_id: uuid.UUID) -> None:
        self.db, self.bus, self.run_id = db, bus, run_id

    def topic(self) -> str:
        return f"workflow:{self.run_id}"

    @asynccontextmanager
    async def execution(
        self, agent: str, input_summary: dict[str, Any]
    ) -> AsyncIterator[ExecutionContext]:
        async with self.db.sessionmaker() as s:
            row = await wf.start_execution(s, self.run_id, agent, input_summary)
        self.bus.publish(self.topic())
        ctx = ExecutionContext(row.id)
        started = time.perf_counter()
        try:
            yield ctx
        except BaseException as exc:
            async with self.db.sessionmaker() as s:
                await wf.finish_execution(
                    s, row.id, status="FAILED",
                    error={"type": type(exc).__name__, "message": str(exc)[:500]},
                    tool_calls=ctx.tool_calls, llm_calls=ctx.llm_calls,
                    latency_ms=round((time.perf_counter() - started) * 1000, 2),
                )  # fmt: skip
            self.bus.publish(self.topic())
            raise
        self.bus.publish(self.topic())

    async def complete(
        self,
        ctx: ExecutionContext,
        *,
        output: BaseModel,
        summary: str,
        grounding: dict[str, Any] | None = None,
        started: float | None = None,
    ) -> None:
        async with self.db.sessionmaker() as s:
            await wf.finish_execution(
                s, ctx.execution_id,
                status="FELL_BACK" if ctx.fell_back else "SUCCEEDED",
                output=output.model_dump(mode="json"), summary=summary,
                tool_calls=ctx.tool_calls, llm_calls=ctx.llm_calls, grounding=grounding,
                tokens_in=ctx.tokens_in or None, tokens_out=ctx.tokens_out or None,
                latency_ms=round((time.perf_counter() - started) * 1000, 2) if started else None,
            )  # fmt: skip
        self.bus.publish(self.topic())
