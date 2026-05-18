#!/usr/bin/env python3
"""Normalize raw paper metadata into a canonical paper table."""

from __future__ import annotations

import argparse
import csv
import re
from pathlib import Path


REQUIRED_COLUMNS = ["paper_id", "title", "year", "doi", "abstract"]

OUTPUT_COLUMNS = [
    "paper_id",
    "title",
    "year",
    "doi",
    "abstract",
    "abstract_available",
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


def normalize_row(row: dict[str, str], row_number: int) -> dict[str, str]:
    title = clean_whitespace(row.get("title", ""))
    year = normalize_year(row.get("year", ""))
    doi = normalize_doi(row.get("doi", ""))
    abstract = clean_whitespace(row.get("abstract", ""))
    paper_id = clean_whitespace(row.get("paper_id", "")) or make_paper_id(title, year, row_number)

    notes = []
    if not title:
        notes.append("missing_title")
    if not year:
        notes.append("missing_year")
    if not abstract:
        notes.append("missing_abstract")

    return {
        "paper_id": paper_id,
        "title": title,
        "year": year,
        "doi": doi,
        "abstract": abstract,
        "abstract_available": "yes" if abstract else "no",
        "metadata_notes": "; ".join(notes),
    }


def read_and_normalize(input_path: Path) -> list[dict[str, str]]:
    with input_path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        validate_columns(reader.fieldnames)
        return [normalize_row(row, index) for index, row in enumerate(reader, start=1)]


def write_rows(output_path: Path, rows: list[dict[str, str]]) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with output_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=OUTPUT_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)


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

    rows = read_and_normalize(input_path)
    write_rows(output_path, rows)

    print(f"Normalized {len(rows)} papers")
    print(f"Wrote {output_path}")


if __name__ == "__main__":
    main()