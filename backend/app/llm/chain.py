"""Fallback chain: primary provider with bounded retries and one repair attempt, then the
deterministic provider. Every attempt is recorded; nothing fails silently."""

from __future__ import annotations

import time

from pydantic import BaseModel

from app.core.config import Settings
from app.core.logging import get_logger
from app.llm.base import (
    AttemptRecord,
    LLMError,
    LLMInvalidOutputError,
    LLMProvider,
    LLMRequest,
    LLMResult,
)
from app.llm.deterministic import DeterministicProvider

log = get_logger(__name__)

REPAIR_HINT = (
    "Your previous answer did not satisfy the required output schema ({detail}). "
    "Return only data that matches the schema exactly."
)


class LLMClient:
    def __init__(
        self, primary: LLMProvider | None, *, timeout_s: float = 30.0, max_attempts: int = 2
    ) -> None:
        self.primary = primary
        self.deterministic = DeterministicProvider()
        self.timeout_s = timeout_s
        self.max_attempts = max_attempts

    @property
    def mode(self) -> str:
        return "DETERMINISTIC" if self.primary is None else "LLM"

    @property
    def description(self) -> str:
        if self.primary is None:
            return "deterministic"
        return f"{self.primary.name}:{self.primary.model}"

    async def generate[T: BaseModel](self, request: LLMRequest[T]) -> LLMResult[T]:
        attempts: list[AttemptRecord] = []
        started = time.perf_counter()
        if self.primary is not None:
            hint: str | None = None
            repaired = False
            attempt = 0
            while attempt < self.max_attempts:
                attempt += 1
                t0 = time.perf_counter()
                try:
                    resp = await self.primary.generate(
                        request, timeout_s=self.timeout_s, repair_hint=hint
                    )
                except LLMInvalidOutputError as exc:
                    attempts.append(_record(self.primary.name, exc, t0))
                    if repaired:
                        break
                    repaired, hint = True, REPAIR_HINT.format(detail=str(exc)[:200])
                    attempt -= 1  # the repair attempt does not consume a retry
                    continue
                except LLMError as exc:
                    attempts.append(_record(self.primary.name, exc, t0))
                    if not exc.retryable:
                        break
                    continue
                attempts.append(AttemptRecord(self.primary.name, "ok", "", _ms(t0)))
                return LLMResult(
                    value=resp.value, provider=self.primary.name, model=resp.model,
                    usage=resp.usage, latency_ms=_ms(started), attempts=tuple(attempts),
                    fell_back=False,
                )  # fmt: skip
            log.warning("llm_fallback", task=request.task, attempts=[a.outcome for a in attempts])
        t0 = time.perf_counter()
        resp = await self.deterministic.generate(request, timeout_s=self.timeout_s)
        attempts.append(AttemptRecord(self.deterministic.name, "ok", "", _ms(t0)))
        return LLMResult(
            value=resp.value, provider=self.deterministic.name, model=resp.model,
            usage=resp.usage, latency_ms=_ms(started), attempts=tuple(attempts),
            fell_back=self.primary is not None,
        )  # fmt: skip


def _ms(t0: float) -> float:
    return round((time.perf_counter() - t0) * 1000, 2)


def _record(provider: str, exc: Exception, t0: float) -> AttemptRecord:
    return AttemptRecord(provider, type(exc).__name__, str(exc)[:300], _ms(t0))


def build_llm_client(settings: Settings) -> LLMClient:
    key = settings.llm_api_key.get_secret_value() if settings.llm_api_key else None
    primary: LLMProvider | None
    match settings.llm_provider:
        case "deterministic":
            primary = None
        case "anthropic":
            from app.llm.anthropic_provider import AnthropicProvider

            primary = AnthropicProvider(
                api_key=key, model=settings.llm_model, base_url=settings.llm_base_url
            )
        case "openai_compatible":
            from app.llm.openai_compatible import OpenAICompatibleProvider

            primary = OpenAICompatibleProvider(
                base_url=settings.llm_base_url, api_key=key, model=settings.llm_model
            )
    return LLMClient(
        primary, timeout_s=settings.llm_timeout_s, max_attempts=settings.llm_max_attempts
    )
