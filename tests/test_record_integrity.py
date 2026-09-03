from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import replace
from pathlib import Path

import pytest

from ad_lit_pipeline.records import (
    RecordIntegrityError,
    read_record_jsonl,
    record_from_dict,
    require_record_integrity,
    validate_record_artifacts,
    validate_record_collection,
    write_integrity_report,
)
from tests.record_contract_fixtures import (
    records_by_type,
    refresh_record_id,
    sha256,
)


FIXTURE_PATH = (
    Path(__file__).resolve().parent
    / "fixtures"
    / "record_contracts"
    / "v1"
    / "records.jsonl"
)


def _records():
    return list(read_record_jsonl(FIXTURE_PATH))


def _codes(report) -> set[str]:
    return {issue.code for issue in report.issues}


def _replace_type(records, replacement):
    return [
        replacement if record.RECORD_TYPE == replacement.RECORD_TYPE else record
        for record in records
    ]


def _second_snapshot():
    payload = deepcopy(records_by_type()["corpus_snapshot"])
    payload["name"] = "Second synthetic snapshot"
    payload["scope"] = dict(payload["scope"])
    payload["scope"]["research_question"] = "Independent snapshot for integrity tests"
    payload["source_version_ids"] = []
    payload["provider_record_ids"] = []
    refresh_record_id(payload)
    payload["corpus_snapshot_id"] = payload["record_id"]
    return record_from_dict(payload)


def test_complete_fixture_has_cross_artifact_integrity() -> None:
    report = validate_record_collection(_records(), verify_local_artifacts=False)

    assert report.is_valid
    assert report.records_checked == 20
    assert report.record_artifacts_checked == 0
    assert report.local_files_verified == 0
    assert report.issues == ()


def test_checked_in_integrity_report_matches_offline_artifact_boundary() -> None:
    expected_path = FIXTURE_PATH.with_name("integrity_report.json")

    report = validate_record_collection(_records())

    assert report.to_dict() == json.loads(expected_path.read_text(encoding="utf-8"))


def test_artifact_loader_retains_context_and_never_fetches_remote_files() -> None:
    report = validate_record_artifacts([FIXTURE_PATH])

    assert report.is_valid
    assert report.records_checked == 20
    assert report.record_artifacts_checked == 1
    assert len(report.warnings) == 4
    assert _codes(report) == {
        "passage_representation_not_checked",
        "remote_artifact_not_checked",
    }
    assert all(issue.artifact_path == str(FIXTURE_PATH) for issue in report.issues)
    assert all(issue.line_number is not None for issue in report.issues)


def test_orphan_reference_is_a_hard_error() -> None:
    records = [record for record in _records() if record.RECORD_TYPE != "passage"]

    report = validate_record_collection(records, verify_local_artifacts=False)

    assert not report.is_valid
    assert "orphan_reference" in _codes(report)


def test_duplicate_ids_and_competing_payloads_are_distinct_errors() -> None:
    records = _records()
    work = next(record for record in records if record.RECORD_TYPE == "scholarly_work")

    duplicate = validate_record_collection(
        [*records, work], verify_local_artifacts=False
    )
    conflict = validate_record_collection(
        [*records, replace(work, preferred_title="Competing title")],
        verify_local_artifacts=False,
    )

    assert "duplicate_record_id" in _codes(duplicate)
    assert "record_id_payload_conflict" in _codes(conflict)


def test_snapshot_closure_detects_undeclared_collected_provider() -> None:
    records = _records()
    payload = deepcopy(records_by_type()["provider_record"])
    payload["provider_item_id"] = "W-FIXTURE-UNDECLARED"
    payload["provider_item_url"] = "https://openalex.org/W-FIXTURE-UNDECLARED"
    payload["raw_record_sha256"] = sha256("undeclared-provider-record")
    refresh_record_id(payload)
    undeclared_provider = record_from_dict(payload)

    report = validate_record_collection(
        [*records, undeclared_provider], verify_local_artifacts=False
    )

    assert "snapshot_membership_omission" in _codes(report)


def test_ownership_mismatch_is_detected_across_records() -> None:
    records = _records()
    access = next(record for record in records if record.RECORD_TYPE == "access_location")
    changed = replace(access, parent_record_ids=())

    report = validate_record_collection(
        _replace_type(records, changed), verify_local_artifacts=False
    )

    assert "ownership_mismatch" in _codes(report)


def test_non_lineage_cross_snapshot_reference_is_rejected() -> None:
    records = _records()
    second = _second_snapshot()
    access = next(record for record in records if record.RECORD_TYPE == "access_location")
    changed = replace(access, corpus_snapshot_id=second.record_id)

    report = validate_record_collection(
        [*_replace_type(records, changed), second],
        verify_local_artifacts=False,
    )

    assert "unauthorized_cross_snapshot_reference" in _codes(report)


def test_explicit_outcome_cross_snapshot_links_are_allowed() -> None:
    records = _records()
    second = _second_snapshot()
    outcome = next(record for record in records if record.RECORD_TYPE == "outcome_event")
    changed = replace(outcome, corpus_snapshot_id=second.record_id)

    report = validate_record_collection(
        [*_replace_type(records, changed), second],
        verify_local_artifacts=False,
    )

    assert "unauthorized_cross_snapshot_reference" not in _codes(report)


