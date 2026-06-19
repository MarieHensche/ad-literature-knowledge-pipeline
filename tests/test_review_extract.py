from __future__ import annotations

import csv
import json
from copy import deepcopy
from pathlib import Path

from ad_lit_pipeline.io.json_io import write_json
from ad_lit_pipeline.llm.client import StaticJSONClient
from ad_lit_pipeline.llm.schemas import review_labels_schema
from ad_lit_pipeline.steps.review.config import normalize_review_config
from ad_lit_pipeline.steps.review.extract_labels import run
from ad_lit_pipeline.topics.contract import load_topic_contract


ROOT = Path(__file__).resolve().parents[1]


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict[str, str]], fieldnames: list[str]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def review_config(tmp_path: Path) -> dict[str, object]:
    contract = deepcopy(load_topic_contract(ROOT / "configs/topics/early_detection_ad.yaml"))
    contract["review"] = {
        "labels": {
            "main_topic": {
                "description": "Best topic-structure main topic.",
                "value_mode": "controlled_fixed",
                "selection": "single",
                "values_from": "topic_structure.main_topics",
                "evidence_sections": ["title", "abstract"],
            },
            "methodology": {
                "description": "Methods used in the paper.",
                "value_mode": "controlled_auto",
                "selection": "multi",
                "values": "auto",
                "max_values_per_paper": 2,
                "max_words_per_value": 3,
                "evidence_sections": ["methods"],
            },
            "study_design": {
                "description": "Study design.",
                "value_mode": "controlled_fixed",
                "selection": "single",
                "values": ["validation_study", "unclear"],
                "max_values_per_paper": 1,
                "evidence_sections": ["title", "abstract", "methods"],
            },
            "key_finding": {
                "description": "Key finding.",
                "value_mode": "free_text",
                "max_items_per_paper": 1,
                "max_words_per_item": 6,
                "missing_value": "unclear",
                "evidence_sections": ["results", "discussion"],
            },
            "dataset_or_sample": {
                "description": "Dataset or sample.",
                "value_mode": "free_text",
                "max_items_per_paper": 2,
                "max_words_per_item": 4,
                "missing_value": "unclear",
                "evidence_sections": ["methods"],
            },
            "direct_quote": {
                "description": "Useful direct quotation.",
                "value_mode": "evidence_quote",
                "evidence_sections": ["results"],
            },
        },
    }
    config = normalize_review_config(contract)
    path = tmp_path / "review_config.json"
    write_json(path, config)
    return {"payload": config, "path": path}


def paper_csv(tmp_path: Path) -> Path:
    text_path = tmp_path / "paper.txt"
    text_path.write_text(
        "\n\n".join(
            [
                "Introduction\nThis paper studies early detection.",
                (
                    "Methods\nThe authors used a classification pipeline with "
                    "MRI features and cross-validation."
                ),
                (
                    "Results\nThe model improved early detection accuracy and "
                    "identified baseline MRI markers."
                ),
                "Discussion\nThe authors note single-cohort validation limits.",
            ]
        ),
        encoding="utf-8",
    )
    csv_path = tmp_path / "papers.csv"
    write_csv(
        csv_path,
        [
            {
                "paper_id": "p1",
                "title": "MRI classification for early detection",
                "year": "2024",
                "doi": "10.123/example",
                "authors": "Smith; Jones",
                "venue": "Example Journal",
                "source": "test",
                "abstract": "An MRI early detection study.",
                "scope_decision": "include",
                "full_text_text_path": str(text_path),
            },
            {
                "paper_id": "p2",
                "title": "Systematic review of MRI classification",
                "year": "2023",
                "doi": "10.123/review",
                "authors": "Reviewer",
                "venue": "Example Journal",
                "source": "test",
                "abstract": "A review paper.",
                "scope_decision": "include",
                "full_text_text_path": str(text_path),
            }
        ],
        [
            "paper_id",
            "title",
            "year",
            "doi",
            "authors",
            "venue",
            "source",
            "abstract",
            "scope_decision",
            "full_text_text_path",
        ],
    )
    return csv_path


def test_extract_review_labels_writes_review_csv(tmp_path: Path) -> None:
    config = review_config(tmp_path)
    papers_path = paper_csv(tmp_path)
    output = tmp_path / "review_labels.csv"
    client = StaticJSONClient(
        [
            {
                "paper_id": "p1",
                "labels": {
                    "main_topic": ["early_detection"],
                    "methodology": [
                        "MRI Classification Method With Too Many Words",
                        "cross validation",
                        "extra method",
                    ],
                    "study_design": ["validation_study"],
                    "dataset_or_sample": (
                        "Training cohort with many extra words; "
                        "external validation cohort with many extra words; "
                        "third cohort"
                    ),
                    "key_finding": (
                        "MRI features improved early detection classification "
                        "with extra trailing details."
                    ),
                    "direct_quote": [
                        {
                            "quote": "improved early detection accuracy",
                            "section": "Results",
                            "reason": "Supports the main finding.",
                        }
                    ],
                },
                "evidence_sections_used": ["methods", "results"],
                "extraction_notes": [],
            }
        ]
    )

    result = run(
        papers_path,
        Path(config["path"]),
        output,
        "test-model",
        client=client,
    )

    rows = read_csv(output)
    assert result.row_counts["review_labeled_papers"] == 1
    assert result.row_counts["review_candidate_papers"] == 2
    assert result.row_counts["review_skipped_review_papers"] == 1
    assert rows[0]["paper_id"] == "p1"
    assert rows[0]["main_topic"] == "early_detection"
    assert rows[0]["methodology"] == "mri_classification_method; cross_validation"
    assert rows[0]["study_design"] == "validation_study"
    assert rows[0]["dataset_or_sample"] == (
        "Training cohort with many; external validation cohort with"
    )
    assert rows[0]["key_finding"] == "MRI features improved early detection classification"
    assert json.loads(rows[0]["direct_quote"])[0]["section"] == "Results"
    assert "classification pipeline" in client.requests[0]["prompt"]
    assert "available_section_headings" in client.requests[0]["prompt"]


def test_extract_review_labels_skips_invalid_fixed_value(tmp_path: Path) -> None:
    config = review_config(tmp_path)
    papers_path = paper_csv(tmp_path)
    output = tmp_path / "review_labels.csv"
    client = StaticJSONClient(
        [
            {
                "paper_id": "p1",
                "labels": {
                    "main_topic": ["not_a_topic"],
                    "methodology": [],
                    "study_design": [],
                    "dataset_or_sample": "",
                    "key_finding": "",
                    "direct_quote": [],
                },
                "evidence_sections_used": [],
                "extraction_notes": ["No valid topic."],
            }
        ]
    )

    result = run(
        papers_path,
        Path(config["path"]),
        output,
        "test-model",
        client=client,
    )

    assert read_csv(output) == []
    assert result.row_counts["review_labeled_papers"] == 0
    assert result.row_counts["review_skipped_review_papers"] == 1
    assert "invalid value" in result.warnings[0]


def test_review_labels_schema_constrains_fixed_values(tmp_path: Path) -> None:
    config = review_config(tmp_path)["payload"]

    schema = review_labels_schema(config)
    main_topic_items = schema["properties"]["labels"]["properties"]["main_topic"][
        "items"
    ]
    methodology_schema = schema["properties"]["labels"]["properties"]["methodology"]
    study_design_schema = schema["properties"]["labels"]["properties"]["study_design"]

    assert "early_detection" in main_topic_items["enum"]
    assert methodology_schema["maxItems"] == 2
    assert study_design_schema["maxItems"] == 1
    assert "validation_study" in study_design_schema["items"]["enum"]
