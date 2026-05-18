#!/usr/bin/env python3
"""Screen normalized papers against the early-detection scope."""

from __future__ import annotations

import argparse
import csv
from pathlib import Path


INCLUDE_TERMS = [
    "early detection",
    "early diagnosis",
    "early dementia",
    "mild cognitive impairment",
    "mci",
    "screening",
    "classification",
    "diagnosis",
    "detecting",
    "detection",
]

EXCLUDE_TERMS = [
    "drug repurposing",
    "drug discovery",
    "treatment",
    "treatment response",
    "care support",
]


OUTPUT_COLUMNS = [
    "paper_id",
    "title",
    "year",
    "doi",
    "abstract",
    "abstract_available",
    "metadata_notes",
    "scope_decision",
    "scope_reason",
]


def text_for_screening(row: dict[str, str]) -> str:
    return " ".join(
        [
            row.get("title", ""),
            row.get("abstract", ""),
        ]
    ).lower()


def decide_scope(row: dict[str, str]) -> tuple[str, str]:
    text = text_for_screening(row)

    matched_exclude = [term for term in EXCLUDE_TERMS if term in text]
    matched_include = [term for term in INCLUDE_TERMS if term in text]

    if matched_exclude:
        return (
            "exclude_or_route_elsewhere",
            (
                f"Matched exclude term(s): {', '.join(matched_exclude)}; "
                f"matched include term(s): {', '.join(matched_include) if matched_include else 'none'}"
            ),
        )

    if matched_include:
        return (
            "include",
            f"Matched include term(s): {', '.join(matched_include)}",
        )


    return (
        "needs_decision",
        "No clear include or exclude term matched.",
    )


def read_rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def write_rows(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)

    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=OUTPUT_COLUMNS)
        writer.writeheader()
        for row in rows:
            writer.writerow({column: row.get(column, "") for column in OUTPUT_COLUMNS})


def main() -> None:
    parser = argparse.ArgumentParser(description="Screen papers against the early-detection scope.")
    parser.add_argument(
        "--input",
        default="data/processed/example_papers_normalized.csv",
        help="Normalized input CSV.",
    )
    parser.add_argument(
        "--output",
        default="data/processed/example_scope_screened.csv",
        help="Output screened CSV.",
    )
    args = parser.parse_args()

    input_path = Path(args.input)
    output_path = Path(args.output)

    rows = read_rows(input_path)
    screened_rows = []

    for row in rows:
        decision, reason = decide_scope(row)
        screened_rows.append(
            {
                **row,
                "scope_decision": decision,
                "scope_reason": reason,
            }
        )

    write_rows(output_path, screened_rows)

    print(f"Screened {len(screened_rows)} papers")
    print(f"Wrote {output_path}")


if __name__ == "__main__":
    main()