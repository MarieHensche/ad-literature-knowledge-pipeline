#!/usr/bin/env python3
"""Audit a filled knowledge extraction table against the schema."""

from __future__ import annotations

import argparse
import csv
from collections import Counter
from pathlib import Path

import yaml


AUDIT_COLUMNS = [
    "paper_id",
    "field",
    "value",
    "issue",
]


SUMMARY_FIELDS = [
    "review_status",
    "knowledge_confidence",
    "evidence_modality_family",
    "primary_clinical_target",
    "early_detection_subtype",
    "population_scope",
    "representation_type",
    "dataset_source_type",
]


def load_schema(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as handle:
        schema = yaml.safe_load(handle)

    if not isinstance(schema, dict) or "fields" not in schema:
        raise ValueError("Schema must contain a top-level 'fields' mapping.")

    return schema


def read_rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def audit_rows(rows: list[dict[str, str]], schema: dict) -> list[dict[str, str]]:
    issues = []
    fields = schema["fields"]

    for row in rows:
        paper_id = row.get("paper_id", "")

        for field_name, field_spec in fields.items():
            value = (row.get(field_name) or "").strip()

            if field_spec.get("required") and not value:
                issues.append(
                    {
                        "paper_id": paper_id,
                        "field": field_name,
                        "value": value,
                        "issue": "missing_required_value",
                    }
                )

            if field_spec.get("type") == "categorical" and value:
                allowed_values = set(field_spec.get("values", []))
                if value not in allowed_values:
                    issues.append(
                        {
                            "paper_id": paper_id,
                            "field": field_name,
                            "value": value,
                            "issue": "invalid_categorical_value",
                        }
                    )

    return issues


def write_audit(path: Path, issues: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)

    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=AUDIT_COLUMNS)
        writer.writeheader()
        writer.writerows(issues)


def print_summary(rows: list[dict[str, str]]) -> None:
    print(f"Rows audited: {len(rows)}")

    for field in SUMMARY_FIELDS:
        counts = Counter((row.get(field) or "").strip() or "<blank>" for row in rows)
        print()
        print(field)
        for value, count in counts.most_common():
            print(f"  {value}: {count}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Audit a filled extraction table.")
    parser.add_argument(
        "--input",
        default="data/processed/example_extraction_filled.csv",
        help="Filled extraction CSV.",
    )
    parser.add_argument(
        "--schema",
        default="schemas/early_detection_knowledge_schema.yaml",
        help="Knowledge schema YAML.",
    )
    parser.add_argument(
        "--output",
        default="data/processed/example_extraction_audit.csv",
        help="Audit output CSV.",
    )
    args = parser.parse_args()

    rows = read_rows(Path(args.input))
    schema = load_schema(Path(args.schema))
    issues = audit_rows(rows, schema)
    write_audit(Path(args.output), issues)

    print_summary(rows)
    print()
    print(f"Issues found: {len(issues)}")
    print(f"Wrote {args.output}")


if __name__ == "__main__":
    main()
    