from __future__ import annotations

import argparse
import re
from pathlib import Path
from typing import Any

from ad_lit_pipeline.corpus.source_types import classify_source_type
from ad_lit_pipeline.core.errors import ValidationError
from ad_lit_pipeline.core.step import StepResult, StepSpec
from ad_lit_pipeline.io.csv_io import read_csv_rows
from ad_lit_pipeline.io.jsonl_io import write_jsonl
from ad_lit_pipeline.knowledge.files import validate_sources_jsonl
from ad_lit_pipeline.knowledge.validation import validate_source


STEP = StepSpec(
    name="export_knowledge_sources",
    inputs=["scope_screened_full_text_csv"],
    outputs=["sources_jsonl"],
    uses_llm=False,
    description="Convert pipeline paper rows into knowledge-layer Source records.",
)


def clean_text(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def first_non_empty(row: dict[str, str], fields: tuple[str, ...]) -> str:
    for field in fields:
        value = clean_text(row.get(field, ""))
        if value:
            return value
    return ""


def normalize_label(value: str) -> str:
    label = clean_text(value).lower()
    label = re.sub(r"[^a-z0-9]+", "_", label)
    return label.strip("_")


def infer_source_type(row: dict[str, str]) -> str:
    """Return the compatibility label from the shared source-type classifier."""
    return classify_source_type(row).source_type


def full_text_status_from_row(row: dict[str, str]) -> str:
    explicit = first_non_empty(
        row,
        ("full_text_status", "full_text_availability_status"),
    )
    if explicit:
        return normalize_label(explicit)

    if first_non_empty(row, ("full_text_text_path", "full_text_path", "full_text_url")):
        return "available"

    return "unknown"


def collection_provenance_from_row(row: dict[str, str]) -> dict[str, str]:
    fields = (
        "source",
        "provider",
        "provider_id",
        "openalex_id",
        "query",
        "query_id",
        "query_tier",
        "source_rank",
        "candidate_rank",
        "screening_status",
        "screening_reason",
        "scope_status",
        "scope_reason",
        "title_relevance_status",
        "title_relevance_reason",
        "full_text_status",
        "full_text_source",
        "full_text_url",
        "full_text_license",
    )
    return {
        field: clean_text(row.get(field, ""))
        for field in fields
        if clean_text(row.get(field, ""))
    }


def source_record_from_row(row: dict[str, str]) -> dict[str, Any]:
    source_id = first_non_empty(row, ("source_id", "paper_id"))
    provider = first_non_empty(row, ("provider", "source_provider", "source")) or "unknown"
    provider_id = first_non_empty(
        row,
        ("provider_id", "openalex_id", "pmid", "pmcid", "doi", "paper_id", "source_id"),
    )

    return {
        "source_id": source_id,
        "title": clean_text(row.get("title", "")),
        "year": clean_text(row.get("year", "")),
        "doi": clean_text(row.get("doi", "")),
        "url": clean_text(row.get("url", "")),
        "abstract": clean_text(row.get("abstract", "")),
        "authors": clean_text(row.get("authors", "")),
        "venue": clean_text(row.get("venue", "")),
        "provider": normalize_label(provider),
        "provider_id": provider_id,
        "source_type": infer_source_type(row),
        "collection_provenance": collection_provenance_from_row(row),
        "full_text_status": full_text_status_from_row(row),
    }


def export_sources(rows: list[dict[str, str]]) -> list[dict[str, Any]]:
    sources: list[dict[str, Any]] = []

    for index, row in enumerate(rows, start=1):
        source = source_record_from_row(row)
        try:
            validate_source(source)
        except ValidationError as exc:
            raise ValidationError(f"Source row {index} is invalid: {exc}") from exc
        sources.append(source)

    return sources


def run(input_path: Path, output_path: Path) -> StepResult:
    rows = read_csv_rows(input_path)
    sources = export_sources(rows)

    write_jsonl(output_path, sources)
    validate_sources_jsonl(output_path)

    return StepResult(
        step_name=STEP.name,
        inputs={"scope_screened_full_text_csv": input_path},
        outputs={"sources_jsonl": output_path},
        row_counts={"sources": len(sources)},
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Export knowledge-layer Source records.")
    parser.add_argument("--input", required=True, help="Input paper CSV.")
    parser.add_argument("--output", required=True, help="Output sources JSONL.")
    args = parser.parse_args()

    result = run(Path(args.input), Path(args.output))

    print(f"Exported {result.row_counts['sources']} sources")
    print(f"Wrote {args.output}")


if __name__ == "__main__":
    main()
