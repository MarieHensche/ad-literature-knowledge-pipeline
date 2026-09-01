from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path

import pytest

from ad_lit_pipeline.core.provenance import collect_contract_provenance
from ad_lit_pipeline.corpus.identity import (
    assess_source_version,
    assess_work_identity,
)
from ad_lit_pipeline.corpus.source_types import (
    CLASSIFICATION_NEEDS_REVIEW,
    CLASSIFICATION_PROVISIONAL,
    CLASSIFICATION_RESOLVED,
    classify_source_type,
)
from ad_lit_pipeline.corpus.specification import (
    CORPUS_SPECIFICATION_SCHEMA_VERSION,
    corpus_specification_from_contract,
    default_corpus_specification_mapping,
    resolve_as_of,
    validate_corpus_specification,
)
from ad_lit_pipeline.corpus.temporal import assess_temporal_eligibility
from ad_lit_pipeline.llm.schemas import topic_contract_schema
from ad_lit_pipeline.records.models import (
    AvailabilityStatus,
    IdentityBasis,
    IdentityStatus,
    PartialDate,
    PartialDateCertainty,
    PartialDatePrecision,
    SourceLifecycleStatus,
    SourceVersionKind,
    TemporalEligibility,
    WorkKind,
)
from ad_lit_pipeline.topics.contract import load_topic_contract, validate_topic_contract


ROOT = Path(__file__).resolve().parents[1]
TOPIC_CONTRACT = ROOT / "configs/topics/early_detection_ad.yaml"


def partial_date(
    value: str | None,
    precision: PartialDatePrecision,
    certainty: PartialDateCertainty = PartialDateCertainty.EXACT,
) -> PartialDate:
    return PartialDate(value=value, precision=precision, certainty=certainty)


def test_checked_in_contract_resolves_complete_corpus_specification() -> None:
    contract = load_topic_contract(TOPIC_CONTRACT)
    specification = corpus_specification_from_contract(contract)

    assert specification.schema_version == CORPUS_SPECIFICATION_SCHEMA_VERSION
    assert specification.as_of is None
    assert specification.as_of_resolution == "collection_start_date"
    assert specification.providers == ("openalex",)
    assert specification.availability_date_rule == "earliest_public_availability"
    assert specification.identity_basis_order == (
        "doi",
        "provider_id",
        "metadata_fingerprint",
    )
    assert specification.metadata_fingerprint_status == "needs_review"
    assert specification.link_versions_only_with_evidence is True
    assert specification.negative_null_result_policy == "include_when_identified"


def test_legacy_contract_uses_same_versioned_compatibility_default() -> None:
    contract = load_topic_contract(TOPIC_CONTRACT)
    del contract["collection"]["corpus_specification"]

    validate_topic_contract(contract)
    specification = corpus_specification_from_contract(contract)

    assert specification.schema_version == CORPUS_SPECIFICATION_SCHEMA_VERSION
    assert specification.unknown_date_policy == "review_and_exclude"
    assert specification.allowed_source_types == tuple(
        sorted(item.value for item in WorkKind)
    )


@pytest.mark.parametrize(
    ("mutator", "message"),
    [
        (
            lambda spec: spec.update(as_of="2026-09-01"),
            "as_of_resolution must be 'explicit'",
        ),
        (
            lambda spec: spec["identity_policy"].update(
                ordered_bases=["provider_id", "doi", "metadata_fingerprint"]
            ),
            "ordered_bases must be",
        ),
        (
            lambda spec: spec["identity_policy"].update(
                metadata_fingerprint_status="resolved"
            ),
            "metadata_fingerprint_status must be",
        ),
        (
            lambda spec: spec["version_policy"].update(
                link_versions_only_with_evidence=False
            ),
            "link_versions_only_with_evidence must be true",
        ),
        (
            lambda spec: spec.update(unknown_date_policy="include_with_warning"),
            "unknown_date_policy must be",
        ),
        (
            lambda spec: spec.update(allowed_source_types=["paper"]),
            "unsupported values",
        ),
        (
            lambda spec: spec.update(allowed_languages=["EN"]),
            "lowercase BCP-47-like",
        ),
        (
            lambda spec: spec.update(unexpected=True),
            "must contain exact fields",
        ),
    ],
)
def test_corpus_specification_rejects_semantic_drift(
    mutator: object,
    message: str,
) -> None:
    specification = default_corpus_specification_mapping()
    mutator(specification)  # type: ignore[operator]

    with pytest.raises(ValueError, match=message):
        validate_corpus_specification(specification)


