from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from ad_lit_pipeline.core.step import StepResult, StepSpec
from ad_lit_pipeline.steps.collection.candidate_identity import (
    dedupe_key,
    normalize_doi,
    normalize_title,
)
from ad_lit_pipeline.topics.matching import merge_topic_matches


STEP = StepSpec(
    name="deduplicate_candidates",
    inputs=["candidate_jsonl"],
    outputs=["deduped_candidate_jsonl"],
    uses_llm=False,
    description="Deduplicate collected paper candidates.",
)


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


def merge_full_text_locations(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged = []
    seen = set()
    for row in rows:
        locations = row.get("full_text_locations")
        if not isinstance(locations, list):
            continue
        for location in locations:
            if not isinstance(location, dict):
                continue
            url = str(location.get("url") or "").strip()
            if not url or url in seen:
                continue
            seen.add(url)
            merged.append(dict(location))
    return merged


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
            duplicate_summary(row) for row in sorted_group
        ]
        merged_matches = merge_topic_matches(
            [row.get("topic_matches") for row in sorted_group]
        )
        if merged_matches:
            representative["topic_matches"] = merged_matches

        merged_full_text_locations = merge_full_text_locations(sorted_group)
        if merged_full_text_locations:
            representative["full_text_locations"] = merged_full_text_locations

        deduped.append(representative)

    return sorted(deduped, key=candidate_sort_key)


def run(input_paths: list[Path], output_path: Path) -> StepResult:
    rows = []
    for input_path in input_paths:
        rows.extend(read_jsonl(input_path))

    deduped = deduplicate(rows)
    write_jsonl(output_path, deduped)

    return StepResult(
        step_name=STEP.name,
        inputs={f"candidate_jsonl_{index}": path for index, path in enumerate(input_paths)},
        outputs={"deduped_candidate_jsonl": output_path},
        row_counts={
            "input_candidates": len(rows),
            "deduped_candidates": len(deduped),
            "duplicates_removed": len(rows) - len(deduped),
        },
    )


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

    input_paths = [Path(input_path) for input_path in args.input]
    result = run(input_paths, Path(args.output))

    print(f"Input candidates: {result.row_counts['input_candidates']}")
    print(f"Deduplicated candidates: {result.row_counts['deduped_candidates']}")
    print(f"Duplicates removed: {result.row_counts['duplicates_removed']}")
    print(f"Wrote {args.output}")
