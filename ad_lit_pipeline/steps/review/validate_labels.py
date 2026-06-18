from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any

from ad_lit_pipeline.core.step import StepResult, StepSpec
from ad_lit_pipeline.io.json_io import read_json_object
from ad_lit_pipeline.topics.contract import normalize_tagging_label


STEP = StepSpec(
    name="validate_review_labels",
    inputs=["review_labels_raw_csv", "review_label_values_json"],
    outputs=["review_quality_report_csv"],
    uses_llm=False,
    description="Validate review labels before evidence-map construction.",
)

REPORT_COLUMNS = ["paper_id", "field", "value", "issue", "severity", "detail"]
REQUIRED_METADATA_COLUMNS = ["paper_id", "title", "year", "doi"]
RECOMMENDED_METADATA_COLUMNS = ["authors", "venue"]
HIGH_MISSINGNESS_THRESHOLD = 0.5
MIN_ROWS_FOR_MISSINGNESS_WARNING = 2


def read_rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def split_values(value: str) -> list[str]:
    values = []
    seen = set()
    for part in str(value or "").split(";"):
        normalized = normalize_tagging_label(part.strip())
        if normalized and normalized not in seen:
            values.append(normalized)
            seen.add(normalized)
    return values


def label_summaries(label_values: dict[str, Any]) -> dict[str, dict[str, Any]]:
    labels = label_values.get("review", {}).get("label_values")
    if not isinstance(labels, list):
        raise ValueError("review_label_values JSON must contain review.label_values.")
    return {
        str(label["label_id"]): label
        for label in labels
        if isinstance(label, dict) and label.get("label_id")
    }


def issue(
    paper_id: str,
    field: str,
    value: str,
    issue_type: str,
    severity: str,
    detail: str = "",
) -> dict[str, str]:
    return {
        "paper_id": paper_id,
        "field": field,
        "value": value,
        "issue": issue_type,
        "severity": severity,
        "detail": detail,
    }


def allowed_values(label: dict[str, Any]) -> set[str]:
    return {
        str(value.get("value"))
        for value in label.get("values", [])
        if isinstance(value, dict) and value.get("value")
    }


def validate_quote_value(
    paper_id: str,
    field: str,
    raw_value: str,
) -> list[dict[str, str]]:
    if not raw_value.strip():
        return []
    try:
        payload = json.loads(raw_value)
    except json.JSONDecodeError as error:
        return [
            issue(
                paper_id,
                field,
                raw_value,
                "malformed_quote_json",
                "error",
                str(error),
            )
        ]
    if not isinstance(payload, list):
        return [issue(paper_id, field, raw_value, "quote_json_not_list", "error")]

    issues = []
    for index, quote in enumerate(payload, start=1):
        if not isinstance(quote, dict):
            issues.append(
                issue(
                    paper_id,
                    field,
                    str(quote),
                    "quote_item_not_object",
                    "error",
                    f"quote_index={index}",
                )
            )
            continue
        if not str(quote.get("quote") or "").strip():
            issues.append(
                issue(paper_id, field, "", "quote_missing_text", "error")
            )
        if not str(quote.get("section") or "").strip():
            issues.append(
                issue(paper_id, field, "", "quote_missing_section", "warning")
            )
    return issues


