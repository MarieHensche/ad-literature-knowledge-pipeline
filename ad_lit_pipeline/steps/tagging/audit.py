from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from pathlib import Path

from ad_lit_pipeline.core.step import StepResult, StepSpec


STEP = StepSpec(
    name="audit_extraction",
    inputs=["extraction_filled_csv", "tagging_config_json", "tagging_rules_json"],
    outputs=["extraction_audit_csv"],
    uses_llm=False,
    description="Audit filled extraction rows against config values and fixed rules.",
)


def load_json(path: Path) -> dict[str, object]:
    with path.open(encoding="utf-8") as handle:
        data = json.load(handle)

    if not isinstance(data, dict):
        raise ValueError(f"Expected JSON object: {path}")

    return data


def read_rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def categories_from_config(config: dict[str, object]) -> list[dict[str, object]]:
    categories = config.get("categories")
    if not isinstance(categories, list):
        raise ValueError("Normalized tagging config must contain categories list.")
    return categories


def allowed_values_by_category(config: dict[str, object]) -> dict[str, set[str]]:
    allowed = {}
    for category in categories_from_config(config):
        category_id = category["category_id"]
        allowed[category_id] = {
            value["value"] for value in category.get("allowed_values", [])
        }
    return allowed


def rules_by_category(rules: dict[str, object]) -> dict[str, dict[str, object]]:
    rule_list = rules.get("rules")
    if not isinstance(rule_list, list):
        raise ValueError("Tagging rules must contain rules list.")
    return {rule["category_id"]: rule for rule in rule_list}


def split_values(value: str) -> list[str]:
    return [part.strip() for part in (value or "").split(";") if part.strip()]


def audit_row(
    row: dict[str, str],
    allowed: dict[str, set[str]],
    rules: dict[str, dict[str, object]],
) -> list[dict[str, str]]:
    issues = []
    paper_id = row.get("paper_id", "")

    for category_id, allowed_values in allowed.items():
        values = split_values(row.get(category_id, ""))
        rule = rules[category_id]

        if rule.get("required") and not values:
            issues.append(
                {
                    "paper_id": paper_id,
                    "field": category_id,
                    "value": "",
                    "issue": "required_missing",
                }
            )

        if not values:
            continue

        invalid_values = [value for value in values if value not in allowed_values]
        for value in invalid_values:
            issues.append(
                {
                    "paper_id": paper_id,
                    "field": category_id,
                    "value": value,
                    "issue": "invalid_value",
                }
            )

        if rule.get("selection") == "single" and len(values) != 1:
            issues.append(
                {
                    "paper_id": paper_id,
                    "field": category_id,
                    "value": "; ".join(values),
                    "issue": "single_selection_has_multiple_values",
                }
            )

    return issues


def summarize(rows: list[dict[str, str]], config: dict[str, object]) -> None:
    print(f"Rows audited: {len(rows)}")

    for category in categories_from_config(config):
        category_id = category["category_id"]
        counter: Counter[str] = Counter()

        for row in rows:
            for value in split_values(row.get(category_id, "")):
                counter[value] += 1

        if counter:
            print()
            print(category_id)
            for value, count in counter.most_common():
                print(f"  {value}: {count}")


def write_issues(output_path: Path, issues: list[dict[str, str]]) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with output_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["paper_id", "field", "value", "issue"],
        )
        writer.writeheader()
        writer.writerows(issues)


def run(
    input_path: Path,
    config_path: Path,
    rules_path: Path,
    output_path: Path,
) -> StepResult:
    rows = read_rows(input_path)
    config = load_json(config_path)
    rules = load_json(rules_path)

    allowed = allowed_values_by_category(config)
    rule_map = rules_by_category(rules)

    issues = []
    for row in rows:
        issues.extend(audit_row(row, allowed, rule_map))

    summarize(rows, config)
    print()
    print(f"Issues found: {len(issues)}")

    write_issues(output_path, issues)
    return StepResult(
        step_name=STEP.name,
        inputs={
            "extraction_filled_csv": input_path,
            "tagging_config_json": config_path,
            "tagging_rules_json": rules_path,
        },
        outputs={"extraction_audit_csv": output_path},
        row_counts={"rows_audited": len(rows), "issues_found": len(issues)},
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Audit filled extraction table.")
    parser.add_argument(
        "--input",
        default="data/processed/example_extraction_filled.csv",
        help="Filled extraction CSV.",
    )
    parser.add_argument(
        "--config",
        default="data/processed/example_tagging_config_normalized.json",
        help="Normalized tagging config JSON.",
    )
    parser.add_argument(
        "--rules",
        default="data/processed/example_tagging_rules.json",
        help="Fixed tagging rules JSON.",
    )
    parser.add_argument(
        "--output",
        default="data/processed/example_extraction_audit.csv",
        help="Audit issue output CSV.",
    )
    args = parser.parse_args()

    output_path = Path(args.output)
    run(Path(args.input), Path(args.config), Path(args.rules), output_path)
    print(f"Wrote {output_path}")
