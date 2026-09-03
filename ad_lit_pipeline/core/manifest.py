from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from ad_lit_pipeline.core.errors import ValidationError
from ad_lit_pipeline.core.provenance import sanitize_value
from ad_lit_pipeline.core.step import StepResult


MANIFEST_SCHEMA_VERSION = "1.0.0"


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
        "path": sanitize_value(str(path), Path.cwd(), key="path"),
        "exists": path.exists(),
        "byte_size": path.stat().st_size if path.is_file() else None,
        "sha256": file_sha256(path),
    }


def step_result_payload(
    result: StepResult,
    status: str,
    *,
    attempt_id: str | None = None,
) -> dict[str, Any]:
    """Convert a StepResult into manifest JSON."""
    project_root = Path.cwd()
    return {
        "step_name": result.step_name,
        "attempt_id": attempt_id,
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
        "row_counts": sanitize_value(
            result.row_counts,
            project_root,
            key="row_counts",
        ),
        "warnings": sanitize_value(
            result.warnings,
            project_root,
            key="warnings",
        ),
        "trace_paths": [
            sanitize_value(str(path), project_root, key="trace_path")
            for path in result.trace_paths
        ],
        "trace_artifacts": [path_payload(path) for path in result.trace_paths],
        "error": sanitize_value(result.error, project_root, key="error"),
        "metadata": sanitize_value(
            {
                key: value
                for key, value in result.metadata.items()
                if key not in {"started_at", "ended_at"}
            },
            project_root,
            key="metadata",
        ),
    }


