from __future__ import annotations

import json
import hashlib
from copy import deepcopy
from dataclasses import FrozenInstanceError
from pathlib import Path
from types import MappingProxyType

import pytest

from ad_lit_pipeline.core.errors import ValidationError
from ad_lit_pipeline.records import (
    RECORD_MODELS,
    SCHEMA_VERSION,
    identity_payload,
    iter_record_jsonl,
    make_payload_record_id,
    make_record_id,
    read_record_jsonl,
    record_from_dict,
    record_to_dict,
    validate_record,
    write_record_jsonl,
)
from tests.record_contract_fixtures import (
    coverage_dimensions,
    records_by_type,
    refresh_record_id,
    valid_record_payloads,
)


EXPECTED_TYPES = (
    "corpus_snapshot",
    "scholarly_work",
    "source_version",
    "provider_record",
    "access_location",
    "document",
    "passage",
    "entity",
    "claim",
    "claim_evidence",
    "relationship",
    "gap_signal",
    "gap_candidate",
    "verification_attempt",
    "gap_score",
    "expert_judgment",
    "outcome_event",
    "mantis_export_profile",
    "mantis_interpretation",
    "mantis_publication_receipt",
)

FIXTURE_DIR = (
    Path(__file__).resolve().parent / "fixtures" / "record_contracts" / "v1"
)


def invalid_payload(
    record_type: str,
    field: str,
    value: object,
    *,
    refresh_id: bool = True,
) -> dict[str, object]:
    payload = deepcopy(records_by_type()[record_type])
    payload[field] = value
    if refresh_id:
        refresh_record_id(payload)
    return payload


def test_fixture_covers_every_registered_contract_once() -> None:
    payloads = valid_record_payloads()

    assert tuple(payload["record_type"] for payload in payloads) == EXPECTED_TYPES
    assert len(payloads) == len(RECORD_MODELS) == 20
    assert set(EXPECTED_TYPES) == set(RECORD_MODELS)


def test_checked_in_jsonl_and_manifest_match_deterministic_builder() -> None:
    manifest = json.loads(
        (FIXTURE_DIR / "manifest.json").read_text(encoding="utf-8")
    )
    fixture_path = FIXTURE_DIR / "records.jsonl"
    fixture_bytes = fixture_path.read_bytes()
    records = read_record_jsonl(fixture_path)

    assert manifest["record_count"] == len(records) == 20
    assert tuple(manifest["record_types"]) == EXPECTED_TYPES
    assert tuple(record.RECORD_TYPE for record in records) == EXPECTED_TYPES
    assert hashlib.sha256(fixture_bytes).hexdigest() == (
        manifest["files"]["records.jsonl"]["sha256"]
    )
    assert [record_to_dict(record) for record in records] == valid_record_payloads()


@pytest.mark.parametrize("payload", valid_record_payloads(), ids=EXPECTED_TYPES)
def test_every_representative_record_validates_and_round_trips(
    payload: dict[str, object],
) -> None:
    record = record_from_dict(payload)
    serialized = record_to_dict(record)

    assert serialized == payload
    assert record_from_dict(serialized) == record
    validate_record(record)
    assert record.record_id == make_payload_record_id(
        record.RECORD_TYPE,
        serialized,
        schema_version=SCHEMA_VERSION,
    )
    assert identity_payload(record.RECORD_TYPE, serialized)


def test_jsonl_codec_streams_in_stable_order_and_is_deterministic(tmp_path) -> None:
    path = tmp_path / "records.jsonl"
    second_path = tmp_path / "records_second.jsonl"
    records = tuple(record_from_dict(item) for item in valid_record_payloads())

    write_record_jsonl(path, records)
    streamed = tuple(iter_record_jsonl(path))
    write_record_jsonl(second_path, streamed)

    assert streamed == records
    assert read_record_jsonl(path) == records
    assert path.read_bytes() == second_path.read_bytes()
    assert path.read_text(encoding="utf-8").count("\n") == 20


def test_jsonl_error_includes_file_and_line_context(tmp_path) -> None:
    path = tmp_path / "invalid.jsonl"
    path.write_text('{"record_type":"unknown"}\nnot-json\n', encoding="utf-8")

    with pytest.raises(ValidationError, match=r"invalid\.jsonl:1"):
        tuple(iter_record_jsonl(path))


def test_records_and_nested_json_are_deeply_immutable() -> None:
    record = record_from_dict(records_by_type()["gap_signal"])

    assert isinstance(record.rule_inputs, MappingProxyType)
    with pytest.raises(FrozenInstanceError):
        record.statement = "changed"  # type: ignore[misc]
    with pytest.raises(TypeError):
        record.rule_inputs["claim_id"] = "changed"  # type: ignore[index]


def test_parser_requires_explicit_nulls_and_rejects_unknown_core_fields() -> None:
    missing = deepcopy(records_by_type()["scholarly_work"])
    missing.pop("extensions")
    unknown = deepcopy(records_by_type()["scholarly_work"])
    unknown["future_field"] = "not namespaced"

    with pytest.raises(ValidationError, match="missing required fields.*extensions"):
        record_from_dict(missing)
    with pytest.raises(ValidationError, match="unknown fields.*future_field"):
        record_from_dict(unknown)


