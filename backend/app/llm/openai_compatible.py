"""Any OpenAI-compatible chat-completions endpoint (Ollama, vLLM, LM Studio, hosted gateways).

Structured output via `response_format: json_schema`; the result is still validated locally.
"""

from __future__ import annotations

import json

import httpx
from pydantic import BaseModel, ValidationError

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


class OpenAICompatibleProvider:
    name = "openai_compatible"

    def __init__(self, *, base_url: str | None, api_key: str | None, model: str | None) -> None:
        if not base_url or not model:
            raise LLMConfigurationError("openai_compatible requires LLM_BASE_URL and LLM_MODEL")
        self.model = model
        self._url = base_url.rstrip("/") + "/chat/completions"
        self._headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}

    async def generate[T: BaseModel](
        self, request: LLMRequest[T], *, timeout_s: float, repair_hint: str | None = None
    ) -> ProviderResponse[T]:
        user = request.user if repair_hint is None else f"{request.user}\n\n{repair_hint}"
        body = {
            "model": self.model,
            "max_tokens": request.max_tokens,
            "messages": [
                {"role": "system", "content": request.system},
                {"role": "user", "content": user},
            ],
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": request.task.replace(".", "_"),
                    "schema": request.schema.model_json_schema(),
                },
            },
        }
        try:
            async with httpx.AsyncClient(timeout=timeout_s) as client:
                r = await client.post(self._url, json=body, headers=self._headers)
        except httpx.TimeoutException as exc:
            raise LLMTimeoutError(str(exc)) from exc
        except httpx.HTTPError as exc:
            raise LLMUnavailableError(str(exc)) from exc
        if r.status_code == 429 or r.status_code >= 500:
            raise LLMUnavailableError(f"HTTP {r.status_code}")
        if r.status_code >= 400:
            raise LLMConfigurationError(f"HTTP {r.status_code}: {r.text[:200]}")
        try:
            data = r.json()
            choice = data["choices"][0]
            if choice.get("finish_reason") == "content_filter":
                raise LLMRefusalError("content filter")
            value = request.schema.model_validate(json.loads(choice["message"]["content"]))
        except (KeyError, IndexError, TypeError, json.JSONDecodeError, ValidationError) as exc:
            raise LLMInvalidOutputError(f"{type(exc).__name__}: {str(exc)[:300]}") from exc
        usage = data.get("usage") or {}
        return ProviderResponse(
            value=value,
            model=str(data.get("model", self.model)),
            usage=TokenUsage(usage.get("prompt_tokens"), usage.get("completion_tokens")),
        )
