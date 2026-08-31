from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path

from ad_lit_pipeline.steps.export import mantis


FIXTURE_DIR = Path(__file__).parent / "fixtures" / "synthetic_baseline" / "v1"
MANIFEST_PATH = FIXTURE_DIR / "manifest.json"


def read_csv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        return list(reader.fieldnames or []), list(reader)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_synthetic_baseline_fixture_matches_manifest() -> None:
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    fixture = manifest["fixture"]

    assert manifest["baseline_id"] == "step_1_1_synthetic_v1"
    assert manifest["status"] == "complete"
    assert manifest["repository"]["head"] == (
        "dd1fbc3d9faa727d9a472ffe709046a6fb10b397"
    )
    assert manifest["pre_step_regression"]["tests_passed"] == 295
    assert manifest["post_step_regression"]["status"] == "passed"
    assert manifest["post_step_regression"]["tests_passed"] == 297
    assert fixture["record_count"] == 8

    ids_by_file: dict[str, list[str]] = {}
    for relative_path, expected in fixture["files"].items():
        path = FIXTURE_DIR / relative_path
        _, rows = read_csv(path)
        assert len(rows) == expected["rows"]
        assert sha256(path) == expected["sha256"]
        ids_by_file[relative_path] = [row["paper_id"] for row in rows]

    case_ids = [case["paper_id"] for case in fixture["cases"]]
    assert ids_by_file["papers.csv"] == case_ids
    assert ids_by_file["extraction_filled.csv"] == case_ids
    assert len(case_ids) == len(set(case_ids))
    assert all(paper_id.startswith("synthetic_ad_") for paper_id in case_ids)

    exported_ids = manifest["expected_mantis"]["exported_ids"]
    assert ids_by_file["expected/mantis_ready.csv"] == exported_ids
    assert exported_ids == [
        case["paper_id"]
        for case in fixture["cases"]
        if case["expected_mantis"] == "export"
    ]


def test_synthetic_baseline_freezes_current_mantis_export(tmp_path: Path) -> None:
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    input_path = FIXTURE_DIR / "extraction_filled.csv"
    expected_path = FIXTURE_DIR / "expected" / "mantis_ready.csv"
    first_output = tmp_path / "mantis_first.csv"
    second_output = tmp_path / "mantis_second.csv"

    first_result = mantis.run(input_path, first_output)
    second_result = mantis.run(input_path, second_output)

    expected_counts = {
        key: manifest["expected_mantis"][key]
        for key in [
            "input_rows",
            "mantis_rows",
            "skipped_not_mantis_relevant",
        ]
    }
    assert first_result.step_name == "export_mantis"
    assert first_result.row_counts == expected_counts
    assert second_result.row_counts == expected_counts
    assert first_output.read_bytes() == second_output.read_bytes()

    actual_fields, actual_rows = read_csv(first_output)
    expected_fields, expected_rows = read_csv(expected_path)
    assert actual_fields == manifest["expected_mantis"]["columns"]
    assert actual_fields == expected_fields
    assert actual_rows == expected_rows

    assert [row["paper_id"] for row in actual_rows] == (
        manifest["expected_mantis"]["exported_ids"]
    )
    assert actual_rows[0]["semantic"] == (
        "Higher speech pause variability was associated with MCI in the "
        "synthetic cohort."
    )
    assert actual_rows[0]["evidence_modality_family"] == (
        "speech_language; sensor_behavior"
    )
    assert actual_rows[4]["semantic"] == actual_rows[4]["title"]
    assert actual_rows[4]["year"] == ""
    assert actual_rows[4]["doi"] == ""

    dropped_fields = {
        "abstract",
        "authors",
        "venue",
        "url",
        "source",
        "scope_decision",
        "main_knowledge_claim",
    }
    assert dropped_fields.isdisjoint(actual_fields)