def test_only_namespaced_object_extensions_are_accepted() -> None:
    unnamespaced = invalid_payload(
        "scholarly_work",
        "extensions",
        {"openalex": {"id": "W1"}},
    )
    scalar = invalid_payload(
        "scholarly_work",
        "extensions",
        {"provider.openalex": "W1"},
    )

    with pytest.raises(ValidationError, match="namespaced key"):
        record_from_dict(unnamespaced)
    with pytest.raises(ValidationError, match="must be an object"):
        record_from_dict(scalar)


def test_stable_id_is_recomputed_not_just_prefix_checked() -> None:
    payload = invalid_payload(
        "scholarly_work",
        "preferred_title",
        "Changed wording does not affect work identity",
        refresh_id=False,
    )
    assert record_from_dict(payload).preferred_title.startswith("Changed")

    identity_change = invalid_payload(
        "scholarly_work",
        "identity_key",
        "doi:10.0000/different",
        refresh_id=False,
    )
    with pytest.raises(ValidationError, match="does not match.*identity projection"):
        record_from_dict(identity_change)


def test_rfc3339_utc_offsets_canonicalize_to_z_before_identity_hashing() -> None:
    payload = deepcopy(records_by_type()["provider_record"])
    payload["retrieved_at"] = "2026-08-27T07:30:00+00:00"

    record = record_from_dict(payload)

    assert record.retrieved_at == "2026-08-27T07:30:00Z"
    assert record_to_dict(record)["retrieved_at"] == "2026-08-27T07:30:00Z"


@pytest.mark.parametrize(
    "timestamp",
    ["2026-08-27T08:00:00", "2026-08-27T10:00:00+02:00", "not-a-date"],
)
def test_records_reject_non_utc_or_invalid_timestamps(timestamp: str) -> None:
    payload = invalid_payload(
        "scholarly_work",
        "created_at",
        timestamp,
        refresh_id=False,
    )
    with pytest.raises(ValidationError, match="RFC3339|UTC|timestamp"):
        record_from_dict(payload)


def test_record_local_validation_rejects_nonfinite_json_numbers() -> None:
    payload = invalid_payload(
        "expert_judgment",
        "duration_seconds",
        float("nan"),
        refresh_id=False,
    )

    with pytest.raises(ValidationError, match="finite number"):
        record_from_dict(payload)


def test_unknown_availability_cannot_be_assumed_temporally_eligible() -> None:
    payload = records_by_type()["source_version"]
    payload["availability_earliest"] = None
    payload["availability_latest"] = None
    payload["availability_status"] = "unknown"
    payload["temporal_eligibility"] = "eligible"
    refresh_record_id(payload)

    with pytest.raises(ValidationError, match="cannot be assumed eligible"):
        record_from_dict(payload)


def test_passage_hash_and_coordinates_are_locally_verified() -> None:
    wrong_hash = invalid_payload(
        "passage",
        "text_sha256",
        "f" * 64,
        refresh_id=False,
    )
    refresh_record_id(wrong_hash)
    with pytest.raises(ValidationError, match="does not match text"):
        record_from_dict(wrong_hash)

    bad_locator = deepcopy(records_by_type()["passage"])
    bad_locator["locator"]["end_char"] = bad_locator["locator"]["start_char"]
    refresh_record_id(bad_locator)
    with pytest.raises(ValidationError, match="greater than start_char"):
        record_from_dict(bad_locator)


def test_claim_verification_outcomes_have_distinct_required_evidence() -> None:
    unsupported = invalid_payload(
        "claim_evidence",
        "passage_spans",
        [],
    )
    with pytest.raises(ValidationError, match="supported outcome requires exact spans"):
        record_from_dict(unsupported)

    contradictory = records_by_type()["claim_evidence"]
    contradictory["verification_outcome"] = "contradicted"
    contradictory["counterclaim_id"] = None
    contradictory["comparability_key"] = None
    refresh_record_id(contradictory)
    with pytest.raises(ValidationError, match="counterclaim.*comparability"):
        record_from_dict(contradictory)


def test_gap_signal_must_be_deterministic_and_match_operational_class() -> None:
    nondeterministic = invalid_payload("gap_signal", "deterministic", False)
    with pytest.raises(ValidationError, match="interpretations alone are not signals"):
        record_from_dict(nondeterministic)

    wrong_type = invalid_payload(
        "gap_signal",
        "signal_type",
        "graph_connectivity_below_threshold",
    )
    with pytest.raises(ValidationError, match="not allowed"):
        record_from_dict(wrong_type)


def test_gap_candidate_requires_independent_signal_and_valid_state_history() -> None:
    without_signal = invalid_payload("gap_candidate", "signal_ids", [])
    with pytest.raises(ValidationError, match="signal_ids.*must not be empty"):
        record_from_dict(without_signal)

    direct_promotion = records_by_type()["gap_candidate"]
    direct_promotion["state_history"][0]["to_gap_status"] = "verified_open"
    direct_promotion["gap_status"] = "verified_open"
    direct_promotion["decisive_verification_attempt_id"] = (
        direct_promotion["verification_attempt_ids"][0]
    )
    refresh_record_id(direct_promotion)
    with pytest.raises(ValidationError, match="transition is not allowed"):
        record_from_dict(direct_promotion)