def test_explicit_as_of_requires_and_preserves_exact_date() -> None:
    contract = load_topic_contract(TOPIC_CONTRACT)
    corpus = contract["collection"]["corpus_specification"]
    corpus["as_of"] = "2025-12-31"
    corpus["as_of_resolution"] = "explicit"

    validate_topic_contract(contract)
    specification = corpus_specification_from_contract(contract)

    assert resolve_as_of(
        specification,
        datetime(2026, 9, 1, 23, 30, tzinfo=timezone.utc),
    ) == "2025-12-31"


def test_unset_as_of_resolves_from_utc_collection_start_not_completion() -> None:
    specification = corpus_specification_from_contract(
        load_topic_contract(TOPIC_CONTRACT)
    )

    assert resolve_as_of(
        specification,
        "2026-09-01T23:30:00-05:00",
    ) == "2026-09-02"


def test_run_provenance_hashes_resolved_corpus_semantics() -> None:
    contracts, providers = collect_contract_provenance(ROOT, TOPIC_CONTRACT)
    topic = contracts["topic_contract"]

    assert providers == ("openalex",)
    assert topic["corpus_specification_status"] == "declared"
    assert len(topic["corpus_specification_sha256"]) == 64
    assert topic["corpus_specification"]["identity_policy"]["ordered_bases"] == [
        "doi",
        "provider_id",
        "metadata_fingerprint",
    ]


def test_generated_contract_schema_requires_corpus_specification() -> None:
    schema = topic_contract_schema(["openalex"])
    collection = schema["properties"]["collection"]

    assert "corpus_specification" in collection["required"]
    corpus_schema = collection["properties"]["corpus_specification"]
    assert corpus_schema["properties"]["schema_version"]["enum"] == ["1.0.0"]


@pytest.mark.parametrize(
    ("row", "work_kind", "source_type", "status"),
    [
        (
            {"type": "review"},
            WorkKind.REVIEW,
            "review",
            CLASSIFICATION_RESOLVED,
        ),
        (
            {"type": "article", "title": "A systematic review of examples"},
            WorkKind.REVIEW,
            "systematic_review",
            CLASSIFICATION_PROVISIONAL,
        ),
        (
            {"type": "dataset"},
            WorkKind.DATASET,
            "dataset",
            CLASSIFICATION_RESOLVED,
        ),
        (
            {"type": "editorial"},
            WorkKind.OTHER,
            "editorial",
            CLASSIFICATION_NEEDS_REVIEW,
        ),
        (
            {"title": "A primary empirical example"},
            WorkKind.RESEARCH_ARTICLE,
            "primary_study",
            CLASSIFICATION_PROVISIONAL,
        ),
    ],
)
def test_shared_source_type_classifier_is_explicit_about_uncertainty(
    row: dict[str, str],
    work_kind: WorkKind,
    source_type: str,
    status: str,
) -> None:
    result = classify_source_type(row)

    assert result.work_kind is work_kind
    assert result.source_type == source_type
    assert result.status == status


def test_work_identity_prefers_normalized_doi() -> None:
    result = assess_work_identity(
        {
            "doi": "https://doi.org/10.1234/Example.1",
            "provider": "openalex",
            "provider_id": "https://openalex.org/W1",
        }
    )

    assert result.identity_basis is IdentityBasis.GLOBAL_IDENTIFIER
    assert result.identity_key == "doi:10.1234/example.1"
    assert result.identity_status is IdentityStatus.RESOLVED


def test_work_identity_falls_back_to_stable_provider_identifier() -> None:
    result = assess_work_identity(
        {
            "provider": "OpenAlex",
            "provider_id": "https://OPENALEX.org/W123/?secret=ignored",
        }
    )

    assert result.identity_basis is IdentityBasis.REGISTRY_IDENTIFIER
    assert result.identity_key == "provider:openalex:https://openalex.org/W123"
    assert result.identity_status is IdentityStatus.RESOLVED


def test_metadata_fingerprint_is_deterministic_but_never_auto_resolved() -> None:
    left = assess_work_identity(
        {
            "title": "Café-based Example Study",
            "year": "2024",
            "authors": "Example Author; Second Author",
        }
    )
    right = assess_work_identity(
        {
            "title": "Cafe\u0301 based example study",
            "publication_year": "2024",
            "contributors": [{"name": "Example Author"}],
        }
    )

    assert left.identity_key == right.identity_key
    assert left.identity_basis is IdentityBasis.METADATA_FINGERPRINT
    assert left.identity_status is IdentityStatus.NEEDS_REVIEW
    assert left.review_reasons == ("metadata_fingerprint_requires_review",)


