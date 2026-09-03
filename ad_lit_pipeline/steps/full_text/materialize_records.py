from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import tempfile
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from ad_lit_pipeline.core.step import StepResult, StepSpec
from ad_lit_pipeline.records import (
    SCHEMA_VERSION,
    canonical_json,
    make_payload_record_id,
    make_record_id,
    normalize_utc_timestamp,
    read_record_jsonl,
    record_from_dict,
    record_to_dict,
    validate_record_artifacts,
)
from ad_lit_pipeline.records.models import (
    AccessLocation,
    CorpusSnapshot,
    Document,
    Passage,
    RecordEnvelope,
    SourceVersion,
)
from ad_lit_pipeline.steps.full_text.passages import (
    PASSAGE_SEGMENTATION_VERSION,
    REPRESENTATION_SCHEMA_VERSION,
    extraction_config_sha256,
    passage_slices,
    read_representation_structure,
    sha256_text,
)


STEP = StepSpec(
    name="materialize_document_passages",
    inputs=["corpus_records_jsonl", "full_text_manifest_csv"],
    outputs=[
        "corpus_document_records_jsonl",
        "document_passage_integrity_json",
    ],
    uses_llm=False,
    description=(
        "Materialize exact source documents and resolvable passages against a "
        "frozen corpus snapshot."
    ),
)

DOCUMENT_MATERIALIZATION_POLICY_VERSION = "1.0.0"
DOCUMENT_INTEGRITY_SCHEMA_VERSION = "1.0.0"
MATERIALIZATION_EXTENSION = "pipeline.document_materialization"
TEXT_REPRESENTATION_EXTENSION = "pipeline.text_representation"
PRODUCING_STEP_ID = STEP.name
ELIGIBLE_IDENTITY_STATUSES = frozenset(
    {"trusted_local", "verified_doi", "verified_title"}
)
SHA256 = re.compile(r"^[0-9a-f]{64}$")
PRIVATE_ACCESS_QUERY_KEY = re.compile(
    r"(?:^|[_-])(api[_-]?key|authorization|cookie|credential|email|key|mailto|"
    r"password|secret|signature|token)(?:$|[_-])",
    re.IGNORECASE,
)


class DocumentMaterializationError(ValueError):
    def __init__(self, issues: Sequence[Mapping[str, Any]]) -> None:
        self.issues = tuple(dict(issue) for issue in issues)
        first = self.issues[0] if self.issues else {"message": "unknown failure"}
        super().__init__(
            "Document materialization denied: "
            + str(first.get("message") or first)
        )


def _issue(code: str, message: str, **context: Any) -> dict[str, Any]:
    return {
        "code": code,
        "message": message,
        **{key: value for key, value in context.items() if value is not None},
    }


