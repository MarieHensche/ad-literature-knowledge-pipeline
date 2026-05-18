#!/usr/bin/env python3
"""Export filled knowledge extraction rows into a Mantis-ready CSV."""

from __future__ import annotations

import argparse
import csv
from pathlib import Path


MANTIS_COLUMNS = [
    "title",
    "categoric",
    "semantic",
    "paper_id",
    "year",
    "doi",
    "primary_clinical_target",
    "early_detection_subtype",
    "population_scope",
    "representation_type",
    "evidence_modality_family",
    "signal_category",
    "dataset_source_type",
    "main_knowledge_claim",
    "evidence_text",
    "review_status",
    "knowledge_confidence",
]


def read_rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def build_semantic_text(row: dict[str, str]) -> str:
    parts = [
        row.get("title", ""),
        row.get("early_detection_question", ""),
        row.get("main_knowledge_claim", ""),
        row.get("evidence_text", ""),
        row.get("evidence_modality_detail", ""),
        row.get("signal_detail", ""),
    ]

    return " ".join(part.strip() for part in parts if part and part.strip())


def to_mantis_row(row: dict[str, str]) -> dict[str, str]:
    output = {column: "" for column in MANTIS_COLUMNS}

    output.update(
        {
            "title": row.get("title", ""),
            "categoric": row.get("early_detection_subtype", ""),
            "semantic": build_semantic_text(row),
            "paper_id": row.get("paper_id", ""),
            "year": row.get("year", ""),
            "doi": row.get("doi", ""),
            "primary_clinical_target": row.get("primary_clinical_target", ""),
            "early_detection_subtype": row.get("early_detection_subtype", ""),
            "population_scope": row.get("population_scope", ""),
            "representation_type": row.get("representation_type", ""),
            "evidence_modality_family": row.get("evidence_modality_family", ""),
            "signal_category": row.get("signal_category", ""),
            "dataset_source_type": row.get("dataset_source_type", ""),
            "main_knowledge_claim": row.get("main_knowledge_claim", ""),
            "evidence_text": row.get("evidence_text", ""),
            "review_status": row.get("review_status", ""),
            "knowledge_confidence": row.get("knowledge_confidence", ""),
        }
    )

    return output


def write_rows(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)

    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=MANTIS_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description="Export a Mantis-ready CSV.")
    parser.add_argument(
        "--input",
        default="data/processed/example_extraction_filled.csv",
        help="Filled extraction CSV.",
    )
    parser.add_argument(
        "--output",
        default="data/processed/example_mantis_ready.csv",
        help="Mantis-ready output CSV.",
    )
    args = parser.parse_args()

    rows = read_rows(Path(args.input))
    mantis_rows = [to_mantis_row(row) for row in rows]
    write_rows(Path(args.output), mantis_rows)

    print(f"Exported {len(mantis_rows)} Mantis rows")
    print(f"Wrote {args.output}")


if __name__ == "__main__":
    main()