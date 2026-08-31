from __future__ import annotations

import hashlib
import json
import math
import re
import unicodedata
from collections.abc import Mapping
from types import MappingProxyType
from typing import Any

from ad_lit_pipeline.core.errors import ValidationError


RECORD_ID_PREFIXES: Mapping[str, str] = MappingProxyType({
    "corpus_snapshot": "snap",
    "scholarly_work": "work",
    "source_version": "srcv",
    "provider_record": "prov",
    "access_location": "access",
    "document": "doc",
    "passage": "passage",
    "entity": "entity",
    "claim": "claim",
    "claim_evidence": "clev",
    "relationship": "rel",
    "gap_signal": "signal",
    "gap_candidate": "gap",
    "verification_attempt": "verify",
    "gap_score": "score",
    "expert_judgment": "judgment",
    "outcome_event": "outcome",
    "mantis_export_profile": "mprofile",
    "mantis_interpretation": "minterp",
    "mantis_publication_receipt": "mreceipt",
})

_PREFIX_TO_RECORD_TYPE = {
    prefix: record_type for record_type, prefix in RECORD_ID_PREFIXES.items()
}
_RECORD_ID_PATTERN = re.compile(
    r"^(?P<prefix>[a-z][a-z0-9]*)_(?P<digest>[0-9a-f]{64})$"
)


def _normalize_json(value: Any, *, path: str) -> Any:
    if value is None or isinstance(value, bool | int):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValidationError(
                f"Canonical JSON value at {path} must be a finite number."
            )
        return value
    if isinstance(value, str):
        return unicodedata.normalize("NFC", value)
    if isinstance(value, Mapping):
        normalized: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise ValidationError(
                    f"Canonical JSON object key at {path} must be a string."
                )
            normalized_key = unicodedata.normalize("NFC", key)
            if normalized_key in normalized:
                raise ValidationError(
                    "Canonical JSON contains object keys that collide after NFC "
                    f"normalization at {path}: {normalized_key!r}."
                )
            normalized[normalized_key] = _normalize_json(
                item,
                path=f"{path}.{normalized_key}",
            )
        return normalized
    if isinstance(value, (list, tuple)):
        return [
            _normalize_json(item, path=f"{path}[{index}]")
            for index, item in enumerate(value)
        ]
    raise ValidationError(
        f"Canonical JSON value at {path} has unsupported type "
        f"{type(value).__name__}."
    )


def canonical_json(payload: Any) -> str:
    """Serialize a JSON-compatible value in a deterministic, NFC-normalized form."""
    normalized = _normalize_json(payload, path="payload")
    try:
        return json.dumps(
            normalized,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    except (TypeError, ValueError) as exc:
        raise ValidationError(f"Could not serialize canonical JSON: {exc}") from exc


def record_id_prefix(record_type: str) -> str:
    """Return the stable ID prefix for one supported record type."""
    if not isinstance(record_type, str) or not record_type.strip():
        raise ValidationError("Record type must be a non-empty string.")
    normalized = unicodedata.normalize("NFC", record_type.strip())
    prefix = RECORD_ID_PREFIXES.get(normalized)
    if prefix is None:
        supported = ", ".join(RECORD_ID_PREFIXES)
        raise ValidationError(
            f"Unsupported record type {normalized!r}; expected one of: {supported}."
        )
    return prefix


def make_record_id(
    record_type: str,
    identity: Mapping[str, Any],
    *,
    schema_version: str,
) -> str:
    """Create a deterministic typed ID from schema-versioned identity fields."""
    prefix = record_id_prefix(record_type)
    if not isinstance(schema_version, str) or not schema_version.strip():
        raise ValidationError("Record ID schema_version must be a non-empty string.")
    if not isinstance(identity, Mapping):
        raise ValidationError("Record ID identity must be a JSON object.")

    hash_payload = {
        "identity": identity,
        "record_type": record_type.strip(),
        "schema_version": schema_version.strip(),
    }
    digest = hashlib.sha256(canonical_json(hash_payload).encode("utf-8")).hexdigest()
    return f"{prefix}_{digest}"


def validate_record_id(
    record_id: str,
    record_type: str | None = None,
) -> None:
    """Validate the syntax and, when supplied, type prefix of a stable record ID."""
    if not isinstance(record_id, str) or not record_id.strip():
        raise ValidationError("Record ID must be a non-empty string.")
    if record_id != record_id.strip():
        raise ValidationError("Record ID must not contain surrounding whitespace.")

    match = _RECORD_ID_PATTERN.fullmatch(record_id)
    if match is None:
        raise ValidationError(
            "Record ID must contain a supported prefix, an underscore, and a "
            "64-character lowercase SHA-256 digest."
        )

    prefix = match.group("prefix")
    actual_record_type = _PREFIX_TO_RECORD_TYPE.get(prefix)
    if actual_record_type is None:
        raise ValidationError(f"Record ID uses unsupported prefix {prefix!r}.")

    if record_type is not None:
        expected_prefix = record_id_prefix(record_type)
        if prefix != expected_prefix:
            raise ValidationError(
                f"Record ID prefix {prefix!r} identifies {actual_record_type!r}, "
                f"not {record_type.strip()!r}."
            )


def record_type_from_id(record_id: str) -> str:
    """Return the registered record type encoded in a validated stable ID."""
    validate_record_id(record_id)
    match = _RECORD_ID_PATTERN.fullmatch(record_id)
    assert match is not None
    return _PREFIX_TO_RECORD_TYPE[match.group("prefix")]
