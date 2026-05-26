from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class LLMTracePaths:
    """Files written for one traced LLM call."""

    system_message: Path
    prompt: Path
    schema: Path
    raw_response: Path
    parsed_response: Path
    metadata: Path

    def as_list(self) -> list[Path]:
        return [
            self.system_message,
            self.prompt,
            self.schema,
            self.raw_response,
            self.parsed_response,
            self.metadata,
        ]


def safe_name(value: str) -> str:
    """Return a filesystem-safe lowercase name."""
    safe = re.sub(r"[^a-zA-Z0-9_.-]+", "_", value).strip("_").lower()
    return safe or "llm_call"


def write_json(path: Path, payload: Any) -> None:
    path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


class LLMTraceWriter:
    """Write prompt, response, schema, and metadata files for LLM calls."""

    def __init__(self, trace_dir: Path) -> None:
        self.trace_dir = trace_dir
        self.trace_dir.mkdir(parents=True, exist_ok=True)

    def write_trace(
        self,
        step_name: str,
        call_id: str,
        system_message: str,
        prompt: str,
        model: str,
        schema_name: str,
        schema: dict[str, Any],
        raw_response: Any,
        parsed_response: Any,
        validation: dict[str, Any] | None = None,
    ) -> LLMTracePaths:
        prefix = self.trace_dir / f"{safe_name(step_name)}_{safe_name(call_id)}"
        paths = LLMTracePaths(
            system_message=Path(f"{prefix}_system.txt"),
            prompt=Path(f"{prefix}_prompt.md"),
            schema=Path(f"{prefix}_schema.json"),
            raw_response=Path(f"{prefix}_raw_response.json"),
            parsed_response=Path(f"{prefix}_parsed.json"),
            metadata=Path(f"{prefix}_metadata.json"),
        )

        paths.system_message.write_text(system_message, encoding="utf-8")
        paths.prompt.write_text(prompt, encoding="utf-8")
        write_json(paths.schema, schema)
        write_json(paths.raw_response, raw_response)
        write_json(paths.parsed_response, parsed_response)
        write_json(
            paths.metadata,
            {
                "step_name": step_name,
                "call_id": call_id,
                "model": model,
                "schema_name": schema_name,
                "validation": validation or {},
            },
        )
        return paths
