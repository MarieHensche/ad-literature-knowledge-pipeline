from __future__ import annotations

import csv
import json
import subprocess
import sys
from pathlib import Path

from ad_lit_pipeline.io.jsonl_io import read_jsonl_objects
from ad_lit_pipeline.steps.collection.fetch_review_overviews import (
    run as run_fetch_review_overviews,
)


ROOT = Path(__file__).resolve().parents[1]


def run_script(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, *args],
        cwd=ROOT,
        check=True,
        text=True,
        capture_output=True,
    )


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict[str, str]], fieldnames: list[str]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def write_json(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


class FakeReviewProvider:
    name = "openalex"

    def __init__(self) -> None:
        self.plan: dict[str, object] | None = None
        self.max_results: int | None = None

    def validate_plan(self, plan: dict[str, object]) -> None:
        self.plan = plan

    def fetch_candidates(
        self,
        plan: dict[str, object],
        max_results: int,
        per_page: int,
        mailto: str | None,
        sleep_seconds: float,
    ) -> list[dict[str, object]]:
        self.plan = plan
        self.max_results = max_results
        return [
            {
                "provider": "openalex",
                "provider_id": "W1",
                "title": "A Review of Early Detection",
                "abstract": "Review evidence about biomarkers and models.",
                "query": "early detection review overview",
                "rank": 1,
            }
        ]


def test_normalize_metadata_example_cli(tmp_path: Path) -> None:
    output = tmp_path / "papers_normalized.csv"

    run_script(
        "scripts/normalize_metadata.py",
        "--input",
        "data/raw/example_papers.csv",
        "--output",
        str(output),
    )

    rows = read_csv(output)
    assert len(rows) == 3
    assert rows[0]["paper_id"] == "example_001"
    assert rows[0]["doi"] == "10.1145/3644116.3644192"
    assert rows[0]["abstract_available"] == "yes"
    assert rows[0]["full_text_available"] == "no"
    assert rows[0]["metadata_notes"] == "missing_full_text_path"


def test_fetch_review_overviews_builds_review_only_openalex_plan(tmp_path: Path) -> None:
    output_path = tmp_path / "review_overviews.jsonl"
    provider = FakeReviewProvider()

    result = run_fetch_review_overviews(
        ROOT / "configs/topics/early_detection_ad.yaml",
        output_path,
        max_results=5,
        provider=provider,
    )

    rows = read_jsonl_objects(output_path)
    assert rows[0]["provider_id"] == "W1"
    assert result.row_counts["review_overviews"] == 1
    assert provider.max_results == 5
    assert provider.plan is not None
    assert provider.plan["filters"] == {
        "publication_types": ["review"],
        "open_access_only": True,
        "has_abstract": True,
        "has_full_text": True,
    }
    assert provider.plan["search_queries"][0]["query"].endswith("review overview")


def test_screen_scope_preserves_metadata_and_appends_contract_fields(
    tmp_path: Path,
) -> None:
    normalized = tmp_path / "papers_normalized.csv"
    screened = tmp_path / "scope_screened.csv"

    run_script(
        "scripts/normalize_metadata.py",
        "--input",
        "data/raw/example_papers.csv",
        "--output",
        str(normalized),
    )
    run_script(
        "scripts/screen_scope.py",
        "--input",
        str(normalized),
        "--output",
        str(screened),
        "--topic-contract",
        "configs/topics/early_detection_ad.yaml",
    )

    with screened.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        assert reader.fieldnames == [
            "paper_id",
            "title",
            "year",
            "doi",
            "abstract",
            "authors",
            "venue",
            "url",
            "source",
            "full_text_path",
            "notes",
            "abstract_available",
            "full_text_available",
            "metadata_notes",
            "scope_decision",
            "scope_reason",
            "scope_matched_include_terms",
            "scope_matched_exclude_terms",
        ]
        rows = list(reader)

    assert [row["scope_decision"] for row in rows] == [
        "include",
        "include",
        "exclude_or_route_elsewhere",
    ]
    assert rows[0]["authors"] == "Li et al."
    assert rows[0]["venue"] == "ACM"
    assert "Matched exclude term(s): drug repurposing, treatment" in rows[2][
        "scope_reason"
    ]
    assert rows[2]["scope_matched_include_terms"] == "screening"
    assert rows[2]["scope_matched_exclude_terms"] == "drug repurposing; treatment"


def test_screen_scope_exclude_wins_and_needs_decision(tmp_path: Path) -> None:
    input_path = tmp_path / "normalized.csv"
    output_path = tmp_path / "screened.csv"
    write_csv(
        input_path,
        [
            {
                "paper_id": "p1",
                "title": "Treatment classification",
                "year": "2024",
                "doi": "",
                "abstract": "A treatment paper with classification language.",
                "authors": "A. Author",
            },
            {
                "paper_id": "p2",
                "title": "Unrelated clinical note",
                "year": "2024",
                "doi": "",
                "abstract": "No matching language.",
                "authors": "B. Author",
            },
        ],
        ["paper_id", "title", "year", "doi", "abstract", "authors"],
    )

    run_script(
        "scripts/screen_scope.py",
        "--input",
        str(input_path),
        "--output",
        str(output_path),
        "--topic-contract",
        "configs/topics/early_detection_ad.yaml",
    )

    rows = read_csv(output_path)
    assert rows[0]["scope_decision"] == "exclude_or_route_elsewhere"
    assert rows[0]["scope_matched_include_terms"] == "classification"
    assert rows[0]["scope_matched_exclude_terms"] == "treatment"
    assert rows[0]["authors"] == "A. Author"
    assert rows[1]["scope_decision"] == "needs_decision"


def test_deduplicate_candidates_prefers_doi_and_abstract(tmp_path: Path) -> None:
    input_path = tmp_path / "candidates.jsonl"
    output_path = tmp_path / "deduped.jsonl"
    rows = [
        {
            "provider": "openalex",
            "provider_id": "W1",
            "doi": "https://doi.org/10.123/example",
            "title": "Example",
            "year": 2024,
            "abstract": "",
            "rank": 1,
        },
        {
            "provider": "openalex",
            "provider_id": "W2",
            "doi": "10.123/example",
            "title": "Example",
            "year": 2024,
            "abstract": "Useful abstract.",
            "rank": 2,
        },
    ]
    input_path.write_text(
        "".join(json.dumps(row) + "\n" for row in rows),
        encoding="utf-8",
    )

    run_script(
        "scripts/deduplicate_candidates.py",
        "--input",
        str(input_path),
        "--output",
        str(output_path),
    )

    output_rows = [
        json.loads(line)
        for line in output_path.read_text(encoding="utf-8").splitlines()
    ]
    assert len(output_rows) == 1
    assert output_rows[0]["provider_id"] == "W2"
    assert output_rows[0]["dedupe_key"] == "doi:10.123/example"
    assert output_rows[0]["duplicate_count"] == 2


def test_export_included_candidates_to_canonical_csv(tmp_path: Path) -> None:
    candidates_path = tmp_path / "deduped.jsonl"
    screening_path = tmp_path / "screening.csv"
    output_path = tmp_path / "papers.csv"

    candidate = {
        "provider": "openalex",
        "provider_id": "W1",
        "doi": "10.123/example",
        "title": "Detection Study",
        "year": 2024,
        "abstract": "Early detection abstract.",
        "authors": "A. Author",
        "venue": "Journal",
        "url": "https://example.test",
        "rank": 1,
        "retrieval_date": "2026-05-25",
        "dedupe_key": "doi:10.123/example",
        "duplicate_count": 1,
    }
    candidates_path.write_text(json.dumps(candidate) + "\n", encoding="utf-8")
    write_csv(
        screening_path,
        [
            {
                "paper_id": "paper_1",
                "title": "Detection Study",
                "year": "2024",
                "doi": "10.123/example",
                "provider": "openalex",
                "provider_id": "W1",
                "source_rank": "1",
                "screening_decision": "include",
                "screening_confidence": "high",
                "screening_reason": "Directly relevant.",
            }
        ],
        [
            "paper_id",
            "title",
            "year",
            "doi",
            "provider",
            "provider_id",
            "source_rank",
            "screening_decision",
            "screening_confidence",
            "screening_reason",
        ],
    )

    run_script(
        "scripts/export_screened_candidates_to_csv.py",
        "--candidates",
        str(candidates_path),
        "--screening",
        str(screening_path),
        "--output",
        str(output_path),
    )

    rows = read_csv(output_path)
    assert rows == [
        {
            "paper_id": "paper_1",
            "title": "Detection Study",
            "year": "2024",
            "doi": "10.123/example",
            "abstract": "Early detection abstract.",
            "authors": "A. Author",
            "venue": "Journal",
            "url": "https://example.test",
            "source": "collected:openalex",
            "full_text_path": "",
            "notes": (
                "provider=openalex; provider_id=W1; source_rank=1; "
                "retrieval_date=2026-05-25; screening_confidence=high; "
                "screening_reason=Directly relevant.; dedupe_key=doi:10.123/example; "
                "duplicate_count=1"
            ),
        }
    ]


def test_audit_extraction_writes_expected_issues(tmp_path: Path) -> None:
    extraction_path = tmp_path / "extraction.csv"
    config_path = tmp_path / "config.json"
    rules_path = tmp_path / "rules.json"
    output_path = tmp_path / "audit.csv"

    write_csv(
        extraction_path,
        [{"paper_id": "p1", "target": "ad; invalid", "review_status": ""}],
        ["paper_id", "target", "review_status"],
    )
    write_json(
        config_path,
        {
            "categories": [
                {
                    "category_id": "target",
                    "allowed_values": [{"value": "ad"}, {"value": "mci"}],
                },
                {
                    "category_id": "review_status",
                    "allowed_values": [{"value": "ai_tagged"}],
                },
            ]
        },
    )
    write_json(
        rules_path,
        {
            "rules": [
                {"category_id": "target", "selection": "single", "required": True},
                {
                    "category_id": "review_status",
                    "selection": "single",
                    "required": True,
                },
            ]
        },
    )

    run_script(
        "scripts/audit_extraction.py",
        "--input",
        str(extraction_path),
        "--config",
        str(config_path),
        "--rules",
        str(rules_path),
        "--output",
        str(output_path),
    )

    rows = read_csv(output_path)
    assert rows == [
        {
            "paper_id": "p1",
            "field": "target",
            "value": "invalid",
            "issue": "invalid_value",
        },
        {
            "paper_id": "p1",
            "field": "target",
            "value": "ad; invalid",
            "issue": "single_selection_has_multiple_values",
        },
        {
            "paper_id": "p1",
            "field": "review_status",
            "value": "",
            "issue": "required_missing",
        },
    ]


def test_export_mantis_ready_uses_claim_and_first_category(tmp_path: Path) -> None:
    extraction_path = tmp_path / "extraction.csv"
    output_path = tmp_path / "mantis.csv"
    write_csv(
        extraction_path,
        [
            {
                "paper_id": "p1",
                "title": "Detection Study",
                "year": "2024",
                "doi": "10.123/example",
                "main_knowledge_claim": "The paper detects early AD.",
                "main_topic_category": "mci_detection; early_ad_detection",
                "research_target": "mci",
                "review_status": "ai_tagged",
            }
        ],
        [
            "paper_id",
            "title",
            "year",
            "doi",
            "main_knowledge_claim",
            "main_topic_category",
            "research_target",
            "review_status",
        ],
    )

    run_script(
        "scripts/export_mantis_ready.py",
        "--input",
        str(extraction_path),
        "--output",
        str(output_path),
    )

    rows = read_csv(output_path)
    assert rows[0]["title"] == "Detection Study"
    assert rows[0]["categoric"] == "mci_detection"
    assert rows[0]["semantic"] == "The paper detects early AD."
    assert rows[0]["review_status"] == "ai_tagged"
