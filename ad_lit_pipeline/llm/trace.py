from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any


TRACE_SCHEMA_VERSION = "1.0.0"


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


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


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
        request_parameters: dict[str, Any] | None = None,
        response_metadata: dict[str, Any] | None = None,
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

        existing = [path for path in paths.as_list() if path.exists()]
        if existing:
            raise FileExistsError(
                "Refusing to overwrite an existing LLM trace for "
                f"{step_name!r}/{call_id!r}: {existing[0]}"
            )

        paths.system_message.write_text(system_message, encoding="utf-8")
        paths.prompt.write_text(prompt, encoding="utf-8")
        write_json(paths.schema, schema)
        write_json(paths.raw_response, raw_response)
        write_json(paths.parsed_response, parsed_response)
        artifacts = {
            "system_message": {
                "path": str(paths.system_message),
                "sha256": file_sha256(paths.system_message),
            },
            "prompt": {
                "path": str(paths.prompt),
                "sha256": file_sha256(paths.prompt),
            },
            "schema": {
                "path": str(paths.schema),
                "sha256": file_sha256(paths.schema),
            },
            "raw_response": {
                "path": str(paths.raw_response),
                "sha256": file_sha256(paths.raw_response),
            },
            "parsed_response": {
                "path": str(paths.parsed_response),
                "sha256": file_sha256(paths.parsed_response),
            },
        }
        write_json(
            paths.metadata,
            {
                "trace_schema_version": TRACE_SCHEMA_VERSION,
                "step_name": step_name,
                "call_id": call_id,
                "model": model,
                "schema_name": schema_name,
                "request_parameters": request_parameters or {},
                "response_metadata": response_metadata or {},
                "validation": validation or {},
                "artifacts": artifacts,
            },
        )
        return paths
