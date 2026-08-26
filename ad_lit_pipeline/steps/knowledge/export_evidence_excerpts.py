from __future__ import annotations

import argparse
import hashlib
from pathlib import Path
from typing import Any

from ad_lit_pipeline.core.errors import ValidationError
from ad_lit_pipeline.core.step import StepResult, StepSpec
from ad_lit_pipeline.io.csv_io import read_csv_rows
from ad_lit_pipeline.io.jsonl_io import write_jsonl
from ad_lit_pipeline.knowledge.files import validate_evidence_excerpts_jsonl
from ad_lit_pipeline.knowledge.validation import validate_evidence_excerpt
from ad_lit_pipeline.steps.full_text.evidence import (
    DEFAULT_MAX_EVIDENCE_CHARS,
    prioritized_sections,
)


STEP = StepSpec(
    name="export_knowledge_evidence_excerpts",
    inputs=["scope_screened_full_text_csv"],
    outputs=["evidence_excerpts_jsonl"],
    uses_llm=False,
    description="Convert prepared full text into knowledge-layer EvidenceExcerpt records.",
)


def clean_text(value: object) -> str:
    return str(value or "").strip()


def source_id_from_row(row: dict[str, str]) -> str:
    return clean_text(row.get("source_id") or row.get("paper_id"))


def full_text_path_from_row(row: dict[str, str]) -> Path | None:
    value = clean_text(row.get("full_text_text_path") or row.get("full_text_path"))
    if not value:
        return None

    path = Path(value).expanduser()
    return path if path.exists() else None


def stable_excerpt_id(source_id: str, section: str, position: int, text: str) -> str:
    digest = hashlib.sha1(text.encode("utf-8")).hexdigest()[:12]
    return f"{source_id}_excerpt_{position:03d}_{section}_{digest}"


def excerpt_records_from_text(
    source_id: str,
    text: str,
    *,
    max_chars: int = DEFAULT_MAX_EVIDENCE_CHARS,
) -> list[dict[str, Any]]:
    """Create bounded EvidenceExcerpt records from one source's full text."""
    excerpts: list[dict[str, Any]] = []
    used_chars = 0

    for section_key, heading, body in prioritized_sections(text):
        body = body.strip()
        if not body:
            continue

        remaining = max_chars - used_chars
        if remaining <= 0:
            break

        if len(body) > remaining:
            body = body[:remaining].rsplit(" ", 1)[0].strip()

        if not body:
            break

        position = len(excerpts) + 1
        excerpt = {
            "excerpt_id": stable_excerpt_id(source_id, section_key, position, body),
            "source_id": source_id,
            "text": body,
            "section": section_key,
            "location": heading,
            "extraction_method": "full_text_section_priority",
        }
        validate_evidence_excerpt(excerpt)
        excerpts.append(excerpt)
        used_chars += len(body)

    return excerpts


def export_evidence_excerpts(
    rows: list[dict[str, str]],
    *,
    max_chars_per_source: int = DEFAULT_MAX_EVIDENCE_CHARS,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Convert paper rows with full-text paths into EvidenceExcerpt records."""
    excerpts: list[dict[str, Any]] = []
    warnings: list[str] = []

    for index, row in enumerate(rows, start=1):
        source_id = source_id_from_row(row)
        if not source_id:
            raise ValidationError(f"Evidence excerpt row {index} has no source_id/paper_id.")

        path = full_text_path_from_row(row)
        if path is None:
            warnings.append(f"{source_id}: no readable full-text path")
            continue

        text = path.read_text(encoding="utf-8")
        source_excerpts = excerpt_records_from_text(
            source_id,
            text,
            max_chars=max_chars_per_source,
        )
        if not source_excerpts:
            warnings.append(f"{source_id}: no usable full-text evidence")
            continue

        excerpts.extend(source_excerpts)

    return excerpts, warnings


def run(input_path: Path, output_path: Path) -> StepResult:
    rows = read_csv_rows(input_path)
    excerpts, warnings = export_evidence_excerpts(rows)

    write_jsonl(output_path, excerpts)
    validate_evidence_excerpts_jsonl(output_path)

    return StepResult(
        step_name=STEP.name,
        inputs={"scope_screened_full_text_csv": input_path},
        outputs={"evidence_excerpts_jsonl": output_path},
        row_counts={"evidence_excerpts": len(excerpts)},
        warnings=warnings,
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Export knowledge-layer EvidenceExcerpt records."
    )
    parser.add_argument("--input", required=True, help="Input paper CSV.")
    parser.add_argument("--output", required=True, help="Output evidence excerpts JSONL.")
    args = parser.parse_args()

    result = run(Path(args.input), Path(args.output))

    print(f"Exported {result.row_counts['evidence_excerpts']} evidence excerpts")
    print(f"Wrote {args.output}")
    for warning in result.warnings:
        print(f"Warning: {warning}")


if __name__ == "__main__":
    main()