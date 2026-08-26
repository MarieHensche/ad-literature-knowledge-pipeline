from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ad_lit_pipeline.core.errors import ValidationError
from ad_lit_pipeline.knowledge.schemas import (
    EVIDENCE_EXCERPT_CONTRACT,
    FIELD_SUMMARY_CONTRACT,
    FINDING_CONTRACT,
    GAP_CONTRACT,
    RELATIONSHIP_CONTRACT,
    SOURCE_CONTRACT,
    SYNTHESIS_CLAIM_CONTRACT,
    RecordContract,
)


def validate_record(
    record: Mapping[str, Any],
    contract: RecordContract,
) -> None:
    """Validate one knowledge-layer record against its contract."""
    if not isinstance(record, Mapping):
        raise ValidationError(f"{contract.name} must be a JSON object.")

    missing = [field for field in contract.required_fields if field not in record]
    if missing:
        raise ValidationError(
            f"{contract.name} missing required fields: {', '.join(missing)}"
        )

    for field in contract.non_empty_fields:
        value = record.get(field)
        if value is None:
            raise ValidationError(f"{contract.name}.{field} must be non-empty.")
        if isinstance(value, str) and not value.strip():
            raise ValidationError(f"{contract.name}.{field} must be non-empty.")

    for field in contract.list_fields:
        if not isinstance(record.get(field), list):
            raise ValidationError(f"{contract.name}.{field} must be a list.")

    for field in contract.string_list_fields:
        values = record.get(field)
        if not isinstance(values, list):
            raise ValidationError(f"{contract.name}.{field} must be a list.")
        for index, value in enumerate(values, start=1):
            if not isinstance(value, str) or not value.strip():
                raise ValidationError(
                    f"{contract.name}.{field}[{index}] must be a non-empty string."
                )

    for field, allowed_values in (contract.controlled_fields or {}).items():
        value = record.get(field)
        if value not in allowed_values:
            joined = ", ".join(allowed_values)
            raise ValidationError(
                f"{contract.name}.{field} must be one of: {joined}"
            )


def validate_records(
    records: list[Mapping[str, Any]],
    contract: RecordContract,
) -> None:
    """Validate a list of records and include row context in failures."""
    for index, record in enumerate(records, start=1):
        try:
            validate_record(record, contract)
        except ValidationError as exc:
            raise ValidationError(
                f"{contract.name} record {index} is invalid: {exc}"
            ) from exc


def validate_source(record: Mapping[str, Any]) -> None:
    validate_record(record, SOURCE_CONTRACT)


def validate_evidence_excerpt(record: Mapping[str, Any]) -> None:
    validate_record(record, EVIDENCE_EXCERPT_CONTRACT)


def validate_finding(record: Mapping[str, Any]) -> None:
    validate_record(record, FINDING_CONTRACT)


def validate_relationship(record: Mapping[str, Any]) -> None:
    validate_record(record, RELATIONSHIP_CONTRACT)


def validate_gap(record: Mapping[str, Any]) -> None:
    validate_record(record, GAP_CONTRACT)


def validate_synthesis_claim(record: Mapping[str, Any]) -> None:
    validate_record(record, SYNTHESIS_CLAIM_CONTRACT)


def validate_field_summary(record: Mapping[str, Any]) -> None:
    validate_record(record, FIELD_SUMMARY_CONTRACT)

    for field in ("source_count", "finding_count"):
        value = record.get(field)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValidationError(
                f"FieldSummary.{field} must be a non-negative integer."
            )