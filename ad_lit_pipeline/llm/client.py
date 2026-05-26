from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Protocol

from ad_lit_pipeline.llm.schemas import text_format
from ad_lit_pipeline.llm.trace import LLMTracePaths, LLMTraceWriter


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

        client = OpenAI()
        response = client.responses.create(
            model=model,
            input=[
                {"role": "system", "content": system_message},
                {"role": "user", "content": prompt},
            ],
            text=text_format(schema_name, schema),
        )

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
            )

        return LLMResult(parsed=parsed, raw_response=raw_response, trace_paths=trace_paths)


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
            )

        return LLMResult(parsed=parsed, raw_response=raw_response, trace_paths=trace_paths)
