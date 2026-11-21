"""Claude via the official Anthropic SDK (structured output through `messages.parse`).

Defaults: model `claude-opus-5-5`; server-side refusal fallbacks enabled ("default" routing). SDK
retries are disabled because the fallback chain owns retry policy.
"""

from __future__ import annotations

import anthropic
from pydantic import BaseModel

from app.llm.base import (
    LLMConfigurationError,
    LLMInvalidOutputError,
    LLMRefusalError,
    LLMRequest,
    LLMTimeoutError,
    LLMUnavailableError,
    ProviderResponse,
    TokenUsage,
)

DEFAULT_MODEL = "claude-opus-5-5"
FALLBACK_BETA = "server-side-fallback-2026-07-01"


class AnthropicProvider:
    name = "anthropic"

    def __init__(self, *, api_key: str | None, model: str | None, base_url: str | None) -> None:
        self.model = model or DEFAULT_MODEL
        # api_key=None lets the SDK resolve credentials from the environment / `ant` profile.
        self._client = anthropic.AsyncAnthropic(api_key=api_key, base_url=base_url, max_retries=0)

    async def generate[T: BaseModel](
        self, request: LLMRequest[T], *, timeout_s: float, repair_hint: str | None = None
    ) -> ProviderResponse[T]:
        user = request.user if repair_hint is None else f"{request.user}\n\n{repair_hint}"
        try:
            response = await self._client.with_options(timeout=timeout_s).beta.messages.parse(
                model=self.model,
                max_tokens=request.max_tokens,
                system=request.system,
                messages=[{"role": "user", "content": user}],
                output_format=request.schema,
                betas=[FALLBACK_BETA],
                fallbacks="default",
            )
        except anthropic.APITimeoutError as exc:
            raise LLMTimeoutError(str(exc)) from exc
        except (anthropic.RateLimitError, anthropic.APIConnectionError) as exc:
            raise LLMUnavailableError(str(exc)) from exc
        except anthropic.APIStatusError as exc:
            if exc.status_code >= 500:
                raise LLMUnavailableError(f"{exc.status_code}: {exc.message}") from exc
            raise LLMConfigurationError(f"{exc.status_code}: {exc.message}") from exc

        if response.stop_reason == "refusal":
            category = response.stop_details.category if response.stop_details else None
            raise LLMRefusalError(f"model declined (category={category})")
        if response.stop_reason == "max_tokens":
            raise LLMInvalidOutputError("response truncated at max_tokens")
        parsed = response.parsed_output
        if parsed is None:
            raise LLMInvalidOutputError("no structured output in response")
        return ProviderResponse(
            value=request.schema.model_validate(parsed.model_dump()),
            model=response.model,
            usage=TokenUsage(response.usage.input_tokens, response.usage.output_tokens),
        )
