#!/usr/bin/env python3
"""Validate the early-detection knowledge schema file."""

from __future__ import annotations

import argparse
from pathlib import Path

import yaml


REQUIRED_TOP_LEVEL_KEYS = {"name", "version", "layer", "fields"}
REQUIRED_FIELD_KEYS = {"type", "required"}


def load_schema(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle)

    if not isinstance(data, dict):
        raise ValueError("Schema must be a YAML mapping at the top level.")

    return data


def validate_schema(schema: dict) -> list[str]:
    errors: list[str] = []

    missing_top_level = REQUIRED_TOP_LEVEL_KEYS - set(schema)
    for key in sorted(missing_top_level):
        errors.append(f"Missing top-level key: {key}")

    fields = schema.get("fields")
    if not isinstance(fields, dict):
        errors.append("Top-level 'fields' must be a mapping.")
        return errors

    for field_name, field_spec in fields.items():
        if not isinstance(field_spec, dict):
            errors.append(f"Field '{field_name}' must be a mapping.")
            continue

        missing_field_keys = REQUIRED_FIELD_KEYS - set(field_spec)
        for key in sorted(missing_field_keys):
            errors.append(f"Field '{field_name}' missing key: {key}")

        field_type = field_spec.get("type")
        if field_type == "categorical":
            values = field_spec.get("values")
            if not isinstance(values, list) or not values:
                errors.append(f"Categorical field '{field_name}' must define non-empty values.")

            if isinstance(values, list) and len(values) != len(set(values)):
                errors.append(f"Categorical field '{field_name}' has duplicate values.")

    return errors


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate a knowledge schema YAML file.")
    parser.add_argument("schema", help="Path to schema YAML file.")
    args = parser.parse_args()

    schema_path = Path(args.schema)
    schema = load_schema(schema_path)
    errors = validate_schema(schema)

    if errors:
        print(f"Schema validation failed: {schema_path}")
        for error in errors:
            print(f"- {error}")
        raise SystemExit(1)

    field_count = len(schema["fields"])
    categorical_count = sum(
        1 for field in schema["fields"].values() if field.get("type") == "categorical"
    )

    print(f"Schema OK: {schema_path}")
    print(f"Fields: {field_count}")
    print(f"Categorical fields: {categorical_count}")


if __name__ == "__main__":
    main()
