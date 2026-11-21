"""Provider-neutral LLM contract (docs/AGENT_DESIGN.md §4, ADR-0005).

Every call asks for a *structured* result validated against a Pydantic schema. A `task` names the
job so the deterministic provider can serve it from rules, and `context` carries the facts the
deterministic implementation needs (LLM providers receive the rendered prompts instead).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from pydantic import BaseModel


class LLMError(Exception):
    """Base class. `retryable` tells the fallback chain whether another attempt can help."""

    retryable = False


class LLMTimeoutError(LLMError):
    retryable = True


class LLMUnavailableError(LLMError):
    """Rate limit, 5xx, connection failure."""

    retryable = True


class LLMRefusalError(LLMError):
    """The model declined (e.g. safety classifier)."""


class LLMInvalidOutputError(LLMError):
    """The response did not validate against the requested schema."""


class LLMConfigurationError(LLMError):
    """Bad credentials, unknown model, malformed request: never retried."""


@dataclass(frozen=True, slots=True)
class LLMRequest[T: BaseModel]:
    task: str
    schema: type[T]
    system: str
    user: str
    context: dict[str, Any] = field(default_factory=dict)
    max_tokens: int = 4000


@dataclass(frozen=True, slots=True)
class TokenUsage:
    input_tokens: int | None = None
    output_tokens: int | None = None


@dataclass(frozen=True, slots=True)
class ProviderResponse[T: BaseModel]:
    value: T
    model: str
    usage: TokenUsage


@dataclass(frozen=True, slots=True)
class AttemptRecord:
    provider: str
    outcome: str  # "ok" | error class name
    detail: str
    latency_ms: float


@dataclass(frozen=True, slots=True)
class LLMResult[T: BaseModel]:
    value: T
    provider: str
    model: str
    usage: TokenUsage
    latency_ms: float
    attempts: tuple[AttemptRecord, ...]
    fell_back: bool  # True when the deterministic provider produced the value after a failure


class LLMProvider(Protocol):
    name: str
    model: str

    async def generate[T: BaseModel](
        self, request: LLMRequest[T], *, timeout_s: float, repair_hint: str | None = None
    ) -> ProviderResponse[T]: ...
