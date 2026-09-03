from __future__ import annotations

import hashlib
import re
import unicodedata
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from ad_lit_pipeline.corpus.source_types import classify_source_type
from ad_lit_pipeline.records.ids import canonical_json
from ad_lit_pipeline.records.models import (
    IdentityBasis,
    IdentityStatus,
    SourceLifecycleStatus,
    SourceVersionKind,
    WorkKind,
)


_DOI_PATTERN = re.compile(r"^10\.\d{4,9}/\S+$", re.IGNORECASE)
_VERSION_KIND_MAP = {
    "preprint": SourceVersionKind.PREPRINT,
    "submitted_manuscript": SourceVersionKind.SUBMITTED_MANUSCRIPT,
    "submitted_version": SourceVersionKind.SUBMITTED_MANUSCRIPT,
    "submittedversion": SourceVersionKind.SUBMITTED_MANUSCRIPT,
    "accepted_manuscript": SourceVersionKind.ACCEPTED_MANUSCRIPT,
    "accepted_version": SourceVersionKind.ACCEPTED_MANUSCRIPT,
    "acceptedversion": SourceVersionKind.ACCEPTED_MANUSCRIPT,
    "published_version": SourceVersionKind.VERSION_OF_RECORD,
    "publishedversion": SourceVersionKind.VERSION_OF_RECORD,
    "version_of_record": SourceVersionKind.VERSION_OF_RECORD,
    "corrected_version": SourceVersionKind.CORRECTED_VERSION,
    "correction": SourceVersionKind.CORRECTED_VERSION,
    "erratum": SourceVersionKind.CORRECTED_VERSION,
    "retraction": SourceVersionKind.RETRACTION_NOTICE,
    "retraction_notice": SourceVersionKind.RETRACTION_NOTICE,
    "protocol": SourceVersionKind.PROTOCOL_VERSION,
    "protocol_version": SourceVersionKind.PROTOCOL_VERSION,
    "registry_version": SourceVersionKind.REGISTRY_VERSION,
    "dataset": SourceVersionKind.DATASET_RELEASE,
    "dataset_release": SourceVersionKind.DATASET_RELEASE,
    "patent": SourceVersionKind.PATENT_PUBLICATION,
    "patent_publication": SourceVersionKind.PATENT_PUBLICATION,
}


@dataclass(frozen=True)
class WorkIdentityAssessment:
    """Deterministic work identity projection plus explicit review state."""

    identity_basis: IdentityBasis | None
    identity_key: str | None
    identity_status: IdentityStatus
    evidence: tuple[str, ...]
    review_reasons: tuple[str, ...]


@dataclass(frozen=True)
class SourceVersionAssessment:
    """Version and lifecycle semantics without fabricating lineage."""

    version_kind: SourceVersionKind
    lifecycle_status: SourceLifecycleStatus
    identity_status: IdentityStatus
    version_identity_key: str | None
    explicit_lineage_references: tuple[str, ...]
    evidence: tuple[str, ...]
    review_reasons: tuple[str, ...]


def normalize_doi(value: Any) -> str:
    doi = unicodedata.normalize("NFC", str(value or "")).strip().casefold()
    for prefix in (
        "https://doi.org/",
        "http://doi.org/",
        "https://dx.doi.org/",
        "http://dx.doi.org/",
        "doi:",
    ):
        if doi.startswith(prefix):
            doi = doi[len(prefix) :]
            break
    return doi.strip().rstrip(".,;)")


def valid_doi(value: Any) -> str | None:
    doi = normalize_doi(value)
    return doi if _DOI_PATTERN.fullmatch(doi) is not None else None


def _iter_values(value: Any) -> Iterable[Any]:
    if isinstance(value, (list, tuple, set, frozenset)):
        yield from value
    elif value not in (None, ""):
        yield value


