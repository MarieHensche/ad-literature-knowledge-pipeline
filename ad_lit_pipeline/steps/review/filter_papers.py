from __future__ import annotations

import argparse
import csv
from pathlib import Path
from typing import Any

from ad_lit_pipeline.core.step import StepResult, StepSpec
from ad_lit_pipeline.io.json_io import write_json
from ad_lit_pipeline.steps.review.extract_labels import is_likely_review_paper


STEP = StepSpec(
    name="filter_review_papers",
    inputs=["scope_screened_full_text_csv"],
    outputs=["review_eligible_papers_csv", "review_filter_report_json"],
    uses_llm=False,
    description="Exclude review articles from the literature-review evidence set.",
)


def read_csv_rows(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        return list(reader.fieldnames or []), list(reader)


def write_csv_rows(
    path: Path,
    fieldnames: list[str],
    rows: list[dict[str, str]],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fieldnames})


def included_rows(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    return [
        row
        for row in rows
        if not row.get("scope_decision") or row.get("scope_decision") == "include"
    ]


def clean_text(value: object) -> str:
    return " ".join(str(value or "").split()).strip()


def review_type_status(row: dict[str, str]) -> str:
    return "likely_review" if is_likely_review_paper(row) else "primary_or_unclear"


def annotated_row(row: dict[str, str], status: str) -> dict[str, str]:
    output = dict(row)
    output["review_type_status"] = status
    output["review_filter_decision"] = (
        "exclude_review_evidence" if status == "likely_review" else "retain"
    )
    return output


def filter_report(included: list[dict[str, str]]) -> tuple[list[dict[str, str]], dict[str, Any]]:
    retained = []
    excluded = []
    suspected_retained = []
    for row in included:
        status = review_type_status(row)
        annotated = annotated_row(row, status)
        record = {
            "paper_id": clean_text(row.get("paper_id")),
            "title": clean_text(row.get("title")),
            "year": clean_text(row.get("year")),
            "doi": clean_text(row.get("doi")),
            "source": clean_text(row.get("source")),
            "review_type_status": status,
            "review_filter_decision": annotated["review_filter_decision"],
        }
        if status == "likely_review":
            excluded.append(record)
        else:
            retained.append(annotated)
            if status != "primary_or_unclear":
                suspected_retained.append(record)

    return retained, {
        "counts": {
            "included_papers": len(included),
            "review_eligible_papers": len(retained),
            "excluded_likely_review_papers": len(excluded),
            "retained_primary_or_unclear_papers": len(retained),
            "retained_suspected_review_papers": len(suspected_retained),
        },
        "retention_rule": (
            "Papers identified as likely review articles by available metadata "
            "are excluded from literature-review evidence synthesis. Retained "
            "papers should be described as primary or unclear, not as fully "
            "verified original studies."
        ),
        "excluded_likely_review_papers": excluded,
        "retained_suspected_review_papers": suspected_retained,
    }


def run(
    papers_path: Path,
    output_path: Path,
    report_path: Path | None = None,
) -> StepResult:
    fieldnames, rows = read_csv_rows(papers_path)
    included = included_rows(rows)
    eligible, report = filter_report(included)
    excluded = report["counts"]["excluded_likely_review_papers"]

    output_fields = list(fieldnames)
    for field in ["review_type_status", "review_filter_decision"]:
        if field not in output_fields:
            output_fields.append(field)
    write_csv_rows(output_path, output_fields, eligible)
    outputs = {"review_eligible_papers_csv": output_path}
    if report_path is not None:
        write_json(report_path, report)
        outputs["review_filter_report_json"] = report_path
    return StepResult(
        step_name=STEP.name,
        inputs={"scope_screened_full_text_csv": papers_path},
        outputs=outputs,
        row_counts={
            "included_papers": len(included),
            "review_eligible_papers": len(eligible),
            "excluded_review_papers": excluded,
        },
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Exclude review articles from the literature-review evidence set."
    )
    parser.add_argument("--papers", required=True, help="Full-text paper CSV.")
    parser.add_argument("--output", required=True, help="Review-eligible output CSV.")
    parser.add_argument(
        "--report",
        default=None,
        help="Optional JSON report for review filtering decisions.",
    )
    args = parser.parse_args()

    run(
        Path(args.papers),
        Path(args.output),
        Path(args.report) if args.report else None,
    )


if __name__ == "__main__":
    main()
