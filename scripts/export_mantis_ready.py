#!/usr/bin/env python3
"""Export AI-tagged extraction data to a Mantis-ready CSV."""

from __future__ import annotations

import argparse
import csv
from pathlib import Path


CORE_COLUMNS = [
    "title",
    "categoric",
    "semantic",
    "paper_id",
    "year",
    "doi",
]


def read_rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def tag_columns(fieldnames: list[str]) -> list[str]:
    excluded = {
        "paper_id",
        "title",
        "year",
        "doi",
        "main_knowledge_claim",
    }

    return [field for field in fieldnames if field not in excluded]


def make_semantic(row: dict[str, str]) -> str:
    claim = row.get("main_knowledge_claim", "").strip()
    return claim or row.get("title", "").strip()


def make_categoric(row: dict[str, str]) -> str:
    subtype = row.get("early_detection_subtype", "").strip()
    target = row.get("primary_clinical_target", "").strip()

    if subtype:
        return subtype.split(";")[0].strip()

    if target:
        return target.split(";")[0].strip()

    return "uncategorized"


def export_row(row: dict[str, str], tag_fields: list[str]) -> dict[str, str]:
    output = {
        "title": row.get("title", ""),
        "categoric": make_categoric(row),
        "semantic": make_semantic(row),
        "paper_id": row.get("paper_id", ""),
        "year": row.get("year", ""),
        "doi": row.get("doi", ""),
    }

    for field in tag_fields:
        output[field] = row.get(field, "")

    return output


def write_rows(output_path: Path, rows: list[dict[str, str]], fieldnames: list[str]) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with output_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description="Export Mantis-ready CSV.")
    parser.add_argument(
        "--input",
        default="data/processed/example_extraction_filled.csv",
        help="AI-tagged extraction CSV.",
    )
    parser.add_argument(
        "--output",
        default="data/processed/example_mantis_ready.csv",
        help="Mantis-ready output CSV.",
    )
    args = parser.parse_args()

    input_path = Path(args.input)
    output_path = Path(args.output)

    rows = read_rows(input_path)

    if not rows:
        raise ValueError(f"No rows found in {input_path}")

    fieldnames = list(rows[0].keys())
    tag_fields = tag_columns(fieldnames)
    output_fields = CORE_COLUMNS + tag_fields

    output_rows = [export_row(row, tag_fields) for row in rows]
    write_rows(output_path, output_rows, output_fields)

    print(f"Exported {len(output_rows)} Mantis rows")
    print(f"Wrote {output_path}")


if __name__ == "__main__":
    main()