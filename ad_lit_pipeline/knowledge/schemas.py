from __future__ import annotations

from dataclasses import dataclass


FINDING_TYPES = (
    "positive",
    "negative",
    "mixed",
    "null",
    "inconclusive",
)

DIRECTIONS = (
    "increases",
    "decreases",
    "associated_with",
    "not_associated_with",
    "mixed",
    "unclear",
    "not_applicable",
)

EXTRACTION_CONFIDENCES = (
    "high",
    "mid_high",
    "medium",
    "mid_low",
    "low",
)

EVIDENCE_STRENGTHS = (
    "high",
    "mid_high",
    "medium",
    "mid_low",
    "low",
)

EXTRACTION_STATUSES = (
    "extracted",
    "needs_review",
    "reviewed",
    "rejected",
)

RELATIONSHIP_TYPES = (
    "supports",
    "contradicts",
    "extends",
    "uses_method",
    "studies_population",
    "uses_dataset",
    "measures_outcome",
    "addresses_gap",
    "cites",
)

GAP_TYPES = (
    "explicit_author_gap",
    "underexplored_topic",
    "underexplored_method",
    "underexplored_population",
    "underexplored_dataset",
    "weak_evidence",
    "contradictory_evidence",
    "temporal_gap",
)


@dataclass(frozen=True)
class RecordContract:
    name: str
    required_fields: tuple[str, ...]
    non_empty_fields: tuple[str, ...] = ()
    list_fields: tuple[str, ...] = ()
    string_list_fields: tuple[str, ...] = ()
    controlled_fields: dict[str, tuple[str, ...]] | None = None


SOURCE_CONTRACT = RecordContract(
    name="Source",
    required_fields=(
        "source_id",
        "title",
        "year",
        "doi",
        "url",
        "abstract",
        "authors",
        "venue",
        "provider",
        "provider_id",
        "source_type",
        "collection_provenance",
        "full_text_status",
    ),
    non_empty_fields=(
        "source_id",
        "title",
        "provider",
        "provider_id",
        "source_type",
        "full_text_status",
    ),
)

EVIDENCE_EXCERPT_CONTRACT = RecordContract(
    name="EvidenceExcerpt",
    required_fields=(
        "excerpt_id",
        "source_id",
        "text",
        "section",
        "location",
        "extraction_method",
    ),
    non_empty_fields=("excerpt_id", "source_id", "text", "extraction_method"),
)

FINDING_CONTRACT = RecordContract(
    name="Finding",
    required_fields=(
        "finding_id",
        "source_id",
        "claim_text",
        "finding_type",
        "topic_ids",
        "method",
        "outcome",
        "study_context",
        "direction",
        "evidence_excerpt_ids",
        "limitations",
        "extraction_confidence",
        "evidence_strength",
        "extraction_status",
    ),
    non_empty_fields=(
        "finding_id",
        "source_id",
        "claim_text",
        "finding_type",
        "method",
        "outcome",
        "study_context",
        "direction",
        "extraction_confidence",
        "evidence_strength",
        "extraction_status",
    ),
    list_fields=("topic_ids", "evidence_excerpt_ids", "limitations"),
    string_list_fields=("topic_ids", "evidence_excerpt_ids", "limitations"),
    controlled_fields={
        "finding_type": FINDING_TYPES,
        "direction": DIRECTIONS,
        "extraction_confidence": EXTRACTION_CONFIDENCES,
        "evidence_strength": EVIDENCE_STRENGTHS,
        "extraction_status": EXTRACTION_STATUSES,
    },
)

RELATIONSHIP_CONTRACT = RecordContract(
    name="Relationship",
    required_fields=(
        "relationship_id",
        "source_entity_id",
        "target_entity_id",
        "relationship_type",
        "basis",
        "evidence_excerpt_ids",
    ),
    non_empty_fields=(
        "relationship_id",
        "source_entity_id",
        "target_entity_id",
        "relationship_type",
        "basis",
    ),
    list_fields=("evidence_excerpt_ids",),
    string_list_fields=("evidence_excerpt_ids",),
    controlled_fields={"relationship_type": RELATIONSHIP_TYPES},
)

GAP_CONTRACT = RecordContract(
    name="Gap",
    required_fields=(
        "gap_id",
        "gap_type",
        "gap_description",
        "topic_ids",
        "basis",
        "supporting_finding_ids",
        "evidence_strength",
    ),
    non_empty_fields=(
        "gap_id",
        "gap_type",
        "gap_description",
        "basis",
        "evidence_strength",
    ),
    list_fields=("topic_ids", "supporting_finding_ids"),
    string_list_fields=("topic_ids", "supporting_finding_ids"),
    controlled_fields={
        "gap_type": GAP_TYPES,
        "evidence_strength": EVIDENCE_STRENGTHS,
    },
)

SYNTHESIS_CLAIM_CONTRACT = RecordContract(
    name="SynthesisClaim",
    required_fields=(
        "synthesis_claim_id",
        "claim_text",
        "topic_ids",
        "supporting_finding_ids",
        "conflicting_finding_ids",
        "evidence_strength",
    ),
    non_empty_fields=(
        "synthesis_claim_id",
        "claim_text",
        "evidence_strength",
    ),
    list_fields=(
        "topic_ids",
        "supporting_finding_ids",
        "conflicting_finding_ids",
    ),
    string_list_fields=(
        "topic_ids",
        "supporting_finding_ids",
        "conflicting_finding_ids",
    ),
    controlled_fields={"evidence_strength": EVIDENCE_STRENGTHS},
)

FIELD_SUMMARY_CONTRACT = RecordContract(
    name="FieldSummary",
    required_fields=(
        "summary_id",
        "research_topic",
        "source_count",
        "finding_count",
        "topic_summaries",
        "gap_ids",
        "synthesis_claim_ids",
        "quality",
    ),
    non_empty_fields=("summary_id",),
    list_fields=("topic_summaries", "gap_ids", "synthesis_claim_ids"),
    string_list_fields=("gap_ids", "synthesis_claim_ids"),
)

KNOWLEDGE_CONTRACTS = {
    "source": SOURCE_CONTRACT,
    "evidence_excerpt": EVIDENCE_EXCERPT_CONTRACT,
    "finding": FINDING_CONTRACT,
    "relationship": RELATIONSHIP_CONTRACT,
    "gap": GAP_CONTRACT,
    "synthesis_claim": SYNTHESIS_CLAIM_CONTRACT,
    "field_summary": FIELD_SUMMARY_CONTRACT,
}