"""Fallback chain behaviour under provider faults (docs/AGENT_DESIGN.md §2, §5)."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from app.agents.grounding import check_grounding
from app.llm.base import (
    LLMConfigurationError,
    LLMInvalidOutputError,
    LLMRefusalError,
    LLMRequest,
    LLMTimeoutError,
    ProviderResponse,
    TokenUsage,
)
from app.llm.chain import LLMClient
from app.llm.deterministic import deterministic_task


class Echo(BaseModel):
    text: str


@deterministic_task("test.echo")
def _echo(context: dict[str, Any]) -> Echo:
    return Echo(text=f"rules:{context['x']}")


class ScriptedProvider:
    """Raises/returns a scripted sequence; records the repair hints it received."""

    name = "scripted"
    model = "fake-1"

    def __init__(self, *script: Exception | str) -> None:
        self.script = list(script)
        self.hints: list[str | None] = []

    async def generate(self, request, *, timeout_s, repair_hint=None):  # type: ignore[no-untyped-def]
        self.hints.append(repair_hint)
        step = self.script.pop(0)
        if isinstance(step, Exception):
            raise step
        return ProviderResponse(
            value=request.schema(text=step), model=self.model, usage=TokenUsage(10, 5)
        )


REQ = LLMRequest(task="test.echo", schema=Echo, system="s", user="u", context={"x": 1})


async def test_deterministic_mode_needs_no_provider() -> None:
    r = await LLMClient(None).generate(REQ)
    assert r.value.text == "rules:1"
    assert r.provider == "deterministic"
    assert not r.fell_back


async def test_primary_success() -> None:
    r = await LLMClient(ScriptedProvider("hello")).generate(REQ)
    assert (r.value.text, r.provider, r.fell_back) == ("hello", "scripted", False)
    assert r.usage.input_tokens == 10


async def test_transient_errors_are_retried_then_fall_back() -> None:
    p = ScriptedProvider(LLMTimeoutError("t1"), LLMTimeoutError("t2"))
    r = await LLMClient(p, max_attempts=2).generate(REQ)
    assert r.fell_back
    assert r.value.text == "rules:1"
    assert [a.outcome for a in r.attempts] == ["LLMTimeoutError", "LLMTimeoutError", "ok"]


async def test_transient_error_then_success() -> None:
    r = await LLMClient(ScriptedProvider(LLMTimeoutError("t"), "second")).generate(REQ)
    assert (r.value.text, r.fell_back) == ("second", False)


async def test_invalid_output_gets_one_repair_attempt() -> None:
    p = ScriptedProvider(LLMInvalidOutputError("bad json"), "fixed")
    r = await LLMClient(p, max_attempts=1).generate(REQ)
    assert r.value.text == "fixed"
    assert p.hints[0] is None
    assert p.hints[1] is not None
    assert "schema" in p.hints[1]


async def test_repeated_invalid_output_falls_back() -> None:
    p = ScriptedProvider(LLMInvalidOutputError("bad"), LLMInvalidOutputError("bad again"))
    r = await LLMClient(p, max_attempts=2).generate(REQ)
    assert r.fell_back


async def test_non_retryable_errors_fall_back_immediately() -> None:
    for error in (LLMConfigurationError("401"), LLMRefusalError("declined")):
        p = ScriptedProvider(error, "never used")
        r = await LLMClient(p, max_attempts=3).generate(REQ)
        assert r.fell_back
        assert len(p.hints) == 1


def test_grounding_check() -> None:
    ok = check_grounding(
        "SUB-02 failed; impact 49.62 and 176,000 people.", {"SUB-02"}, [49.62, 176000]
    )
    assert ok.ok
    bad = check_grounding("SUB-99 failed; impact 51.30.", {"SUB-02"}, [49.62])
    assert not bad.ok
    assert bad.unknown_asset_codes == ["SUB-99"]
    assert bad.unknown_numbers == ["51.30"]
    # Small integers are not checked (ambiguous: "2 hours", "wave 3").
    assert check_grounding("within 2 hours, wave 3", set(), []).ok
