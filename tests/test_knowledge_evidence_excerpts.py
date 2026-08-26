from __future__ import annotations

from pathlib import Path

import pytest

from ad_lit_pipeline.core.errors import ValidationError
from ad_lit_pipeline.io.csv_io import write_csv_rows
from ad_lit_pipeline.io.jsonl_io import read_jsonl_objects
from ad_lit_pipeline.steps.knowledge.export_evidence_excerpts import (
    excerpt_records_from_text,
    export_evidence_excerpts,
    run,
)


def full_text() -> str:
    return """
Abstract
This paper studies early detection.

Results
The method increased detection accuracy in the evaluated cohort.

Conclusion
The evidence suggests early promise, but more validation is needed.
""".strip()


def paper_row(text_path: Path) -> dict[str, str]:
    return {
        "paper_id": "paper_1",
        "title": "Example paper",
        "full_text_text_path": str(text_path),
    }


def test_excerpt_records_from_text_creates_section_records() -> None:
    excerpts = excerpt_records_from_text("paper_1", full_text(), max_chars=1000)

    assert len(excerpts) == 3
    assert excerpts[0]["source_id"] == "paper_1"
    assert excerpts[0]["section"] == "abstract"
    assert excerpts[0]["extraction_method"] == "full_text_section_priority"
    assert excerpts[0]["excerpt_id"].startswith("paper_1_excerpt_001_")


def test_export_evidence_excerpts_reads_full_text_path(tmp_path: Path) -> None:
    text_path = tmp_path / "paper_1.txt"
    text_path.write_text(full_text(), encoding="utf-8")

    excerpts, warnings = export_evidence_excerpts([paper_row(text_path)])

    assert warnings == []
    assert len(excerpts) == 3
    assert {excerpt["section"] for excerpt in excerpts} == {
        "abstract",
        "results",
        "conclusion",
    }


def test_export_evidence_excerpts_warns_for_missing_full_text() -> None:
    excerpts, warnings = export_evidence_excerpts(
        [{"paper_id": "paper_1", "full_text_text_path": ""}]
    )

    assert excerpts == []
    assert warnings == ["paper_1: no readable full-text path"]


def test_export_evidence_excerpts_rejects_missing_source_id() -> None:
    with pytest.raises(ValidationError, match="no source_id/paper_id"):
        export_evidence_excerpts([{"full_text_text_path": ""}])


def test_run_writes_evidence_excerpts_jsonl(tmp_path: Path) -> None:
    text_path = tmp_path / "paper_1.txt"
    input_path = tmp_path / "papers.csv"
    output_path = tmp_path / "evidence_excerpts.jsonl"
    row = paper_row(text_path)

    text_path.write_text(full_text(), encoding="utf-8")
    write_csv_rows(input_path, [row], list(row))

    result = run(input_path, output_path)
    excerpts = read_jsonl_objects(output_path)

    assert result.row_counts["evidence_excerpts"] == 3
    assert len(excerpts) == 3
    assert excerpts[0]["source_id"] == "paper_1"