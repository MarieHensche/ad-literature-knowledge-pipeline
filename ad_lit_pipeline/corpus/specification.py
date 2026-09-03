from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any

from ad_lit_pipeline.records.models import (
    IdentityStatus,
    NegativeNullPolicy,
    SourceVersionKind,
    WorkKind,
)


CORPUS_SPECIFICATION_SCHEMA_VERSION = "1.0.0"
IDENTITY_BASIS_ORDER = ("doi", "provider_id", "metadata_fingerprint")
AS_OF_RESOLUTIONS = {"explicit", "collection_start_date"}
AVAILABILITY_DATE_RULES = {"earliest_public_availability"}
ACCESS_POLICIES = {
    "metadata_or_full_text",
    "open_access_only",
    "full_text_required",
}
UNKNOWN_DATE_POLICIES = {"review_and_exclude"}
AMBIGUOUS_IDENTITY_POLICIES = {"review"}
VERSION_POLICY_MODES = {"retain_all_identified"}
_LANGUAGE_PATTERN = re.compile(r"^[a-z]{2,3}(?:-[a-z0-9]{2,8})*$")
_EXACT_FIELDS = {
    "access_policy",
    "allowed_languages",
    "allowed_source_types",
    "as_of",
    "as_of_resolution",
    "availability_date_rule",
    "identity_policy",
    "include_unknown_language",
    "negative_null_result_policy",
    "schema_version",
    "unknown_date_policy",
    "version_policy",
}
_IDENTITY_POLICY_FIELDS = {
    "ambiguous_identity_policy",
    "metadata_fingerprint_status",
    "ordered_bases",
}
_VERSION_POLICY_FIELDS = {
    "link_versions_only_with_evidence",
    "mode",
    "preferred_version_kind",
    "retained_version_kinds",
}


@dataclass(frozen=True)
class CorpusSpecification:
    """Resolved, provider-aware corpus semantics for one topic contract."""

    schema_version: str
    as_of: str | None
    as_of_resolution: str
    availability_date_rule: str
    providers: tuple[str, ...]
    publication_start: str | None
    publication_end: str | None
    allowed_source_types: tuple[str, ...]
    allowed_languages: tuple[str, ...]
    include_unknown_language: bool
    access_policy: str
    retained_version_kinds: tuple[str, ...]
    preferred_version_kind: str
    retain_all_identified_versions: bool
    link_versions_only_with_evidence: bool
    identity_basis_order: tuple[str, ...]
    metadata_fingerprint_status: str
    ambiguous_identity_policy: str
    unknown_date_policy: str
    negative_null_result_policy: str

    def semantic_mapping(self) -> dict[str, Any]:
        """Return stable JSON-compatible semantics for provenance and hashing."""
        return {
            "schema_version": self.schema_version,
            "as_of": self.as_of,
            "as_of_resolution": self.as_of_resolution,
            "availability_date_rule": self.availability_date_rule,
            "providers": list(self.providers),
            "publication_start": self.publication_start,
            "publication_end": self.publication_end,
            "allowed_source_types": list(self.allowed_source_types),
            "allowed_languages": list(self.allowed_languages),
            "include_unknown_language": self.include_unknown_language,
            "access_policy": self.access_policy,
            "version_policy": {
                "mode": (
                    "retain_all_identified"
                    if self.retain_all_identified_versions
                    else "unsupported"
                ),
                "retained_version_kinds": list(self.retained_version_kinds),
                "preferred_version_kind": self.preferred_version_kind,
                "link_versions_only_with_evidence": (
                    self.link_versions_only_with_evidence
                ),
            },
            "identity_policy": {
                "ordered_bases": list(self.identity_basis_order),
                "metadata_fingerprint_status": (
                    self.metadata_fingerprint_status
                ),
                "ambiguous_identity_policy": self.ambiguous_identity_policy,
            },
            "unknown_date_policy": self.unknown_date_policy,
            "negative_null_result_policy": self.negative_null_result_policy,
        }


def default_corpus_specification_mapping() -> dict[str, Any]:
    """Return the v1 provider-neutral compatibility default as a fresh mapping."""
    return {
        "schema_version": CORPUS_SPECIFICATION_SCHEMA_VERSION,
        "as_of": None,
        "as_of_resolution": "collection_start_date",
        "availability_date_rule": "earliest_public_availability",
        "allowed_source_types": [item.value for item in WorkKind],
        "allowed_languages": [],
        "include_unknown_language": True,
        "access_policy": "metadata_or_full_text",
        "version_policy": {
            "mode": "retain_all_identified",
            "retained_version_kinds": [item.value for item in SourceVersionKind],
            "preferred_version_kind": SourceVersionKind.VERSION_OF_RECORD.value,
            "link_versions_only_with_evidence": True,
        },
        "identity_policy": {
            "ordered_bases": list(IDENTITY_BASIS_ORDER),
            "metadata_fingerprint_status": IdentityStatus.NEEDS_REVIEW.value,
            "ambiguous_identity_policy": "review",
        },
        "unknown_date_policy": "review_and_exclude",
        "negative_null_result_policy": (
            NegativeNullPolicy.INCLUDE_WHEN_IDENTIFIED.value
        ),
    }


