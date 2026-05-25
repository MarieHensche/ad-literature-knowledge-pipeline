from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from ad_lit_pipeline.core.step import StepResult


def utc_now() -> str:
    """Return the current UTC timestamp in ISO 8601 format."""
    return datetime.now(timezone.utc).isoformat()


def new_run_id() -> str:
    """Create a compact run id."""
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid4().hex[:8]


def file_sha256(path: Path) -> str | None:
    """Return a file hash, or None if the file does not exist."""
    if not path.exists() or not path.is_file():
        return None

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def path_payload(path: Path) -> dict[str, Any]:
    """Return manifest metadata for a path."""
    return {
        "path": str(path),
        "exists": path.exists(),
        "sha256": file_sha256(path),
    }


def step_result_payload(result: StepResult, status: str) -> dict[str, Any]:
    """Convert a StepResult into manifest JSON."""
    return {
        "step_name": result.step_name,
        "status": status,
        "started_at": result.metadata.get("started_at"),
        "ended_at": result.metadata.get("ended_at"),
        "elapsed_seconds": result.elapsed_seconds,
        "inputs": {
            name: path_payload(path)
            for name, path in result.inputs.items()
        },
        "outputs": {
            name: path_payload(path)
            for name, path in result.outputs.items()
        },
        "row_counts": result.row_counts,
        "warnings": result.warnings,
        "trace_paths": [str(path) for path in result.trace_paths],
        "error": result.error,
        "metadata": {
            key: value
            for key, value in result.metadata.items()
            if key not in {"started_at", "ended_at"}
        },
    }


class ManifestRecorder:
    """Write an inspectable manifest for a pipeline run."""

    def __init__(
        self,
        run_id: str,
        collection: str,
        pipeline_name: str,
        run_dir: Path,
        topic_contract_path: Path | None = None,
        model: str | None = None,
    ) -> None:
        self.run_id = run_id
        self.collection = collection
        self.pipeline_name = pipeline_name
        self.run_dir = run_dir
        self.manifest_path = run_dir / "manifest.json"
        self.payload: dict[str, Any] = {
            "run_id": run_id,
            "collection": collection,
            "pipeline_name": pipeline_name,
            "status": "running",
            "started_at": utc_now(),
            "ended_at": None,
            "topic_contract": (
                path_payload(topic_contract_path) if topic_contract_path else None
            ),
            "model": model,
            "steps": [],
            "failed_step": None,
        }

    @classmethod
    def create(
        cls,
        collection: str,
        pipeline_name: str,
        runs_dir: Path = Path("runs"),
        run_id: str | None = None,
        topic_contract_path: Path | None = None,
        model: str | None = None,
    ) -> "ManifestRecorder":
        resolved_run_id = run_id or new_run_id()
        run_dir = runs_dir / resolved_run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        recorder = cls(
            resolved_run_id,
            collection,
            pipeline_name,
            run_dir,
            topic_contract_path,
            model,
        )
        recorder.write()
        return recorder

    @classmethod
    def load(cls, manifest_path: Path) -> dict[str, Any]:
        return json.loads(manifest_path.read_text(encoding="utf-8"))

    def record_step(self, result: StepResult, status: str = "succeeded") -> None:
        self.payload["steps"].append(step_result_payload(result, status))
        if status == "failed":
            self.payload["failed_step"] = result.step_name
        self.write()

    def finish(self, status: str = "succeeded") -> None:
        self.payload["status"] = status
        self.payload["ended_at"] = utc_now()
        self.write()

    def write(self) -> None:
        self.manifest_path.write_text(
            json.dumps(self.payload, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )


def resume_step_from_manifest(manifest_path: Path) -> str | None:
    """Return the failed/incomplete step name from a previous manifest."""
    payload = ManifestRecorder.load(manifest_path)
    failed_step = payload.get("failed_step")
    if isinstance(failed_step, str) and failed_step:
        return failed_step

    for step in payload.get("steps", []):
        if step.get("status") != "succeeded":
            return step.get("step_name")
    return None

