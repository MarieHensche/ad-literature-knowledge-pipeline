from __future__ import annotations

import argparse
import csv
import re
from pathlib import Path

from ad_lit_pipeline.core.step import StepResult, StepSpec


STEP = StepSpec(
    name="import_bibtex",
    inputs=["bibtex_file"],
    outputs=["raw_papers_csv"],
    uses_llm=False,
    description="Convert BibTeX entries into the canonical paper CSV format.",
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

ENTRY_TYPES_TO_SKIP = {"comment", "preamble", "string"}


def clean_whitespace(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def bibtex_to_text(value: str) -> str:
    replacements = {
        r"\&": "&",
        r"\%": "%",
        r"\_": "_",
        r"\#": "#",
        r"\$": "$",
        r"\{": "{",
        r"\}": "}",
        r"~": " ",
        r"\textendash": "-",
        r"\textemdash": "-",
        "--": "-",
    }

    text = value or ""
    for old, new in replacements.items():
        text = text.replace(old, new)

    text = re.sub(r"\\[A-Za-z]+\s*", "", text)
    text = text.replace("{", "").replace("}", "")
    return clean_whitespace(text)


def find_matching_delimiter(text: str, open_index: int) -> int:
    opening = text[open_index]
    closing = "}" if opening == "{" else ")"
    depth = 0
    in_quote = False
    escaped = False

    for index in range(open_index, len(text)):
        char = text[index]

        if escaped:
            escaped = False
            continue

        if char == "\\":
            escaped = True
            continue

        if char == '"':
            in_quote = not in_quote
            continue

        if in_quote:
            continue

        if char == opening:
            depth += 1
        elif char == closing:
            depth -= 1
            if depth == 0:
                return index

    raise ValueError("Unclosed BibTeX entry.")


def split_entry_key_and_fields(body: str) -> tuple[str, str]:
    depth = 0
    in_quote = False
    escaped = False

    for index, char in enumerate(body):
        if escaped:
            escaped = False
            continue

        if char == "\\":
            escaped = True
            continue

        if char == '"':
            in_quote = not in_quote
            continue

        if in_quote:
            continue

        if char in "{(":
            depth += 1
        elif char in "})":
            depth -= 1
        elif char == "," and depth == 0:
            return body[:index].strip(), body[index + 1 :]

    return body.strip(), ""


def parse_braced_value(text: str, start: int) -> tuple[str, int]:
    end = find_matching_delimiter(text, start)
    return text[start + 1 : end], end + 1


def parse_quoted_value(text: str, start: int) -> tuple[str, int]:
    parts = []
    escaped = False

    for index in range(start + 1, len(text)):
        char = text[index]

        if escaped:
            parts.append(char)
            escaped = False
            continue

        if char == "\\":
            parts.append(char)
            escaped = True
            continue

        if char == '"':
            return "".join(parts), index + 1

        parts.append(char)

    raise ValueError("Unclosed quoted BibTeX value.")


def parse_bare_value(text: str, start: int) -> tuple[str, int]:
    parts = []
    index = start

    while index < len(text) and text[index] not in ",#":
        parts.append(text[index])
        index += 1

    return "".join(parts).strip(), index


def parse_value(text: str, start: int) -> tuple[str, int]:
    segments = []
    index = start

    while index < len(text):
        while index < len(text) and text[index].isspace():
            index += 1

        if index >= len(text) or text[index] == ",":
            break

        if text[index] == "{":
            segment, index = parse_braced_value(text, index)
        elif text[index] == '"':
            segment, index = parse_quoted_value(text, index)
        else:
            segment, index = parse_bare_value(text, index)

        segments.append(segment)

        while index < len(text) and text[index].isspace():
            index += 1

        if index < len(text) and text[index] == "#":
            index += 1
            continue

        break

    return "".join(segments), index


def parse_fields(text: str) -> dict[str, str]:
    fields = {}
    index = 0

    while index < len(text):
        while index < len(text) and (text[index].isspace() or text[index] == ","):
            index += 1

        if index >= len(text):
            break

        name_start = index
        while index < len(text) and re.match(r"[A-Za-z0-9_\-]", text[index]):
            index += 1

        name = text[name_start:index].strip().lower()
        if not name:
            index += 1
            continue

        while index < len(text) and text[index].isspace():
            index += 1

        if index >= len(text) or text[index] != "=":
            raise ValueError(f"Expected '=' after BibTeX field: {name}")

        index += 1
        value, index = parse_value(text, index)
        fields[name] = bibtex_to_text(value)

        while index < len(text) and text[index] != ",":
            index += 1

    return fields


def parse_bibtex(text: str) -> list[dict[str, object]]:
    entries = []
    index = 0

    while index < len(text):
        at_index = text.find("@", index)
        if at_index == -1:
            break

        type_start = at_index + 1
        type_end = type_start
        while type_end < len(text) and re.match(r"[A-Za-z]", text[type_end]):
            type_end += 1

        entry_type = text[type_start:type_end].lower()
        index = type_end

        while index < len(text) and text[index].isspace():
            index += 1

        if index >= len(text) or text[index] not in "{(":
            raise ValueError(f"Expected '{{' or '(' after BibTeX entry type: {entry_type}")

        end = find_matching_delimiter(text, index)
        body = text[index + 1 : end]
        index = end + 1

        if entry_type in ENTRY_TYPES_TO_SKIP:
            continue

        key, field_text = split_entry_key_and_fields(body)
        entries.append(
            {
                "entry_type": entry_type,
                "key": clean_whitespace(key),
                "fields": parse_fields(field_text),
            }
        )

    return entries


def first_available(fields: dict[str, str], names: list[str]) -> str:
    for name in names:
        value = fields.get(name, "")
        if value:
            return value
    return ""


def normalize_authors(value: str) -> str:
    authors = [
        clean_whitespace(author)
        for author in re.split(r"\s+and\s+", value or "")
        if clean_whitespace(author)
    ]
    return "; ".join(authors)


def normalize_doi(value: str) -> str:
    doi = clean_whitespace(value)
    doi = doi.replace("https://doi.org/", "")
    doi = doi.replace("http://doi.org/", "")
    doi = doi.replace("doi:", "")
    return doi.strip()


def extract_pdf_path(value: str) -> str:
    if not value:
        return ""

    candidates = re.split(r";\s*", value)
    for candidate in candidates:
        parts = [part for part in candidate.split(":") if part]
        for part in parts:
            if part.lower().endswith(".pdf"):
                return part

    return ""


def safe_paper_id(value: str, fallback: str) -> str:
    stem = re.sub(r"[^A-Za-z0-9_-]+", "_", value or "").strip("_").lower()
    return stem or fallback


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


def entry_to_row(entry: dict[str, object], row_number: int, seen_ids: set[str]) -> dict[str, str]:
    fields = entry["fields"]
    if not isinstance(fields, dict):
        raise ValueError("Parsed BibTeX entry is missing fields.")

    key = str(entry.get("key", ""))
    entry_type = str(entry.get("entry_type", ""))
    fallback_id = f"bibtex_{row_number:04d}"
    paper_id = make_unique_paper_id(safe_paper_id(key, fallback_id), seen_ids)
    venue = first_available(
        fields,
        ["journal", "journaltitle", "booktitle", "conference", "proceedings", "publisher"],
    )

    return {
        "paper_id": paper_id,
        "title": fields.get("title", ""),
        "year": first_available(fields, ["year", "date"]),
        "doi": normalize_doi(fields.get("doi", "")),
        "abstract": fields.get("abstract", ""),
        "authors": normalize_authors(fields.get("author", "")),
        "venue": venue,
        "url": first_available(fields, ["url", "link"]),
        "source": f"bibtex:{entry_type}",
        "full_text_path": extract_pdf_path(fields.get("file", "")),
        "notes": f"bibtex_key={key}" if key else "",
    }


def read_bibtex(input_path: Path) -> list[dict[str, object]]:
    return parse_bibtex(input_path.read_text(encoding="utf-8"))


def write_rows(output_path: Path, rows: list[dict[str, str]]) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with output_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=OUTPUT_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)


def run(input_path: Path, output_path: Path) -> StepResult:
    entries = read_bibtex(input_path)
    seen_ids: set[str] = set()
    rows = [
        entry_to_row(entry, index, seen_ids)
        for index, entry in enumerate(entries, start=1)
    ]

    write_rows(output_path, rows)

    missing_abstracts = sum(1 for row in rows if not row["abstract"])
    return StepResult(
        step_name=STEP.name,
        inputs={"bibtex_file": input_path},
        outputs={"raw_papers_csv": output_path},
        row_counts={"papers": len(rows), "missing_abstracts": missing_abstracts},
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Convert BibTeX entries into the canonical paper CSV format."
    )
    parser.add_argument(
        "--input",
        required=True,
        help="Input BibTeX file.",
    )
    parser.add_argument(
        "--output",
        required=True,
        help="Output canonical paper CSV.",
    )
    args = parser.parse_args()

    input_path = Path(args.input)
    output_path = Path(args.output)

    result = run(input_path, output_path)

    print(f"Imported BibTeX entries: {result.row_counts['papers']}")
    print(f"Rows missing abstracts: {result.row_counts['missing_abstracts']}")
    print(f"Wrote {output_path}")


if __name__ == "__main__":
    main()
