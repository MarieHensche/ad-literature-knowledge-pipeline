from __future__ import annotations

import argparse
import csv
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from ad_lit_pipeline.core.step import StepResult, StepSpec
from ad_lit_pipeline.io.json_io import read_json_object, write_json
from ad_lit_pipeline.topics.contract import normalize_tagging_label


STEP = StepSpec(
    name="normalize_review_label_values",
    inputs=["review_labels_raw_csv", "review_config_normalized_json"],
    outputs=["review_label_values_json"],
    uses_llm=False,
    description="Normalize controlled literature-review label values.",
)


def read_csv_rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def labels_from_config(config: dict[str, Any]) -> list[dict[str, Any]]:
    labels = config.get("review", {}).get("labels")
    if not isinstance(labels, list):
        raise ValueError("Normalized review config must contain review.labels list.")
    return labels


def split_multi_value(raw_value: str) -> list[str]:
    values = []
    seen = set()
    for value in str(raw_value or "").split(";"):
        cleaned = value.strip()
        normalized = normalize_tagging_label(cleaned)
        if normalized and normalized not in seen:
            values.append(normalized)
            seen.add(normalized)
    return values


AUTO_VALUE_TOKEN_REPLACEMENTS = {
    "analyses": "analysis",
    "analytic": "analysis",
    "analytical": "analysis",
    "approaches": "approach",
    "methodologies": "methodology",
    "methods": "method",
    "techniques": "technique",
}

AUTO_VALUE_FILLER_TOKENS = {
    "approach",
    "method",
    "methodology",
    "technique",
}


def canonical_auto_value(value: str) -> str:
    normalized = normalize_tagging_label(value)
    tokens = [
        AUTO_VALUE_TOKEN_REPLACEMENTS.get(token, token)
        for token in normalized.split("_")
        if token
    ]
    compact_tokens = [token for token in tokens if token not in AUTO_VALUE_FILLER_TOKENS]
    if len(compact_tokens) >= 2:
        tokens = compact_tokens

    if len(tokens) >= 3 and tokens[-1] == "analysis" and tokens[-2] == "analysis":
        tokens = [*tokens[:-2], "analysis"]

    if len(tokens) >= 3 and tokens[-1] == "analysis" and tokens[-2] == "theoretical":
        tokens = [*tokens[:-2], "analysis"]

    return "_".join(tokens)


def allowed_values(label: dict[str, Any]) -> dict[str, str]:
    allowed = {}
    for value in label.get("allowed_values", []):
        if not isinstance(value, dict):
            continue
        raw_value = str(value.get("value") or "").strip()
        normalized = normalize_tagging_label(raw_value)
        if normalized:
            allowed[normalized] = str(value.get("label") or raw_value or normalized)
    return allowed


def value_records(
    counts: Counter[str],
    surface_forms: dict[str, Counter[str]],
    labels: dict[str, str] | None = None,
    canonicalized_from: dict[str, Counter[str]] | None = None,
) -> list[dict[str, Any]]:
    records = []
    for value in sorted(counts):
        surfaces = surface_forms.get(value, Counter())
        record = {
            "value": value,
            "label": (labels or {}).get(value, value),
            "paper_count": counts[value],
            "surface_forms": [
                {"form": form, "count": count}
                for form, count in surfaces.most_common()
            ],
        }
        source_values = (canonicalized_from or {}).get(value, Counter())
        if len(source_values) > 1 or (
            len(source_values) == 1 and next(iter(source_values)) != value
        ):
            record["canonicalized_from"] = [
                {"value": source, "count": count}
                for source, count in source_values.most_common()
            ]
        records.append(record)
    return records