def test_reassessment_version_records_terminal_to_verification_transition() -> None:
    prior = records_by_type()["gap_candidate"]
    payload = deepcopy(prior)
    payload["candidate_version"] = 2
    payload["supersedes_candidate_id"] = prior["record_id"]
    payload["state_history"] = [
        {
            "from_gap_status": "uncertain",
            "to_gap_status": "verification_in_progress",
            "transitioned_at": "2026-08-27T09:00:00Z",
            "actor_id": "fixture-verifier-v1",
            "verification_attempt_id": payload["verification_attempt_ids"][0],
            "completed_check_ids": ["new_evidence_access_or_rule_recorded"],
            "reason": "New accessible evidence permits reassessment.",
            "new_candidate_version": True,
        }
    ]
    refresh_record_id(payload)

    assert record_from_dict(payload).candidate_version == 2


def test_gap_scores_are_three_distinct_dimensions() -> None:
    payload = records_by_type()["gap_score"]
    payload["importance"]["dimension"] = "novelty"
    refresh_record_id(payload)

    with pytest.raises(ValidationError, match="importance.*must be 'importance'"):
        record_from_dict(payload)


def test_optional_composite_score_requires_an_explicit_versioned_rule() -> None:
    payload = records_by_type()["gap_score"]
    payload["composite"] = {
        "dimension": "composite",
        "score": 0.66,
        "scale_min": 0.0,
        "scale_max": 1.0,
        "rationale": "Illustrative composite only.",
        "evidence_ids": [],
        "assessor_id": "fixture-scoring-protocol-v1",
        "uncertainty": 0.3,
        "calibration_reference_id": None,
    }
    refresh_record_id(payload)

    with pytest.raises(ValidationError, match="explicit composite rule"):
        record_from_dict(payload)


def test_mantis_interpretation_is_never_evidence_or_a_signal_by_itself() -> None:
    as_evidence = invalid_payload("mantis_interpretation", "is_evidence", True)
    with pytest.raises(ValidationError, match="never scientific evidence"):
        record_from_dict(as_evidence)

    no_signal = records_by_type()["mantis_interpretation"]
    no_signal["independent_signal_ids"] = []
    refresh_record_id(no_signal)
    with pytest.raises(ValidationError, match="independent deterministic signal"):
        record_from_dict(no_signal)


def test_mantis_profile_requires_title_semantic_and_gates_connection() -> None:
    missing_title = records_by_type()["mantis_export_profile"]
    missing_title["fields"] = missing_title["fields"][1:]
    refresh_record_id(missing_title)
    with pytest.raises(ValidationError, match="exactly one Title"):
        record_from_dict(missing_title)

    connection = records_by_type()["mantis_export_profile"]
    connection["fields"].append(
        {
            "output_name": "connections",
            "source_path": "relationship_ids",
            "mantis_type": "Connection",
            "required": False,
            "null_policy": "empty",
            "multivalue_policy": "join",
            "separator": "|",
            "semantic_order": None,
        }
    )
    refresh_record_id(connection)
    with pytest.raises(ValidationError, match="compatibility verification"):
        record_from_dict(connection)


def test_mantis_receipts_reject_credentials_and_incomplete_success() -> None:
    credential = invalid_payload(
        "mantis_publication_receipt",
        "host",
        "https://user:secret@mantis.example",
    )
    with pytest.raises(ValidationError, match="hostname"):
        record_from_dict(credential)

    incomplete = invalid_payload(
        "mantis_publication_receipt",
        "map_id",
        None,
        refresh_id=False,
    )
    with pytest.raises(ValidationError, match="success requires"):
        record_from_dict(incomplete)


def test_local_validation_accepts_syntactic_orphan_for_step_1_4() -> None:
    payload = records_by_type()["claim"]
    orphan = make_record_id(
        "source_version",
        {"fixture": "intentionally absent"},
        schema_version=SCHEMA_VERSION,
    )
    payload["source_version_id"] = orphan
    refresh_record_id(payload)

    record = record_from_dict(payload)

    assert record.source_version_id == orphan


def test_jsonl_output_is_standard_json_not_python_enum_repr(tmp_path) -> None:
    path = tmp_path / "records.jsonl"
    write_record_jsonl(
        path,
        [record_from_dict(records_by_type()["claim_evidence"])],
    )
    payload = json.loads(path.read_text(encoding="utf-8"))

    assert payload["verification_outcome"] == "supported"
    assert payload["record_status"] == "active"
    assert payload["material_checks"]["population"] == "matched"


def test_coverage_requires_every_scientific_validity_dimension() -> None:
    dimensions = coverage_dimensions()
    dimensions.pop("adjacent_literature")
    payload = invalid_payload(
        "gap_signal",
        "coverage_dimensions",
        dimensions,
    )

    with pytest.raises(ValidationError, match="exact policy dimensions"):
        record_from_dict(payload)
