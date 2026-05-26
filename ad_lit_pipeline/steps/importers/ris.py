from __future__ import annotations

import argparse
import csv
import re
from pathlib import Path

from ad_lit_pipeline.core.step import StepResult, StepSpec


STEP = StepSpec(
    name="import_ris",
    inputs=["ris_file"],
    outputs=["raw_papers_csv"],
    uses_llm=False,
    description="Convert RIS paper metadata into the canonical paper CSV.",
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


def clean_whitespace(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def normalize_year(value: str) -> str:
    match = re.search(r"\d{4}", value or "")
    return match.group(0) if match else ""


def normalize_doi(value: str) -> str:
    doi = clean_whitespace(value)
    doi = doi.replace("https://doi.org/", "")
    doi = doi.replace("http://doi.org/", "")
    doi = doi.replace("doi:", "")
    return doi.strip()


def parse_ris(path: Path) -> list[dict[str, list[str]]]:
    records = []
    current: dict[str, list[str]] = {}
    last_tag: str | None = None

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()

        if not line:
            continue

        match = re.match(r"^([A-Z0-9]{2})\s*-\s*(.*)$", line)

        if not match:
            if current and last_tag:
                current[last_tag][-1] = clean_whitespace(
                    f"{current[last_tag][-1]} {line}"
                )
            continue

        tag, value = match.group(1), match.group(2).strip()

        if tag == "TY":
            if current:
                records.append(current)
            current = {"TY": [value]}
            last_tag = tag
            continue

        if tag == "ER":
            if current:
                records.append(current)
            current = {}
            last_tag = None
            continue

        current.setdefault(tag, []).append(value)
        last_tag = tag

    if current:
        records.append(current)

    return records


def first(record: dict[str, list[str]], tags: list[str]) -> str:
    for tag in tags:
        values = record.get(tag, [])
        for value in values:
            if clean_whitespace(value):
                return clean_whitespace(value)
    return ""


def all_values(record: dict[str, list[str]], tags: list[str]) -> list[str]:
    values = []
    for tag in tags:
        values.extend(clean_whitespace(value) for value in record.get(tag, []))
    return [value for value in values if value]


def make_paper_id(record: dict[str, list[str]], row_number: int) -> str:
    doi = normalize_doi(first(record, ["DO"]))
    if doi:
        return re.sub(r"[^A-Za-z0-9_-]+", "_", doi).strip("_").lower()

    title = first(record, ["TI", "T1", "CT"])
    words = re.findall(r"[A-Za-z0-9]+", title.lower())
    return "_".join(words[:6]) if words else f"ris_{row_number:04d}"


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


def record_to_row(
    record: dict[str, list[str]],
    row_number: int,
    seen_ids: set[str],
) -> dict[str, str]:
    paper_id = make_unique_paper_id(make_paper_id(record, row_number), seen_ids)

    title = first(record, ["TI", "T1", "CT"])
    year = normalize_year(first(record, ["PY", "Y1", "DA"]))
    doi = normalize_doi(first(record, ["DO"]))
    abstract = first(record, ["AB", "N2"])
    authors = "; ".join(all_values(record, ["AU", "A1"]))
    venue = first(record, ["JO", "JF", "JA", "T2", "BT", "PB"])
    url = first(record, ["UR", "L2"])
    full_text_path = first(record, ["L1", "L4"])
    entry_type = first(record, ["TY"])
    notes = first(record, ["N1", "M1"])

    return {
        "paper_id": paper_id,
        "title": title,
        "year": year,
        "doi": doi,
        "abstract": abstract,
        "authors": authors,
        "venue": venue,
        "url": url,
        "source": f"ris:{entry_type}" if entry_type else "ris",
        "full_text_path": full_text_path if full_text_path.lower().endswith(".pdf") else "",
        "notes": notes or f"ris_row={row_number}",
    }


def write_rows(output_path: Path, rows: list[dict[str, str]]) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with output_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=OUTPUT_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)


def run(input_path: Path, output_path: Path) -> StepResult:
    records = parse_ris(input_path)
    seen_ids: set[str] = set()

    rows = [
        record_to_row(record, index, seen_ids)
        for index, record in enumerate(records, start=1)
    ]

    write_rows(output_path, rows)

    missing_abstracts = sum(1 for row in rows if not row["abstract"])
    return StepResult(
        step_name=STEP.name,
        inputs={"ris_file": input_path},
        outputs={"raw_papers_csv": output_path},
        row_counts={"papers": len(rows), "missing_abstracts": missing_abstracts},
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Convert RIS metadata into canonical paper CSV."
    )
    parser.add_argument("--input", required=True, help="Input .ris file.")
    parser.add_argument("--output", required=True, help="Output canonical paper CSV.")
    args = parser.parse_args()

    input_path = Path(args.input)
    output_path = Path(args.output)

    result = run(input_path, output_path)

    print(f"Imported RIS records: {result.row_counts['papers']}")
    print(f"Rows missing abstracts: {result.row_counts['missing_abstracts']}")
    print(f"Wrote {output_path}")


if __name__ == "__main__":
    main()