def _mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{label} must be a mapping.")
    return value


def _exact_fields(value: Mapping[str, Any], expected: set[str], label: str) -> None:
    missing = sorted(expected - set(value))
    extra = sorted(set(value) - expected)
    if missing or extra:
        raise ValueError(
            f"{label} must contain exact fields; missing={missing}, extra={extra}."
        )


def _string_list(
    value: Any,
    label: str,
    *,
    allow_empty: bool = False,
) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise ValueError(f"{label} must be a list.")
    cleaned = tuple(
        item.strip() for item in value if isinstance(item, str) and item.strip()
    )
    if len(cleaned) != len(value):
        raise ValueError(f"{label} must contain non-empty strings.")
    if not allow_empty and not cleaned:
        raise ValueError(f"{label} must not be empty.")
    if len(set(cleaned)) != len(cleaned):
        raise ValueError(f"{label} must not contain duplicates.")
    return cleaned


def _exact_date(value: Any, label: str) -> str:
    if not isinstance(value, str) or re.fullmatch(r"\d{4}-\d{2}-\d{2}", value) is None:
        raise ValueError(f"{label} must use YYYY-MM-DD.")
    try:
        date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{label} must be a valid calendar date.") from exc
    return value


def validate_corpus_specification(value: Any, label: str = "corpus_specification") -> None:
    """Validate the complete v1 corpus-scoping semantics."""
    spec = _mapping(value, label)
    _exact_fields(spec, _EXACT_FIELDS, label)
    if spec["schema_version"] != CORPUS_SPECIFICATION_SCHEMA_VERSION:
        raise ValueError(
            f"{label}.schema_version must be "
            f"{CORPUS_SPECIFICATION_SCHEMA_VERSION}."
        )

    as_of = spec["as_of"]
    if as_of is not None:
        _exact_date(as_of, f"{label}.as_of")
    as_of_resolution = spec["as_of_resolution"]
    if as_of_resolution not in AS_OF_RESOLUTIONS:
        raise ValueError(
            f"{label}.as_of_resolution must be one of "
            f"{sorted(AS_OF_RESOLUTIONS)}."
        )
    expected_resolution = "explicit" if as_of is not None else "collection_start_date"
    if as_of_resolution != expected_resolution:
        raise ValueError(
            f"{label}.as_of_resolution must be {expected_resolution!r} when "
            f"as_of is {as_of!r}."
        )
    if spec["availability_date_rule"] not in AVAILABILITY_DATE_RULES:
        raise ValueError(
            f"{label}.availability_date_rule must be "
            "'earliest_public_availability'."
        )

    source_types = _string_list(
        spec["allowed_source_types"], f"{label}.allowed_source_types"
    )
    invalid_types = sorted(set(source_types) - {item.value for item in WorkKind})
    if invalid_types:
        raise ValueError(
            f"{label}.allowed_source_types contains unsupported values: "
            f"{invalid_types}."
        )
    languages = _string_list(
        spec["allowed_languages"],
        f"{label}.allowed_languages",
        allow_empty=True,
    )
    invalid_languages = [
        language
        for language in languages
        if language != language.casefold()
        or _LANGUAGE_PATTERN.fullmatch(language) is None
    ]
    if invalid_languages:
        raise ValueError(
            f"{label}.allowed_languages must use lowercase BCP-47-like tags: "
            f"{invalid_languages}."
        )
    if not isinstance(spec["include_unknown_language"], bool):
        raise ValueError(f"{label}.include_unknown_language must be boolean.")
    if spec["access_policy"] not in ACCESS_POLICIES:
        raise ValueError(
            f"{label}.access_policy must be one of {sorted(ACCESS_POLICIES)}."
        )

    version_policy = _mapping(spec["version_policy"], f"{label}.version_policy")
    _exact_fields(
        version_policy,
        _VERSION_POLICY_FIELDS,
        f"{label}.version_policy",
    )
    if version_policy["mode"] not in VERSION_POLICY_MODES:
        raise ValueError(
            f"{label}.version_policy.mode must be 'retain_all_identified'."
        )
    retained_versions = _string_list(
        version_policy["retained_version_kinds"],
        f"{label}.version_policy.retained_version_kinds",
    )
    invalid_versions = sorted(
        set(retained_versions) - {item.value for item in SourceVersionKind}
    )
    if invalid_versions:
        raise ValueError(
            f"{label}.version_policy.retained_version_kinds contains unsupported "
            f"values: {invalid_versions}."
        )
    if version_policy["preferred_version_kind"] not in retained_versions:
        raise ValueError(
            f"{label}.version_policy.preferred_version_kind must be retained."
        )
    if version_policy["link_versions_only_with_evidence"] is not True:
        raise ValueError(
            f"{label}.version_policy.link_versions_only_with_evidence must be true."
        )

    identity_policy = _mapping(
        spec["identity_policy"], f"{label}.identity_policy"
    )
    _exact_fields(
        identity_policy,
        _IDENTITY_POLICY_FIELDS,
        f"{label}.identity_policy",
    )
    ordered_bases = _string_list(
        identity_policy["ordered_bases"],
        f"{label}.identity_policy.ordered_bases",
    )
    if ordered_bases != IDENTITY_BASIS_ORDER:
        raise ValueError(
            f"{label}.identity_policy.ordered_bases must be "
            f"{list(IDENTITY_BASIS_ORDER)}."
        )
    if (
        identity_policy["metadata_fingerprint_status"]
        != IdentityStatus.NEEDS_REVIEW.value
    ):
        raise ValueError(
            f"{label}.identity_policy.metadata_fingerprint_status must be "
            f"'{IdentityStatus.NEEDS_REVIEW.value}'."
        )
    if (
        identity_policy["ambiguous_identity_policy"]
        not in AMBIGUOUS_IDENTITY_POLICIES
    ):
        raise ValueError(
            f"{label}.identity_policy.ambiguous_identity_policy must be 'review'."
        )
    if spec["unknown_date_policy"] not in UNKNOWN_DATE_POLICIES:
        raise ValueError(
            f"{label}.unknown_date_policy must be 'review_and_exclude'."
        )
    if spec["negative_null_result_policy"] not in {
        item.value for item in NegativeNullPolicy
    }:
        raise ValueError(
            f"{label}.negative_null_result_policy is unsupported."
        )