def controlled_label_summary(
    label: dict[str, Any],
    rows: list[dict[str, str]],
) -> dict[str, Any]:
    label_id = str(label["label_id"])
    mode = str(label.get("value_mode") or "")
    fixed_values = allowed_values(label)
    counts: Counter[str] = Counter()
    surface_forms: dict[str, Counter[str]] = defaultdict(Counter)
    canonicalized_from: dict[str, Counter[str]] = defaultdict(Counter)
    invalid_values: Counter[str] = Counter()
    empty_count = 0

    for row in rows:
        raw_cell = row.get(label_id, "")
        values = split_multi_value(raw_cell)
        if not values:
            empty_count += 1
            continue
        for value in values:
            if mode == "controlled_fixed" and fixed_values and value not in fixed_values:
                invalid_values[value] += 1
                continue
            output_value = canonical_auto_value(value) if mode == "controlled_auto" else value
            counts[output_value] += 1
            canonicalized_from[output_value][value] += 1
            for raw_part in str(raw_cell or "").split(";"):
                if normalize_tagging_label(raw_part.strip()) == value:
                    surface_forms[output_value][raw_part.strip()] += 1

    if mode == "controlled_fixed":
        for value in fixed_values:
            counts.setdefault(value, 0)

    return {
        "label_id": label_id,
        "label": label.get("label", label_id),
        "value_mode": mode,
        "selection": label.get("selection", ""),
        "required": bool(label.get("required", False)),
        "total_rows": len(rows),
        "empty_count": empty_count,
        "non_empty_count": len(rows) - empty_count,
        "values": value_records(
            counts,
            surface_forms,
            fixed_values,
            canonicalized_from if mode == "controlled_auto" else None,
        ),
        "invalid_values": [
            {"value": value, "count": count}
            for value, count in sorted(invalid_values.items())
        ],
    }


def non_controlled_label_summary(
    label: dict[str, Any],
    rows: list[dict[str, str]],
) -> dict[str, Any]:
    label_id = str(label["label_id"])
    non_empty_count = sum(1 for row in rows if str(row.get(label_id, "")).strip())
    return {
        "label_id": label_id,
        "label": label.get("label", label_id),
        "value_mode": label.get("value_mode", ""),
        "selection": label.get("selection", ""),
        "required": bool(label.get("required", False)),
        "total_rows": len(rows),
        "empty_count": len(rows) - non_empty_count,
        "non_empty_count": non_empty_count,
        "values": [],
        "invalid_values": [],
    }


def normalize_review_label_values(
    rows: list[dict[str, str]],
    config: dict[str, Any],
) -> dict[str, Any]:
    summaries = []
    for label in labels_from_config(config):
        mode = str(label.get("value_mode") or "")
        if mode in {"controlled_fixed", "controlled_auto"}:
            summaries.append(controlled_label_summary(label, rows))
        else:
            summaries.append(non_controlled_label_summary(label, rows))

    return {
        "research_topic": config.get("research_topic", {}),
        "scope": config.get("scope", {}),
        "collection": config.get("collection", {}),
        "topic_structure": config.get("topic_structure", {}),
        "review": {
            "review_type": config.get("review", {}).get("review_type", "narrative"),
            "output": config.get("review", {}).get("output", {}),
            "label_count": len(summaries),
            "paper_count": len(rows),
            "label_values": summaries,
        },
    }


def run(
    review_labels_path: Path,
    review_config_path: Path,
    output_path: Path,
) -> StepResult:
    rows = read_csv_rows(review_labels_path)
    config = read_json_object(review_config_path)
    normalized = normalize_review_label_values(rows, config)
    value_count = sum(
        len(label.get("values", []))
        for label in normalized["review"]["label_values"]
    )
    invalid_count = sum(
        len(label.get("invalid_values", []))
        for label in normalized["review"]["label_values"]
    )
    write_json(
        output_path,
        {
            "source_labels": str(review_labels_path),
            "source_config": str(review_config_path),
            **normalized,
        },
    )
    return StepResult(
        step_name=STEP.name,
        inputs={
            "review_labels_raw_csv": review_labels_path,
            "review_config_normalized_json": review_config_path,
        },
        outputs={"review_label_values_json": output_path},
        row_counts={
            "review_label_rows": len(rows),
            "review_labels": int(normalized["review"]["label_count"]),
            "review_label_values": value_count,
            "review_label_invalid_values": invalid_count,
        },
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Normalize literature-review label values."
    )
    parser.add_argument("--labels", required=True, help="Raw review labels CSV.")
    parser.add_argument("--review-config", required=True, help="Normalized review JSON.")
    parser.add_argument("--output", required=True, help="Review label values JSON.")
    args = parser.parse_args()

    run(Path(args.labels), Path(args.review_config), Path(args.output))


if __name__ == "__main__":
    main()
