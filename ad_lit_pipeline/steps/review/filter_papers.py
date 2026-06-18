from __future__ import annotations

import argparse
import csv
from pathlib import Path

from ad_lit_pipeline.core.step import StepResult, StepSpec
from ad_lit_pipeline.steps.review.extract_labels import is_likely_review_paper


STEP = StepSpec(
    name="filter_review_papers",
    inputs=["scope_screened_full_text_csv"],
    outputs=["review_eligible_papers_csv"],
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


def run(papers_path: Path, output_path: Path) -> StepResult:
    fieldnames, rows = read_csv_rows(papers_path)
    included = included_rows(rows)
    eligible = [row for row in included if not is_likely_review_paper(row)]
    excluded = len(included) - len(eligible)

    write_csv_rows(output_path, fieldnames, eligible)
    return StepResult(
        step_name=STEP.name,
        inputs={"scope_screened_full_text_csv": papers_path},
        outputs={"review_eligible_papers_csv": output_path},
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
    args = parser.parse_args()

    run(Path(args.papers), Path(args.output))


if __name__ == "__main__":
    main()
