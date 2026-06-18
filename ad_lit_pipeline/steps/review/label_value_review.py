from __future__ import annotations

import argparse
from copy import deepcopy
from pathlib import Path
from typing import Any

from ad_lit_pipeline.core.errors import PipelinePause
from ad_lit_pipeline.core.step import StepResult, StepSpec
from ad_lit_pipeline.io.json_io import read_json_object, write_json
from ad_lit_pipeline.io.yaml_io import read_yaml_object, write_yaml_object
from ad_lit_pipeline.topics.contract import normalize_tagging_label


STEP = StepSpec(
    name="review_review_label_values",
    inputs=["review_label_values_json"],
    outputs=["review_label_values_review_yaml", "review_label_values_json"],
    uses_llm=False,
    description="Pause for optional human review of literature-review label values.",
)

STATUS_NEEDS_REVIEW = "needs_review"
STATUS_APPROVED = "approved"


def review_payload(label_values: dict[str, Any], source_path: Path) -> dict[str, Any]:
    labels = {}
    for label in label_values.get("review", {}).get("label_values", []):
        if not isinstance(label, dict):
            continue
        label_id = str(label.get("label_id") or "")
        if not label_id:
            continue
        values = [
            str(value.get("value"))
            for value in label.get("values", [])
            if isinstance(value, dict) and value.get("value")
        ]
        value_details = []
        for value in label.get("values", []):
            if not isinstance(value, dict) or not value.get("value"):
                continue
            detail = {
                "value": str(value.get("value")),
                "paper_count": int(value.get("paper_count") or 0),
                "surface_forms": value.get("surface_forms", []),
            }
            if value.get("canonicalized_from"):
                detail["canonicalized_from"] = value["canonicalized_from"]
            value_details.append(detail)

        labels[label_id] = {
            "label": str(label.get("label") or label_id),
            "value_mode": str(label.get("value_mode") or ""),
            "selection": str(label.get("selection") or ""),
            "values": values,
            "value_details": value_details,
        }

    return {
        "status": STATUS_NEEDS_REVIEW,
        "source_review_label_values": str(source_path),
        "instructions": [
            "Edit values for controlled review labels only.",
            "Use value_details as read-only context for counts and surface forms.",
            "Delete a value to remove it from later review aggregation.",
            "Add a lowercase snake_case value to keep a user-approved new value.",
            "Set status to approved when the values are ready to merge.",
        ],
        "labels": labels,
    }


def review_status(payload: dict[str, Any]) -> str:
    return str(payload.get("status") or "").strip().lower()


def reviewed_values(raw_values: object, label_id: str) -> list[str]:
    if not isinstance(raw_values, list):
        raise ValueError(f"labels.{label_id}.values must be a list.")

    values = []
    seen = set()
    for item in raw_values:
        raw_value = item.get("value") if isinstance(item, dict) else item
        value = normalize_tagging_label(str(raw_value or ""))
        if not value or value in seen:
            continue
        values.append(value)
        seen.add(value)
    return values


def value_record_by_id(label: dict[str, Any]) -> dict[str, dict[str, Any]]:
    records = {}
    for value in label.get("values", []):
        if isinstance(value, dict) and value.get("value"):
            records[str(value["value"])] = value
    return records


def merge_reviewed_values(
    label_values: dict[str, Any],
    review: dict[str, Any],
) -> tuple[dict[str, Any], int]:
    labels = review.get("labels")
    if not isinstance(labels, dict):
        raise ValueError("Review file must contain labels mapping.")

    merged = deepcopy(label_values)
    changed = 0
    for label in merged.get("review", {}).get("label_values", []):
        if not isinstance(label, dict):
            continue
        label_id = str(label.get("label_id") or "")
        payload = labels.get(label_id)
        if not isinstance(payload, dict):
            continue
        values = reviewed_values(payload.get("values"), label_id)
        existing = value_record_by_id(label)
        next_records = []
        for value in values:
            if value in existing:
                next_records.append(existing[value])
            else:
                next_records.append(
                    {
                        "value": value,
                        "label": value,
                        "paper_count": 0,
                        "surface_forms": [],
                    }
                )
        if [record.get("value") for record in label.get("values", [])] != values:
            changed += 1
        label["values"] = next_records

    return merged, changed


def run(label_values_path: Path, review_path: Path) -> StepResult:
    label_values = read_json_object(label_values_path)
    if not review_path.exists():
        write_yaml_object(review_path, review_payload(label_values, label_values_path))
        result = StepResult(
            step_name=STEP.name,
            inputs={"review_label_values_json": label_values_path},
            outputs={
                "review_label_values_review_yaml": review_path,
                "review_label_values_json": label_values_path,
            },
            metadata={"status": STATUS_NEEDS_REVIEW},
        )
        raise PipelinePause(
            (
                "Review label values need approval. Edit "
                f"{review_path}, set status to approved, then resume from "
                "review_review_label_values."
            ),
            result,
        )

    review = read_yaml_object(review_path)
    status = review_status(review)
    if status != STATUS_APPROVED:
        result = StepResult(
            step_name=STEP.name,
            inputs={
                "review_label_values_json": label_values_path,
                "review_label_values_review_yaml": review_path,
            },
            outputs={
                "review_label_values_review_yaml": review_path,
                "review_label_values_json": label_values_path,
            },
            metadata={"status": status or STATUS_NEEDS_REVIEW},
        )
        raise PipelinePause(
            (
                "Review label values are not approved yet. Edit "
                f"{review_path}, set status to approved, then resume from "
                "review_review_label_values."
            ),
            result,
        )

    merged, changed = merge_reviewed_values(label_values, review)
    write_json(label_values_path, merged)
    return StepResult(
        step_name=STEP.name,
        inputs={
            "review_label_values_json": label_values_path,
            "review_label_values_review_yaml": review_path,
        },
        outputs={
            "review_label_values_review_yaml": review_path,
            "review_label_values_json": label_values_path,
        },
        row_counts={"review_value_labels_changed": changed},
        metadata={"status": STATUS_APPROVED},
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Review literature-review label values."
    )
    parser.add_argument("--label-values", required=True)
    parser.add_argument("--review-file", required=True)
    args = parser.parse_args()

    run(Path(args.label_values), Path(args.review_file))


if __name__ == "__main__":
    main()
