from __future__ import annotations

import csv
import hashlib
import json
import re
import subprocess
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ad_lit_pipeline.core.errors import ValidationError
from ad_lit_pipeline.records import (
    SCHEMA_VERSION,
    MantisExportProfile,
    MantisPublicationReceipt,
    make_payload_record_id,
    record_from_dict,
)
from ad_lit_pipeline.records.ids import canonical_json
from ad_lit_pipeline.records.models import MantisDataType


MANTIS_COMMAND = "mantis"
DEFAULT_MANTIS_HOST = "mantis.csail.mit.edu"
_SUPPORTED_TOOL_PATTERN = re.compile(r"^mantisai-cli==(?P<version>\d+\.\d+\.\d+)$")
_SECRET_PATTERNS = (
    re.compile(r"(?i)(api[_ -]?key|authorization|bearer)\s*[:=]?\s*\S+"),
    re.compile(r"https?://\S+"),
    re.compile(r"\b[A-Za-z0-9_-]{32,}\b"),
)
_TYPE_FLAGS = {
    MantisDataType.TITLE: "--title-column",
    MantisDataType.SEMANTIC: "--semantic-column",
    MantisDataType.CATEGORIC: "--categoric-column",
    MantisDataType.NUMERIC: "--numeric-column",
    MantisDataType.DATE: "--date-column",
    MantisDataType.LINKS: "--links-column",
}
_EMPTY_SHA256 = hashlib.sha256(b"").hexdigest()


@dataclass(frozen=True)
class CommandResult:
    returncode: int
    stdout: str
    stderr: str


@dataclass(frozen=True)
class PublicationDestination:
    """Explicit Mantis destination; visibility remains private in v1."""

    map_name: str
    space_mode: str
    space_id: str | None = None
    space_name: str | None = None

    def __post_init__(self) -> None:
        if self.space_mode not in {"new", "existing"}:
            raise ValidationError("Mantis space_mode must be 'new' or 'existing'.")
        if not self.map_name.strip():
            raise ValidationError("Mantis map_name must be non-empty.")
        if self.space_mode == "existing" and not self.space_id:
            raise ValidationError("Existing Mantis publication requires space_id.")
        if self.space_mode == "new" and not self.space_name:
            raise ValidationError("New Mantis publication requires space_name.")


CommandRunner = Callable[[Sequence[str]], CommandResult]


def _run_command(command: Sequence[str]) -> CommandResult:
    completed = subprocess.run(
        list(command),
        check=False,
        capture_output=True,
        text=True,
        timeout=300,
    )
    return CommandResult(
        returncode=completed.returncode,
        stdout=completed.stdout,
        stderr=completed.stderr,
    )


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _supported_version(profile: MantisExportProfile) -> str:
    versions: list[str] = []
    for declaration in profile.supported_tool_versions:
        match = _SUPPORTED_TOOL_PATTERN.fullmatch(declaration)
        if match:
            versions.append(match.group("version"))
    if len(versions) != 1:
        raise ValidationError(
            "Mantis profile must declare exactly one exact mantisai-cli version."
        )
    return versions[0]


def _extract_version(output: str) -> str | None:
    match = re.search(r"(?<!\d)(\d+\.\d+\.\d+)(?!\d)", output)
    return match.group(1) if match else None


def _sanitize_error(value: str) -> str:
    sanitized = value.strip().replace("\x00", "")
    for pattern in _SECRET_PATTERNS:
        sanitized = pattern.sub("[redacted]", sanitized)
    sanitized = " ".join(sanitized.split())
    return sanitized[:500] or "Mantis CLI failed without a diagnostic message."


def build_create_map_command(
    csv_path: Path,
    profile: MantisExportProfile,
    destination: PublicationDestination,
) -> tuple[str, ...]:
    """Build a credential-free, private, non-activating CLI command."""
    if profile.connection_compatibility_verified:
        raise ValidationError("Connection publication is disabled in compatibility v1.")
    command = [
        MANTIS_COMMAND,
        "create",
        "map",
        str(csv_path),
        "--space-mode",
        destination.space_mode,
    ]
    if destination.space_mode == "new":
        command.extend(("--space-name", destination.space_name or ""))
    else:
        command.extend(("--space-id", destination.space_id or ""))
    command.extend(("--private", "--map-name", destination.map_name, "--no-activate"))
    by_type: dict[MantisDataType, list[str]] = {}
    for field in profile.fields:
        if field.mantis_type is MantisDataType.CONNECTION:
            raise ValidationError("Connection columns are disabled in compatibility v1.")
        by_type.setdefault(field.mantis_type, []).append(field.output_name)
    for data_type, flag in _TYPE_FLAGS.items():
        columns = by_type.get(data_type)
        if columns:
            command.extend((flag, ",".join(columns)))
    return tuple(command)


def _find_value(payload: Any, keys: set[str]) -> str | None:
    if isinstance(payload, Mapping):
        for key, value in payload.items():
            if key in keys and isinstance(value, str) and value.strip():
                return value.strip()
        for value in payload.values():
            found = _find_value(value, keys)
            if found:
                return found
    elif isinstance(payload, list):
        for value in payload:
            found = _find_value(value, keys)
            if found:
                return found
    return None


