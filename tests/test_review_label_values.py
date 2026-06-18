from __future__ import annotations

import csv
import json
from copy import deepcopy
from pathlib import Path

from ad_lit_pipeline.io.json_io import write_json
from ad_lit_pipeline.steps.review.config import normalize_review_config
from ad_lit_pipeline.steps.review.label_values import run
from ad_lit_pipeline.topics.contract import load_topic_contract


ROOT = Path(__file__).resolve().parents[1]


def write_csv(path: Path, rows: list[dict[str, str]], fieldnames: list[str]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def review_config_path(tmp_path: Path) -> Path:
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
                "evidence_sections": ["methods"],
            },
            "key_finding": {
                "description": "Key finding.",
                "value_mode": "free_text",
                "evidence_sections": ["results"],
            },
        },
    }
    path = tmp_path / "review_config.json"
    write_json(path, normalize_review_config(contract))
    return path


def test_normalize_review_label_values_counts_fixed_and_auto_values(
    tmp_path: Path,
) -> None:
    labels_path = tmp_path / "review_labels.csv"
    config_path = review_config_path(tmp_path)
    output_path = tmp_path / "review_label_values.json"
    write_csv(
        labels_path,
        [
            {
                "paper_id": "p1",
                "main_topic": "early_detection",
                "methodology": "MRI Classification; cross validation",
                "key_finding": "Finding one.",
            },
            {
                "paper_id": "p2",
                "main_topic": "early_detection",
                "methodology": "mri_classification; Cross-Validation",
                "key_finding": "",
            },
            {
                "paper_id": "p3",
                "main_topic": "not_a_topic",
                "methodology": "graph analytical methods",
                "key_finding": "Finding three.",
            },
            {
                "paper_id": "p4",
                "main_topic": "early_detection",
                "methodology": "graph theoretical analysis",
                "key_finding": "Finding four.",
            },
        ],
        ["paper_id", "main_topic", "methodology", "key_finding"],
    )

    result = run(labels_path, config_path, output_path)
    payload = json.loads(output_path.read_text(encoding="utf-8"))
    labels = {
        label["label_id"]: label
        for label in payload["review"]["label_values"]
    }

    assert "main_topics" in payload["topic_structure"]
    assert payload["review"]["review_type"] == "narrative"
    assert payload["review"]["output"]["citation_style"] == "harvard"
    assert "include_criteria" in payload["scope"]
    assert "search_queries" in payload["collection"]
    assert result.row_counts["review_label_rows"] == 4
    assert labels["main_topic"]["invalid_values"] == [
        {"value": "not_a_topic", "count": 1}
    ]
    main_topic_values = {
        value["value"]: value["paper_count"]
        for value in labels["main_topic"]["values"]
    }
    assert main_topic_values["early_detection"] == 3

    methodology_values = {
        value["value"]: value
        for value in labels["methodology"]["values"]
    }
    assert methodology_values["mri_classification"]["paper_count"] == 2
    assert methodology_values["cross_validation"]["paper_count"] == 2
    assert methodology_values["graph_analysis"]["paper_count"] == 2
    assert methodology_values["graph_analysis"]["canonicalized_from"] == [
        {"value": "graph_analytical_methods", "count": 1},
        {"value": "graph_theoretical_analysis", "count": 1},
    ]
    assert methodology_values["mri_classification"]["surface_forms"] == [
        {"form": "MRI Classification", "count": 1},
        {"form": "mri_classification", "count": 1},
    ]
    assert labels["key_finding"]["non_empty_count"] == 3
