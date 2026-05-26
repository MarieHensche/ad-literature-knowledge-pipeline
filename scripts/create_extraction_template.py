#!/usr/bin/env python3
"""Create a knowledge extraction template for papers included in scope."""

from __future__ import annotations

import argparse
import csv
from pathlib import Path

import yaml


METADATA_COLUMNS = [
    "paper_id",
    "title",
    "year",
    "doi",
    "abstract",
]


DEFAULT_VALUES = {
    "review_status": "todo",
}


def load_schema(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as handle:
        schema = yaml.safe_load(handle)

    if not isinstance(schema, dict) or "fields" not in schema:
        raise ValueError("Schema must contain a top-level 'fields' mapping.")

    return schema


def read_rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def schema_columns(schema: dict) -> list[str]:
    return list(schema["fields"].keys())


def make_template_row(row: dict[str, str], columns: list[str]) -> dict[str, str]:
    output = {column: "" for column in columns}

    for column in METADATA_COLUMNS:
        if column in output:
            output[column] = row.get(column, "")

    for column, value in DEFAULT_VALUES.items():
        if column in output:
            output[column] = value

    return output


def write_rows(path: Path, rows: list[dict[str, str]], columns: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)

    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description="Create a knowledge extraction template.")
    parser.add_argument(
        "--screened",
        default="data/processed/example_scope_screened.csv",
        help="Screened paper CSV.",
    )
    parser.add_argument(
        "--schema",
        required=True,
        help="Knowledge schema YAML.",
    )
    parser.add_argument(
        "--output",
        default="data/processed/example_extraction_template.csv",
        help="Output extraction template CSV.",
    )
    args = parser.parse_args()

    screened_path = Path(args.screened)
    schema_path = Path(args.schema)
    output_path = Path(args.output)

    schema = load_schema(schema_path)
    columns = schema_columns(schema)
    screened_rows = read_rows(screened_path)

    included_rows = [
        row for row in screened_rows if row.get("scope_decision") == "include"
    ]

    template_rows = [
        make_template_row(row, columns)
        for row in included_rows
    ]

    write_rows(output_path, template_rows, columns)

    print(f"Included papers: {len(included_rows)}")
    print(f"Wrote {output_path}")


if __name__ == "__main__":
    main()
