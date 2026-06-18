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
                "scope": {
                    "include_criteria": ["Include relevant studies."],
                    "exclude_criteria": ["Exclude unrelated studies."],
                    "boundary_rules": ["Include borderline evidence carefully."],
                },
                "collection": {
                    "preferred_provider": "openalex",
                    "allowed_providers": ["openalex"],
                    "search_queries": [
                        {
                            "query": "early detection Alzheimer",
                            "reason": "topic query",
                        }
                    ],
                },
                "topic_structure": {
                    "main_topics": [
                        {
                            "value": "early_detection",
                            "label": "Early detection",
                        },
                        {
                            "value": "biomarkers",
                            "label": "Biomarkers",
                        },
                    ],
                    "term_hints": [
                        {
                            "topic_id": "early_detection",
                            "is_anchor": True,
                            "terms": [
                                {
                                    "value": "screening",
                                    "label": "screening",
                                }
                            ],
                        }
                    ],
                },
                "review": {
                    "review_type": "narrative",
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
                                },
                                {
                                    "value": "machine_learning",
                                    "label": "machine learning",
                                    "paper_count": 1,
                                },
                                {
                                    "value": "deep_learning",
                                    "label": "deep learning",
                                    "paper_count": 1,
                                }
                            ],
                            "value_mappings": [
                                {
                                    "from": "mri_method",
                                    "to": "mri_classification",
                                }
                            ],
                            "dropped_values": ["too_broad"],
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
                "methodology": "machine_learning; deep_learning",
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
            {
                "paper_id": "p3",
                "title": "Paper three",
                "year": "2022",
                "doi": "10.123/three",
                "authors": "Roe",
                "venue": "Journal",
                "source": "openalex",
                "main_topic": "early_detection",
                "methodology": "mri_method; too_broad",
                "key_finding": "Mapped MRI evidence stayed usable.",
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
            },
            {
                "paper_id": "p3",
                "field": "methodology",
                "value": "mri_method",
                "issue": "review_value_mapped",
                "severity": "warning",
                "detail": "mapped_to=mri_classification",
            }
        ],
        ["paper_id", "field", "value", "issue", "severity", "detail"],
    )

    result = run(labels_path, values_path, quality_path, output_path)
    payload = json.loads(output_path.read_text(encoding="utf-8"))

    assert result.row_counts["review_usable_papers"] == 2
    assert result.row_counts["review_sections"] == 7
    assert payload["overview"]["excluded_paper_count"] == 1
    assert payload["overview"]["review_type"] == "narrative"
    assert payload["overview"]["section_plan"] == (
        "stable_skeleton_with_main_topic_sections"
    )
    assert payload["overview"]["label_coverage"][0]["paper_count"] == 2
    assert payload["overview"]["review_methodology"]["collection_context"][
        "preferred_provider"
    ] == "openalex"
    assert payload["overview"]["review_methodology"]["scope_context"][
        "include_criteria"
    ] == ["Include relevant studies."]
    assert payload["overview"]["review_methodology"]["comparison_guidance"].startswith(
        "Do not directly rank"
    )
    assert {
        "parent_value": "machine_learning",
        "child_value": "deep_learning",
        "use": (
            "Treat the child as a more specific instance of the parent when "
            "synthesizing methods."
        ),
    } in payload["overview"]["method_hierarchy_hints"]
    assert payload["quality"]["excluded_paper_ids"] == ["p2"]
    assert payload["papers"][0]["citation_key"] == "Smith and Jones (2024)"
    assert payload["papers"][0]["harvard_inline"] == "(Smith and Jones, 2024)"

    section_ids = [section["section_id"] for section in payload["sections"]]
    assert section_ids == [
        "review_methodology",
        "main_topic_early_detection",
        "main_topic_biomarkers",
        "comparative_methods_and_evidence",
        "datasets_and_study_designs",
        "limitations_gaps_and_future_work",
        "conclusion",
    ]
    topic_section = payload["sections"][1]
    assert topic_section["section_type"] == "main_topic_lens"
    assert topic_section["label"] == "Early detection In The Included Literature"
    assert topic_section["topic_focus"]["value"] == "early_detection"
    assert topic_section["topic_focus"]["term_hints"] == [
        {"value": "screening", "label": "screening"}
    ]

    section = payload["sections"][3]
    assert payload["overview"]["section_label"] == "methodology"
    assert section["section_id"] == "comparative_methods_and_evidence"
    assert section["section_type"] == "comparative_methods"
    assert section["source_label"] == "review_plan"
    assert section["paper_ids"] == ["p1", "p3"]
    assert section["controlled_value_counts"]["methodology"] == [
        {
            "value": "machine_learning",
            "label": "machine learning",
            "paper_count": 1,
        },
        {
            "value": "deep_learning",
            "label": "deep learning",
            "paper_count": 1,
        },
        {
            "value": "mri_classification",
            "label": "mri classification",
            "paper_count": 1,
        }
    ]
    assert section["text_evidence"]["key_finding"][0]["paper_id"] == "p1"
    assert section["quotes"][0]["quote"] == "classification improved"