def _doi_values(row: Mapping[str, Any]) -> tuple[set[str], tuple[str, ...]]:
    valid: set[str] = set()
    invalid: set[str] = set()
    for field in ("doi", "dois"):
        for value in _iter_values(row.get(field)):
            normalized = normalize_doi(value)
            parsed = valid_doi(value)
            if parsed:
                valid.add(parsed)
            elif normalized:
                invalid.add(normalized)

    identifiers = row.get("identifiers")
    identifier_items: Iterable[Any]
    if isinstance(identifiers, Mapping):
        identifier_items = (
            {"scheme": key, "value": value}
            for key, value in identifiers.items()
        )
    elif isinstance(identifiers, list):
        identifier_items = identifiers
    else:
        identifier_items = ()
    for identifier in identifier_items:
        if not isinstance(identifier, Mapping):
            continue
        if str(identifier.get("scheme") or "").casefold() != "doi":
            continue
        for value in _iter_values(identifier.get("value")):
            parsed = valid_doi(value)
            if parsed:
                valid.add(parsed)
            else:
                normalized = normalize_doi(value)
                if normalized:
                    invalid.add(normalized)
    return valid, tuple(sorted(invalid))


def normalize_provider(value: Any) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "_", str(value or "").casefold())
    return re.sub(r"_+", "_", normalized).strip("_")


def normalize_provider_id(value: Any) -> str:
    identifier = unicodedata.normalize("NFC", str(value or "")).strip()
    if not identifier:
        return ""
    if identifier.startswith(("http://", "https://")):
        parsed = urlsplit(identifier)
        identifier = urlunsplit(
            (
                parsed.scheme.casefold(),
                parsed.netloc.casefold(),
                parsed.path.rstrip("/"),
                "",
                "",
            )
        )
    return identifier


def _normalized_words(value: Any) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(
        character for character in text if not unicodedata.combining(character)
    )
    text = re.sub(r"[^a-z0-9]+", " ", text.casefold())
    return re.sub(r"\s+", " ", text).strip()


def _first_nonempty(row: Mapping[str, Any], fields: tuple[str, ...]) -> str:
    for field in fields:
        value = str(row.get(field) or "").strip()
        if value:
            return value
    return ""


def _first_author(value: Any) -> str:
    if isinstance(value, list):
        first = value[0] if value else ""
        if isinstance(first, Mapping):
            first = first.get("name") or first.get("display_name") or ""
        return _normalized_words(first)
    return _normalized_words(re.split(r"[;|]", str(value or ""), maxsplit=1)[0])


def _metadata_fingerprint(row: Mapping[str, Any]) -> tuple[str | None, tuple[str, ...]]:
    title = _normalized_words(
        _first_nonempty(row, ("title", "display_name", "preferred_title"))
    )
    publication = _first_nonempty(
        row,
        ("publication_date", "publication_year", "year"),
    )
    first_author = _first_author(row.get("authors") or row.get("contributors"))
    venue = _normalized_words(
        _first_nonempty(row, ("venue", "journal", "publisher"))
    )
    if not title:
        return None, ("metadata_fingerprint_missing_title",)
    if not publication and not first_author and not venue:
        return None, ("metadata_fingerprint_missing_discriminator",)
    projection = {
        "first_author": first_author or None,
        "publication": publication or None,
        "title": title,
        "venue": venue or None,
    }
    digest = hashlib.sha256(canonical_json(projection).encode("utf-8")).hexdigest()
    evidence = tuple(
        key
        for key, value in projection.items()
        if value is not None
    )
    return f"metadata_sha256:{digest}", evidence


