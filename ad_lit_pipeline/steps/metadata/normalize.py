from __future__ import annotations

import argparse
import csv
import re
from pathlib import Path

from ad_lit_pipeline.core.step import StepResult, StepSpec


STEP = StepSpec(
    name="normalize_metadata",
    inputs=["raw_papers_csv"],
    outputs=["normalized_papers_csv"],
    uses_llm=False,
    description="Normalize raw paper metadata into the canonical paper table.",
)

REQUIRED_COLUMNS = ["paper_id", "title", "year", "doi", "abstract"]

OPTIONAL_COLUMNS = [
    "authors",
    "venue",
    "url",
    "source",
    "full_text_path",
    "full_text_availability_status",
    "full_text_availability_source",
    "full_text_url",
    "full_text_url_kind",
    "full_text_url_checked_at",
    "full_text_url_content_type",
    "full_text_license",
    "full_text_is_open_access",
    "full_text_availability_error",
    "notes",
]

OUTPUT_COLUMNS = [
    "paper_id",
    "title",
    "year",
    "doi",
    "abstract",
    *OPTIONAL_COLUMNS,
    "abstract_available",
    "full_text_available",
    "metadata_notes",
]

DERIVED_COLUMNS = [
    "abstract_available",
    "full_text_available",
    "metadata_notes",
]


def clean_whitespace(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def normalize_doi(value: str) -> str:
    doi = clean_whitespace(value)
    doi = doi.replace("https://doi.org/", "")
    doi = doi.replace("http://doi.org/", "")
    doi = doi.replace("doi:", "")
    return doi.strip()


def normalize_year(value: str) -> str:
    value = clean_whitespace(value)
    match = re.search(r"\d{4}", value)
    return match.group(0) if match else ""


def normalize_optional_fields(row: dict[str, str]) -> dict[str, str]:
    return {column: clean_whitespace(row.get(column, "")) for column in OPTIONAL_COLUMNS}


def make_paper_id(title: str, year: str, row_number: int) -> str:
    words = re.findall(r"[A-Za-z0-9]+", title.lower())
    stem = "_".join(words[:6]) if words else f"paper_{row_number:04d}"
    return f"{stem}_{year}" if year else stem


def validate_columns(fieldnames: list[str] | None) -> None:
    if fieldnames is None:
        raise ValueError("Input CSV has no header row.")

    missing = [column for column in REQUIRED_COLUMNS if column not in fieldnames]
    if missing:
        raise ValueError(f"Input CSV missing required column(s): {', '.join(missing)}")


def normalize_row(
    row: dict[str, str],
    row_number: int,
    preserved_columns: list[str] | None = None,
) -> dict[str, str]:
    title = clean_whitespace(row.get("title", ""))
    year = normalize_year(row.get("year", ""))
    doi = normalize_doi(row.get("doi", ""))
    abstract = clean_whitespace(row.get("abstract", ""))
    optional_fields = normalize_optional_fields(row)
    paper_id = clean_whitespace(row.get("paper_id", "")) or make_paper_id(
        title, year, row_number
    )

    notes = []
    if not title:
        notes.append("missing_title")
    if not year:
        notes.append("missing_year")
    if not abstract:
        notes.append("missing_abstract")
    full_text_locator = optional_fields.get("full_text_path") or optional_fields.get(
        "full_text_url"
    )
    if not full_text_locator:
        notes.append("missing_full_text_path")

    return {
        "paper_id": paper_id,
        "title": title,
        "year": year,
        "doi": doi,
        "abstract": abstract,
        **optional_fields,
        **{
            column: str(row.get(column) or "")
            for column in preserved_columns or []
        },
        "abstract_available": "yes" if abstract else "no",
        "full_text_available": "yes" if full_text_locator else "no",
        "metadata_notes": "; ".join(notes),
    }


def preserved_input_columns(fieldnames: list[str]) -> list[str]:
    canonical_columns = set(REQUIRED_COLUMNS + OPTIONAL_COLUMNS + DERIVED_COLUMNS)
    return [column for column in fieldnames if column not in canonical_columns]


def output_columns(preserved_columns: list[str]) -> list[str]:
    return [
        *REQUIRED_COLUMNS,
        *OPTIONAL_COLUMNS,
        *preserved_columns,
        *DERIVED_COLUMNS,
    ]


def read_and_normalize(
    input_path: Path,
) -> tuple[list[dict[str, str]], list[str]]:
    with input_path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        validate_columns(reader.fieldnames)
        extra_columns = preserved_input_columns(list(reader.fieldnames or []))
        rows = [
            normalize_row(row, index, extra_columns)
            for index, row in enumerate(reader, start=1)
        ]
        return rows, extra_columns


def write_rows(
    output_path: Path,
    rows: list[dict[str, str]],
    fieldnames: list[str] | None = None,
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with output_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames or OUTPUT_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)


def run(input_path: Path, output_path: Path) -> StepResult:
    rows, preserved_columns = read_and_normalize(input_path)
    write_rows(output_path, rows, output_columns(preserved_columns))
    return StepResult(
        step_name=STEP.name,
        inputs={"raw_papers_csv": input_path},
        outputs={"normalized_papers_csv": output_path},
        row_counts={"papers": len(rows)},
        metadata={"preserved_input_columns": preserved_columns},
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Normalize paper metadata.")
    parser.add_argument(
        "--input",
        default="data/raw/example_papers.csv",
        help="Raw input CSV.",
    )
    parser.add_argument(
        "--output",
        default="data/processed/example_papers_normalized.csv",
        help="Normalized output CSV.",
    )
    args = parser.parse_args()

    input_path = Path(args.input)
    output_path = Path(args.output)

    result = run(input_path, output_path)

    print(f"Normalized {result.row_counts['papers']} papers")
    print(f"Wrote {output_path}")
