from __future__ import annotations

import json
from pathlib import Path

import pytest

from ad_lit_pipeline.core.errors import PipelinePause
from ad_lit_pipeline.io.yaml_io import read_yaml_object, write_yaml_object
from ad_lit_pipeline.steps.review.label_value_review import run


def label_values_path(tmp_path: Path) -> Path:
    path = tmp_path / "review_label_values.json"
    path.write_text(
        json.dumps(
            {
                "research_topic": {"title": "Topic", "description": "Description"},
                "review": {
                    "label_count": 2,
                    "paper_count": 2,
                    "label_values": [
                        {
                            "label_id": "methodology",
                            "label": "methodology",
                            "value_mode": "controlled_auto",
                            "selection": "multi",
                            "values": [
                                {
                                    "value": "mri_classification",
                                    "label": "mri_classification",
                                    "paper_count": 2,
                                    "surface_forms": [],
                                },
                                {
                                    "value": "cross_validation",
                                    "label": "cross_validation",
                                    "paper_count": 1,
                                    "surface_forms": [],
                                },
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
                    ],
                },
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return path


def test_review_label_value_review_writes_file_and_pauses(tmp_path: Path) -> None:
    values_path = label_values_path(tmp_path)
    review_path = tmp_path / "review_label_values_review.yaml"

    with pytest.raises(PipelinePause):
        run(values_path, review_path)

    payload = read_yaml_object(review_path)
    assert payload["status"] == "needs_review"
    assert payload["labels"]["methodology"]["values"] == [
        "mri_classification",
        "cross_validation",
    ]
    assert payload["labels"]["methodology"]["value_details"][0]["value"] == (
        "mri_classification"
    )
    assert payload["labels"]["methodology"]["value_details"][0]["paper_count"] == 2


def test_review_label_value_review_merges_approved_values(tmp_path: Path) -> None:
    values_path = label_values_path(tmp_path)
    review_path = tmp_path / "review_label_values_review.yaml"
    with pytest.raises(PipelinePause):
        run(values_path, review_path)

    payload = read_yaml_object(review_path)
    payload["status"] = "approved"
    payload["labels"]["methodology"]["values"] = [
        "mri_classification",
        "new_user_value",
    ]
    write_yaml_object(review_path, payload)

    result = run(values_path, review_path)
    merged = json.loads(values_path.read_text(encoding="utf-8"))
    methodology = merged["review"]["label_values"][0]

    assert result.row_counts["review_value_labels_changed"] == 1
    assert [value["value"] for value in methodology["values"]] == [
        "mri_classification",
        "new_user_value",
    ]
    assert methodology["values"][0]["paper_count"] == 2
    assert methodology["values"][1]["paper_count"] == 0


def test_review_label_value_review_records_mappings_and_drops(tmp_path: Path) -> None:
    values_path = label_values_path(tmp_path)
    review_path = tmp_path / "review_label_values_review.yaml"
    with pytest.raises(PipelinePause):
        run(values_path, review_path)

    payload = read_yaml_object(review_path)
    payload["status"] = "approved"
    payload["labels"]["methodology"]["values"] = ["mri_classification"]
    payload["labels"]["methodology"]["merge_values"] = {
        "cross_validation": "mri_classification"
    }
    payload["labels"]["methodology"]["drop_values"] = ["too_broad"]
    write_yaml_object(review_path, payload)

    run(values_path, review_path)
    merged = json.loads(values_path.read_text(encoding="utf-8"))
    methodology = merged["review"]["label_values"][0]

    assert methodology["value_mappings"] == [
        {"from": "cross_validation", "to": "mri_classification"}
    ]
    assert methodology["dropped_values"] == ["too_broad"]
