from __future__ import annotations

from pathlib import Path

import pytest

from ad_lit_pipeline.core.errors import ValidationError
from ad_lit_pipeline.io.csv_io import write_csv_rows
from ad_lit_pipeline.io.jsonl_io import read_jsonl_objects
from ad_lit_pipeline.steps.knowledge.export_sources import (
    export_sources,
    run,
    source_record_from_row,
)


def paper_row() -> dict[str, str]:
    return {
        "paper_id": "paper_1",
        "title": "Example early detection study",
        "year": "2024",
        "doi": "10.123/example",
        "url": "https://example.org/paper",
        "abstract": "This paper reports an example result.",
        "authors": "Example Author",
        "venue": "Example Journal",
        "source": "openalex",
        "full_text_status": "available",
        "full_text_text_path": "/tmp/example.txt",
        "query": "early detection",
        "query_tier": "0",
        "title_relevance_status": "included",
    }


def test_source_record_from_row_reuses_existing_metadata() -> None:
    source = source_record_from_row(paper_row())

    assert source["source_id"] == "paper_1"
    assert source["title"] == "Example early detection study"
    assert source["provider"] == "openalex"
    assert source["provider_id"] == "10.123/example"
    assert source["source_type"] == "primary_study"
    assert source["full_text_status"] == "available"
    assert source["collection_provenance"]["query"] == "early detection"


def test_export_sources_validates_rows() -> None:
    sources = export_sources([paper_row()])

    assert len(sources) == 1
    assert sources[0]["source_id"] == "paper_1"


def test_export_sources_rejects_missing_title() -> None:
    row = paper_row()
    row["title"] = ""

    with pytest.raises(ValidationError, match="Source row 1"):
        export_sources([row])


def test_run_writes_sources_jsonl(tmp_path: Path) -> None:
    input_path = tmp_path / "papers.csv"
    output_path = tmp_path / "sources.jsonl"
    row = paper_row()

    write_csv_rows(input_path, [row], list(row))

    result = run(input_path, output_path)
    sources = read_jsonl_objects(output_path)

    assert result.row_counts["sources"] == 1
    assert sources[0]["source_id"] == "paper_1"
    assert sources[0]["collection_provenance"]["query_tier"] == "0"