def validate_row(
    row: dict[str, str],
    labels: dict[str, dict[str, Any]],
) -> list[dict[str, str]]:
    paper_id = row.get("paper_id", "")
    issues = []
    for column in REQUIRED_METADATA_COLUMNS:
        if not str(row.get(column, "")).strip():
            issues.append(
                issue(paper_id, column, "", "required_metadata_missing", "error")
            )
    for column in RECOMMENDED_METADATA_COLUMNS:
        if not str(row.get(column, "")).strip():
            issues.append(
                issue(paper_id, column, "", "recommended_metadata_missing", "warning")
            )

    for label_id, label in labels.items():
        raw_value = row.get(label_id, "")
        mode = str(label.get("value_mode") or "")
        values = split_values(raw_value)
        if label.get("required") and not str(raw_value or "").strip():
            issues.append(
                issue(paper_id, label_id, "", "required_review_label_missing", "error")
            )

        if mode in {"controlled_fixed", "controlled_auto"}:
            allowed = allowed_values(label)
            invalid = [value for value in values if allowed and value not in allowed]
            for value in invalid:
                issues.append(
                    issue(paper_id, label_id, value, "invalid_review_value", "error")
                )
            if label.get("selection") == "single" and len(values) > 1:
                issues.append(
                    issue(
                        paper_id,
                        label_id,
                        "; ".join(values),
                        "single_selection_has_multiple_values",
                        "error",
                    )
                )
        elif mode == "evidence_quote":
            issues.extend(validate_quote_value(paper_id, label_id, raw_value))

    return issues


def missingness_issues(
    rows: list[dict[str, str]],
    labels: dict[str, dict[str, Any]],
) -> list[dict[str, str]]:
    issues = []
    for label_id, label in labels.items():
        invalid_values = label.get("invalid_values", [])
        if isinstance(invalid_values, list):
            for invalid in invalid_values:
                if not isinstance(invalid, dict):
                    continue
                issues.append(
                    issue(
                        "",
                        label_id,
                        str(invalid.get("value") or ""),
                        "observed_invalid_value_summary",
                        "error",
                        f"count={invalid.get('count', 0)}",
                    )
                )

        if len(rows) < MIN_ROWS_FOR_MISSINGNESS_WARNING:
            continue

        empty_count = sum(1 for row in rows if not str(row.get(label_id, "")).strip())
        ratio = empty_count / len(rows)
        if ratio >= HIGH_MISSINGNESS_THRESHOLD:
            issues.append(
                issue(
                    "",
                    label_id,
                    "",
                    "high_missingness",
                    "warning",
                    f"{empty_count}_of_{len(rows)}_rows_empty",
                )
            )
    return issues


def validate_review_labels(
    rows: list[dict[str, str]],
    label_values: dict[str, Any],
) -> list[dict[str, str]]:
    labels = label_summaries(label_values)
    issues = []
    seen_paper_ids: set[str] = set()
    duplicate_ids: set[str] = set()
    for row in rows:
        paper_id = str(row.get("paper_id") or "").strip()
        if paper_id and paper_id in seen_paper_ids:
            duplicate_ids.add(paper_id)
        seen_paper_ids.add(paper_id)
        issues.extend(validate_row(row, labels))
    for paper_id in sorted(duplicate_ids):
        issues.append(
            issue(paper_id, "paper_id", paper_id, "duplicate_paper_id", "error")
        )
    issues.extend(missingness_issues(rows, labels))
    return issues


def write_report(path: Path, issues: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=REPORT_COLUMNS)
        writer.writeheader()
        for row in issues:
            writer.writerow({field: row.get(field, "") for field in REPORT_COLUMNS})


def run(
    review_labels_path: Path,
    review_label_values_path: Path,
    output_path: Path,
) -> StepResult:
    rows = read_rows(review_labels_path)
    label_values = read_json_object(review_label_values_path)
    issues = validate_review_labels(rows, label_values)
    write_report(output_path, issues)
    error_count = sum(1 for row in issues if row.get("severity") == "error")
    warning_count = sum(1 for row in issues if row.get("severity") == "warning")
    return StepResult(
        step_name=STEP.name,
        inputs={
            "review_labels_raw_csv": review_labels_path,
            "review_label_values_json": review_label_values_path,
        },
        outputs={"review_quality_report_csv": output_path},
        row_counts={
            "review_label_rows": len(rows),
            "review_quality_issues": len(issues),
            "review_quality_errors": error_count,
            "review_quality_warnings": warning_count,
        },
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate literature-review labels.")
    parser.add_argument("--labels", required=True)
    parser.add_argument("--label-values", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    run(Path(args.labels), Path(args.label_values), Path(args.output))


if __name__ == "__main__":
    main()