def test_conflicting_dois_are_ambiguous_and_have_no_identity_key() -> None:
    result = assess_work_identity(
        {
            "doi": "10.1234/one",
            "identifiers": [{"scheme": "doi", "value": "10.1234/two"}],
        }
    )

    assert result.identity_status is IdentityStatus.AMBIGUOUS
    assert result.identity_key is None
    assert result.review_reasons == ("conflicting_doi_identifiers",)


def test_insufficient_metadata_is_routed_to_review_without_fabricated_key() -> None:
    result = assess_work_identity({"title": "Only a title"})

    assert result.identity_status is IdentityStatus.NEEDS_REVIEW
    assert result.identity_key is None
    assert "metadata_fingerprint_missing_discriminator" in result.review_reasons


def test_published_version_uses_explicit_provider_version_evidence() -> None:
    row = {
        "doi": "10.1234/example",
        "type": "article",
        "primary_location": {"version": "publishedVersion"},
    }
    result = assess_source_version(row)

    assert result.version_kind is SourceVersionKind.VERSION_OF_RECORD
    assert result.lifecycle_status is SourceLifecycleStatus.ACTIVE
    assert result.identity_status is IdentityStatus.RESOLVED
    assert result.version_identity_key is not None


def test_preprint_and_retracted_article_remain_distinct_version_states() -> None:
    preprint = assess_source_version(
        {
            "doi": "10.1234/preprint",
            "type": "preprint",
        }
    )
    retracted = assess_source_version(
        {
            "doi": "10.1234/article",
            "type": "article",
            "primary_location": {"version": "publishedVersion"},
            "is_retracted": True,
        }
    )

    assert preprint.version_kind is SourceVersionKind.PREPRINT
    assert retracted.version_kind is SourceVersionKind.VERSION_OF_RECORD
    assert retracted.lifecycle_status is SourceLifecycleStatus.RETRACTED


def test_correction_requires_explicit_lineage_reference() -> None:
    without_lineage = assess_source_version(
        {
            "doi": "10.1234/correction",
            "type": "correction",
        }
    )
    with_lineage = assess_source_version(
        {
            "doi": "10.1234/correction",
            "type": "correction",
            "version_of": "10.1234/original",
        }
    )

    assert without_lineage.version_kind is SourceVersionKind.CORRECTED_VERSION
    assert "version_lineage_reference_required" in without_lineage.review_reasons
    assert with_lineage.explicit_lineage_references == ("10.1234/original",)


def test_exact_availability_on_cutoff_is_eligible() -> None:
    result = assess_temporal_eligibility(
        partial_date("2025-12-31", PartialDatePrecision.DAY),
        None,
        as_of="2025-12-31",
    )

    assert result.availability_status is AvailabilityStatus.KNOWN
    assert result.temporal_eligibility is TemporalEligibility.ELIGIBLE
    assert result.review_required is False


def test_partial_availability_crossing_cutoff_is_unknown_and_reviewed() -> None:
    result = assess_temporal_eligibility(
        partial_date("2025", PartialDatePrecision.YEAR),
        None,
        as_of="2025-06-30",
    )

    assert result.availability_status is AvailabilityStatus.BOUNDED
    assert result.temporal_eligibility is TemporalEligibility.UNKNOWN
    assert result.review_required is True
    assert result.reasons == ("availability_bounds_cross_cutoff",)


def test_unknown_or_estimated_availability_is_not_silently_included() -> None:
    missing = assess_temporal_eligibility(None, None, as_of="2025-12-31")
    estimated = assess_temporal_eligibility(
        partial_date(
            "2025-01-01",
            PartialDatePrecision.DAY,
            PartialDateCertainty.ESTIMATED,
        ),
        None,
        as_of="2025-12-31",
    )

    assert missing.temporal_eligibility is TemporalEligibility.UNKNOWN
    assert estimated.temporal_eligibility is TemporalEligibility.UNKNOWN
    assert missing.review_required is True
    assert estimated.review_required is True


def test_availability_after_cutoff_is_ineligible_without_review_ambiguity() -> None:
    result = assess_temporal_eligibility(
        partial_date("2026-01-01", PartialDatePrecision.DAY),
        None,
        as_of="2025-12-31",
    )

    assert result.temporal_eligibility is TemporalEligibility.AFTER_CUTOFF
    assert result.review_required is False
