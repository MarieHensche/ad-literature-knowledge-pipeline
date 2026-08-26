from __future__ import annotations

from pathlib import Path

import pytest

from ad_lit_pipeline.core.artifacts import knowledge_artifacts
from ad_lit_pipeline.core.errors import ValidationError
from ad_lit_pipeline.knowledge.validation import (
    validate_evidence_excerpt,
    validate_field_summary,
    validate_finding,
    validate_gap,
    validate_relationship,
    validate_source,
)
from ad_lit_pipeline.io.json_io import write_json
from ad_lit_pipeline.io.jsonl_io import write_jsonl
from ad_lit_pipeline.knowledge.files import (
    validate_field_summary_json,
    validate_findings_jsonl,
    validate_sources_jsonl,
)

def source_record() -> dict[str, object]:
    return {
        "source_id": "paper_1",
        "title": "Example paper",
        "year": "2024",
        "doi": "10.123/example",
        "url": "https://example.org/paper",
        "abstract": "An example abstract.",
        "authors": "Example Author",
        "venue": "Example Journal",
        "provider": "openalex",
        "provider_id": "W123",
        "source_type": "primary_study",
        "collection_provenance": {"query": "example"},
        "full_text_status": "available",
    }


def evidence_excerpt_record() -> dict[str, object]:
    return {
        "excerpt_id": "excerpt_1",
        "source_id": "paper_1",
        "text": "The study reported an example result.",
        "section": "results",
        "location": "results paragraph 1",
        "extraction_method": "full_text_sectioning",
    }


def finding_record() -> dict[str, object]:
    return {
        "finding_id": "finding_1",
        "source_id": "paper_1",
        "claim_text": "The example method improved detection.",
        "finding_type": "positive",
        "topic_ids": ["early_detection"],
        "method": "example_method",
        "outcome": "detection_accuracy",
        "study_context": "example cohort",
        "direction": "increases",
        "evidence_excerpt_ids": ["excerpt_1"],
        "limitations": ["small sample"],
        "extraction_confidence": "high",
        "evidence_strength": "medium",
        "extraction_status": "extracted",
    }


def relationship_record() -> dict[str, object]:
    return {
        "relationship_id": "relationship_1",
        "source_entity_id": "finding_1",
        "target_entity_id": "finding_2",
        "relationship_type": "supports",
        "basis": "Both findings report the same direction.",
        "evidence_excerpt_ids": ["excerpt_1"],
    }


def gap_record() -> dict[str, object]:
    return {
        "gap_id": "gap_1",
        "gap_type": "weak_evidence",
        "gap_description": "Evidence is limited to small cohorts.",
        "topic_ids": ["early_detection"],
        "basis": "Only one supporting finding is available.",
        "supporting_finding_ids": ["finding_1"],
        "evidence_strength": "low",
    }


def synthesis_claim_record() -> dict[str, object]:
    return {
        "synthesis_claim_id": "synthesis_claim_1",
        "claim_text": "Example methods show early promise.",
        "topic_ids": ["early_detection"],
        "supporting_finding_ids": ["finding_1"],
        "conflicting_finding_ids": [],
        "evidence_strength": "medium",
    }


def field_summary_record() -> dict[str, object]:
    return {
        "summary_id": "field_summary_1",
        "research_topic": {"title": "Example field"},
        "source_count": 1,
        "finding_count": 1,
        "topic_summaries": [{"topic_id": "early_detection"}],
        "gap_ids": ["gap_1"],
        "synthesis_claim_ids": ["synthesis_claim_1"],
        "quality": {"status": "draft"},
    }


def test_valid_knowledge_records_pass_validation() -> None:
    validate_source(source_record())
    validate_evidence_excerpt(evidence_excerpt_record())
    validate_finding(finding_record())
    validate_relationship(relationship_record())
    validate_gap(gap_record())
    validate_field_summary(field_summary_record())


def test_finding_requires_required_fields() -> None:
    record = finding_record()
    del record["claim_text"]

    with pytest.raises(ValidationError, match="missing required fields"):
        validate_finding(record)


def test_finding_rejects_invalid_controlled_value() -> None:
    record = finding_record()
    record["direction"] = "improves"

    with pytest.raises(ValidationError, match="Finding.direction"):
        validate_finding(record)


def test_finding_requires_string_lists() -> None:
    record = finding_record()
    record["topic_ids"] = ["early_detection", ""]

    with pytest.raises(ValidationError, match=r"Finding.topic_ids\[2\]"):
        validate_finding(record)


def test_field_summary_counts_must_be_non_negative_integers() -> None:
    record = field_summary_record()
    record["finding_count"] = -1

    with pytest.raises(ValidationError, match="FieldSummary.finding_count"):
        validate_field_summary(record)


def test_knowledge_artifact_paths_match_processed_convention() -> None:
    artifacts = knowledge_artifacts("example")

    assert artifacts.sources_jsonl == Path("data/processed/example_sources.jsonl")
    assert artifacts.evidence_excerpts_jsonl == Path(
        "data/processed/example_evidence_excerpts.jsonl"
    )
    assert artifacts.findings_jsonl == Path("data/processed/example_findings.jsonl")
    assert artifacts.relationships_jsonl == Path(
        "data/processed/example_relationships.jsonl"
    )
    assert artifacts.gaps_jsonl == Path("data/processed/example_gaps.jsonl")
    assert artifacts.synthesis_claims_jsonl == Path(
        "data/processed/example_synthesis_claims.jsonl"
    )
    assert artifacts.field_summary_json == Path(
        "data/processed/example_field_summary.json"
    )


def test_validate_sources_jsonl_returns_record_count(tmp_path: Path) -> None:
    path = tmp_path / "sources.jsonl"
    write_jsonl(path, [source_record(), source_record()])

    assert validate_sources_jsonl(path) == 2


def test_validate_findings_jsonl_rejects_invalid_record(tmp_path: Path) -> None:
    path = tmp_path / "findings.jsonl"
    record = finding_record()
    record["evidence_strength"] = "very_strong"
    write_jsonl(path, [record])

    with pytest.raises(ValidationError, match="Finding record 1"):
        validate_findings_jsonl(path)


def test_validate_field_summary_json_returns_payload(tmp_path: Path) -> None:
    path = tmp_path / "field_summary.json"
    payload = field_summary_record()
    write_json(path, payload)

    assert validate_field_summary_json(path) == payload


def test_knowledge_package_exports_public_api() -> None:
    from ad_lit_pipeline import knowledge

    assert "finding" in knowledge.KNOWLEDGE_CONTRACTS
    assert "positive" in knowledge.FINDING_TYPES
    assert knowledge.validate_finding is validate_finding