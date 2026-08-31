from __future__ import annotations

import hashlib
from copy import deepcopy
from typing import Any

from ad_lit_pipeline.records import SCHEMA_VERSION, make_payload_record_id
from ad_lit_pipeline.records.ids import make_record_id


JsonObject = dict[str, Any]

SCIENTIFIC_RECORD_TYPES = {
    "claim_evidence",
    "relationship",
    "gap_signal",
    "gap_candidate",
    "verification_attempt",
    "gap_score",
    "expert_judgment",
    "outcome_event",
    "mantis_interpretation",
}
GAP_ONTOLOGY_RECORD_TYPES = {
    "gap_signal",
    "gap_candidate",
    "verification_attempt",
    "gap_score",
}


def sha256(label: str) -> str:
    return hashlib.sha256(label.encode("utf-8")).hexdigest()


def policy_versions(record_type: str) -> dict[str, str]:
    versions = {"record_contracts": SCHEMA_VERSION}
    if record_type in SCIENTIFIC_RECORD_TYPES:
        versions["scientific_validity"] = "1.0.0"
    if record_type in GAP_ONTOLOGY_RECORD_TYPES:
        versions["gap_ontology"] = "1.0.0"
    return versions


def placeholder_id(record_type: str) -> str:
    return make_record_id(
        record_type,
        {"fixture_placeholder": record_type},
        schema_version=SCHEMA_VERSION,
    )


def base_payload(
    record_type: str,
    snapshot_id: str,
    *,
    parent_record_ids: list[str] | None = None,
    source_record_ids: list[str] | None = None,
) -> JsonObject:
    return {
        "record_type": record_type,
        "schema_version": SCHEMA_VERSION,
        "record_id": placeholder_id(record_type),
        "created_at": "2026-08-27T08:00:00Z",
        "corpus_snapshot_id": snapshot_id,
        "producing_run_id": "fixture-run-step-1-3",
        "producing_step_id": "record_contract_fixture",
        "parent_record_ids": sorted(parent_record_ids or []),
        "source_record_ids": sorted(source_record_ids or []),
        "provenance": [
            {
                "kind": "artifact",
                "relation": "derived_from_fixture",
                "reference": "https://example.invalid/step-1-3/source.json",
                "sha256": sha256("fixture-source"),
            }
        ],
        "record_status": "active",
        "validation_warnings": [],
        "policy_versions": policy_versions(record_type),
        "extensions": {
            "fixture.step_1_3": {"synthetic": True, "case": "valid"}
        },
    }


def refresh_record_id(payload: JsonObject) -> JsonObject:
    payload["record_id"] = make_payload_record_id(
        payload["record_type"],
        payload,
        schema_version=payload["schema_version"],
    )
    return payload


def partial_date(value: str) -> JsonObject:
    return {"value": value, "precision": "day", "certainty": "exact"}


def identifier(scheme: str, value: str, uri: str | None) -> JsonObject:
    return {"scheme": scheme, "value": value, "uri": uri}


def coverage_dimensions() -> JsonObject:
    return {
        "providers": "openalex covered",
        "source_types": "research articles covered",
        "date_window": "2020-01-01 through 2026-08-27",
        "languages": "English covered",
        "query_variants": "declared variants executed",
        "synonym_coverage": "declared synonyms executed",
        "adjacent_literature": "adjacent search executed",
        "retrieval_failures": "none observed",
        "inaccessible_material": "none central",
        "deduplication": "work and version identities applied",
    }


def assessment(dimension: str, value: float, rationale: str) -> JsonObject:
    return {
        "dimension": dimension,
        "value": value,
        "scale": "probability_0_1",
        "rationale": rationale,
        "assessor_id": "fixture-validator-v1",
    }


def score_dimension(
    dimension: str,
    score: float,
    evidence_ids: list[str],
) -> JsonObject:
    return {
        "dimension": dimension,
        "score": score,
        "scale_min": 0.0,
        "scale_max": 1.0,
        "rationale": f"Synthetic {dimension} rationale for contract testing.",
        "evidence_ids": sorted(evidence_ids),
        "assessor_id": "fixture-scoring-protocol-v1",
        "uncertainty": 0.2,
        "calibration_reference_id": None,
    }


