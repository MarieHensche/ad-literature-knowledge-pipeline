from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any, Protocol

from ad_lit_pipeline.llm.schemas import text_format
from ad_lit_pipeline.llm.trace import LLMTracePaths, LLMTraceWriter


DEFAULT_OPENAI_TIMEOUT_SECONDS = 45.0
DEFAULT_OPENAI_MAX_RETRIES = 0


@dataclass(frozen=True)
class LLMResult:
    """Parsed JSON result plus optional trace files."""

    parsed: dict[str, Any]
    raw_response: Any
    trace_paths: LLMTracePaths | None = None


class JSONLLMClient(Protocol):
    """Protocol for LLM clients that return JSON objects."""

    def create_json(
        self,
        model: str,
        system_message: str,
        prompt: str,
        schema_name: str,
        schema: dict[str, Any],
        step_name: str,
        call_id: str,
        trace_writer: LLMTraceWriter | None = None,
    ) -> LLMResult:
        """Create a JSON response from an LLM."""


class OpenAIResponsesClient:
    """OpenAI Responses API client used by pipeline LLM steps."""

    def __init__(
        self,
        timeout_seconds: float | None = None,
        max_retries: int | None = None,
    ) -> None:
        self.timeout_seconds = (
            timeout_seconds
            if timeout_seconds is not None
            else openai_timeout_seconds_from_env()
        )
        self.max_retries = (
            max_retries if max_retries is not None else openai_max_retries_from_env()
        )

    def create_json(
        self,
        model: str,
        system_message: str,
        prompt: str,
        schema_name: str,
        schema: dict[str, Any],
        step_name: str,
        call_id: str,
        trace_writer: LLMTraceWriter | None = None,
    ) -> LLMResult:
        from openai import OpenAI

        client = OpenAI(
            timeout=self.timeout_seconds,
            max_retries=self.max_retries,
        )

        # Retry logic: try up to 2 times (1 initial attempt + 1 retry) on JSON decode errors
        last_error = None
        for attempt in range(2):
            try:
                try:
                    response = client.responses.create(
                        model=model,
                        input=[
                            {"role": "system", "content": system_message},
                            {"role": "user", "content": prompt},
                        ],
                        text=text_format(schema_name, schema),
                    )
                except Exception as error:
                    raise ValueError(
                        f"OpenAI request failed for {step_name}/{call_id} "
                        f"with model {model} "
                        f"(timeout={self.timeout_seconds}s, "
                        f"max_retries={self.max_retries}): {error}"
                    ) from error

                parsed = json.loads(response.output_text)

                if not isinstance(parsed, dict):
                    raise ValueError("Expected JSON object from LLM response.")

                raw_response: Any
                if hasattr(response, "model_dump"):
                    raw_response = response.model_dump()
                else:
                    raw_response = {"output_text": response.output_text}

                trace_paths = None
                if trace_writer is not None:
                    response_metadata = {}
                    if isinstance(raw_response, dict):
                        for key in (
                            "id",
                            "model",
                            "created_at",
                            "service_tier",
                            "usage",
                        ):
                            if key in raw_response:
                                response_metadata[key] = raw_response[key]
                    trace_paths = trace_writer.write_trace(
                        step_name=step_name,
                        call_id=call_id,
                        system_message=system_message,
                        prompt=prompt,
                        model=model,
                        schema_name=schema_name,
                        schema=schema,
                        raw_response=raw_response,
                        parsed_response=parsed,
                        request_parameters={
                            "api": "responses",
                            "response_format": "json_schema",
                            "timeout_seconds": self.timeout_seconds,
                            "sdk_max_retries": self.max_retries,
                            "application_json_decode_attempts": 2,
                        },
                        response_metadata=response_metadata,
                    )

                return LLMResult(parsed=parsed, raw_response=raw_response, trace_paths=trace_paths)

            except json.JSONDecodeError as error:
                last_error = error
                # Retry once on JSON decode errors (transient API issues)
                if attempt < 1:
                    continue
                else:
                    # Out of retries, raise error
                    raise ValueError(
                        f"LLM returned malformed JSON (possible transient API issue). "
                        f"Try re-running the command. Error: {error}"
                    ) from error

        # Should not reach here, but if we do, raise the last error
        if last_error:
            raise ValueError(
                f"LLM returned malformed JSON (possible transient API issue). "
                f"Try re-running the command. Error: {last_error}"
            ) from last_error
        raise ValueError("Unexpected error in create_json")


def openai_timeout_seconds_from_env() -> float:
    raw_value = os.getenv("OPENAI_TIMEOUT_SECONDS", "").strip()
    if not raw_value:
        return DEFAULT_OPENAI_TIMEOUT_SECONDS
    try:
        timeout = float(raw_value)
    except ValueError as error:
        raise ValueError("OPENAI_TIMEOUT_SECONDS must be a number.") from error
    if timeout <= 0:
        raise ValueError("OPENAI_TIMEOUT_SECONDS must be greater than 0.")
    return timeout


def openai_max_retries_from_env() -> int:
    raw_value = os.getenv("OPENAI_MAX_RETRIES", "").strip()
    if not raw_value:
        return DEFAULT_OPENAI_MAX_RETRIES
    try:
        max_retries = int(raw_value)
    except ValueError as error:
        raise ValueError("OPENAI_MAX_RETRIES must be an integer.") from error
    if max_retries < 0:
        raise ValueError("OPENAI_MAX_RETRIES must be 0 or greater.")
    return max_retries


class StaticJSONClient:
    """Fake JSON client for tests and offline smoke checks."""

    def __init__(self, responses: list[dict[str, Any]]) -> None:
        self.responses = list(responses)
        self.requests: list[dict[str, Any]] = []

    def create_json(
        self,
        model: str,
        system_message: str,
        prompt: str,
        schema_name: str,
        schema: dict[str, Any],
        step_name: str,
        call_id: str,
        trace_writer: LLMTraceWriter | None = None,
    ) -> LLMResult:
        if not self.responses:
            raise ValueError("StaticJSONClient has no responses left.")

        self.requests.append(
            {
                "model": model,
                "system_message": system_message,
                "prompt": prompt,
                "schema_name": schema_name,
                "schema": schema,
                "step_name": step_name,
                "call_id": call_id,
            }
        )
        parsed = self.responses.pop(0)
        raw_response = {"output_text": json.dumps(parsed)}

        trace_paths = None
        if trace_writer is not None:
            trace_paths = trace_writer.write_trace(
                step_name=step_name,
                call_id=call_id,
                system_message=system_message,
                prompt=prompt,
                model=model,
                schema_name=schema_name,
                schema=schema,
                raw_response=raw_response,
                parsed_response=parsed,
                request_parameters={
                    "client": "static_json",
                    "response_format": "json_schema",
                },
            )

        return LLMResult(parsed=parsed, raw_response=raw_response, trace_paths=trace_paths)
