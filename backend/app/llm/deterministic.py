"""Deterministic provider: each task is served by a registered rule-based function of `context`.

This is the default mode (no API key) and the fallback for every LLM failure, so the platform
never becomes unusable because a provider is down.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from pydantic import BaseModel

from app.llm.base import LLMConfigurationError, LLMRequest, ProviderResponse, TokenUsage

Handler = Callable[[dict[str, Any]], BaseModel]
_HANDLERS: dict[str, Handler] = {}


def deterministic_task(name: str) -> Callable[[Handler], Handler]:
    def register(fn: Handler) -> Handler:
        if name in _HANDLERS:
            raise ValueError(f"deterministic handler already registered for {name!r}")
        _HANDLERS[name] = fn
        return fn

    return register


class DeterministicProvider:
    name = "deterministic"
    model = "rules-v1"

    async def generate[T: BaseModel](
        self, request: LLMRequest[T], *, timeout_s: float, repair_hint: str | None = None
    ) -> ProviderResponse[T]:
        handler = _HANDLERS.get(request.task)
        if handler is None:
            raise LLMConfigurationError(
                f"no deterministic implementation for task {request.task!r}"
            )
        value = handler(request.context)
        return ProviderResponse(
            value=request.schema.model_validate(value.model_dump()),
            model=self.model,
            usage=TokenUsage(),
        )
