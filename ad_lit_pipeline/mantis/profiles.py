from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from ad_lit_pipeline.core.errors import ValidationError
from ad_lit_pipeline.io.yaml_io import read_yaml_object
from ad_lit_pipeline.records import (
    SCHEMA_VERSION,
    MantisExportProfile,
    make_payload_record_id,
    record_from_dict,
)
from ad_lit_pipeline.records.ids import canonical_json


DEFAULT_PROFILE_DIRECTORY = (
    Path(__file__).resolve().parents[2] / "configs" / "mantis"
)
PROFILE_TEMPLATE_SCHEMA_VERSION = "1.0.0"

_TOP_LEVEL_FIELDS = {
    "template_schema_version",
    "profile_version",
    "compatibility_version",
    "record_kind",
    "source_contract",
    "source_schema_version",
    "eligible_statuses",
    "point_id_source_path",
    "fields",
    "semantic_text",
    "row_sort_paths",
    "csv_policy",
    "supported_tool_versions",
    "connection_compatibility_verified",
}
_FIELD_FIELDS = {
    "output_name",
    "source_path",
    "mantis_type",
    "required",
    "null_policy",
    "multivalue_policy",
    "separator",
    "semantic_order",
}
_SAFE_ELIGIBLE_STATUSES = {
    "paper": ("active", "corrected"),
    "verified_claim": ("supported", "contradicted"),
    "verified_gap": ("verified_open",),
}


@dataclass(frozen=True)
class ProfileContext:
    """Run envelope needed to compile an immutable export profile record."""

    corpus_snapshot_id: str
    producing_run_id: str
    created_at: str
    producing_step_id: str = "export_mantis_views"


def _require_exact_fields(
    payload: Mapping[str, Any], expected: set[str], *, context: str
) -> None:
    missing = sorted(expected - set(payload))
    unknown = sorted(set(payload) - expected)
    if missing or unknown:
        raise ValidationError(
            f"{context} fields do not match the profile contract: "
            f"missing={missing}, unknown={unknown}."
        )


def _validate_template(payload: Mapping[str, Any], *, context: str) -> None:
    _require_exact_fields(payload, _TOP_LEVEL_FIELDS, context=context)
    if payload["template_schema_version"] != PROFILE_TEMPLATE_SCHEMA_VERSION:
        raise ValidationError(
            f"Unsupported Mantis template schema in {context}: "
            f"{payload['template_schema_version']!r}."
        )
    record_kind = payload["record_kind"]
    if record_kind not in _SAFE_ELIGIBLE_STATUSES:
        raise ValidationError(f"Unsupported Mantis record kind in {context}.")
    eligible = payload["eligible_statuses"]
    if not isinstance(eligible, list) or tuple(eligible) != _SAFE_ELIGIBLE_STATUSES[record_kind]:
        raise ValidationError(
            f"Mantis profile {context} must use the scientific eligibility "
            f"statuses {_SAFE_ELIGIBLE_STATUSES[record_kind]}."
        )
    fields = payload["fields"]
    if not isinstance(fields, list) or not fields:
        raise ValidationError(f"Mantis profile {context} requires non-empty fields.")
    for index, field in enumerate(fields):
        if not isinstance(field, Mapping):
            raise ValidationError(f"{context} fields[{index}] must be an object.")
        _require_exact_fields(
            field,
            _FIELD_FIELDS,
            context=f"{context} fields[{index}]",
        )
    if any(field["mantis_type"] == "Connection" for field in fields):
        raise ValidationError(
            f"Mantis profile {context} cannot use Connection in compatibility v1."
        )


def load_profile_template(path: Path) -> dict[str, Any]:
    """Load one strict Mantis profile template without silently defaulting."""
    try:
        payload = read_yaml_object(path)
    except (OSError, ValueError) as exc:
        raise ValidationError(f"Could not load Mantis profile {path}: {exc}") from exc
    _validate_template(payload, context=str(path))
    return payload


def template_sha256(template: Mapping[str, Any]) -> str:
    return hashlib.sha256(canonical_json(template).encode("utf-8")).hexdigest()


def compile_profile(
    template: Mapping[str, Any], context: ProfileContext
) -> MantisExportProfile:
    """Compile and validate a snapshot-bound profile record."""
    _validate_template(template, context="Mantis template")
    digest = template_sha256(template)
    body = {key: value for key, value in template.items() if key != "template_schema_version"}
    payload: dict[str, Any] = {
        "record_type": "mantis_export_profile",
        "schema_version": SCHEMA_VERSION,
        "record_id": "pending",
        "created_at": context.created_at,
        "corpus_snapshot_id": context.corpus_snapshot_id,
        "producing_run_id": context.producing_run_id,
        "producing_step_id": context.producing_step_id,
        "parent_record_ids": [],
        "source_record_ids": [],
        "provenance": [
            {
                "kind": "artifact",
                "relation": "compiled_from_mantis_profile_template",
                "reference": (
                    f"configs/mantis/{body['record_kind']}_v1.yaml"
                ),
                "sha256": digest,
            }
        ],
        "record_status": "active",
        "validation_warnings": [],
        "policy_versions": {
            "record_contracts": SCHEMA_VERSION,
            "mantis_profile_template": PROFILE_TEMPLATE_SCHEMA_VERSION,
        },
        "extensions": {
            "mantis.profile_template": {
                "template_sha256": digest,
                "connection_fields_disabled": True,
            }
        },
        **body,
    }
    payload["record_id"] = make_payload_record_id(
        "mantis_export_profile", payload, schema_version=SCHEMA_VERSION
    )
    record = record_from_dict(payload)
    if not isinstance(record, MantisExportProfile):
        raise AssertionError("Mantis profile decoder returned an unexpected record.")
    return record
