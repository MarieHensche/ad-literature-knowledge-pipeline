from __future__ import annotations

import csv
import json
from pathlib import Path

from ad_lit_pipeline.steps.review.validate_labels import run


def write_csv(path: Path, rows: list[dict[str, str]], fieldnames: list[str]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def label_values_path(tmp_path: Path) -> Path:
    path = tmp_path / "review_label_values.json"
    path.write_text(
        json.dumps(
            {
                "review": {
                    "label_values": [
                        {
                            "label_id": "main_topic",
                            "label": "main topic",
                            "value_mode": "controlled_fixed",
                            "selection": "single",
                            "required": True,
                            "values": [
                                {"value": "early_detection", "paper_count": 1}
                            ],
                            "invalid_values": [
                                {"value": "not_a_topic", "count": 1}
                            ],
                        },
                        {
                            "label_id": "methodology",
                            "label": "methodology",
                            "value_mode": "controlled_auto",
                            "selection": "multi",
                            "required": False,
                            "values": [
                                {"value": "mri_classification", "paper_count": 1}
                            ],
                            "invalid_values": [],
                        },
                        {
                            "label_id": "key_finding",
                            "label": "key finding",
                            "value_mode": "free_text",
                            "selection": "",
                            "required": True,
                            "values": [],
                            "invalid_values": [],
                        },
                        {
                            "label_id": "direct_quote",
                            "label": "direct quote",
                            "value_mode": "evidence_quote",
                            "selection": "",
                            "required": False,
                            "values": [],
                            "invalid_values": [],
                        },
                    ]
                }
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return path


def test_validate_review_labels_reports_quality_issues(tmp_path: Path) -> None:
    labels_path = tmp_path / "review_labels.csv"
    values_path = label_values_path(tmp_path)
    output_path = tmp_path / "review_quality_report.csv"
    write_csv(
        labels_path,
        [
            {
                "paper_id": "p1",
                "title": "Paper one",
                "year": "2024",
                "doi": "10.123/one",
                "authors": "",
                "venue": "",
                "main_topic": "early_detection",
                "methodology": "mri_classification",
                "key_finding": "Finding one.",
                "direct_quote": '[{"quote": "useful quote", "section": ""}]',
            },
            {
                "paper_id": "p1",
                "title": "",
                "year": "",
                "doi": "",
                "authors": "",
                "venue": "",
                "main_topic": "not_a_topic",
                "methodology": "unknown_method",
                "key_finding": "",
                "direct_quote": "not json",
            },
        ],
        [
            "paper_id",
            "title",
            "year",
            "doi",
            "authors",
            "venue",
            "main_topic",
            "methodology",
            "key_finding",
            "direct_quote",
        ],
    )

    result = run(labels_path, values_path, output_path)
    issues = read_csv(output_path)
    issue_types = {row["issue"] for row in issues}

    assert result.row_counts["review_quality_errors"] > 0
    assert "required_metadata_missing" in issue_types
    assert "recommended_metadata_missing" in issue_types
    assert "invalid_review_value" in issue_types
    assert "required_review_label_missing" in issue_types
    assert "malformed_quote_json" in issue_types
    assert "quote_missing_section" in issue_types
    assert "duplicate_paper_id" in issue_types
    assert "observed_invalid_value_summary" in issue_types
    methodology_issues = [
        row for row in issues if row["field"] == "methodology"
    ]
    assert {row["severity"] for row in methodology_issues} == {"warning"}


def test_validate_review_labels_allows_valid_rows(tmp_path: Path) -> None:
    labels_path = tmp_path / "review_labels.csv"
    values_path = label_values_path(tmp_path)
    output_path = tmp_path / "review_quality_report.csv"
    write_csv(
        labels_path,
        [
            {
                "paper_id": "p1",
                "title": "Paper one",
                "year": "2024",
                "doi": "10.123/one",
                "authors": "A. Author",
                "venue": "Journal",
                "main_topic": "early_detection",
                "methodology": "mri_classification",
                "key_finding": "Finding one.",
                "direct_quote": (
                    '[{"quote": "useful quote", "section": "Results", '
                    '"reason": "supports finding"}]'
                ),
            }
        ],
        [
            "paper_id",
            "title",
            "year",
            "doi",
            "authors",
            "venue",
            "main_topic",
            "methodology",
            "key_finding",
            "direct_quote",
        ],
    )

    result = run(labels_path, values_path, output_path)

    assert result.row_counts["review_quality_issues"] == 1
    assert read_csv(output_path)[0]["issue"] == "observed_invalid_value_summary"
