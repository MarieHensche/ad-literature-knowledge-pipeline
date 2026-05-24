#!/usr/bin/env python3
"""Deduplicate collected paper candidates."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows = []
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            line = line.strip()
            if not line:
                continue

            row = json.loads(line)
            if not isinstance(row, dict):
                raise ValueError(f"Expected JSON object in {path}:{line_number}")

            rows.append(row)

    return rows


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)

    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def normalize_doi(value: Any) -> str:
    doi = str(value or "").strip().lower()
    doi = doi.replace("https://doi.org/", "")
    doi = doi.replace("http://doi.org/", "")
    doi = doi.replace("doi:", "")
    return doi.strip()


def normalize_title(value: Any) -> str:
    title = str(value or "").lower()
    title = re.sub(r"[^a-z0-9]+", " ", title)
    return re.sub(r"\s+", " ", title).strip()


def dedupe_key(row: dict[str, Any]) -> str:
    doi = normalize_doi(row.get("doi"))
    if doi:
        return f"doi:{doi}"

    title = normalize_title(row.get("title"))
    year = str(row.get("year") or "").strip()

    if title and year:
        return f"title_year:{title}:{year}"

    if title:
        return f"title:{title}"

    provider = row.get("provider") or "unknown"
    provider_id = row.get("provider_id") or ""
    return f"provider_id:{provider}:{provider_id}"


def duplicate_summary(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "provider": row.get("provider", ""),
        "provider_id": row.get("provider_id", ""),
        "doi": row.get("doi", ""),
        "title": row.get("title", ""),
        "year": row.get("year", ""),
        "rank": row.get("rank", ""),
        "query": row.get("query", ""),
        "retrieval_date": row.get("retrieval_date", ""),
    }


def candidate_sort_key(row: dict[str, Any]) -> tuple[int, int]:
    has_abstract = 0 if row.get("abstract") else 1
    try:
        rank = int(row.get("rank") or 999999)
    except ValueError:
        rank = 999999

    return (has_abstract, rank)


def deduplicate(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = {}

    for row in rows:
        groups.setdefault(dedupe_key(row), []).append(row)

    deduped = []

    for key, group in groups.items():
        sorted_group = sorted(group, key=candidate_sort_key)
        representative = dict(sorted_group[0])

        representative["dedupe_key"] = key
        representative["duplicate_count"] = len(group)
        representative["duplicate_provenance"] = [
            duplicate_summary(row)
            for row in sorted_group
        ]

        deduped.append(representative)

    return sorted(deduped, key=candidate_sort_key)


def main() -> None:
    parser = argparse.ArgumentParser(description="Deduplicate candidate paper metadata.")
    parser.add_argument(
        "--input",
        nargs="+",
        required=True,
        help="Input candidate JSONL file(s).",
    )
    parser.add_argument(
        "--output",
        required=True,
        help="Output deduplicated candidate JSONL.",
    )
    args = parser.parse_args()

    rows = []
    for input_path in args.input:
        rows.extend(read_jsonl(Path(input_path)))

    deduped = deduplicate(rows)
    duplicate_count = len(rows) - len(deduped)

    write_jsonl(Path(args.output), deduped)

    print(f"Input candidates: {len(rows)}")
    print(f"Deduplicated candidates: {len(deduped)}")
    print(f"Duplicates removed: {duplicate_count}")
    print(f"Wrote {args.output}")


if __name__ == "__main__":
    main()