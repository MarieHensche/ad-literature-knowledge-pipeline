from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any

from ad_lit_pipeline.core.errors import PipelinePause
from ad_lit_pipeline.core.step import StepResult, StepSpec
from ad_lit_pipeline.io.json_io import read_json_object, write_json
from ad_lit_pipeline.steps.review.evidence_map import (
    clean_controlled_values,
    labels_by_id,
    problematic_paper_ids,
)


STEP = StepSpec(
    name="build_review_coverage_report",
    inputs=[
        "review_eligible_papers_csv",
        "review_filter_report_json",
        "review_labels_raw_csv",
        "review_label_values_json",
        "review_quality_report_csv",
    ],
    outputs=["review_coverage_report_json"],
    uses_llm=False,
    description="Summarize review evidence coverage before synthesis.",
)

TEXT_USEFUL_FIELDS = [
    "dataset_or_sample",
    "key_finding",
    "paper_limitation",
    "direct_quote",
    "future_work_or_gap",
]
MIN_USABLE_PAPERS = 3
MIN_CITATION_ELIGIBLE_PAPERS = 3


def read_csv_rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def clean_text(value: object) -> str:
    return " ".join(str(value or "").split()).strip()


def useful_text(value: object) -> bool:
    text = clean_text(value)
    return bool(text and text != "[]" and text.lower() != "unclear")


def has_valid_citation_metadata(row: dict[str, str]) -> bool:
    return all(
        clean_text(row.get(column))
        for column in ["paper_id", "title", "year", "authors", "doi"]
    )


def has_useful_evidence(
    row: dict[str, str],
    labels: dict[str, dict[str, Any]],
) -> bool:
    for label_id, label in labels.items():
        mode = str(label.get("value_mode") or "")
        if mode in {"controlled_fixed", "controlled_auto"}:
            if clean_controlled_values(row.get(label_id, ""), label):
                return True
        elif label_id in TEXT_USEFUL_FIELDS and useful_text(row.get(label_id)):
            return True
    return False