def valid_record_payloads() -> list[JsonObject]:
    """Return one coherent, copyright-safe payload for every v1 record type."""
    dummy_snapshot_id = placeholder_id("corpus_snapshot")

    provider = base_payload("provider_record", dummy_snapshot_id)
    provider.update(
        {
            "provider_name": "openalex",
            "provider_version": None,
            "endpoint": "https://api.openalex.org/works",
            "provider_item_id": "W-FIXTURE-001",
            "provider_item_url": "https://openalex.org/W-FIXTURE-001",
            "query_id": "fixture-query-001",
            "request_sha256": sha256("openalex-request"),
            "redacted_request_url": (
                "https://api.openalex.org/works?filter=fixture"
            ),
            "query_tier": 1,
            "page_or_cursor": "page:1",
            "provider_rank": 1,
            "retrieved_at": "2026-08-27T07:30:00Z",
            "provider_updated_at": "2026-08-26T12:00:00Z",
            "retrieval_status": "succeeded",
            "raw_record_media_type": "application/json",
            "raw_record_sha256": sha256("raw-openalex-record"),
            "raw_record_uri": (
                "https://example.invalid/artifacts/openalex-W-FIXTURE-001.json"
            ),
            "license": "CC0",
            "error_code": None,
            "error_message": None,
        }
    )
    refresh_record_id(provider)

    work = base_payload("scholarly_work", dummy_snapshot_id)
    work.update(
        {
            "preferred_title": "Synthetic External Validation Study",
            "alternate_titles": [],
            "work_kind": "research_article",
            "identifiers": [
                identifier(
                    "doi",
                    "10.0000/step1.3.fixture",
                    "https://doi.org/10.0000/step1.3.fixture",
                )
            ],
            "identity_basis": "global_identifier",
            "identity_key": "doi:10.0000/step1.3.fixture",
            "identity_status": "resolved",
        }
    )
    refresh_record_id(work)

    source_version = base_payload(
        "source_version",
        dummy_snapshot_id,
        parent_record_ids=[work["record_id"]],
        source_record_ids=[provider["record_id"]],
    )
    source_version.update(
        {
            "work_id": work["record_id"],
            "version_kind": "version_of_record",
            "version_label": "Version of record",
            "version_number": "1",
            "version_identifiers": [
                identifier(
                    "doi",
                    "10.0000/step1.3.fixture",
                    "https://doi.org/10.0000/step1.3.fixture",
                )
            ],
            "title": "Synthetic External Validation Study",
            "abstract": "A fictional result and bounded future-work request.",
            "contributors": [
                {
                    "name": "Synthetic Researcher",
                    "role": "author",
                    "position": 0,
                    "identifiers": [],
                }
            ],
            "venue": "Synthetic Methods Journal",
            "publisher": None,
            "language": "en",
            "source_type": "primary_study",
            "study_design_entity_ids": [],
            "publication_date": partial_date("2025-04-01"),
            "availability_earliest": partial_date("2025-04-01"),
            "availability_latest": partial_date("2025-04-01"),
            "availability_date_rule": "earliest_public_provider_date_v1",
            "availability_status": "known",
            "temporal_eligibility": "eligible",
            "lifecycle_status": "active",
            "previous_source_version_ids": [],
            "provider_record_ids": [provider["record_id"]],
            "reference_identifiers": [],
        }
    )
    refresh_record_id(source_version)

    snapshot = base_payload("corpus_snapshot", dummy_snapshot_id)
    snapshot.update(
        {
            "name": "Synthetic Step 1.3 corpus snapshot",
            "description": "A frozen cross-domain contract fixture.",
            "snapshot_status": "frozen",
            "as_of": "2026-08-27",
            "availability_date_rule": "earliest_public_provider_date_v1",
            "topic_contract_ref": {
                "topic_id": "fixture_topic",
                "sha256": sha256("fixture-topic-contract"),
                "path": "configs/topics/fixture.yaml",
                "version": "1.0.0",
            },
            "scope": {
                "research_question": "Which findings need external validation?",
                "providers": ["openalex"],
                "source_types": ["research_article"],
                "languages": ["en"],
                "publication_start": "2020-01-01",
                "publication_end": "2026-08-27",
                "inclusion_policy_sha256": sha256("fixture-inclusion-policy"),
                "exclusion_policy_sha256": sha256("fixture-exclusion-policy"),
            },
            "negative_null_policy": "include_when_identified",
            "collection_plan_sha256": sha256("fixture-collection-plan"),
            "resolved_plan_sha256": sha256("fixture-resolved-plan"),
            "retrieval_started_at": "2026-08-27T07:00:00Z",
            "retrieval_completed_at": "2026-08-27T07:45:00Z",
            "source_version_ids": [source_version["record_id"]],
            "provider_record_ids": [provider["record_id"]],
            "coverage": {
                "status": "adequate_for_rule",
                "rule_id": "fixture-snapshot-coverage-v1",
                "searched_sources": ["openalex"],
                "dimensions": coverage_dimensions(),
                "limitations": ["Synthetic corpus with one work."],
            },
            "frozen_at": "2026-08-27T07:50:00Z",
        }
    )
    snapshot_id = make_payload_record_id("corpus_snapshot", snapshot)
    snapshot["record_id"] = snapshot_id
    snapshot["corpus_snapshot_id"] = snapshot_id
    for record in (provider, work, source_version):
        record["corpus_snapshot_id"] = snapshot_id

    uri = "https://example.invalid/full-text/fixture.pdf"
    access = base_payload(
        "access_location",
        snapshot_id,
        parent_record_ids=[source_version["record_id"]],
        source_record_ids=[provider["record_id"]],
    )
    access.update(
        {
            "source_version_id": source_version["record_id"],
            "provider_record_id": provider["record_id"],
            "uri": uri,
            "uri_sha256": sha256(uri),
            "location_kind": "pdf",
            "access_method": "public_http",
            "observed_at": "2026-08-27T07:35:00Z",
            "access_status": "available",
            "media_type": "application/pdf",
            "license": "CC-BY-4.0",
            "is_open_access": True,
            "http_status": 200,
            "redirect_uri": None,
            "failure_reason": None,
        }
    )
    refresh_record_id(access)

    document = base_payload(
        "document",
        snapshot_id,
        parent_record_ids=[source_version["record_id"]],
        source_record_ids=[access["record_id"]],
    )
    document.update(
        {
            "source_version_id": source_version["record_id"],
            "access_location_id": access["record_id"],
            "document_role": "main",
            "media_type": "application/pdf",
            "language": "en",
            "content_sha256": sha256("synthetic-pdf-bytes"),
            "byte_size": 4096,
            "retrieved_at": "2026-08-27T07:40:00Z",
            "artifact_uri": "https://example.invalid/artifacts/fixture.pdf",
            "license": "CC-BY-4.0",
            "document_status": "stored",
            "page_count": 3,
            "encrypted": False,
        }
    )
    refresh_record_id(document)

    passage_text = (
        "Future work should evaluate this method in an independent older-adult "
        "cohort."
    )
    passage = base_payload(
        "passage",
        snapshot_id,
        parent_record_ids=[document["record_id"]],
        source_record_ids=[source_version["record_id"]],
    )
    passage.update(
        {
            "document_id": document["record_id"],
            "source_version_id": source_version["record_id"],
            "sequence_index": 0,
            "passage_kind": "paragraph",
            "text": passage_text,
            "text_sha256": sha256(passage_text),
            "language": "en",
            "section_path": ["Discussion", "Future work"],
            "locator": {
                "coordinate_system": "normalized_utf8_text_v1",
                "representation_sha256": sha256("normalized-document-text"),
                "start_char": 120,
                "end_char": 203,
                "page_start": 3,
                "page_end": 3,
                "paragraph_index": 1,
            },
            "extractor_name": "synthetic-fixture-extractor",
            "extractor_version": "1.0.0",
            "extraction_config_sha256": sha256("fixture-extraction-config"),
            "extracted_at": "2026-08-27T07:55:00Z",
        }
    )
    refresh_record_id(passage)

    entity = base_payload(
        "entity",
        snapshot_id,
        source_record_ids=[passage["record_id"]],
    )
    entity.update(
        {
            "entity_type": "method",
            "canonical_name": "Synthetic classifier",
            "normalized_name": "synthetic classifier",
            "definition": None,
            "aliases": ["fixture classifier"],
            "ontology_identifiers": [],
            "resolution_status": "resolved",
            "resolution_method": "fixture_exact_match_v1",
            "canonical_entity_id": None,
            "source_passage_ids": [passage["record_id"]],
            "topic_ids": ["fixture_topic"],
        }
    )
    refresh_record_id(entity)

    claim = base_payload(
        "claim",
        snapshot_id,
        source_record_ids=[passage["record_id"], source_version["record_id"]],
    )
    claim.update(
        {
            "claim_origin": "source_asserted",
            "claim_type": "future_work",
            "claim_text": (
                "The authors request independent older-adult validation."
            ),
            "source_version_id": source_version["record_id"],
            "source_claim_ids": [],
            "topic_ids": ["fixture_topic"],
            "polarity": "not_applicable",
            "direction": "not_applicable",
            "modality": "recommended",
            "subject_entity_ids": [entity["record_id"]],
            "population_entity_ids": [],
            "intervention_entity_ids": [],
            "comparator_entity_ids": [],
            "outcome_entity_ids": [],
            "measurement_entity_ids": [],
            "method_entity_ids": [entity["record_id"]],
            "dataset_entity_ids": [],
            "study_design_entity_ids": [],
            "setting_entity_ids": [],
            "time_horizon": None,
            "quantitative_details": [],
            "comparability_profile": {
                "population": "older adults",
                "method": "synthetic classifier",
                "outcome": "external validation",
            },
            "extraction_status": "reviewed",
            "extraction_assessment": assessment(
                "extraction_confidence",
                0.9,
                "The exact passage explicitly states the request.",
            ),
        }
    )
    refresh_record_id(claim)

    claim_evidence = base_payload(
        "claim_evidence",
        snapshot_id,
        parent_record_ids=[claim["record_id"]],
        source_record_ids=[passage["record_id"]],
    )
    claim_evidence.update(
        {
            "claim_id": claim["record_id"],
            "source_version_id": source_version["record_id"],
            "evidence_role": "primary_support",
            "passage_spans": [
                {
                    "passage_id": passage["record_id"],
                    "start_char": 0,
                    "end_char": len(passage_text),
                    "quoted_text_sha256": sha256(passage_text),
                }
            ],
            "checked_passage_ids": [passage["record_id"]],
            "verification_outcome": "supported",
            "verifier_id": "fixture-verifier-v1",
            "verification_method": "exact_span_entailment_review_v1",
            "verified_at": "2026-08-27T08:05:00Z",
            "material_checks": {
                "population": "matched",
                "method": "matched",
                "outcome": "matched",
                "direction": "not_applicable",
                "study_design": "not_applicable",
                "numeric_details": "not_applicable",
            },
            "counterclaim_id": None,
            "comparability_key": None,
            "insufficiency_reasons": [],
            "uncertainty_reasons": [],
            "unresolved_checks": [],
            "human_review_triggers": [],
            "verification_assessment": assessment(
                "verification_confidence",
                0.95,
                "The claim is directly entailed by the exact passage.",
            ),
        }
    )
    refresh_record_id(claim_evidence)

    relationship = base_payload(
        "relationship",
        snapshot_id,
        source_record_ids=[claim_evidence["record_id"]],
    )
    relationship.update(
        {
            "subject_id": source_version["record_id"],
            "subject_type": "source_version",
            "predicate": "reports",
            "object_id": claim["record_id"],
            "object_type": "claim",
            "relationship_status": "verified",
            "basis": "The source version reports the passage-verified claim.",
            "claim_evidence_ids": [claim_evidence["record_id"]],
            "passage_ids": [passage["record_id"]],
            "comparability_key": None,
            "valid_as_of": "2026-08-27",
            "asserted_at": "2026-08-27T08:10:00Z",
        }
    )
    refresh_record_id(relationship)

    profile = base_payload("mantis_export_profile", snapshot_id)
    profile.update(
        {
            "profile_version": "1.0.0",
            "compatibility_version": "1.0.0",
            "record_kind": "paper",
            "source_contract": "scholarly_work",
            "source_schema_version": "1.0.0",
            "eligible_statuses": ["active"],
            "point_id_source_path": "record_id",
            "fields": [
                {
                    "output_name": "title",
                    "source_path": "preferred_title",
                    "mantis_type": "Title",
                    "required": True,
                    "null_policy": "error",
                    "multivalue_policy": "first",
                    "separator": None,
                    "semantic_order": None,
                },
                {
                    "output_name": "semantic",
                    "source_path": "preferred_title",
                    "mantis_type": "Semantic",
                    "required": True,
                    "null_policy": "error",
                    "multivalue_policy": "first",
                    "separator": None,
                    "semantic_order": 0,
                },
            ],
            "semantic_text": {
                "template": "{preferred_title}",
                "source_paths": ["preferred_title"],
            },
            "row_sort_paths": ["record_id"],
            "csv_policy": {
                "encoding": "utf-8",
                "delimiter": ",",
                "line_ending": "lf",
            },
            "supported_tool_versions": ["mantis-web-2026"],
            "connection_compatibility_verified": False,
        }
    )
    refresh_record_id(profile)

    source_hash = sha256("fixture-mantis-csv")
    receipt = base_payload(
        "mantis_publication_receipt",
        snapshot_id,
        parent_record_ids=[profile["record_id"]],
    )
    receipt.update(
        {
            "export_profile_id": profile["record_id"],
            "profile_version": "1.0.0",
            "compatibility_version": "1.0.0",
            "source_contract": "scholarly_work",
            "source_schema_version": "1.0.0",
            "source_artifact_reference": {
                "kind": "artifact",
                "relation": "published_from",
                "reference": "https://example.invalid/artifacts/mantis.csv",
                "sha256": source_hash,
            },
            "source_sha256": source_hash,
            "record_count": 1,
            "tool_name": "mantis-web",
            "tool_version": "2026.08",
            "host": "mantis.csail.mit.edu",
            "operation": "manual_import",
            "duplicate_policy": "reject",
            "attempt_number": 1,
            "retry_of_receipt_id": None,
            "started_at": "2026-08-27T08:15:00Z",
            "completed_at": "2026-08-27T08:16:00Z",
            "published_at": "2026-08-27T08:16:00Z",
            "publication_status": "succeeded",
            "space_id": "fixture-space",
            "map_id": "fixture-paper-map",
            "space_uri": "https://mantis.csail.mit.edu/space/fixture-space",
            "map_uri": "https://mantis.csail.mit.edu/map/fixture-paper-map",
            "idempotency_key": "fixture-paper-map-v1",
            "error": None,
        }
    )
    refresh_record_id(receipt)

    candidate = base_payload("gap_candidate", snapshot_id)
    candidate.update(
        {
            "gap_lineage_id": "fixture-gap-lineage-external-validation",
            "candidate_version": 1,
            "supersedes_candidate_id": None,
            "gap_type_id": "explicit_author_stated",
            "gap_type_version": "1.0.0",
            "title": "Independent older-adult validation",
            "statement": (
                "The source authors request independent older-adult validation."
            ),
            "rationale": "A verified future-work passage supplies the signal.",
            "research_question": (
                "Does the synthetic classifier validate in an independent "
                "older-adult cohort?"
            ),
            "corpus_scope": {
                "description": "Synthetic OpenAlex research-article scope",
                "providers": ["openalex"],
            },
            "as_of": "2026-08-27",
            "availability_date_rule": "earliest_public_provider_date_v1",
            "signal_ids": [],
            "supporting_claim_ids": [claim["record_id"]],
            "coverage_status": "adequate_for_rule",
            "coverage_dimensions": coverage_dimensions(),
            "uncertainty_reasons": [
                "An author request does not establish field-wide novelty."
            ],
            "resolution_rule_id": "direct-external-validation-study-v1",
            "resolution_rule_version": "1.0.0",
            "gap_status": "proposed",
            "state_history": [],
            "verification_attempt_ids": [],
            "decisive_verification_attempt_id": None,
            "human_review_trigger_ids": [],
            "canonical_gap_id": None,
        }
    )
    refresh_record_id(candidate)

    signal = base_payload(
        "gap_signal",
        snapshot_id,
        source_record_ids=[claim["record_id"], passage["record_id"]],
    )
    signal.update(
        {
            "signal_type": "explicit_future_work_passage",
            "gap_type_ids": ["explicit_author_stated"],
            "rule_id": "explicit-future-work-passage-v1",
            "rule_version": "1.0.0",
            "statement": (
                "The authors request independent older-adult validation."
            ),
            "corpus_scope": {
                "description": "Synthetic OpenAlex research-article scope",
                "providers": ["openalex"],
            },
            "as_of": "2026-08-27",
            "availability_date_rule": "earliest_public_provider_date_v1",
            "query_or_cell": "claim_type=future_work",
            "rule_inputs": {
                "claim_id": claim["record_id"],
                "passage_id": passage["record_id"],
            },
            "rule_result": {"matched": True, "attribution": "source_authors"},
            "rule_trace_sha256": sha256("fixture-gap-signal-trace"),
            "supporting_claim_ids": [claim["record_id"]],
            "supporting_passage_ids": [passage["record_id"]],
            "relationship_ids": [relationship["record_id"]],
            "checked_source_version_ids": [source_version["record_id"]],
            "retrieval_query_log_ids": ["fixture-query-log-001"],
            "coverage_status": "adequate_for_rule",
            "coverage_dimensions": coverage_dimensions(),
            "uncertainty_reasons": [
                "Adjacent literature may address the bounded request."
            ],
            "deterministic": True,
            "source_interpretation_ids": [],
        }
    )
    refresh_record_id(signal)

    attempt = base_payload(
        "verification_attempt",
        snapshot_id,
        parent_record_ids=[candidate["record_id"]],
        source_record_ids=[signal["record_id"]],
    )
    attempt.update(
        {
            "gap_candidate_id": candidate["record_id"],
            "attempt_number": 1,
            "attempt_status": "in_progress",
            "from_gap_status": "verification_in_progress",
            "resulting_gap_status": None,
            "protocol_id": "fixture-gap-verification",
            "protocol_version": "1.0.0",
            "started_at": "2026-08-27T08:20:00Z",
            "completed_at": None,
            "verifier_ids": ["fixture-verifier-v1"],
            "checks": [],
            "supporting_claim_evidence_ids": [claim_evidence["record_id"]],
            "counterclaim_evidence_ids": [],
            "checked_passage_ids": [passage["record_id"]],
            "counterretrieval_ids": ["fixture-counterretrieval-001"],
            "retrieval_query_log_ids": ["fixture-query-log-001"],
            "refuting_evidence_ids": [],
            "resolving_evidence_ids": [],
            "coverage_status": "adequate_for_rule",
            "coverage_dimensions": coverage_dimensions(),
            "human_review_trigger_ids": [],
            "expert_judgment_ids": [],
            "uncertainty_reasons": ["Counterretrieval remains in progress."],
            "unresolved_check_ids": ["counterretrieval_complete"],
            "decision_rationale": "Verification is still in progress.",
            "resolution_rule_id": None,
            "resolution_as_of": None,
            "canonical_gap_id": None,
            "artifact_type": None,
            "artifact_basis_ids": [],
        }
    )
    refresh_record_id(attempt)

    candidate["signal_ids"] = [signal["record_id"]]
    candidate["gap_status"] = "verification_in_progress"
    candidate["state_history"] = [
        {
            "from_gap_status": "proposed",
            "to_gap_status": "verification_in_progress",
            "transitioned_at": "2026-08-27T08:20:00Z",
            "actor_id": "fixture-verifier-v1",
            "verification_attempt_id": attempt["record_id"],
            "completed_check_ids": [
                "candidate_version_frozen",
                "corpus_snapshot_recorded",
                "as_of_recorded",
                "deterministic_signal_recorded",
            ],
            "reason": "Begin standard counterretrieval and verification.",
            "new_candidate_version": False,
        }
    ]
    candidate["verification_attempt_ids"] = [attempt["record_id"]]

    interpretation = base_payload(
        "mantis_interpretation",
        snapshot_id,
        source_record_ids=[work["record_id"]],
    )
    interpretation.update(
        {
            "space_id": "fixture-space",
            "map_id": "fixture-paper-map",
            "map_profile_version": "1.0.0",
            "map_input_sha256": source_hash,
            "selected_point_ids": [work["record_id"]],
            "selected_remote_point_ids": ["remote-point-001"],
            "actor": "fixture-researcher",
            "actor_type": "human",
            "prompt_or_action": "Compare the selected paper with adjacent points.",
            "interpreted_at": "2026-08-27T08:25:00Z",
            "output_text": (
                "Hypothesis: independent external validation may be useful."
            ),
            "interpretation_type": "gap_hypothesis",
            "is_evidence": False,
            "downstream_state": "candidate_created",
            "independent_signal_ids": [signal["record_id"]],
            "created_candidate_ids": [candidate["record_id"]],
            "publication_receipt_id": receipt["record_id"],
        }
    )
    refresh_record_id(interpretation)
    signal["source_interpretation_ids"] = [interpretation["record_id"]]

    expert = base_payload(
        "expert_judgment",
        snapshot_id,
        parent_record_ids=[candidate["record_id"]],
        source_record_ids=[receipt["record_id"]],
    )
    expert.update(
        {
            "protocol_id": "fixture-expert-protocol",
            "protocol_version": "1.0.0",
            "task_id": "fixture-task-001",
            "assignment_id": "fixture-assignment-001",
            "expert_id": "fixture-expert-pseudonym-001",
            "gap_candidate_id": candidate["record_id"],
            "gap_list_version_id": "fixture-gap-list-v1",
            "condition_id": "mantis-assisted",
            "blinding_state": "partially_blinded",
            "presented_artifact_ids": [candidate["record_id"]],
            "mantis_profile_id": profile["record_id"],
            "mantis_input_sha256": source_hash,
            "mantis_receipt_id": receipt["record_id"],
            "decision": "accept",
            "decision_confidence": 0.8,
            "confidence_scale_id": "probability_0_1",
            "rationale": "The bounded question is useful for further review.",
            "started_at": "2026-08-27T08:30:00Z",
            "submitted_at": "2026-08-27T08:35:00Z",
            "duration_seconds": 300.0,
            "known_evidence_ids": [],
            "canonical_gap_id": None,
            "supersedes_judgment_id": None,
        }
    )
    refresh_record_id(expert)

    gap_score = base_payload(
        "gap_score",
        snapshot_id,
        parent_record_ids=[candidate["record_id"]],
        source_record_ids=[claim_evidence["record_id"]],
    )
    gap_score.update(
        {
            "gap_candidate_id": candidate["record_id"],
            "score_version": "1.0.0",
            "protocol_id": "fixture-gap-scoring",
            "protocol_version": "1.0.0",
            "candidate_gap_status": "verification_in_progress",
            "novelty": score_dimension(
                "novelty", 0.5, [claim_evidence["record_id"]]
            ),
            "importance": score_dimension(
                "importance", 0.7, [claim_evidence["record_id"]]
            ),
            "feasibility": score_dimension(
                "feasibility", 0.8, [claim_evidence["record_id"]]
            ),
            "calibration_status": "uncalibrated",
            "calibration_dataset_id": None,
            "expert_judgment_ids": [expert["record_id"]],
            "composite": None,
            "composite_rule_id": None,
            "composite_rule_version": None,
        }
    )
    refresh_record_id(gap_score)

    outcome = base_payload(
        "outcome_event",
        snapshot_id,
        parent_record_ids=[candidate["record_id"]],
        source_record_ids=[expert["record_id"]],
    )
    outcome.update(
        {
            "protocol_id": "fixture-outcome-protocol",
            "protocol_version": "1.0.0",
            "gap_candidate_id": candidate["record_id"],
            "expert_judgment_ids": [expert["record_id"]],
            "research_project_id": "fixture-project-001",
            "event_type": "study_started",
            "occurred_on": "2026-08-27",
            "date_precision": "day",
            "outcome_status": "reported",
            "source_reference_ids": [expert["record_id"]],
            "verification_method": "synthetic_fixture_assertion",
            "corrects_event_id": None,
            "causal_attribution": "none",
            "notes": "Synthetic event for schema validation only.",
        }
    )
    refresh_record_id(outcome)

    records = [
        snapshot,
        work,
        source_version,
        provider,
        access,
        document,
        passage,
        entity,
        claim,
        claim_evidence,
        relationship,
        signal,
        candidate,
        attempt,
        gap_score,
        expert,
        outcome,
        profile,
        interpretation,
        receipt,
    ]
    return deepcopy(records)


def records_by_type() -> dict[str, JsonObject]:
    return {record["record_type"]: record for record in valid_record_payloads()}
