from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping

from ad_lit_pipeline.core.errors import ValidationError
from ad_lit_pipeline.records.ids import record_id_prefix


SCHEMA_VERSION = "1.0.0"


@dataclass(frozen=True)
class RecordSchemaSpec:
    """Static dispatch and identity metadata for one record schema version."""

    record_type: str
    schema_version: str
    class_name: str
    id_prefix: str
    identity_field_paths: tuple[str, ...]


def _spec(
    record_type: str,
    class_name: str,
    *identity_field_paths: str,
) -> RecordSchemaSpec:
    if not identity_field_paths:
        raise ValueError(f"{record_type} must declare identity field paths")
    return RecordSchemaSpec(
        record_type=record_type,
        schema_version=SCHEMA_VERSION,
        class_name=class_name,
        id_prefix=record_id_prefix(record_type),
        identity_field_paths=tuple(identity_field_paths),
    )


_RECORD_SPECS = (
    _spec(
        "corpus_snapshot",
        "CorpusSnapshot",
        "as_of",
        "scope",
        "collection_plan_sha256",
        "resolved_plan_sha256",
        "source_version_ids",
        "provider_record_ids",
        "policy_versions",
    ),
    _spec(
        "scholarly_work",
        "ScholarlyWork",
        "identity_basis",
        "identity_key",
    ),
    _spec(
        "source_version",
        "SourceVersion",
        "work_id",
        "version_kind",
        "version_identifiers",
        "source_record_ids",
        "availability_earliest",
        "availability_latest",
        "availability_date_rule",
    ),
    _spec(
        "provider_record",
        "ProviderRecord",
        "provider_name",
        "endpoint",
        "provider_item_id",
        "retrieved_at",
        "request_sha256",
        "raw_record_sha256",
    ),
    _spec(
        "access_location",
        "AccessLocation",
        "source_version_id",
        "uri_sha256",
        "observed_at",
        "access_status",
    ),
    _spec(
        "document",
        "Document",
        "source_version_id",
        "document_role",
        "content_sha256",
    ),
    _spec(
        "passage",
        "Passage",
        "document_id",
        "locator.representation_sha256",
        "locator.start_char",
        "locator.end_char",
        "text_sha256",
    ),
    _spec(
        "entity",
        "Entity",
        "entity_type",
        "ontology_identifiers",
        "normalized_name",
        "topic_ids",
        "source_passage_ids",
    ),
    _spec(
        "claim",
        "Claim",
        "claim_origin",
        "source_version_id",
        "source_claim_ids",
        "claim_type",
        "subject_entity_ids",
        "population_entity_ids",
        "intervention_entity_ids",
        "comparator_entity_ids",
        "outcome_entity_ids",
        "measurement_entity_ids",
        "method_entity_ids",
        "dataset_entity_ids",
        "study_design_entity_ids",
        "setting_entity_ids",
        "polarity",
        "direction",
        "modality",
        "comparability_profile",
        "claim_text",
    ),
    _spec(
        "claim_evidence",
        "ClaimEvidence",
        "claim_id",
        "verifier_id",
        "verified_at",
        "evidence_role",
        "passage_spans",
        "verification_outcome",
    ),
    _spec(
        "relationship",
        "Relationship",
        "subject_id",
        "predicate",
        "object_id",
        "valid_as_of",
        "claim_evidence_ids",
        "passage_ids",
    ),
    _spec(
        "gap_signal",
        "GapSignal",
        "signal_type",
        "corpus_snapshot_id",
        "rule_id",
        "rule_version",
        "as_of",
        "corpus_scope",
        "query_or_cell",
        "rule_inputs",
        "supporting_claim_ids",
        "supporting_passage_ids",
        "relationship_ids",
        "checked_source_version_ids",
    ),
    _spec(
        "gap_candidate",
        "GapCandidate",
        "gap_lineage_id",
        "candidate_version",
    ),
    _spec(
        "verification_attempt",
        "VerificationAttempt",
        "gap_candidate_id",
        "attempt_number",
        "protocol_id",
        "protocol_version",
    ),
    _spec(
        "gap_score",
        "GapScore",
        "gap_candidate_id",
        "score_version",
        "protocol_id",
        "protocol_version",
    ),
    _spec(
        "expert_judgment",
        "ExpertJudgment",
        "protocol_id",
        "protocol_version",
        "task_id",
        "assignment_id",
        "expert_id",
        "gap_candidate_id",
    ),
    _spec(
        "outcome_event",
        "OutcomeEvent",
        "protocol_id",
        "protocol_version",
        "research_project_id",
        "gap_candidate_id",
        "event_type",
        "occurred_on",
        "source_reference_ids",
    ),
    _spec(
        "mantis_export_profile",
        "MantisExportProfile",
        "profile_version",
        "compatibility_version",
        "record_kind",
        "source_contract",
        "source_schema_version",
    ),
    _spec(
        "mantis_interpretation",
        "MantisInterpretation",
        "space_id",
        "map_id",
        "map_profile_version",
        "map_input_sha256",
        "selected_point_ids",
        "actor",
        "prompt_or_action",
        "interpreted_at",
    ),
    _spec(
        "mantis_publication_receipt",
        "MantisPublicationReceipt",
        "export_profile_id",
        "profile_version",
        "source_sha256",
        "tool_name",
        "tool_version",
        "host",
        "operation",
        "attempt_number",
        "idempotency_key",
    ),
)


RECORD_SCHEMA_REGISTRY: Mapping[
    tuple[str, str], RecordSchemaSpec
] = MappingProxyType(
    {
        (spec.record_type, spec.schema_version): spec
        for spec in _RECORD_SPECS
    }
)


def get_record_spec(
    record_type: str,
    schema_version: str = SCHEMA_VERSION,
) -> RecordSchemaSpec:
    """Return the exact registered contract or reject an unsupported version."""
    if not isinstance(record_type, str) or not record_type.strip():
        raise ValidationError("Record type must be a non-empty string.")
    if not isinstance(schema_version, str) or not schema_version.strip():
        raise ValidationError("Schema version must be a non-empty string.")
    key = (record_type.strip(), schema_version.strip())
    spec = RECORD_SCHEMA_REGISTRY.get(key)
    if spec is None:
        raise ValidationError(
            "Unsupported record contract: "
            f"record_type={key[0]!r}, schema_version={key[1]!r}."
        )
    return spec


def list_record_specs(
    schema_version: str = SCHEMA_VERSION,
) -> tuple[RecordSchemaSpec, ...]:
    """List registered contracts for one exact schema version in stable order."""
    if not isinstance(schema_version, str) or not schema_version.strip():
        raise ValidationError("Schema version must be a non-empty string.")
    normalized_version = schema_version.strip()
    specs = tuple(
        spec
        for spec in _RECORD_SPECS
        if spec.schema_version == normalized_version
    )
    if not specs:
        raise ValidationError(
            f"Unsupported schema version {normalized_version!r}."
        )
    return specs