def label_coverage(
    rows: list[dict[str, str]],
    labels: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    records = []
    for label_id, label in labels.items():
        mode = str(label.get("value_mode") or "")
        count = 0
        for row in rows:
            if mode in {"controlled_fixed", "controlled_auto"}:
                if clean_controlled_values(row.get(label_id, ""), label):
                    count += 1
            elif useful_text(row.get(label_id)):
                count += 1
        records.append(
            {
                "label_id": label_id,
                "value_mode": mode,
                "papers_with_usable_value": count,
                "total_labeled_papers": len(rows),
            }
        )
    return records


def issue_counts(quality_rows: list[dict[str, str]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in quality_rows:
        issue = clean_text(row.get("issue"))
        if issue:
            counts[issue] = counts.get(issue, 0) + 1
    return dict(sorted(counts.items()))


def citation_target(citation_eligible_count: int) -> dict[str, int]:
    if citation_eligible_count < 20:
        minimum = citation_eligible_count
        target = citation_eligible_count
    else:
        minimum = 20
        target = min(40, citation_eligible_count)
    return {
        "minimum_cited_papers": minimum,
        "target_cited_papers": target,
        "maximum_cited_papers": min(40, citation_eligible_count),
    }


def build_report(
    eligible_rows: list[dict[str, str]],
    label_rows: list[dict[str, str]],
    label_values: dict[str, Any],
    quality_rows: list[dict[str, str]],
    filter_report: dict[str, Any] | None = None,
) -> dict[str, Any]:
    labels = labels_by_id(label_values)
    excluded_ids = problematic_paper_ids(quality_rows, labels)
    usable_rows = [
        row
        for row in label_rows
        if clean_text(row.get("paper_id"))
        and clean_text(row.get("paper_id")) not in excluded_ids
    ]
    evidence_rows = [row for row in usable_rows if has_useful_evidence(row, labels)]
    citation_rows = [
        row
        for row in evidence_rows
        if has_valid_citation_metadata(row)
    ]
    key_finding_count = sum(1 for row in usable_rows if useful_text(row.get("key_finding")))

    warnings = []
    critical = []
    if len(usable_rows) < MIN_USABLE_PAPERS:
        critical.append(
            f"Only {len(usable_rows)} usable review papers are available."
        )
    if len(citation_rows) < MIN_CITATION_ELIGIBLE_PAPERS:
        critical.append(
            f"Only {len(citation_rows)} papers have citation metadata and useful evidence."
        )
    if label_rows and key_finding_count == 0:
        critical.append("No usable key findings were extracted.")
    if len(label_rows) < len(eligible_rows):
        warnings.append(
            f"{len(eligible_rows) - len(label_rows)} review-eligible papers were not labeled."
        )
    if key_finding_count < len(usable_rows):
        warnings.append(
            f"{len(usable_rows) - key_finding_count} usable papers lack a key finding."
        )
    filter_counts = {}
    retention_rule = ""
    if isinstance(filter_report, dict):
        counts = filter_report.get("counts")
        if isinstance(counts, dict):
            filter_counts = counts
        retention_rule = clean_text(filter_report.get("retention_rule"))

    return {
        "status": "critical" if critical else ("warning" if warnings else "ok"),
        "counts": {
            "review_eligible_papers": len(eligible_rows),
            "review_labeled_papers": len(label_rows),
            "review_usable_papers": len(usable_rows),
            "papers_with_useful_evidence": len(evidence_rows),
            "citation_eligible_papers": len(citation_rows),
            "excluded_papers": len(label_rows) - len(usable_rows),
        },
        "citation_target": citation_target(len(citation_rows)),
        "label_coverage": label_coverage(usable_rows, labels),
        "quality_issue_counts": issue_counts(quality_rows),
        "review_filter": {
            "counts": filter_counts,
            "retention_rule": retention_rule,
        },
        "excluded_paper_ids": sorted(excluded_ids),
        "warnings": warnings,
        "critical_issues": critical,
    }


def run(
    review_eligible_papers_path: Path,
    review_labels_path: Path,
    review_label_values_path: Path,
    review_quality_report_path: Path,
    output_path: Path,
    review_filter_report_path: Path | None = None,
) -> StepResult:
    eligible_rows = read_csv_rows(review_eligible_papers_path)
    label_rows = read_csv_rows(review_labels_path)
    label_values = read_json_object(review_label_values_path)
    quality_rows = read_csv_rows(review_quality_report_path)
    filter_report = (
        read_json_object(review_filter_report_path)
        if review_filter_report_path is not None and review_filter_report_path.exists()
        else None
    )
    report = build_report(
        eligible_rows,
        label_rows,
        label_values,
        quality_rows,
        filter_report,
    )
    write_json(
        output_path,
        {
            "source_review_eligible_papers": str(review_eligible_papers_path),
            "source_labels": str(review_labels_path),
            "source_label_values": str(review_label_values_path),
            "source_quality_report": str(review_quality_report_path),
            "source_review_filter_report": (
                str(review_filter_report_path) if review_filter_report_path else ""
            ),
            **report,
        },
    )
    result = StepResult(
        step_name=STEP.name,
        inputs={
            "review_eligible_papers_csv": review_eligible_papers_path,
            "review_filter_report_json": review_filter_report_path,
            "review_labels_raw_csv": review_labels_path,
            "review_label_values_json": review_label_values_path,
            "review_quality_report_csv": review_quality_report_path,
        },
        outputs={"review_coverage_report_json": output_path},
        row_counts=report["counts"],
        warnings=[*report["warnings"], *report["critical_issues"]],
        metadata={"status": report["status"]},
    )
    if report["critical_issues"]:
        raise PipelinePause(
            (
                "Review coverage is critically poor. Inspect "
                f"{output_path} before continuing."
            ),
            result,
        )
    return result


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build a literature-review coverage report."
    )
    parser.add_argument("--review-eligible-papers", required=True)
    parser.add_argument("--labels", required=True)
    parser.add_argument("--label-values", required=True)
    parser.add_argument("--quality-report", required=True)
    parser.add_argument("--review-filter-report", default=None)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    run(
        Path(args.review_eligible_papers),
        Path(args.labels),
        Path(args.label_values),
        Path(args.quality_report),
        Path(args.output),
        Path(args.review_filter_report) if args.review_filter_report else None,
    )


if __name__ == "__main__":
    main()