def test_cross_record_evidence_span_hash_is_verified() -> None:
    records = _records()
    payload = deepcopy(records_by_type()["claim_evidence"])
    payload["passage_spans"][0]["quoted_text_sha256"] = sha256(
        "different quoted text"
    )
    refresh_record_id(payload)
    changed = record_from_dict(payload)

    report = validate_record_collection(
        _replace_type(records, changed), verify_local_artifacts=False
    )

    assert "evidence_span_hash_mismatch" in _codes(report)


def test_temporal_eligibility_is_checked_against_snapshot_cutoff() -> None:
    records = _records()
    payload = deepcopy(records_by_type()["source_version"])
    payload["availability_earliest"] = {
        "value": "2027-01-01",
        "precision": "day",
        "certainty": "exact",
    }
    payload["availability_latest"] = deepcopy(payload["availability_earliest"])
    payload["publication_date"] = deepcopy(payload["availability_earliest"])
    refresh_record_id(payload)
    changed = record_from_dict(payload)

    report = validate_record_collection(
        _replace_type(records, changed), verify_local_artifacts=False
    )

    assert "temporal_eligibility_mismatch" in _codes(report)


def test_dependency_chronology_rejects_document_before_access() -> None:
    records = _records()
    document = next(record for record in records if record.RECORD_TYPE == "document")
    changed = replace(document, retrieved_at="2026-08-27T07:34:00Z")

    report = validate_record_collection(
        _replace_type(records, changed), verify_local_artifacts=False
    )

    assert "chronology_mismatch" in _codes(report)


def test_parent_cycles_are_hard_errors() -> None:
    records = _records()
    work = next(record for record in records if record.RECORD_TYPE == "scholarly_work")
    payload = deepcopy(records_by_type()["scholarly_work"])
    payload["identity_key"] = "doi:10.0000/step1.4.second"
    payload["identifiers"][0]["value"] = "10.0000/step1.4.second"
    payload["identifiers"][0]["uri"] = "https://doi.org/10.0000/step1.4.second"
    refresh_record_id(payload)
    second_work = record_from_dict(payload)
    first_in_cycle = replace(work, parent_record_ids=(second_work.record_id,))
    second_in_cycle = replace(second_work, parent_record_ids=(work.record_id,))

    report = validate_record_collection(
        [*_replace_type(records, first_in_cycle), second_in_cycle],
        verify_local_artifacts=False,
    )

    assert "parent_record_cycle" in _codes(report)


def test_local_artifact_hash_and_size_are_verified(tmp_path) -> None:
    records = _records()
    document = next(record for record in records if record.RECORD_TYPE == "document")
    local_path = tmp_path / "synthetic.pdf"
    local_path.write_bytes(b"synthetic-pdf-bytes")
    changed = replace(
        document,
        artifact_uri=local_path.name,
        byte_size=len(b"synthetic-pdf-bytes"),
    )

    valid = validate_record_collection(
        _replace_type(records, changed), artifact_root=tmp_path
    )
    local_path.write_bytes(b"tampered")
    tampered = validate_record_collection(
        _replace_type(records, changed), artifact_root=tmp_path
    )

    assert valid.is_valid
    assert valid.local_files_verified == 1
    assert "local_artifact_hash_mismatch" in _codes(tampered)
    assert "local_artifact_size_mismatch" in _codes(tampered)


def test_exact_passage_occurrence_is_checked_when_representation_exists(
    tmp_path,
) -> None:
    records = _records()
    document = next(record for record in records if record.RECORD_TYPE == "document")
    pdf_path = tmp_path / "synthetic.pdf"
    text_path = tmp_path / "normalized.txt"
    pdf_path.write_bytes(b"synthetic-pdf-bytes")
    text_path.write_text("normalized-document-text", encoding="utf-8")
    extensions = dict(document.extensions)
    extensions["pipeline.text_representation"] = {
        "artifact_uri": text_path.name,
        "sha256": sha256("normalized-document-text"),
        "encoding": "utf-8",
    }
    changed = replace(
        document,
        artifact_uri=pdf_path.name,
        byte_size=len(b"synthetic-pdf-bytes"),
        extensions=extensions,
    )

    report = validate_record_collection(
        _replace_type(records, changed), artifact_root=tmp_path
    )

    assert "passage_occurrence_mismatch" in _codes(report)
    assert "passage_representation_not_checked" not in _codes(report)


def test_invalid_json_is_data_and_strict_helper_retains_report(tmp_path) -> None:
    path = tmp_path / "bad.jsonl"
    path.write_text('{"record_type": "unknown"}\nnot-json\n', encoding="utf-8")
    report = validate_record_artifacts([path], verify_local_artifacts=False)

    assert _codes(report) >= {"invalid_local_record", "invalid_record_json"}
    with pytest.raises(RecordIntegrityError) as exc_info:
        require_record_integrity(report)
    assert exc_info.value.report is report


def test_integrity_report_serialization_is_stable(tmp_path) -> None:
    report = validate_record_collection(_records(), verify_local_artifacts=False)
    path = tmp_path / "integrity.json"

    write_integrity_report(path, report)

    assert json.loads(path.read_text(encoding="utf-8")) == report.to_dict()
    assert path.read_bytes().endswith(b"\n")