def assess_work_identity(row: Mapping[str, Any]) -> WorkIdentityAssessment:
    """Apply DOI, provider ID, then review-only metadata fingerprint ordering."""
    dois, invalid_dois = _doi_values(row)
    if len(dois) > 1:
        return WorkIdentityAssessment(
            identity_basis=IdentityBasis.GLOBAL_IDENTIFIER,
            identity_key=None,
            identity_status=IdentityStatus.AMBIGUOUS,
            evidence=tuple(f"doi:{doi}" for doi in sorted(dois)),
            review_reasons=("conflicting_doi_identifiers",),
        )
    if len(dois) == 1:
        doi = next(iter(dois))
        reasons = (
            ("ignored_invalid_doi_values",) if invalid_dois else ()
        )
        return WorkIdentityAssessment(
            identity_basis=IdentityBasis.GLOBAL_IDENTIFIER,
            identity_key=f"doi:{doi}",
            identity_status=IdentityStatus.RESOLVED,
            evidence=(f"normalized_doi:{doi}",),
            review_reasons=reasons,
        )

    provider = normalize_provider(
        row.get("provider") or row.get("provider_name") or row.get("source")
    )
    provider_id = normalize_provider_id(
        row.get("provider_id") or row.get("provider_item_id")
    )
    if provider and provider_id:
        reasons = (
            ("invalid_doi_fell_back_to_provider_id",) if invalid_dois else ()
        )
        return WorkIdentityAssessment(
            identity_basis=IdentityBasis.REGISTRY_IDENTIFIER,
            identity_key=f"provider:{provider}:{provider_id}",
            identity_status=IdentityStatus.RESOLVED,
            evidence=(
                f"normalized_provider:{provider}",
                f"provider_item_id:{provider_id}",
            ),
            review_reasons=reasons,
        )

    fingerprint, fingerprint_evidence = _metadata_fingerprint(row)
    if fingerprint is not None:
        reasons = ["metadata_fingerprint_requires_review"]
        if invalid_dois:
            reasons.append("invalid_doi_fell_back_to_metadata")
        if provider or provider_id:
            reasons.append("incomplete_provider_identity")
        return WorkIdentityAssessment(
            identity_basis=IdentityBasis.METADATA_FINGERPRINT,
            identity_key=fingerprint,
            identity_status=IdentityStatus.NEEDS_REVIEW,
            evidence=tuple(
                f"metadata_field:{field}" for field in fingerprint_evidence
            ),
            review_reasons=tuple(reasons),
        )

    reasons = list(fingerprint_evidence)
    if invalid_dois:
        reasons.append("invalid_doi")
    if provider or provider_id:
        reasons.append("incomplete_provider_identity")
    return WorkIdentityAssessment(
        identity_basis=None,
        identity_key=None,
        identity_status=IdentityStatus.NEEDS_REVIEW,
        evidence=(),
        review_reasons=tuple(dict.fromkeys(reasons or ["no_identity_basis"])),
    )


def _normalize_version_label(value: Any) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "_", str(value or "").casefold())
    return re.sub(r"_+", "_", normalized).strip("_")


def _nested_version_values(row: Mapping[str, Any]) -> Iterable[tuple[str, str]]:
    for field in ("version_kind", "version", "location_version"):
        value = str(row.get(field) or "").strip()
        if value:
            yield field, value
    for field in ("best_oa_location", "primary_location"):
        location = row.get(field)
        if isinstance(location, Mapping):
            value = str(location.get("version") or "").strip()
            if value:
                yield f"{field}.version", value