def _provider_list(collection: Mapping[str, Any]) -> tuple[str, ...]:
    providers = _string_list(
        collection.get("allowed_providers"), "collection.allowed_providers"
    )
    return tuple(sorted(provider.casefold() for provider in providers))


def corpus_specification_from_contract(
    contract: Mapping[str, Any],
) -> CorpusSpecification:
    """Resolve v1 corpus semantics, including compatible legacy defaults."""
    collection = _mapping(contract.get("collection"), "collection")
    raw_spec = collection.get("corpus_specification")
    if raw_spec is None:
        raw_spec = default_corpus_specification_mapping()
    validate_corpus_specification(raw_spec, "collection.corpus_specification")
    spec = _mapping(raw_spec, "collection.corpus_specification")
    version_policy = _mapping(
        spec["version_policy"], "collection.corpus_specification.version_policy"
    )
    identity_policy = _mapping(
        spec["identity_policy"], "collection.corpus_specification.identity_policy"
    )
    window = collection.get("publication_window")
    window_map = window if isinstance(window, Mapping) else {}
    return CorpusSpecification(
        schema_version=str(spec["schema_version"]),
        as_of=str(spec["as_of"]) if spec["as_of"] is not None else None,
        as_of_resolution=str(spec["as_of_resolution"]),
        availability_date_rule=str(spec["availability_date_rule"]),
        providers=_provider_list(collection),
        publication_start=(
            str(window_map["start"]) if window_map.get("start") else None
        ),
        publication_end=(
            str(window_map["end"]) if window_map.get("end") else None
        ),
        allowed_source_types=tuple(sorted(spec["allowed_source_types"])),
        allowed_languages=tuple(sorted(spec["allowed_languages"])),
        include_unknown_language=bool(spec["include_unknown_language"]),
        access_policy=str(spec["access_policy"]),
        retained_version_kinds=tuple(
            sorted(version_policy["retained_version_kinds"])
        ),
        preferred_version_kind=str(version_policy["preferred_version_kind"]),
        retain_all_identified_versions=version_policy["mode"]
        == "retain_all_identified",
        link_versions_only_with_evidence=bool(
            version_policy["link_versions_only_with_evidence"]
        ),
        identity_basis_order=tuple(identity_policy["ordered_bases"]),
        metadata_fingerprint_status=str(
            identity_policy["metadata_fingerprint_status"]
        ),
        ambiguous_identity_policy=str(
            identity_policy["ambiguous_identity_policy"]
        ),
        unknown_date_policy=str(spec["unknown_date_policy"]),
        negative_null_result_policy=str(spec["negative_null_result_policy"]),
    )


def resolve_as_of(
    specification: CorpusSpecification,
    collection_started_at: date | datetime | str,
) -> str:
    """Resolve an exact inclusive cutoff without using run completion time."""
    if specification.as_of is not None:
        return specification.as_of
    if specification.as_of_resolution != "collection_start_date":
        raise ValueError("Unsupported unresolved as_of policy.")
    if isinstance(collection_started_at, datetime):
        if collection_started_at.tzinfo is None:
            raise ValueError("collection_started_at datetime must be timezone-aware.")
        return collection_started_at.astimezone(timezone.utc).date().isoformat()
    if isinstance(collection_started_at, date):
        return collection_started_at.isoformat()
    if isinstance(collection_started_at, str):
        value = collection_started_at.strip()
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError(
                "collection_started_at must be an RFC3339 timestamp."
            ) from exc
        if parsed.tzinfo is None:
            raise ValueError("collection_started_at timestamp must include a timezone.")
        return parsed.astimezone(timezone.utc).date().isoformat()
    raise TypeError("collection_started_at must be a date, datetime, or timestamp.")
