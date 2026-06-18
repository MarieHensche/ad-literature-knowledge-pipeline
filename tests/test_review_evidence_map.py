from __future__ import annotations

import csv
import json
from pathlib import Path

from ad_lit_pipeline.steps.review.evidence_map import run


def write_csv(path: Path, rows: list[dict[str, str]], fieldnames: list[str]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def write_label_values(path: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "research_topic": {"title": "Early AD detection"},
                "review": {
                    "label_values": [
                        {
                            "label_id": "main_topic",
                            "label": "main topic",
                            "value_mode": "controlled_fixed",
                            "selection": "single",
                            "values": [
                                {
                                    "value": "early_detection",
                                    "label": "Early detection",
                                    "paper_count": 2,
                                },
                                {
                                    "value": "biomarkers",
                                    "label": "Biomarkers",
                                    "paper_count": 1,
                                },
                            ],
                            "invalid_values": [],
                        },
                        {
                            "label_id": "methodology",
                            "label": "methodology",
                            "value_mode": "controlled_auto",
                            "selection": "multi",
                            "values": [
                                {
                                    "value": "mri_classification",
                                    "label": "mri classification",
                                    "paper_count": 1,
                                }
                            ],
                            "invalid_values": [],
                        },
                        {
                            "label_id": "key_finding",
                            "label": "key finding",
                            "value_mode": "free_text",
                            "selection": "",
                            "values": [],
                            "invalid_values": [],
                        },
                        {
                            "label_id": "paper_limitation",
                            "label": "paper limitation",
                            "value_mode": "free_text",
                            "selection": "",
                            "values": [],
                            "invalid_values": [],
                        },
                        {
                            "label_id": "direct_quote",
                            "label": "direct quote",
                            "value_mode": "evidence_quote",
                            "selection": "",
                            "values": [],
                            "invalid_values": [],
                        },
                    ]
                },
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def test_build_review_evidence_map_groups_usable_evidence(
    tmp_path: Path,
) -> None:
    labels_path = tmp_path / "review_labels.csv"
    values_path = tmp_path / "review_label_values.json"
    quality_path = tmp_path / "review_quality_report.csv"
    output_path = tmp_path / "review_evidence_map.json"
    write_label_values(values_path)
    fieldnames = [
        "paper_id",
        "title",
        "year",
        "doi",
        "authors",
        "venue",
        "source",
        "main_topic",
        "methodology",
        "key_finding",
        "paper_limitation",
        "direct_quote",
    ]
    write_csv(
        labels_path,
        [
            {
                "paper_id": "p1",
                "title": "Paper one",
                "year": "2024",
                "doi": "10.123/one",
                "authors": "Smith; Jones",
                "venue": "Journal",
                "source": "openalex",
                "main_topic": "early_detection",
                "methodology": "mri_classification",
                "key_finding": "MRI models improved early detection.",
                "paper_limitation": "Small cohort.",
                "direct_quote": (
                    '[{"quote": "classification improved", '
                    '"section": "Results", "reason": "supports finding"}]'
                ),
            },
            {
                "paper_id": "p2",
                "title": "Paper two",
                "year": "2023",
                "doi": "10.123/two",
                "authors": "Doe",
                "venue": "Conference",
                "source": "openalex",
                "main_topic": "biomarkers",
                "methodology": "",
                "key_finding": "Biomarkers shifted earlier.",
                "paper_limitation": "",
                "direct_quote": "",
            },
        ],
        fieldnames,
    )
    write_csv(
        quality_path,
        [
            {
                "paper_id": "p2",
                "field": "main_topic",
                "value": "not_a_topic",
                "issue": "invalid_review_value",
                "severity": "error",
                "detail": "",
            }
        ],
        ["paper_id", "field", "value", "issue", "severity", "detail"],
    )

    result = run(labels_path, values_path, quality_path, output_path)
    payload = json.loads(output_path.read_text(encoding="utf-8"))

    assert result.row_counts["review_usable_papers"] == 1
    assert result.row_counts["review_sections"] == 1
    assert payload["overview"]["excluded_paper_count"] == 1
    assert payload["quality"]["excluded_paper_ids"] == ["p2"]
    assert payload["papers"][0]["citation_key"] == "Smith (2024)"

    section = payload["sections"][0]
    assert payload["overview"]["section_label"] == "methodology"
    assert section["section_id"] == "mri_classification"
    assert section["label"] == "mri classification"
    assert section["source_label"] == "methodology"
    assert section["paper_ids"] == ["p1"]
    assert section["controlled_value_counts"]["methodology"] == [
        {
            "value": "mri_classification",
            "label": "mri classification",
            "paper_count": 1,
        }
    ]
    assert section["text_evidence"]["key_finding"][0]["paper_id"] == "p1"
    assert section["quotes"][0]["quote"] == "classification improved"