def _parse_creation_output(output: str) -> tuple[str, str, str | None, str | None]:
    candidates = [output.strip(), *reversed(output.splitlines())]
    payload: Any = None
    for candidate in candidates:
        try:
            payload = json.loads(candidate)
            break
        except (json.JSONDecodeError, TypeError):
            continue
    if payload is None:
        raise ValidationError("Mantis CLI did not return machine-readable JSON.")
    space_id = _find_value(payload, {"space_id", "spaceId"})
    map_id = _find_value(payload, {"map_id", "mapId", "floor_id", "floorId"})
    if not space_id or not map_id:
        raise ValidationError("Mantis CLI response omitted space_id or map_id.")
    space_uri = _find_value(payload, {"space_uri", "spaceUri"})
    map_uri = _find_value(payload, {"map_uri", "mapUri", "floor_uri", "floorUri"})
    return space_id, map_id, space_uri, map_uri


def _receipt(
    *,
    profile: MantisExportProfile,
    csv_path: Path,
    source_sha256: str,
    record_count: int,
    producing_run_id: str,
    created_at: str,
    started_at: str,
    completed_at: str,
    tool_version: str,
    success: bool,
    destination: PublicationDestination,
    space_id: str | None = None,
    map_id: str | None = None,
    space_uri: str | None = None,
    map_uri: str | None = None,
    error_code: str | None = None,
    error_message: str | None = None,
    source_available: bool = True,
    remote_attempted: bool = True,
) -> MantisPublicationReceipt:
    idempotency_key = hashlib.sha256(
        canonical_json(
            {
                "profile_id": profile.record_id,
                "source_sha256": source_sha256,
                "space_mode": destination.space_mode,
                "space_id": destination.space_id,
                "space_name": destination.space_name,
                "map_name": destination.map_name,
            }
        ).encode("utf-8")
    ).hexdigest()
    payload: dict[str, Any] = {
        "record_type": "mantis_publication_receipt",
        "schema_version": SCHEMA_VERSION,
        "record_id": "pending",
        "created_at": created_at,
        "corpus_snapshot_id": profile.corpus_snapshot_id,
        "producing_run_id": producing_run_id,
        "producing_step_id": "publish_mantis_views",
        "parent_record_ids": [profile.record_id],
        "source_record_ids": [profile.record_id],
        "provenance": [
            {
                "kind": "artifact",
                "relation": "publication_attempted_from",
                "reference": str(csv_path),
                "sha256": source_sha256,
            }
        ],
        "record_status": "active",
        "validation_warnings": [],
        "policy_versions": {"record_contracts": SCHEMA_VERSION},
        "extensions": {
            "mantis.publication_safety": {
                "visibility": "private",
                "activate": False,
                "credentials_in_command": False,
                "source_available": source_available,
                "remote_attempted": remote_attempted,
            }
        },
        "export_profile_id": profile.record_id,
        "profile_version": profile.profile_version,
        "compatibility_version": profile.compatibility_version,
        "source_contract": profile.source_contract,
        "source_schema_version": profile.source_schema_version,
        "source_artifact_reference": {
            "kind": "artifact",
            "relation": "published_from",
            "reference": str(csv_path),
            "sha256": source_sha256,
        },
        "source_sha256": source_sha256,
        "record_count": record_count,
        "tool_name": "mantisai-cli",
        "tool_version": tool_version,
        "host": DEFAULT_MANTIS_HOST,
        "operation": "create",
        "duplicate_policy": "reject",
        "attempt_number": 1,
        "retry_of_receipt_id": None,
        "started_at": started_at,
        "completed_at": completed_at,
        "published_at": completed_at if success else None,
        "publication_status": "succeeded" if success else "failed",
        "space_id": space_id,
        "map_id": map_id,
        "space_uri": space_uri,
        "map_uri": map_uri,
        "idempotency_key": idempotency_key,
        "error": (
            None
            if success
            else {
                "code": error_code or "mantis_publication_failed",
                "message": _sanitize_error(error_message or "Mantis publication failed."),
                "retryable": True,
            }
        ),
    }
    payload["record_id"] = make_payload_record_id(
        "mantis_publication_receipt", payload, schema_version=SCHEMA_VERSION
    )
    record = record_from_dict(payload)
    if not isinstance(record, MantisPublicationReceipt):
        raise AssertionError("Receipt decoder returned an unexpected record.")
    return record


def _source_metadata(csv_path: Path) -> tuple[str, int]:
    if not csv_path.is_file():
        raise FileNotFoundError(f"Mantis publication CSV does not exist: {csv_path}")
    source_sha256 = _file_sha256(csv_path)
    with csv_path.open(encoding="utf-8", newline="") as handle:
        record_count = sum(1 for _ in csv.DictReader(handle))
    return source_sha256, record_count


