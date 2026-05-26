from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any

from ad_lit_pipeline.core.step import StepResult, StepSpec


STEP = StepSpec(
    name="export_included_candidates",
    inputs=["deduped_candidates_jsonl", "candidate_screening_csv"],
    outputs=["papers_csv"],
    uses_llm=False,
    description="Export included screened candidates to canonical paper CSV.",
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


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)

    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=OUTPUT_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)


def candidate_key(candidate: dict[str, Any]) -> tuple[str, str]:
    doi = str(candidate.get("doi") or "").strip().lower()
    provider_id = str(candidate.get("provider_id") or "").strip()
    return doi, provider_id


def screening_key(row: dict[str, str]) -> tuple[str, str]:
    doi = str(row.get("doi") or "").strip().lower()
    provider_id = str(row.get("provider_id") or "").strip()
    return doi, provider_id


def make_notes(candidate: dict[str, Any], screening: dict[str, str]) -> str:
    notes = [
        f"provider={candidate.get('provider', '')}",
        f"provider_id={candidate.get('provider_id', '')}",
        f"source_rank={candidate.get('rank', '')}",
        f"retrieval_date={candidate.get('retrieval_date', '')}",
        f"screening_confidence={screening.get('screening_confidence', '')}",
        f"screening_reason={screening.get('screening_reason', '')}",
    ]

    dedupe_key = candidate.get("dedupe_key")
    if dedupe_key:
        notes.append(f"dedupe_key={dedupe_key}")

    duplicate_count = candidate.get("duplicate_count")
    if duplicate_count:
        notes.append(f"duplicate_count={duplicate_count}")

    return "; ".join(str(note) for note in notes if str(note).strip())


def candidate_to_canonical_row(
    candidate: dict[str, Any],
    screening: dict[str, str],
) -> dict[str, str]:
    return {
        "paper_id": screening.get("paper_id", ""),
        "title": str(candidate.get("title") or screening.get("title") or ""),
        "year": str(candidate.get("year") or screening.get("year") or ""),
        "doi": str(candidate.get("doi") or screening.get("doi") or ""),
        "abstract": str(candidate.get("abstract") or ""),
        "authors": str(candidate.get("authors") or ""),
        "venue": str(candidate.get("venue") or ""),
        "url": str(candidate.get("url") or ""),
        "source": f"collected:{candidate.get('provider', '')}",
        "full_text_path": "",
        "notes": make_notes(candidate, screening),
    }


def export_included(
    candidates: list[dict[str, Any]],
    screening_rows: list[dict[str, str]],
) -> list[dict[str, str]]:
    candidates_by_key = {candidate_key(candidate): candidate for candidate in candidates}

    output_rows = []

    for screening in screening_rows:
        if screening.get("screening_decision") != "include":
            continue

        key = screening_key(screening)
        candidate = candidates_by_key.get(key)

        if candidate is None:
            raise ValueError(
                "Could not match included screening row to candidate: "
                f"doi={key[0]} provider_id={key[1]}"
            )

        output_rows.append(candidate_to_canonical_row(candidate, screening))

    return output_rows


def run(candidates_path: Path, screening_path: Path, output_path: Path) -> StepResult:
    candidates = read_jsonl(candidates_path)
    screening_rows = read_csv(screening_path)
    output_rows = export_included(candidates, screening_rows)
    write_csv(output_path, output_rows)

    return StepResult(
        step_name=STEP.name,
        inputs={
            "deduped_candidates_jsonl": candidates_path,
            "candidate_screening_csv": screening_path,
        },
        outputs={"papers_csv": output_path},
        row_counts={
            "screened_rows": len(screening_rows),
            "included_rows_exported": len(output_rows),
        },
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Export included screened candidates to canonical CSV."
    )
    parser.add_argument("--candidates", required=True, help="Deduplicated candidates JSONL.")
    parser.add_argument("--screening", required=True, help="Candidate screening CSV.")
    parser.add_argument("--output", required=True, help="Output canonical paper CSV.")
    args = parser.parse_args()

    result = run(Path(args.candidates), Path(args.screening), Path(args.output))

    print(f"Screened rows: {result.row_counts['screened_rows']}")
    print(f"Included rows exported: {result.row_counts['included_rows_exported']}")
    print(f"Wrote {args.output}")
