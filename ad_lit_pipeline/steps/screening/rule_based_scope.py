from __future__ import annotations

import argparse
import csv
from pathlib import Path
from typing import Any

from ad_lit_pipeline.core.step import StepResult, StepSpec
from ad_lit_pipeline.topics.contract import (
    load_topic_contract,
    rule_based_screening_from_contract,
)


STEP = StepSpec(
    name="screen_scope",
    inputs=["normalized_papers_csv", "topic_contract_yaml"],
    outputs=["scope_screened_csv"],
    uses_llm=False,
    description="Screen normalized papers with topic-contract include/exclude terms.",
)

SCOPE_COLUMNS = [
    "scope_decision",
    "scope_reason",
    "scope_matched_include_terms",
    "scope_matched_exclude_terms",
]


def text_for_screening(row: dict[str, str]) -> str:
    return " ".join(
        [
            row.get("title", ""),
            row.get("abstract", ""),
        ]
    ).lower()


def matched_terms(text: str, terms: list[str]) -> list[str]:
    return [term for term in terms if term.lower() in text]


def decide_scope(
    row: dict[str, str],
    include_terms: list[str],
    exclude_terms: list[str],
    exclude_wins: bool = True,
) -> dict[str, str]:
    text = text_for_screening(row)
    matched_exclude = matched_terms(text, exclude_terms)
    matched_include = matched_terms(text, include_terms)

    if matched_exclude and (exclude_wins or not matched_include):
        decision = "exclude_or_route_elsewhere"
        reason = (
            f"Matched exclude term(s): {', '.join(matched_exclude)}; "
            f"matched include term(s): {', '.join(matched_include) if matched_include else 'none'}"
        )
    elif matched_include:
        decision = "include"
        reason = f"Matched include term(s): {', '.join(matched_include)}"
    else:
        decision = "needs_decision"
        reason = "No clear include or exclude term matched."

    return {
        "scope_decision": decision,
        "scope_reason": reason,
        "scope_matched_include_terms": "; ".join(matched_include),
        "scope_matched_exclude_terms": "; ".join(matched_exclude),
    }


def read_rows(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        return list(reader.fieldnames or []), list(reader)


def output_columns(input_columns: list[str]) -> list[str]:
    columns = list(input_columns)
    for column in SCOPE_COLUMNS:
        if column not in columns:
            columns.append(column)
    return columns


def write_rows(
    path: Path,
    rows: list[dict[str, str]],
    fieldnames: list[str],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)

    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({column: row.get(column, "") for column in fieldnames})


def settings_from_contract(topic_contract_path: Path) -> dict[str, Any]:
    contract = load_topic_contract(topic_contract_path)
    return rule_based_screening_from_contract(contract)


def screen_rows(
    rows: list[dict[str, str]],
    include_terms: list[str],
    exclude_terms: list[str],
    exclude_wins: bool,
) -> list[dict[str, str]]:
    screened_rows = []
    for row in rows:
        screened_rows.append(
            {
                **row,
                **decide_scope(row, include_terms, exclude_terms, exclude_wins),
            }
        )
    return screened_rows


def run(
    input_path: Path,
    output_path: Path,
    topic_contract_path: Path,
) -> StepResult:
    fieldnames, rows = read_rows(input_path)
    settings = settings_from_contract(topic_contract_path)
    screened_rows = screen_rows(
        rows,
        list(settings["include_terms"]),
        list(settings["exclude_terms"]),
        bool(settings["exclude_wins"]),
    )
    write_rows(output_path, screened_rows, output_columns(fieldnames))

    return StepResult(
        step_name=STEP.name,
        inputs={
            "normalized_papers_csv": input_path,
            "topic_contract_yaml": topic_contract_path,
        },
        outputs={"scope_screened_csv": output_path},
        row_counts={"papers_screened": len(screened_rows)},
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Screen papers against a topic contract scope."
    )
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
    parser.add_argument(
        "--topic-contract",
        required=True,
        help="Topic contract YAML with rule-based screening terms.",
    )
    args = parser.parse_args()

    result = run(Path(args.input), Path(args.output), Path(args.topic_contract))

    print(f"Screened {result.row_counts['papers_screened']} papers")
    print(f"Wrote {args.output}")