def failure_receipt(
    csv_path: Path,
    profile: MantisExportProfile,
    destination: PublicationDestination,
    *,
    producing_run_id: str,
    created_at: str,
    started_at: str,
    completed_at: str,
    error_code: str,
    error_message: str,
    tool_version: str | None = None,
    remote_attempted: bool = False,
) -> MantisPublicationReceipt:
    """Create a durable failure receipt without requiring a readable source CSV."""
    source_available = True
    try:
        source_sha256, record_count = _source_metadata(csv_path)
    except (OSError, UnicodeError, csv.Error):
        source_available = False
        source_sha256 = _EMPTY_SHA256
        record_count = 0
    if tool_version is None:
        try:
            tool_version = _supported_version(profile)
        except ValidationError:
            tool_version = "unavailable"
    return _receipt(
        profile=profile,
        csv_path=csv_path,
        source_sha256=source_sha256,
        record_count=record_count,
        producing_run_id=producing_run_id,
        created_at=created_at,
        started_at=started_at,
        completed_at=completed_at,
        tool_version=tool_version,
        success=False,
        destination=destination,
        error_code=error_code,
        error_message=error_message,
        source_available=source_available,
        remote_attempted=remote_attempted,
    )


def publish_csv(
    csv_path: Path,
    profile: MantisExportProfile,
    destination: PublicationDestination,
    *,
    enabled: bool,
    producing_run_id: str,
    created_at: str,
    started_at: str,
    completed_at: str,
    runner: CommandRunner = _run_command,
) -> MantisPublicationReceipt:
    """Publish one CSV only after an explicit feature gate and record a receipt."""
    if not enabled:
        raise ValidationError(
            "Mantis publication is disabled; pass the explicit publish feature gate."
        )
    observed_version = "unavailable"
    remote_attempted = False
    try:
        expected_version = _supported_version(profile)
        source_sha256, record_count = _source_metadata(csv_path)
        if record_count == 0:
            return _receipt(
                profile=profile,
                csv_path=csv_path,
                source_sha256=source_sha256,
                record_count=0,
                producing_run_id=producing_run_id,
                created_at=created_at,
                started_at=started_at,
                completed_at=completed_at,
                tool_version=expected_version,
                success=False,
                destination=destination,
                error_code="empty_mantis_view",
                error_message=(
                    "Mantis publication skipped because the view has no rows."
                ),
                remote_attempted=False,
            )
        version_result = runner((MANTIS_COMMAND, "--version"))
        observed_version = _extract_version(
            f"{version_result.stdout}\n{version_result.stderr}"
        ) or "unknown"
        if version_result.returncode != 0 or observed_version != expected_version:
            detail = (
                f"Expected mantisai-cli {expected_version}, observed "
                f"{observed_version}."
            )
            return _receipt(
                profile=profile,
                csv_path=csv_path,
                source_sha256=source_sha256,
                record_count=record_count,
                producing_run_id=producing_run_id,
                created_at=created_at,
                started_at=started_at,
                completed_at=completed_at,
                tool_version=observed_version,
                success=False,
                destination=destination,
                error_code="unsupported_mantis_cli_version",
                error_message=detail,
                remote_attempted=False,
            )
        command = build_create_map_command(csv_path, profile, destination)
        remote_attempted = True
        result = runner(command)
        if result.returncode != 0:
            return _receipt(
                profile=profile,
                csv_path=csv_path,
                source_sha256=source_sha256,
                record_count=record_count,
                producing_run_id=producing_run_id,
                created_at=created_at,
                started_at=started_at,
                completed_at=completed_at,
                tool_version=observed_version,
                success=False,
                destination=destination,
                error_code="mantis_cli_failed",
                error_message=result.stderr or result.stdout,
            )
        space_id, map_id, space_uri, map_uri = _parse_creation_output(result.stdout)
        return _receipt(
            profile=profile,
            csv_path=csv_path,
            source_sha256=source_sha256,
            record_count=record_count,
            producing_run_id=producing_run_id,
            created_at=created_at,
            started_at=started_at,
            completed_at=completed_at,
            tool_version=observed_version,
            success=True,
            destination=destination,
            space_id=space_id,
            map_id=map_id,
            space_uri=space_uri,
            map_uri=map_uri,
        )
    except Exception as exc:
        if isinstance(exc, FileNotFoundError):
            error_code = "missing_mantis_view"
        elif isinstance(exc, ValidationError):
            error_code = "invalid_mantis_publication_request"
        elif isinstance(exc, (OSError, UnicodeError, csv.Error)):
            error_code = "mantis_publication_io_error"
        elif isinstance(exc, subprocess.SubprocessError):
            error_code = "mantis_publication_subprocess_error"
        else:
            error_code = "mantis_publication_exception"
        return failure_receipt(
            csv_path,
            profile,
            destination,
            producing_run_id=producing_run_id,
            created_at=created_at,
            started_at=started_at,
            completed_at=completed_at,
            tool_version=observed_version,
            error_code=error_code,
            error_message=str(exc),
            remote_attempted=remote_attempted,
        )