def _now_utc() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _atomic_write(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
    finally:
        if temporary_path.exists():
            temporary_path.unlink()


def _json_bytes(value: Mapping[str, Any]) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")


def _records_bytes(records: Sequence[RecordEnvelope]) -> bytes:
    return b"".join(
        canonical_json(record_to_dict(record)).encode("utf-8") + b"\n"
        for record in records
    )


def _artifact_reference(path: Path, artifact_root: Path) -> str:
    resolved = path.resolve()
    root = artifact_root.resolve()
    if not resolved.is_relative_to(root):
        raise ValueError(f"Artifact {resolved} is outside artifact root {root}.")
    return resolved.relative_to(root).as_posix()


def _read_manifest(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _placeholder_id(record_type: str) -> str:
    return make_record_id(
        record_type,
        {"phase": "materialize_document_passages", "record_type": record_type},
        schema_version=SCHEMA_VERSION,
    )


def _base_payload(
    record_type: str,
    *,
    snapshot_id: str,
    created_at: str,
    producing_run_id: str,
    parent_record_ids: Sequence[str],
    source_record_ids: Sequence[str],
    provenance: Sequence[Mapping[str, Any]],
    extensions: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "record_type": record_type,
        "schema_version": SCHEMA_VERSION,
        "record_id": _placeholder_id(record_type),
        "created_at": created_at,
        "corpus_snapshot_id": snapshot_id,
        "producing_run_id": producing_run_id,
        "producing_step_id": PRODUCING_STEP_ID,
        "parent_record_ids": sorted(set(parent_record_ids)),
        "source_record_ids": sorted(set(source_record_ids)),
        "provenance": [dict(item) for item in provenance],
        "record_status": "active",
        "validation_warnings": [],
        "policy_versions": {
            "record_contracts": SCHEMA_VERSION,
            "document_materialization": DOCUMENT_MATERIALIZATION_POLICY_VERSION,
        },
        "extensions": dict(extensions or {}),
    }


def _refresh_id(payload: dict[str, Any]) -> str:
    record_id = make_payload_record_id(
        str(payload["record_type"]),
        payload,
        schema_version=str(payload["schema_version"]),
    )
    payload["record_id"] = record_id
    return record_id


def _provenance(reference: str, sha256: str, relation: str) -> dict[str, Any]:
    return {
        "kind": "artifact",
        "relation": relation,
        "reference": reference,
        "sha256": sha256,
    }


def _safe_access_uri(value: str) -> str:
    candidate = str(value or "").strip()
    parsed = urlsplit(candidate)
    if parsed.scheme in {"http", "https"}:
        hostname = parsed.hostname or ""
        if ":" in hostname and not hostname.startswith("["):
            hostname = f"[{hostname}]"
        port = f":{parsed.port}" if parsed.port is not None else ""
        query = [
            (key, item)
            for key, item in parse_qsl(parsed.query, keep_blank_values=True)
            if not PRIVATE_ACCESS_QUERY_KEY.search(key)
        ]
        return urlunsplit(
            (
                parsed.scheme.casefold(),
                f"{hostname.casefold()}{port}",
                parsed.path,
                urlencode(query, doseq=True),
                "",
            )
        )
    return candidate


def _parse_bool(value: Any) -> bool | None:
    normalized = str(value or "").strip().casefold()
    if normalized in {"true", "yes", "1"}:
        return True
    if normalized in {"false", "no", "0"}:
        return False
    return None


def _integer(value: Any, *, field: str, allow_empty: bool = False) -> int | None:
    if value in (None, "") and allow_empty:
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be an integer.") from exc
    if parsed < 0:
        raise ValueError(f"{field} must not be negative.")
    return parsed


def _copy_content_addressed(
    source: Path,
    destination_dir: Path,
    *,
    sha256: str,
    suffix: str,
) -> Path:
    destination = destination_dir / f"{sha256}{suffix}"
    if destination.exists():
        if _sha256_file(destination) != sha256:
            raise ValueError(f"Existing content-addressed artifact is corrupt: {destination}")
        return destination
    _atomic_write(destination, source.read_bytes())
    if _sha256_file(destination) != sha256:
        raise ValueError(f"Copied artifact hash verification failed: {destination}")
    return destination


def _suffix(media_type: str) -> str:
    return {
        "application/pdf": ".pdf",
        "text/html": ".html",
        "application/xhtml+xml": ".html",
        "text/plain": ".txt",
    }.get(media_type, ".bin")


def _paper_id(source_version: SourceVersion) -> str:
    extension = source_version.extensions.get("pipeline.corpus_materialization")
    if not isinstance(extension, Mapping):
        return ""
    return str(extension.get("paper_id") or "").strip()


def _access_payload(
    *,
    source_version: SourceVersion,
    uri: str,
    observed_at: str,
    media_type: str,
    license_value: str | None,
    is_open_access: bool | None,
    created_at: str,
    producing_run_id: str,
) -> dict[str, Any]:
    payload = _base_payload(
        "access_location",
        snapshot_id=source_version.corpus_snapshot_id,
        created_at=created_at,
        producing_run_id=producing_run_id,
        parent_record_ids=[source_version.record_id],
        source_record_ids=[],
        provenance=[
            {
                "kind": "external",
                "relation": "resolved_full_text_location",
                "reference": uri,
                "sha256": None,
            }
        ],
        extensions={
            MATERIALIZATION_EXTENSION: {
                "observation_source": "full_text_resolution",
                "identity_verified": True,
            }
        },
    )
    local = not urlsplit(uri).scheme.startswith("http")
    payload.update(
        {
            "source_version_id": source_version.record_id,
            "provider_record_id": None,
            "uri": uri,
            "uri_sha256": _sha256_bytes(uri.encode("utf-8")),
            "location_kind": (
                "pdf"
                if media_type == "application/pdf"
                else "html"
                if media_type in {"text/html", "application/xhtml+xml"}
                else "landing_page"
            ),
            "access_method": "local_file" if local else "public_http",
            "observed_at": observed_at,
            "access_status": "available",
            "media_type": media_type,
            "license": license_value,
            "is_open_access": is_open_access,
            "http_status": None,
            "redirect_uri": None,
            "failure_reason": None,
        }
    )
    _refresh_id(payload)
    return payload


def _document_and_passages(
    *,
    row: Mapping[str, str],
    source_version: SourceVersion,
    access_location_id: str,
    artifact_root: Path,
    run_artifacts_dir: Path,
    created_at: str,
    producing_run_id: str,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    paper_id = str(row.get("paper_id") or "").strip()
    identity_status = str(row.get("full_text_identity_status") or "").strip()
    if identity_status not in ELIGIBLE_IDENTITY_STATUSES:
        raise ValueError(
            f"identity status {identity_status!r} is not document-eligible"
        )
    if str(row.get("full_text_usable_for_tagging") or "").casefold() != "yes":
        raise ValueError("full text is not marked usable")
    if _parse_bool(row.get("full_text_encrypted")) is True:
        raise ValueError("encrypted source bytes cannot produce a stored document")

    source_path = Path(str(row.get("full_text_source_artifact_path") or "")).expanduser()
    text_path = Path(str(row.get("full_text_text_path") or "")).expanduser()
    structure_path = Path(str(row.get("full_text_structure_path") or "")).expanduser()
    for label, path in (
        ("source artifact", source_path),
        ("text representation", text_path),
        ("representation structure", structure_path),
    ):
        if not str(path) or not path.is_file():
            raise ValueError(f"{label} is missing: {path}")

    source_sha256 = str(row.get("full_text_source_sha256") or "")
    text_sha256 = str(row.get("full_text_text_sha256") or "")
    structure_sha256 = str(row.get("full_text_structure_sha256") or "")
    if not all(SHA256.fullmatch(value) for value in (
        source_sha256,
        text_sha256,
        structure_sha256,
    )):
        raise ValueError("source, text, and structure SHA-256 values are required")
    source_size = _integer(
        row.get("full_text_source_byte_size"),
        field="full_text_source_byte_size",
    )
    assert source_size is not None
    if _sha256_file(source_path) != source_sha256:
        raise ValueError("source artifact hash mismatch")
    if source_path.stat().st_size != source_size:
        raise ValueError("source artifact byte-size mismatch")
    representation = text_path.read_text(encoding="utf-8")
    if sha256_text(representation) != text_sha256:
        raise ValueError("text representation hash mismatch")
    if _sha256_file(structure_path) != structure_sha256:
        raise ValueError("representation structure hash mismatch")
    page_spans = read_representation_structure(
        structure_path,
        representation_sha256=text_sha256,
    )
    if page_spans and page_spans[-1].end_char > len(representation):
        raise ValueError("page span exceeds the text representation")

    media_type = str(row.get("full_text_source_media_type") or "").strip()
    if not media_type:
        raise ValueError("source media type is missing")
    retrieved_at = normalize_utc_timestamp(
        str(row.get("full_text_retrieved_at") or ""),
        context=f"{paper_id}.full_text_retrieved_at",
    )
    page_count = _integer(
        row.get("full_text_page_count"),
        field="full_text_page_count",
        allow_empty=True,
    )
    if page_count == 0:
        raise ValueError("full_text_page_count must be positive when present")
    if media_type == "application/pdf" and (
        page_count is None or not page_spans
    ):
        raise ValueError(
            "PDF document lacks independently resolvable page boundaries"
        )
    if (
        page_spans
        and page_count is not None
        and page_spans[-1].page_number > page_count
    ):
        raise ValueError("page span exceeds the declared PDF page count")

    source_copy = _copy_content_addressed(
        source_path,
        run_artifacts_dir / "source",
        sha256=source_sha256,
        suffix=_suffix(media_type),
    )
    text_copy = _copy_content_addressed(
        text_path,
        run_artifacts_dir / "representations",
        sha256=text_sha256,
        suffix=".txt",
    )
    structure_copy = _copy_content_addressed(
        structure_path,
        run_artifacts_dir / "representations",
        sha256=structure_sha256,
        suffix=".json",
    )
    source_reference = _artifact_reference(source_copy, artifact_root)
    text_reference = _artifact_reference(text_copy, artifact_root)
    structure_reference = _artifact_reference(structure_copy, artifact_root)

    document_payload = _base_payload(
        "document",
        snapshot_id=source_version.corpus_snapshot_id,
        created_at=created_at,
        producing_run_id=producing_run_id,
        parent_record_ids=[source_version.record_id],
        source_record_ids=[access_location_id],
        provenance=[
            _provenance(source_reference, source_sha256, "stored_exact_source_bytes"),
            _provenance(
                text_reference,
                text_sha256,
                "extracted_normalized_text_representation",
            ),
        ],
        extensions={
            MATERIALIZATION_EXTENSION: {
                "paper_id": paper_id,
                "identity_status": identity_status,
                "identity_evidence": str(
                    row.get("full_text_identity_evidence") or ""
                ),
                "structure_artifact_uri": structure_reference,
                "structure_sha256": structure_sha256,
            },
            TEXT_REPRESENTATION_EXTENSION: {
                "artifact_uri": text_reference,
                "sha256": text_sha256,
                "encoding": "utf-8",
                "structure_artifact_uri": structure_reference,
                "structure_sha256": structure_sha256,
                "structure_schema_version": REPRESENTATION_SCHEMA_VERSION,
            },
        },
    )
    document_payload.update(
        {
            "source_version_id": source_version.record_id,
            "access_location_id": access_location_id,
            "document_role": "main",
            "media_type": media_type,
            "language": source_version.language,
            "content_sha256": source_sha256,
            "byte_size": source_size,
            "retrieved_at": retrieved_at,
            "artifact_uri": source_reference,
            "license": str(row.get("full_text_resolved_license") or "").strip()
            or None,
            "document_status": "stored",
            "page_count": page_count,
            "encrypted": False,
        }
    )
    document_id = _refresh_id(document_payload)

    extractor_name = str(row.get("full_text_extraction_engine") or "").strip()
    extractor_version = str(
        row.get("full_text_extraction_engine_version") or ""
    ).strip()
    if not extractor_name or not extractor_version:
        raise ValueError("extractor name and version are required")
    config_hash = extraction_config_sha256(4_000)
    passage_payloads: list[dict[str, Any]] = []
    for passage in passage_slices(representation, page_spans):
        payload = _base_payload(
            "passage",
            snapshot_id=source_version.corpus_snapshot_id,
            created_at=created_at,
            producing_run_id=producing_run_id,
            parent_record_ids=[document_id],
            source_record_ids=[source_version.record_id],
            provenance=[
                _provenance(
                    text_reference,
                    text_sha256,
                    "located_in_normalized_text_representation",
                )
            ],
            extensions={
                MATERIALIZATION_EXTENSION: {
                    "segmentation_version": PASSAGE_SEGMENTATION_VERSION,
                    "paper_id": paper_id,
                }
            },
        )
        payload.update(
            {
                "document_id": document_id,
                "source_version_id": source_version.record_id,
                "sequence_index": passage.sequence_index,
                "passage_kind": passage.passage_kind,
                "text": passage.text,
                "text_sha256": sha256_text(passage.text),
                "language": source_version.language,
                "section_path": list(passage.section_path),
                "locator": {
                    "coordinate_system": "utf8_decoded_unicode_codepoints_v1",
                    "representation_sha256": text_sha256,
                    "start_char": passage.start_char,
                    "end_char": passage.end_char,
                    "page_start": passage.page_start,
                    "page_end": passage.page_end,
                    "paragraph_index": passage.paragraph_index,
                },
                "extractor_name": extractor_name,
                "extractor_version": extractor_version,
                "extraction_config_sha256": config_hash,
                "extracted_at": created_at,
            }
        )
        _refresh_id(payload)
        passage_payloads.append(payload)
    if not passage_payloads:
        raise ValueError("normalized representation produced no passages")
    return document_payload, passage_payloads


def materialize(
    *,
    corpus_records_path: Path,
    full_text_manifest_path: Path,
    producing_run_id: str,
    artifact_root: Path,
    run_artifacts_dir: Path,
    created_at: str | None = None,
) -> tuple[tuple[RecordEnvelope, ...], dict[str, Any]]:
    root = artifact_root.resolve()
    run_dir = run_artifacts_dir.resolve()
    if not run_dir.is_relative_to(root):
        raise DocumentMaterializationError(
            [_issue("artifact_path_escape", "Run artifact directory is outside root.")]
        )
    input_integrity = validate_record_artifacts(
        [corpus_records_path],
        artifact_root=root,
        verify_local_artifacts=True,
    )
    if not input_integrity.is_valid:
        raise DocumentMaterializationError(
            [
                _issue(issue.code, issue.message, record_id=issue.record_id)
                for issue in input_integrity.errors
            ]
        )
    records = list(read_record_jsonl(corpus_records_path))
    if any(isinstance(record, (Document, Passage)) for record in records):
        raise DocumentMaterializationError(
            [
                _issue(
                    "document_records_already_present",
                    "Input corpus already contains Document or Passage records.",
                )
            ]
        )
    snapshots = [record for record in records if isinstance(record, CorpusSnapshot)]
    if len(snapshots) != 1 or snapshots[0].snapshot_status.value != "frozen":
        raise DocumentMaterializationError(
            [_issue("frozen_snapshot_required", "Exactly one frozen snapshot is required.")]
        )
    snapshot = snapshots[0]
    source_versions = [
        record for record in records if isinstance(record, SourceVersion)
    ]
    accesses = [record for record in records if isinstance(record, AccessLocation)]
    manifest = _read_manifest(full_text_manifest_path)
    rows_by_paper: dict[str, Mapping[str, str]] = {}
    duplicate_ids: set[str] = set()
    for row in manifest:
        paper_id = str(row.get("paper_id") or "").strip()
        if not paper_id:
            continue
        if paper_id in rows_by_paper:
            duplicate_ids.add(paper_id)
        rows_by_paper[paper_id] = row
    if duplicate_ids:
        raise DocumentMaterializationError(
            [
                _issue(
                    "duplicate_manifest_paper_id",
                    f"Full-text manifest repeats paper_id {paper_id!r}.",
                )
                for paper_id in sorted(duplicate_ids)
            ]
        )

    generated_at = normalize_utc_timestamp(
        created_at or _now_utc(),
        context="document materialization created_at",
    )
    access_by_key = {
        (record.source_version_id, _safe_access_uri(record.uri)): record
        for record in accesses
    }
    new_access_payloads: list[dict[str, Any]] = []
    document_payloads: list[dict[str, Any]] = []
    passage_payloads: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    for source_version in source_versions:
        paper_id = _paper_id(source_version)
        row = rows_by_paper.get(paper_id)
        if row is None:
            failures.append(
                _issue(
                    "full_text_manifest_row_missing",
                    "No full-text manifest row resolves to this source version.",
                    paper_id=paper_id or None,
                    source_version_id=source_version.record_id,
                )
            )
            continue
        status = str(row.get("full_text_status") or "").strip()
        if str(row.get("full_text_usable_for_tagging") or "").casefold() != "yes":
            failures.append(
                _issue(
                    "document_not_materialized",
                    f"Full-text status {status!r} is not eligible.",
                    paper_id=paper_id,
                    source_version_id=source_version.record_id,
                )
            )
            continue
        try:
            retrieved_at = normalize_utc_timestamp(
                str(row.get("full_text_retrieved_at") or ""),
                context=f"{paper_id}.full_text_retrieved_at",
            )
            media_type = str(
                row.get("full_text_source_media_type") or ""
            ).strip()
            resolved_uri = _safe_access_uri(
                str(
                    row.get("full_text_resolved_url")
                    or row.get("full_text_source_artifact_path")
                    or ""
                )
            )
            if not resolved_uri:
                raise ValueError("resolved source URI is missing")
            key = (source_version.record_id, resolved_uri)
            access = access_by_key.get(key)
            pending_access_payload: dict[str, Any] | None = None
            if access is None:
                pending_access_payload = _access_payload(
                    source_version=source_version,
                    uri=resolved_uri,
                    observed_at=retrieved_at,
                    media_type=media_type,
                    license_value=str(
                        row.get("full_text_resolved_license") or ""
                    ).strip()
                    or None,
                    is_open_access=_parse_bool(
                        row.get("full_text_is_open_access")
                    ),
                    created_at=generated_at,
                    producing_run_id=producing_run_id,
                )
                access_id = str(pending_access_payload["record_id"])
            else:
                access_id = access.record_id
            document_payload, passages = _document_and_passages(
                row=row,
                source_version=source_version,
                access_location_id=access_id,
                artifact_root=root,
                run_artifacts_dir=run_dir,
                created_at=generated_at,
                producing_run_id=producing_run_id,
            )
            if pending_access_payload is not None:
                new_access_payloads.append(pending_access_payload)
            document_payloads.append(document_payload)
            passage_payloads.extend(passages)
        except (OSError, TypeError, ValueError) as exc:
            failures.append(
                _issue(
                    "document_not_materialized",
                    str(exc),
                    paper_id=paper_id,
                    source_version_id=source_version.record_id,
                )
            )

    additions = [
        *sorted(new_access_payloads, key=lambda item: str(item["record_id"])),
        *sorted(document_payloads, key=lambda item: str(item["record_id"])),
        *sorted(passage_payloads, key=lambda item: str(item["record_id"])),
    ]
    combined = tuple([*records, *(record_from_dict(item) for item in additions)])
    summary = {
        "snapshot_id": snapshot.record_id,
        "source_versions": len(source_versions),
        "new_access_locations": len(new_access_payloads),
        "documents": len(document_payloads),
        "passages": len(passage_payloads),
        "failures": failures,
        "input_integrity": input_integrity.to_dict(),
    }
    return combined, summary


def _failure_report(
    *,
    generated_at: str,
    producing_run_id: str,
    issues: Sequence[Mapping[str, Any]],
    output_path: Path,
) -> dict[str, Any]:
    stale = output_path.exists()
    return {
        "record_type": "document_passage_integrity_report",
        "schema_version": DOCUMENT_INTEGRITY_SCHEMA_VERSION,
        "generated_at": generated_at,
        "producing_run_id": producing_run_id,
        "producing_step_id": PRODUCING_STEP_ID,
        "status": "failed",
        "issues": [dict(item) for item in issues],
        "record_integrity": None,
        "output": {
            "records_written": False,
            "path": str(output_path),
            "stale_existing_artifact_preserved": stale,
            "stale_existing_sha256": _sha256_file(output_path) if stale else None,
        },
    }


def run(
    corpus_records_path: Path,
    full_text_manifest_path: Path,
    output_path: Path,
    integrity_report_path: Path,
    producing_run_id: str,
    *,
    artifact_root: Path = Path("."),
    run_artifacts_dir: Path | None = None,
    created_at: str | None = None,
) -> StepResult:
    generated_at = normalize_utc_timestamp(
        created_at or _now_utc(),
        context="document materialization generated_at",
    )
    target_artifacts = run_artifacts_dir or (
        artifact_root / "runs" / producing_run_id / "artifacts" / "documents"
    )
    inputs = {
        "corpus_records_jsonl": corpus_records_path,
        "full_text_manifest_csv": full_text_manifest_path,
    }
    try:
        records, summary = materialize(
            corpus_records_path=corpus_records_path,
            full_text_manifest_path=full_text_manifest_path,
            producing_run_id=producing_run_id,
            artifact_root=artifact_root,
            run_artifacts_dir=target_artifacts,
            created_at=generated_at,
        )
    except (DocumentMaterializationError, OSError, TypeError, ValueError) as exc:
        issues = (
            exc.issues
            if isinstance(exc, DocumentMaterializationError)
            else (_issue("document_materialization_error", str(exc)),)
        )
        report = _failure_report(
            generated_at=generated_at,
            producing_run_id=producing_run_id,
            issues=issues,
            output_path=output_path,
        )
        _atomic_write(integrity_report_path, _json_bytes(report))
        return StepResult(
            step_name=STEP.name,
            inputs=inputs,
            outputs={"document_passage_integrity_json": integrity_report_path},
            error=str(exc),
            metadata={"status": "failed", "issue_count": len(issues)},
        )

    serialized = _records_bytes(records)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=output_path.parent,
        prefix=f".{output_path.name}.",
        suffix=".candidate",
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(serialized)
            handle.flush()
            os.fsync(handle.fileno())
        integrity = validate_record_artifacts(
            [temporary_path],
            artifact_root=artifact_root,
            verify_local_artifacts=True,
        )
        if not integrity.is_valid:
            issues = [
                _issue(issue.code, issue.message, record_id=issue.record_id)
                for issue in integrity.errors
            ]
            report = _failure_report(
                generated_at=generated_at,
                producing_run_id=producing_run_id,
                issues=issues,
                output_path=output_path,
            )
            report["record_integrity"] = integrity.to_dict()
            _atomic_write(integrity_report_path, _json_bytes(report))
            return StepResult(
                step_name=STEP.name,
                inputs=inputs,
                outputs={"document_passage_integrity_json": integrity_report_path},
                error="Document and passage record integrity validation failed.",
                metadata={"status": "failed", "issue_count": len(issues)},
            )
        os.replace(temporary_path, output_path)
    finally:
        if temporary_path.exists():
            temporary_path.unlink()

    failures = list(summary["failures"])
    output_sha256 = _sha256_bytes(serialized)
    report = {
        "record_type": "document_passage_integrity_report",
        "schema_version": DOCUMENT_INTEGRITY_SCHEMA_VERSION,
        "generated_at": generated_at,
        "producing_run_id": producing_run_id,
        "producing_step_id": PRODUCING_STEP_ID,
        "status": "complete_with_failures" if failures else "complete",
        "snapshot_id": summary["snapshot_id"],
        "materialization": {
            "source_versions": summary["source_versions"],
            "new_access_locations": summary["new_access_locations"],
            "documents": summary["documents"],
            "passages": summary["passages"],
            "failures": failures,
        },
        "input_integrity": summary["input_integrity"],
        "record_integrity": integrity.to_dict(),
        "output": {
            "records_written": True,
            "path": str(output_path),
            "sha256": output_sha256,
            "byte_count": len(serialized),
        },
    }
    _atomic_write(integrity_report_path, _json_bytes(report))
    warnings = [
        f"{item.get('paper_id') or item.get('source_version_id')}: "
        f"{item['message']}"
        for item in failures
    ]
    return StepResult(
        step_name=STEP.name,
        inputs=inputs,
        outputs={
            "corpus_document_records_jsonl": output_path,
            "document_passage_integrity_json": integrity_report_path,
        },
        row_counts={
            "source_versions": int(summary["source_versions"]),
            "documents": int(summary["documents"]),
            "passages": int(summary["passages"]),
            "document_failures": len(failures),
        },
        warnings=warnings,
        metadata={
            "status": report["status"],
            "snapshot_id": summary["snapshot_id"],
            "records_sha256": output_sha256,
            "integrity_error_count": len(integrity.errors),
            "integrity_warning_count": len(integrity.warnings),
        },
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Materialize strict v1 Document and Passage records."
    )
    parser.add_argument("--corpus-records", required=True)
    parser.add_argument("--full-text-manifest", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--integrity-report", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--artifact-root", default=".")
    parser.add_argument("--run-artifacts-dir")
    args = parser.parse_args()
    result = run(
        Path(args.corpus_records),
        Path(args.full_text_manifest),
        Path(args.output),
        Path(args.integrity_report),
        args.run_id,
        artifact_root=Path(args.artifact_root),
        run_artifacts_dir=(
            Path(args.run_artifacts_dir) if args.run_artifacts_dir else None
        ),
    )
    if result.error:
        raise SystemExit(result.error)
    print(f"Documents: {result.row_counts['documents']}")
    print(f"Passages: {result.row_counts['passages']}")


if __name__ == "__main__":
    main()
