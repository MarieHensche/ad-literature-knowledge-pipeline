from __future__ import annotations

import argparse
import csv
from pathlib import Path
from typing import Any

from ad_lit_pipeline.core.step import StepResult, StepSpec
from ad_lit_pipeline.steps.collection.export_included import (
    OUTPUT_COLUMNS,
    candidate_key,
    candidate_to_canonical_row,
    read_csv,
    read_jsonl,
    screening_key,
    screening_sort_key,
)


STEP = StepSpec(
    name="select_calibration_papers",
    inputs=["deduped_candidates_jsonl", "candidate_screening_csv"],
    outputs=["calibration_papers_csv"],
    uses_llm=False,
    description="Select a small non-review paper set for collection-time calibration.",
)

CALIBRATION_COLUMNS = [
    *OUTPUT_COLUMNS,
    "scope_decision",
    "scope_reason",
    "calibration_selection_reason",
]

REVIEW_TITLE_MARKERS = (
    "systematic review",
    "scoping review",
    "meta-analysis",
    "meta analysis",
    "literature review",
    "review and meta-analysis",
)
NON_PRIMARY_TITLE_MARKERS = (
    "protocol",
    "study protocol",
    "trial protocol",
)


def raw_record(candidate: dict[str, Any]) -> dict[str, Any]:
    value = candidate.get("raw_record")
    return value if isinstance(value, dict) else {}


def is_likely_review(candidate: dict[str, Any]) -> bool:
    raw = raw_record(candidate)
    if str(raw.get("type") or "").casefold() == "review":
        return True

    title = str(candidate.get("title") or "").casefold()
    return any(marker in title for marker in REVIEW_TITLE_MARKERS)


def is_likely_non_primary(candidate: dict[str, Any]) -> bool:
    title = str(candidate.get("title") or "").casefold()
    return any(marker in title for marker in NON_PRIMARY_TITLE_MARKERS)


def write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=CALIBRATION_COLUMNS)
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {field: row.get(field, "") for field in CALIBRATION_COLUMNS}
            )


def selection_reason(screening: dict[str, str]) -> str:
    tier = screening.get("title_relevance_tier", "")
    rank = screening.get("source_rank", "")
    confidence = screening.get("screening_confidence", "")
    parts = [
        "Selected for collection-time contract calibration",
        f"title_relevance_tier={tier}" if tier else "",
        f"source_rank={rank}" if rank else "",
        f"screening_confidence={confidence}" if confidence else "",
    ]
    return "; ".join(part for part in parts if part)


def select_calibration_rows(
    candidates: list[dict[str, Any]],
    screening_rows: list[dict[str, str]],
    max_papers: int,
) -> tuple[list[dict[str, str]], dict[str, int]]:
    if max_papers < 1:
        raise ValueError("max_papers must be at least 1.")

    candidates_by_key = {candidate_key(candidate): candidate for candidate in candidates}
    rows: list[dict[str, str]] = []
    skipped_reviews = 0
    skipped_non_primary = 0

    for screening in sorted(screening_rows, key=screening_sort_key):
        if screening.get("screening_decision") != "include":
            continue

        key = screening_key(screening)
        candidate = candidates_by_key.get(key)
        if candidate is None:
            raise ValueError(
                "Could not match included screening row to candidate: "
                f"doi={key[0]} provider_id={key[1]}"
            )

        if is_likely_review(candidate):
            skipped_reviews += 1
            continue
        if is_likely_non_primary(candidate):
            skipped_non_primary += 1
            continue

        row = candidate_to_canonical_row(candidate, screening)
        row["scope_decision"] = "include"
        row["scope_reason"] = screening.get("screening_reason", "")
        row["calibration_selection_reason"] = selection_reason(screening)
        rows.append(row)
        if len(rows) >= max_papers:
            break

    return rows, {
        "selected_calibration_papers": len(rows),
        "skipped_review_candidates": skipped_reviews,
        "skipped_non_primary_candidates": skipped_non_primary,
    }


def run(
    candidates_path: Path,
    screening_path: Path,
    output_path: Path,
    max_papers: int,
) -> StepResult:
    candidates = read_jsonl(candidates_path)
    screening_rows = read_csv(screening_path)
    selected_rows, counts = select_calibration_rows(
        candidates,
        screening_rows,
        max_papers,
    )
    write_csv(output_path, selected_rows)

    warnings = []
    if not selected_rows:
        warnings.append(
            "No non-review primary-like candidates were selected for "
            "collection-time contract calibration."
        )

    return StepResult(
        step_name=STEP.name,
        inputs={
            "deduped_candidates_jsonl": candidates_path,
            "candidate_screening_csv": screening_path,
        },
        outputs={"calibration_papers_csv": output_path},
        row_counts={
            "screened_rows": len(screening_rows),
            **counts,
        },
        warnings=warnings,
        metadata={"max_papers": max_papers},
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Select non-review candidates for contract calibration."
    )
    parser.add_argument(
        "--candidates",
        required=True,
        help="Deduplicated candidates JSONL.",
    )
    parser.add_argument("--screening", required=True, help="Candidate screening CSV.")
    parser.add_argument("--output", required=True, help="Output calibration CSV.")
    parser.add_argument(
        "--max-papers",
        type=int,
        default=3,
        help="Maximum non-review candidates to select for calibration.",
    )
    args = parser.parse_args()

    result = run(
        Path(args.candidates),
        Path(args.screening),
        Path(args.output),
        args.max_papers,
    )

    print(
        "Selected calibration papers: "
        f"{result.row_counts['selected_calibration_papers']}"
    )
    print(f"Wrote {args.output}")


if __name__ == "__main__":
    main()
