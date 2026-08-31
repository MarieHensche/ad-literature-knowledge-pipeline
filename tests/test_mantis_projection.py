from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from ad_lit_pipeline.mantis.profiles import (
    DEFAULT_PROFILE_DIRECTORY,
    ProfileContext,
    compile_profile,
    load_profile_template,
    template_sha256,
)
from ad_lit_pipeline.mantis.projection import export_mantis_views, project_records
from ad_lit_pipeline.records import (
    CorpusSnapshot,
    RecordIntegrityError,
    read_record_jsonl,
    validate_record_collection,
    write_record_jsonl,
)
from tests.mantis_fixtures import mantis_records


FIXTURE_DIRECTORY = Path(__file__).parent / "fixtures" / "mantis_views" / "v1"
MANIFEST = json.loads(
    (FIXTURE_DIRECTORY / "manifest.json").read_text(encoding="utf-8")
)
CREATED_AT = "2026-08-27T08:00:00Z"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_mantis_fixture_is_complete_valid_and_frozen(tmp_path: Path) -> None:
    records = mantis_records()
    report = validate_record_collection(records, verify_local_artifacts=False)
    source = tmp_path / "records.jsonl"
    write_record_jsonl(source, records)

    assert report.is_valid
    assert not report.errors
    assert _sha256(source) == MANIFEST["source_jsonl_sha256"]
    assert MANIFEST["copyright_status"].startswith("All records")


def test_all_versioned_mantis_views_match_frozen_csvs(tmp_path: Path) -> None:
    source = tmp_path / "records.jsonl"
    output = tmp_path / "mantis"
    write_record_jsonl(source, mantis_records())

    first = export_mantis_views(
        source,
        output,
        producing_run_id="fixture-run-step-1-7",
        created_at=CREATED_AT,
    )
    second = export_mantis_views(
        source,
        tmp_path / "second",
        producing_run_id="fixture-run-step-1-7",
        created_at=CREATED_AT,
    )

    assert {view.record_kind: view.row_count for view in first} == {
        kind: expected["rows"] for kind, expected in MANIFEST["views"].items()
    }
    for first_view, second_view in zip(first, second, strict=True):
        expected = FIXTURE_DIRECTORY / "expected" / f"{first_view.record_kind}.csv"
        assert first_view.csv_path.read_bytes() == expected.read_bytes()
        assert first_view.csv_path.read_bytes() == second_view.csv_path.read_bytes()
        assert _sha256(first_view.csv_path) == MANIFEST["views"][
            first_view.record_kind
        ]["csv_sha256"]
        report = json.loads(first_view.report_path.read_text(encoding="utf-8"))
        assert report["eligible_row_count"] == 1
        assert report["excluded_record_count"] == 0
        assert report["connection_fields_enabled"] is False


def test_profile_templates_are_hash_frozen_by_the_fixture_manifest() -> None:
    for kind, expected in MANIFEST["profile_template_sha256"].items():
        template = load_profile_template(
            DEFAULT_PROFILE_DIRECTORY / f"{kind}_v1.yaml"
        )
        assert template_sha256(template) == expected


def test_in_progress_gap_is_excluded_from_verified_open_view() -> None:
    records = read_record_jsonl(
        Path("tests/fixtures/record_contracts/v1/records.jsonl")
    )
    snapshot = next(
        record for record in records if isinstance(record, CorpusSnapshot)
    )
    profile = compile_profile(
        load_profile_template(DEFAULT_PROFILE_DIRECTORY / "verified_gap_v1.yaml"),
        ProfileContext(
            corpus_snapshot_id=snapshot.record_id,
            producing_run_id="gap-exclusion-test",
            created_at=CREATED_AT,
        ),
    )

    result = project_records(records, profile)

    assert result.rows == ()
    assert result.report["exclusion_reasons"] == {
        "gap_status_verification_in_progress": 1
    }


def test_projection_rejects_an_incomplete_record_collection() -> None:
    incomplete = tuple(
        record
        for record in mantis_records()
        if record.RECORD_TYPE != "source_version"
    )
    snapshot = next(
        record for record in incomplete if isinstance(record, CorpusSnapshot)
    )
    profile = compile_profile(
        load_profile_template(DEFAULT_PROFILE_DIRECTORY / "paper_v1.yaml"),
        ProfileContext(
            corpus_snapshot_id=snapshot.record_id,
            producing_run_id="integrity-rejection-test",
            created_at=CREATED_AT,
        ),
    )

    with pytest.raises(RecordIntegrityError):
        project_records(incomplete, profile)
