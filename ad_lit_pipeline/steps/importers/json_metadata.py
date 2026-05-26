from __future__ import annotations

import argparse
import csv
import json
import re
from pathlib import Path
from typing import Any

from ad_lit_pipeline.core.step import StepResult, StepSpec


STEP = StepSpec(
    name="import_json_metadata",
    inputs=["json_metadata_file"],
    outputs=["raw_papers_csv"],
    uses_llm=False,
    description="Convert JSON or JSONL paper metadata into the canonical paper CSV.",
)

OUTPUT_COLUMNS = [
    "paper_id",
    "title",
    "year",
    "doi",
    "abstract",
    "authors",
    "venue",
    "url",
    "source",
    "full_text_path",
    "notes",
]


def clean_whitespace(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def first_value(record: dict[str, Any], keys: list[str]) -> Any:
    for key in keys:
        value = record.get(key)
        if value not in (None, ""):
            return value
    return ""


def nested_value(record: dict[str, Any], path: list[str]) -> Any:
    value: Any = record
    for key in path:
        if not isinstance(value, dict):
            return ""
        value = value.get(key)
    return value or ""


def normalize_year(value: Any) -> str:
    text = clean_whitespace(value)
    match = re.search(r"\d{4}", text)
    return match.group(0) if match else ""


def normalize_doi(value: Any) -> str:
    doi = clean_whitespace(value)
    doi = doi.replace("https://doi.org/", "")
    doi = doi.replace("http://doi.org/", "")
    doi = doi.replace("doi:", "")
    return doi.strip()


def normalize_authors(value: Any) -> str:
    if isinstance(value, str):
        return clean_whitespace(value)

    if isinstance(value, list):
        authors = []
        for item in value:
            if isinstance(item, str):
                authors.append(clean_whitespace(item))
            elif isinstance(item, dict):
                authors.append(
                    clean_whitespace(
                        item.get("name")
                        or item.get("fullName")
                        or item.get("display_name")
                        or item.get("author_name")
                    )
                )
        return "; ".join(author for author in authors if author)

    return ""


def make_paper_id(record: dict[str, Any], row_number: int) -> str:
    candidate = first_value(
        record,
        ["paper_id", "paperId", "id", "corpusId", "key", "record_id"],
    )

    if candidate:
        return re.sub(r"[^A-Za-z0-9_-]+", "_", clean_whitespace(candidate)).strip("_").lower()

    title = clean_whitespace(record.get("title"))
    words = re.findall(r"[A-Za-z0-9]+", title.lower())
    stem = "_".join(words[:6]) if words else f"json_{row_number:04d}"
    return stem


def make_unique_paper_id(paper_id: str, seen: set[str]) -> str:
    if paper_id not in seen:
        seen.add(paper_id)
        return paper_id

    counter = 2
    while f"{paper_id}_{counter}" in seen:
        counter += 1

    unique = f"{paper_id}_{counter}"
    seen.add(unique)
    return unique


def load_json_records(path: Path) -> list[dict[str, Any]]:
    text = path.read_text(encoding="utf-8").strip()

    if path.suffix.lower() == ".jsonl":
        records = [json.loads(line) for line in text.splitlines() if line.strip()]
    else:
        data = json.loads(text)

        if isinstance(data, list):
            records = data
        elif isinstance(data, dict):
            for key in ["papers", "items", "results", "records", "data", "publications"]:
                if isinstance(data.get(key), list):
                    records = data[key]
                    break
            else:
                records = [data]
        else:
            raise ValueError("JSON input must be an object, an array, or JSONL records.")

    invalid = [record for record in records if not isinstance(record, dict)]
    if invalid:
        raise ValueError("Every JSON/JSONL record must be an object.")

    return records


def record_to_row(record: dict[str, Any], row_number: int, seen_ids: set[str]) -> dict[str, str]:
    external_ids = record.get("externalIds") if isinstance(record.get("externalIds"), dict) else {}
    open_access_pdf = (
        record.get("openAccessPdf") if isinstance(record.get("openAccessPdf"), dict) else {}
    )
    publication_venue = (
        record.get("publicationVenue")
        if isinstance(record.get("publicationVenue"), dict)
        else {}
    )

    paper_id = make_unique_paper_id(make_paper_id(record, row_number), seen_ids)

    doi = first_value(record, ["doi", "DOI"])
    if not doi and isinstance(external_ids, dict):
        doi = external_ids.get("DOI") or external_ids.get("doi")

    venue = first_value(
        record,
        ["venue", "journal", "booktitle", "conference", "sourceTitle", "container_title"],
    )
    if not venue and isinstance(publication_venue, dict):
        venue = publication_venue.get("name")

    url = first_value(record, ["url", "URL", "link", "landing_page_url"])
    if not url and isinstance(open_access_pdf, dict):
        url = open_access_pdf.get("url")

    return {
        "paper_id": paper_id,
        "title": clean_whitespace(first_value(record, ["title", "name"])),
        "year": normalize_year(first_value(record, ["year", "publicationYear", "pub_year", "date"])),
        "doi": normalize_doi(doi),
        "abstract": clean_whitespace(first_value(record, ["abstract", "summary", "description"])),
        "authors": normalize_authors(first_value(record, ["authors", "author", "creators"])),
        "venue": clean_whitespace(venue),
        "url": clean_whitespace(url),
        "source": clean_whitespace(first_value(record, ["source", "database"])) or "json_metadata",
        "full_text_path": clean_whitespace(first_value(record, ["full_text_path", "pdf_path"])),
        "notes": f"json_row={row_number}",
    }


def write_rows(output_path: Path, rows: list[dict[str, str]]) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with output_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=OUTPUT_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)


def run(input_path: Path, output_path: Path) -> StepResult:
    records = load_json_records(input_path)
    seen_ids: set[str] = set()

    rows = [
        record_to_row(record, index, seen_ids)
        for index, record in enumerate(records, start=1)
    ]

    write_rows(output_path, rows)

    missing_abstracts = sum(1 for row in rows if not row["abstract"])
    return StepResult(
        step_name=STEP.name,
        inputs={"json_metadata_file": input_path},
        outputs={"raw_papers_csv": output_path},
        row_counts={"papers": len(rows), "missing_abstracts": missing_abstracts},
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Convert JSON or JSONL paper metadata to canonical CSV."
    )
    parser.add_argument("--input", required=True, help="Input .json or .jsonl metadata file.")
    parser.add_argument("--output", required=True, help="Output canonical paper CSV.")
    args = parser.parse_args()

    input_path = Path(args.input)
    output_path = Path(args.output)

    result = run(input_path, output_path)

    print(f"Imported metadata records: {result.row_counts['papers']}")
    print(f"Rows missing abstracts: {result.row_counts['missing_abstracts']}")
    print(f"Wrote {output_path}")


if __name__ == "__main__":
    main()
