from __future__ import annotations

import csv
import json
from pathlib import Path

from ad_lit_pipeline.steps.review.coverage_report import run


def write_csv(path: Path, rows: list[dict[str, str]], fieldnames: list[str]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def write_label_values(path: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "review": {
                    "label_values": [
                        {
                            "label_id": "methodology",
                            "value_mode": "controlled_auto",
                            "values": [{"value": "mri_classification"}],
                            "value_mappings": [
                                {
                                    "from": "mri_method",
                                    "to": "mri_classification",
                                }
                            ],
                            "dropped_values": ["too_broad"],
                        },
                        {
                            "label_id": "key_finding",
                            "value_mode": "free_text",
                            "values": [],
                        },
                        {
                            "label_id": "paper_limitation",
                            "value_mode": "free_text",
                            "values": [],
                        },
                    ]
                }
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def test_review_coverage_report_counts_usable_values_and_citation_target(
    tmp_path: Path,
) -> None:
    eligible_path = tmp_path / "eligible.csv"
    labels_path = tmp_path / "labels.csv"
    values_path = tmp_path / "values.json"
    quality_path = tmp_path / "quality.csv"
    filter_report_path = tmp_path / "filter_report.json"
    output_path = tmp_path / "coverage.json"
    fieldnames = [
        "paper_id",
        "title",
        "year",
        "doi",
        "authors",
        "methodology",
        "key_finding",
        "paper_limitation",
    ]
    rows = [
        {
            "paper_id": "p1",
            "title": "Paper one",
            "year": "2024",
            "doi": "10.123/one",
            "authors": "Smith",
            "methodology": "mri_classification",
            "key_finding": "Finding one.",
            "paper_limitation": "",
        },
        {
            "paper_id": "p2",
            "title": "Paper two",
            "year": "2023",
            "doi": "10.123/two",
            "authors": "Jones",
            "methodology": "mri_method; too_broad",
            "key_finding": "unclear",
            "paper_limitation": "Small sample.",
        },
        {
            "paper_id": "p3",
            "title": "Paper three",
            "year": "2022",
            "doi": "10.123/three",
            "authors": "Roe",
            "methodology": "",
            "key_finding": "Finding three.",
            "paper_limitation": "",
        },
    ]
    write_csv(eligible_path, rows, fieldnames)
    write_csv(labels_path, rows, fieldnames)
    write_label_values(values_path)
    write_csv(
        quality_path,
        [
            {
                "paper_id": "p2",
                "field": "methodology",
                "value": "mri_method",
                "issue": "review_value_mapped",
                "severity": "warning",
                "detail": "",
            }
        ],
        ["paper_id", "field", "value", "issue", "severity", "detail"],
    )
    filter_report_path.write_text(
        json.dumps(
            {
                "counts": {
                    "included_papers": 4,
                    "review_eligible_papers": 3,
                    "excluded_likely_review_papers": 1,
                },
                "retention_rule": (
                    "Papers identified as likely review articles by available "
                    "metadata are excluded."
                ),
            }
        ),
        encoding="utf-8",
    )

    result = run(
        eligible_path,
        labels_path,
        values_path,
        quality_path,
        output_path,
        filter_report_path,
    )
    payload = json.loads(output_path.read_text(encoding="utf-8"))
    coverage = {
        item["label_id"]: item["papers_with_usable_value"]
        for item in payload["label_coverage"]
    }

    assert result.row_counts["review_usable_papers"] == 3
    assert result.row_counts["citation_eligible_papers"] == 3
    assert payload["citation_target"]["target_cited_papers"] == 3
    assert payload["review_filter"]["counts"]["excluded_likely_review_papers"] == 1
    assert coverage["methodology"] == 2
    assert coverage["key_finding"] == 2
    assert coverage["paper_limitation"] == 1
