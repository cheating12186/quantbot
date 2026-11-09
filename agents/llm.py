"""Optional Groq integration with JSON-schema validation and bounded retries.

The deterministic system remains authoritative. LLM text is labelled and can
only reject a trade in review; it can never relax a Python-enforced control.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError

from config.settings import Settings

T = TypeVar("T", bound=BaseModel)


@dataclass
class LLMResult:
    value: Any = None
    input_tokens: int = 0
    output_tokens: int = 0
    latency_ms: float = 0
    error: str | None = None


class GroqService:
    def __init__(self, settings: Settings):
        self.settings = settings
        self._client = None
        if settings.groq_api_key:
            try:
                from groq import Groq
                self._client = Groq(api_key=settings.groq_api_key, timeout=settings.llm_timeout_seconds)
            except Exception:
                self._client = None

    @property
    def available(self) -> bool:
        return self._client is not None

    def structured(
        self,
        schema: type[T],
        system_prompt: str,
        user_prompt: str,
    ) -> LLMResult:
        if self._client is None:
            return LLMResult(error="Groq unavailable: GROQ_API_KEY is not configured")
        started = time.perf_counter()
        last_error = "Unknown LLM error"
        for attempt in range(self.settings.llm_max_retries + 1):
            try:
                response = self._client.chat.completions.create(
                    model=self.settings.groq_model,
                    messages=[
                        {"role": "system", "content": system_prompt + " Return only a valid JSON object matching this schema: " + json.dumps(schema.model_json_schema())},
                        {"role": "user", "content": user_prompt},
                    ],
                    response_format={"type": "json_object"},
                    temperature=0.1,
                )
                content = response.choices[0].message.content or "{}"
                value = schema.model_validate_json(content)
                return LLMResult(
                    value=value,
                    input_tokens=getattr(response.usage, "prompt_tokens", 0) or 0,
                    output_tokens=getattr(response.usage, "completion_tokens", 0) or 0,
                    latency_ms=round((time.perf_counter() - started) * 1000, 3),
                )
            except (ValidationError, json.JSONDecodeError) as exc:
                last_error = f"Structured response validation failed: {exc}"
                break  # Retrying malformed JSON without new evidence is not useful.
            except Exception as exc:
                last_error = f"Groq request failed (attempt {attempt + 1}): {exc}"
                if attempt < self.settings.llm_max_retries:
                    time.sleep(min(0.25 * (2**attempt), 1.0))
        return LLMResult(error=last_error, latency_ms=round((time.perf_counter() - started) * 1000, 3))

    def list_models(self) -> LLMResult:
        """Return the live account model list when credentials are available."""
        if self._client is None:
            return LLMResult(error="Groq unavailable: GROQ_API_KEY is not configured")
        try:
            response = self._client.models.list()
            return LLMResult(value=sorted(model.id for model in response.data))
        except Exception as exc:
            return LLMResult(error=f"Groq model listing failed: {exc}")

    def tool_call(
        self,
        tool_name: str,
        tool_schema: type[T],
        system_prompt: str,
        user_prompt: str,
    ) -> LLMResult:
        """Use Groq function calling, then validate returned arguments in Pydantic."""
        if self._client is None:
            return LLMResult(error="Groq unavailable: GROQ_API_KEY is not configured")
        started = time.perf_counter()
        try:
            schema = tool_schema.model_json_schema()
            response = self._client.chat.completions.create(
                model=self.settings.groq_model,
                messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}],
                tools=[{"type": "function", "function": {
                    "name": tool_name,
                    "description": "Set validated quantitative research parameters. Do not calculate financial metrics.",
                    "parameters": schema,
                }}],
                tool_choice={"type": "function", "function": {"name": tool_name}},
                temperature=0,
            )
            message = response.choices[0].message
            if not message.tool_calls:
                return LLMResult(error="Groq returned no tool call")
            arguments = message.tool_calls[0].function.arguments
            value = tool_schema.model_validate_json(arguments)
            return LLMResult(
                value=value,
                input_tokens=getattr(response.usage, "prompt_tokens", 0) or 0,
                output_tokens=getattr(response.usage, "completion_tokens", 0) or 0,
                latency_ms=round((time.perf_counter() - started) * 1000, 3),
            )
        except Exception as exc:
            return LLMResult(error=f"Groq tool call failed: {exc}", latency_ms=round((time.perf_counter() - started) * 1000, 3))