def validate_manifest_payload(
    payload: dict[str, Any],
    *,
    allow_legacy: bool = True,
) -> None:
    """Validate the stable run-manifest envelope while permitting legacy reads."""
    if not isinstance(payload, dict):
        raise ValidationError("Run manifest must be a JSON object.")
    schema_version = payload.get("manifest_schema_version")
    if schema_version is None and allow_legacy:
        return
    if schema_version != MANIFEST_SCHEMA_VERSION:
        raise ValidationError(
            f"Unsupported manifest_schema_version {schema_version!r}."
        )
    for field in ("run_id", "collection", "pipeline_name", "status", "started_at"):
        if not isinstance(payload.get(field), str) or not payload[field].strip():
            raise ValidationError(f"Run manifest {field} must be a non-empty string.")
    if not isinstance(payload.get("steps"), list):
        raise ValidationError("Run manifest steps must be an array.")
    attempts = payload.get("attempts")
    if not isinstance(attempts, list) or not attempts:
        raise ValidationError("Run manifest attempts must be a non-empty array.")
    attempt_ids = []
    for index, attempt in enumerate(attempts):
        if not isinstance(attempt, dict):
            raise ValidationError(f"Run manifest attempts[{index}] must be an object.")
        attempt_id = attempt.get("attempt_id")
        if not isinstance(attempt_id, str) or not attempt_id:
            raise ValidationError(
                f"Run manifest attempts[{index}].attempt_id must be non-empty."
            )
        attempt_ids.append(attempt_id)
    if len(attempt_ids) != len(set(attempt_ids)):
        raise ValidationError("Run manifest attempt IDs must be unique.")
    for index, step in enumerate(payload["steps"]):
        if not isinstance(step, dict):
            raise ValidationError(f"Run manifest steps[{index}] must be an object.")
        attempt_id = step.get("attempt_id")
        if attempt_id is not None and attempt_id not in attempt_ids:
            raise ValidationError(
                f"Run manifest steps[{index}] uses unknown attempt_id {attempt_id!r}."
            )


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
        *,
        provenance: dict[str, Any] | None = None,
        resume: bool = False,
    ) -> None:
        self.run_id = run_id
        self.collection = collection
        self.pipeline_name = pipeline_name
        self.run_dir = run_dir
        self.manifest_path = run_dir / "manifest.json"
        self.current_attempt_id = ""
        self.payload: dict[str, Any] = {
            "manifest_schema_version": MANIFEST_SCHEMA_VERSION,
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
            "provenance": provenance,
            "attempts": [],
            "steps": [],
            "failed_step": None,
        }
        self._start_attempt(provenance, resume=resume)

    @classmethod
    def create(
        cls,
        collection: str,
        pipeline_name: str,
        runs_dir: Path = Path("runs"),
        run_id: str | None = None,
        topic_contract_path: Path | None = None,
        model: str | None = None,
        *,
        provenance: dict[str, Any] | None = None,
        resume: bool = False,
    ) -> "ManifestRecorder":
        resolved_run_id = run_id or new_run_id()
        run_dir = runs_dir / resolved_run_id
        manifest_path = run_dir / "manifest.json"
        if resume:
            if not manifest_path.is_file():
                raise ValueError(
                    f"Cannot resume run {resolved_run_id!r}: manifest does not exist."
                )
            return cls._resume_existing(
                manifest_path=manifest_path,
                collection=collection,
                pipeline_name=pipeline_name,
                topic_contract_path=topic_contract_path,
                model=model,
                provenance=provenance,
            )
        runs_dir.mkdir(parents=True, exist_ok=True)
        try:
            run_dir.mkdir(exist_ok=False)
        except FileExistsError as exc:
            raise ValueError(
                f"Run ID {resolved_run_id!r} already exists. Use --resume to "
                "continue it, or choose a different --run-id."
            ) from exc
        recorder = cls(
            resolved_run_id,
            collection,
            pipeline_name,
            run_dir,
            topic_contract_path,
            model,
            provenance=provenance,
            resume=False,
        )
        recorder.write()
        return recorder

    @classmethod
    def load(cls, manifest_path: Path) -> dict[str, Any]:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        validate_manifest_payload(payload, allow_legacy=True)
        return payload

    @classmethod
    def _resume_existing(
        cls,
        *,
        manifest_path: Path,
        collection: str,
        pipeline_name: str,
        topic_contract_path: Path | None,
        model: str | None,
        provenance: dict[str, Any] | None,
    ) -> "ManifestRecorder":
        payload = cls.load(manifest_path)
        cls._validate_resume_compatibility(
            payload,
            collection=collection,
            pipeline_name=pipeline_name,
            topic_contract_path=topic_contract_path,
            model=model,
            provenance=provenance,
        )
        recorder = cls.__new__(cls)
        recorder.run_id = str(payload["run_id"])
        recorder.collection = collection
        recorder.pipeline_name = pipeline_name
        recorder.run_dir = manifest_path.parent
        recorder.manifest_path = manifest_path
        recorder.current_attempt_id = ""
        recorder.payload = payload
        recorder._upgrade_legacy_payload()
        recorder._mark_interrupted_attempt()

        current_topic = (
            path_payload(topic_contract_path) if topic_contract_path else None
        )
        previous_topic = recorder.payload.get("topic_contract")
        if (
            isinstance(previous_topic, dict)
            and previous_topic.get("sha256") is None
            and isinstance(current_topic, dict)
            and current_topic.get("sha256") is not None
        ):
            recorder.payload["topic_contract"] = current_topic
        recorder._start_attempt(provenance, resume=True)
        recorder.payload["status"] = "running"
        recorder.payload["ended_at"] = None
        recorder.write()
        return recorder

    @staticmethod
    def _validate_resume_compatibility(
        payload: dict[str, Any],
        *,
        collection: str,
        pipeline_name: str,
        topic_contract_path: Path | None,
        model: str | None,
        provenance: dict[str, Any] | None,
    ) -> None:
        for field, expected in (
            ("collection", collection),
            ("pipeline_name", pipeline_name),
            ("model", model),
        ):
            actual = payload.get(field)
            if actual != expected:
                raise ValueError(
                    f"Cannot resume with incompatible {field}: "
                    f"manifest={actual!r}, requested={expected!r}."
                )
        previous_topic = payload.get("topic_contract")
        current_topic = path_payload(topic_contract_path) if topic_contract_path else None
        if previous_topic is None and current_topic is None:
            ManifestRecorder._validate_resume_provenance(payload, provenance)
            return
        if not isinstance(previous_topic, dict) or not isinstance(current_topic, dict):
            raise ValueError("Cannot resume with a different topic-contract boundary.")
        previous_hash = previous_topic.get("sha256")
        current_hash = current_topic.get("sha256")
        if previous_hash is not None and current_hash is None:
            raise ValueError(
                "Cannot resume because the recorded topic contract is unavailable."
            )
        if (
            previous_hash is not None
            and current_hash is not None
            and previous_hash != current_hash
        ):
            raise ValueError("Cannot resume after the topic contract changed.")
        ManifestRecorder._validate_resume_provenance(payload, provenance)

    @staticmethod
    def _validate_resume_provenance(
        payload: dict[str, Any],
        provenance: dict[str, Any] | None,
    ) -> None:
        previous = payload.get("provenance")
        if not isinstance(previous, dict) or not isinstance(provenance, dict):
            return
        previous_invocation = previous.get("invocation")
        current_invocation = provenance.get("invocation")
        if not isinstance(previous_invocation, dict) or not isinstance(
            current_invocation, dict
        ):
            return
        for field, label in (
            ("pipeline_steps", "pipeline structure"),
            ("resume_compatibility_options", "effective options"),
            ("resume_compatibility_sha256", "effective options"),
        ):
            previous_value = previous_invocation.get(field)
            current_value = current_invocation.get(field)
            if (
                previous_value is not None
                and current_value is not None
                and previous_value != current_value
            ):
                raise ValueError(f"Cannot resume after the {label} changed.")
        previous_policy = (
            previous.get("contracts", {}).get("topic_structure_policy")
            if isinstance(previous.get("contracts"), dict)
            else None
        )
        current_policy = (
            provenance.get("contracts", {}).get("topic_structure_policy")
            if isinstance(provenance.get("contracts"), dict)
            else None
        )
        if isinstance(previous_policy, dict) and isinstance(current_policy, dict):
            previous_hash = previous_policy.get("semantic_sha256")
            current_hash = current_policy.get("semantic_sha256")
            if (
                previous_hash is not None
                and current_hash is not None
                and previous_hash != current_hash
            ):
                raise ValueError(
                    "Cannot resume after the effective topic-structure policy changed."
                )

    def _upgrade_legacy_payload(self) -> None:
        self.payload.setdefault("manifest_schema_version", MANIFEST_SCHEMA_VERSION)
        self.payload.setdefault("provenance", None)
        attempts = self.payload.setdefault("attempts", [])
        if attempts:
            return
        steps = self.payload.get("steps")
        step_count = len(steps) if isinstance(steps, list) else 0
        attempts.append(
            {
                "attempt_id": "attempt-0000-legacy",
                "sequence": 0,
                "resume": False,
                "status": self.payload.get("status", "unknown"),
                "started_at": self.payload.get("started_at"),
                "ended_at": self.payload.get("ended_at"),
                "step_start_index": 0,
                "step_end_index": step_count,
                "provenance": None,
            }
        )

    def _mark_interrupted_attempt(self) -> None:
        """Close an attempt left running by abrupt process termination."""
        attempts = self.payload.get("attempts")
        if not isinstance(attempts, list) or not attempts:
            return
        previous = attempts[-1]
        if previous.get("status") != "running" or previous.get("ended_at"):
            return
        detected_at = utc_now()
        previous["status"] = "interrupted"
        previous["ended_at"] = detected_at
        previous["step_end_index"] = len(self.payload.get("steps", []))
        previous["interruption_detected_at"] = detected_at

    def _start_attempt(
        self,
        provenance: dict[str, Any] | None,
        *,
        resume: bool,
    ) -> None:
        attempts = self.payload["attempts"]
        sequence = len(attempts) + 1
        self.current_attempt_id = f"attempt-{sequence:04d}"
        attempts.append(
            {
                "attempt_id": self.current_attempt_id,
                "sequence": sequence,
                "resume": resume,
                "status": "running",
                "started_at": utc_now(),
                "ended_at": None,
                "step_start_index": len(self.payload["steps"]),
                "step_end_index": None,
                "provenance": provenance,
            }
        )

    def _current_attempt(self) -> dict[str, Any]:
        for attempt in reversed(self.payload["attempts"]):
            if attempt.get("attempt_id") == self.current_attempt_id:
                return attempt
        raise RuntimeError("Manifest has no active attempt.")

    def record_step(self, result: StepResult, status: str = "succeeded") -> None:
        self.payload["steps"].append(
            step_result_payload(
                result,
                status,
                attempt_id=self.current_attempt_id,
            )
        )
        if status != "succeeded":
            self.payload["failed_step"] = result.step_name
        elif self.payload.get("failed_step") == result.step_name:
            self.payload["failed_step"] = None
        self.write()

    def finish(self, status: str = "succeeded") -> None:
        self.payload["status"] = status
        self.payload["ended_at"] = utc_now()
        attempt = self._current_attempt()
        attempt["status"] = status
        attempt["ended_at"] = self.payload["ended_at"]
        attempt["step_end_index"] = len(self.payload["steps"])
        if status in {"succeeded", "dry_run"}:
            self.payload["failed_step"] = None
        self.write()

    def write(self) -> None:
        validate_manifest_payload(self.payload, allow_legacy=False)
        temporary = self.manifest_path.with_name(
            f".{self.manifest_path.name}.{uuid4().hex}.tmp"
        )
        try:
            temporary.write_text(
                json.dumps(self.payload, indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
            os.replace(temporary, self.manifest_path)
        finally:
            temporary.unlink(missing_ok=True)


def resume_step_from_manifest(manifest_path: Path) -> str | None:
    """Return the failed/incomplete step name from a previous manifest."""
    payload = ManifestRecorder.load(manifest_path)
    if payload.get("status") in {"succeeded", "dry_run"}:
        return None
    pending = resume_steps_from_manifest(manifest_path, payload=payload)
    return pending[0] if pending else None


def recorded_selected_steps(payload: dict[str, Any]) -> list[str] | None:
    """Return a validated original selected-step sequence when one was recorded."""
    provenance = payload.get("provenance")
    invocation = provenance.get("invocation") if isinstance(provenance, dict) else None
    selected = (
        invocation.get("selected_steps") if isinstance(invocation, dict) else None
    )
    if not isinstance(selected, list) or not all(
        isinstance(step, str) and step for step in selected
    ):
        return None
    return selected


def resume_steps_from_manifest(
    manifest_path: Path,
    *,
    payload: dict[str, Any] | None = None,
    fallback_steps: list[str] | None = None,
) -> list[str]:
    """Return the original selected-step suffix that remains to be rerun."""
    manifest = payload or ManifestRecorder.load(manifest_path)
    if manifest.get("status") in {"succeeded", "dry_run"}:
        return []
    selected = recorded_selected_steps(manifest)
    if selected is None:
        if fallback_steps is not None:
            return list(fallback_steps)
        failed_step = manifest.get("failed_step")
        return [failed_step] if isinstance(failed_step, str) and failed_step else []

    latest_status: dict[str, str] = {}
    for step in manifest.get("steps", []):
        name = step.get("step_name")
        status = step.get("status")
        if isinstance(name, str) and isinstance(status, str):
            latest_status[name] = status
    for index, step_name in enumerate(selected):
        if latest_status.get(step_name) != "succeeded":
            return selected[index:]
    return []