def _boolean(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().casefold() in {"1", "true", "yes"}


def _lineage_references(row: Mapping[str, Any]) -> tuple[str, ...]:
    references: set[str] = set()
    for field in (
        "is_version_of",
        "version_of",
        "previous_version_id",
        "previous_source_version_ids",
        "related_version_ids",
    ):
        for value in _iter_values(row.get(field)):
            cleaned = str(value or "").strip()
            if cleaned:
                references.add(cleaned)
    return tuple(sorted(references))


def _version_identity_key(
    row: Mapping[str, Any],
    work_identity: WorkIdentityAssessment,
    version_kind: SourceVersionKind,
) -> str | None:
    if work_identity.identity_key is None:
        return None
    projection = {
        "provider_id": normalize_provider_id(
            row.get("provider_id") or row.get("provider_item_id")
        )
        or None,
        "version_kind": version_kind.value,
        "version_label": _first_nonempty(
            row, ("version_label", "version_number", "version")
        )
        or None,
        "work_identity_key": work_identity.identity_key,
    }
    digest = hashlib.sha256(canonical_json(projection).encode("utf-8")).hexdigest()
    return f"source_version_sha256:{digest}"


def assess_source_version(
    row: Mapping[str, Any],
    work_identity: WorkIdentityAssessment | None = None,
) -> SourceVersionAssessment:
    """Classify one version while requiring evidence for cross-version lineage."""
    identity = work_identity or assess_work_identity(row)
    source_type = classify_source_type(row)
    evidence: list[str] = []
    review_reasons: list[str] = []
    version_kind: SourceVersionKind | None = None

    for field, value in _nested_version_values(row):
        normalized = _normalize_version_label(value)
        mapped = _VERSION_KIND_MAP.get(normalized)
        if mapped is not None:
            version_kind = mapped
            evidence.append(f"explicit_version:{field}={normalized}")
            break
        review_reasons.append(f"unmapped_version_label:{field}={normalized}")

    if version_kind is None:
        source_map = {
            "preprint": SourceVersionKind.PREPRINT,
            "correction": SourceVersionKind.CORRECTED_VERSION,
            "retraction_notice": SourceVersionKind.RETRACTION_NOTICE,
            "protocol": SourceVersionKind.PROTOCOL_VERSION,
            "study_protocol": SourceVersionKind.PROTOCOL_VERSION,
            "dataset": SourceVersionKind.DATASET_RELEASE,
            "patent": SourceVersionKind.PATENT_PUBLICATION,
        }
        version_kind = source_map.get(source_type.source_type)
        if version_kind is not None:
            evidence.append(f"classified_source_type:{source_type.source_type}")

    if version_kind is None and source_type.work_kind is WorkKind.DATASET:
        version_kind = SourceVersionKind.DATASET_RELEASE
        evidence.append("classified_work_kind:dataset")
    if version_kind is None and source_type.work_kind is WorkKind.PATENT:
        version_kind = SourceVersionKind.PATENT_PUBLICATION
        evidence.append("classified_work_kind:patent")
    if version_kind is None and source_type.work_kind is WorkKind.PROTOCOL:
        version_kind = SourceVersionKind.PROTOCOL_VERSION
        evidence.append("classified_work_kind:protocol")

    if version_kind is None and (
        identity.identity_basis is IdentityBasis.GLOBAL_IDENTIFIER
        and source_type.work_kind in {WorkKind.RESEARCH_ARTICLE, WorkKind.REVIEW}
    ):
        version_kind = SourceVersionKind.VERSION_OF_RECORD
        evidence.append("provisional_doi_publication_version")
        review_reasons.append("version_of_record_inferred_from_doi_and_source_type")

    if version_kind is None:
        version_kind = SourceVersionKind.OTHER
        review_reasons.append("source_version_kind_unresolved")

    if _boolean(row.get("is_retracted")):
        lifecycle = SourceLifecycleStatus.RETRACTED
        evidence.append("provider_lifecycle:is_retracted")
    elif _boolean(row.get("is_withdrawn")):
        lifecycle = SourceLifecycleStatus.WITHDRAWN
        evidence.append("provider_lifecycle:is_withdrawn")
    elif version_kind is SourceVersionKind.CORRECTED_VERSION:
        lifecycle = SourceLifecycleStatus.CORRECTED
    elif version_kind is SourceVersionKind.OTHER:
        lifecycle = SourceLifecycleStatus.UNKNOWN
    else:
        lifecycle = SourceLifecycleStatus.ACTIVE

    explicit_lineage = _lineage_references(row)
    if explicit_lineage:
        evidence.append("explicit_version_lineage_reference")
    elif version_kind in {
        SourceVersionKind.CORRECTED_VERSION,
        SourceVersionKind.RETRACTION_NOTICE,
    }:
        review_reasons.append("version_lineage_reference_required")

    if identity.identity_status in {IdentityStatus.AMBIGUOUS, IdentityStatus.NEEDS_REVIEW}:
        status = identity.identity_status
    elif review_reasons:
        status = IdentityStatus.PROVISIONAL
    else:
        status = IdentityStatus.RESOLVED

    return SourceVersionAssessment(
        version_kind=version_kind,
        lifecycle_status=lifecycle,
        identity_status=status,
        version_identity_key=_version_identity_key(row, identity, version_kind),
        explicit_lineage_references=explicit_lineage,
        evidence=tuple(evidence),
        review_reasons=tuple(dict.fromkeys(review_reasons)),
    )
