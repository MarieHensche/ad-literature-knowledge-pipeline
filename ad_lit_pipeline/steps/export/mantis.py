from __future__ import annotations

import argparse
import csv
from pathlib import Path

from ad_lit_pipeline.core.step import StepResult, StepSpec
from ad_lit_pipeline.topics.contract import REQUIRED_TOPIC_CATEGORY_IDS


STEP = StepSpec(
    name="export_mantis",
    inputs=["extraction_filled_csv"],
    outputs=["mantis_ready_csv"],
    uses_llm=False,
    description="Export AI-tagged extraction data to a Mantis-ready CSV.",
)

CORE_COLUMNS = [
    "title",
    "categoric",
    "semantic",
    "paper_id",
    "year",
    "doi",
]

MAIN_TOPIC_CATEGORY_COLUMN = REQUIRED_TOPIC_CATEGORY_IDS[0]
RESEARCH_TARGET_COLUMN = REQUIRED_TOPIC_CATEGORY_IDS[1]
MANTIS_EXPORT_TOPIC_CATEGORIES = {"core_topic"}


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


def first_selected_value(value: str) -> str:
    return value.split(";")[0].strip() if value.strip() else ""


def selected_values(value: str) -> list[str]:
    return [item.strip() for item in value.split(";") if item.strip()]


def is_mantis_exportable(row: dict[str, str]) -> bool:
    values = selected_values(row.get(MAIN_TOPIC_CATEGORY_COLUMN, ""))
    return any(value in MANTIS_EXPORT_TOPIC_CATEGORIES for value in values)


def make_categoric(row: dict[str, str]) -> str:
    category = first_selected_value(row.get(MAIN_TOPIC_CATEGORY_COLUMN, ""))
    target = first_selected_value(row.get(RESEARCH_TARGET_COLUMN, ""))

    if category:
        return category

    if target:
        return target

    paper_id = row.get("paper_id", "<unknown>")
    raise ValueError(
        "Mantis export requires a value in "
        f"{MAIN_TOPIC_CATEGORY_COLUMN} or {RESEARCH_TARGET_COLUMN} "
        f"for paper_id={paper_id}"
    )


def validate_required_columns(fieldnames: list[str], input_path: Path) -> None:
    missing = [
        column for column in REQUIRED_TOPIC_CATEGORY_IDS if column not in fieldnames
    ]
    if missing:
        raise ValueError(
            f"Mantis export input {input_path} is missing required generic "
            f"topic column(s): {', '.join(missing)}"
        )


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


def write_rows(
    output_path: Path,
    rows: list[dict[str, str]],
    fieldnames: list[str],
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with output_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def run(input_path: Path, output_path: Path) -> StepResult:
    rows = read_rows(input_path)

    if not rows:
        raise ValueError(f"No rows found in {input_path}")

    fieldnames = list(rows[0].keys())
    validate_required_columns(fieldnames, input_path)
    tag_fields = tag_columns(fieldnames)
    output_fields = CORE_COLUMNS + tag_fields

    exportable_rows = [row for row in rows if is_mantis_exportable(row)]
    output_rows = [export_row(row, tag_fields) for row in exportable_rows]
    write_rows(output_path, output_rows, output_fields)

    return StepResult(
        step_name=STEP.name,
        inputs={"extraction_filled_csv": input_path},
        outputs={"mantis_ready_csv": output_path},
        row_counts={
            "input_rows": len(rows),
            "mantis_rows": len(output_rows),
            "skipped_not_mantis_relevant": len(rows) - len(output_rows),
        },
    )


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

    result = run(Path(args.input), Path(args.output))

    print(f"Exported {result.row_counts['mantis_rows']} Mantis rows")
    print(f"Wrote {args.output}")
