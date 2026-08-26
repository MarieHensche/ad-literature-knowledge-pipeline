from __future__ import annotations

import argparse
import os
from pathlib import Path
from typing import Any

from ad_lit_pipeline.core.env import load_dotenv
from ad_lit_pipeline.core.step import StepResult, StepSpec
from ad_lit_pipeline.io.json_io import read_json_object, write_json
from ad_lit_pipeline.llm.client import JSONLLMClient, OpenAIResponsesClient
from ad_lit_pipeline.llm.schemas import review_sections_schema
from ad_lit_pipeline.llm.trace import LLMTraceWriter
from ad_lit_pipeline.prompts.render import render_edit_review_sections_prompt
from ad_lit_pipeline.steps.review.synthesize_sections import (
    evidence_map_with_citations,
    validate_section_response,
)


STEP = StepSpec(
    name="edit_review_sections",
    inputs=["review_evidence_map_json", "review_sections_json"],
    outputs=["review_edited_sections_json"],
    uses_llm=True,
    description="Edit literature-review sections for consistency and rigor.",
)

SYSTEM_MESSAGE = (
    "You edit scientific literature-review sections without adding new evidence."
)


class ReviewEditValidationError(ValueError):
    def __init__(
        self,
        section_id: str,
        message: str,
        response: dict[str, Any],
        evidence_section: dict[str, Any],
        draft_section: dict[str, Any],
        trace_paths: list[Path],
    ) -> None:
        super().__init__(message)
        self.section_id = section_id
        self.response = response
        self.evidence_section = evidence_section
        self.draft_section = draft_section
        self.trace_paths = trace_paths


def clean_text(value: object) -> str:
    return " ".join(str(value or "").split()).strip()


def sections_by_id(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    sections = payload.get("sections")
    if not isinstance(sections, list):
        raise ValueError("Expected sections list.")
    return {
        clean_text(section.get("section_id")): section
        for section in sections
        if isinstance(section, dict) and clean_text(section.get("section_id"))
    }


def validate_edited_sections(
    evidence_map: dict[str, Any],
    draft_payload: dict[str, Any],
    response: dict[str, Any],
    warnings: list[str] | None = None,
) -> list[dict[str, Any]]:
    draft_sections = sections_by_id(draft_payload)
    evidence_sections = sections_by_id(evidence_map)
    validation_warnings = warnings if warnings is not None else []
    edited = response.get("sections")
    if not isinstance(edited, list):
        raise ValueError("Edited review response must contain sections list.")

    edited_by_id = {
        clean_text(section.get("section_id")): section
        for section in edited
        if isinstance(section, dict)
    }
    missing_section_ids = set(draft_sections) - set(edited_by_id)
    if missing_section_ids:
        raise ValueError(
            "Edited review response omitted expected section ids. "
            f"Missing {sorted(missing_section_ids)}; got {sorted(edited_by_id)}."
        )
    extra_section_ids = set(edited_by_id) - set(draft_sections)
    if extra_section_ids:
        validation_warnings.append(
            "Dropped extra edited review section ids not requested for this "
            f"edit call: {sorted(extra_section_ids)}."
        )

    validated = []
    for section_id in draft_sections:
        evidence_section = evidence_sections.get(section_id)
        if evidence_section is None:
            raise ValueError(
                f"Evidence map is missing section {section_id!r} for editing."
            )
        validated.append(
            validate_section_response(
                evidence_section,
                edited_by_id[section_id],
                validation_warnings,
            )
        )
    return validated


def payload_with_one_section(
    payload: dict[str, Any],
    section: dict[str, Any],
) -> dict[str, Any]:
    single = dict(payload)
    single["sections"] = [section]
    return single


def call_llm_for_section(
    evidence_map: dict[str, Any],
    draft_payload: dict[str, Any],
    evidence_section: dict[str, Any],
    draft_section: dict[str, Any],
    model: str,
    client: JSONLLMClient,
    trace_writer: LLMTraceWriter | None = None,
) -> tuple[list[dict[str, Any]], list[Path], list[str]]:
    prompt = render_edit_review_sections_prompt(
        evidence_map_with_citations(
            payload_with_one_section(evidence_map, evidence_section)
        ),
        payload_with_one_section(draft_payload, draft_section),
    )
    section_id = clean_text(draft_section.get("section_id")) or "section"
    result = client.create_json(
        model=model,
        system_message=SYSTEM_MESSAGE,
        prompt=prompt,
        schema_name="review_sections",
        schema=review_sections_schema(),
        step_name=STEP.name,
        call_id=f"edit_{section_id}",
        trace_writer=trace_writer,
    )
    trace_paths = result.trace_paths.as_list() if result.trace_paths else []
    warnings: list[str] = []
    try:
        sections = validate_edited_sections(
            payload_with_one_section(evidence_map, evidence_section),
            payload_with_one_section(draft_payload, draft_section),
            result.parsed,
            warnings,
        )
    except ValueError as error:
        raise ReviewEditValidationError(
            section_id,
            str(error),
            result.parsed,
            evidence_section,
            draft_section,
            trace_paths,
        ) from error
    return sections, trace_paths, warnings


def edit_diagnostics_paths(output_path: Path) -> tuple[Path, Path]:
    stem = output_path.stem
    return (
        output_path.with_name(f"{stem}_edit_diagnostics.json"),
        output_path.with_name(f"{stem}_edit_diagnostics.md"),
    )


def clear_edit_diagnostics(output_path: Path) -> None:
    for path in edit_diagnostics_paths(output_path):
        try:
            path.unlink()
        except FileNotFoundError:
            continue


def write_edit_diagnostics(
    evidence_map_path: Path,
    review_sections_path: Path,
    output_path: Path,
    error: ReviewEditValidationError,
) -> dict[str, Path]:
    json_path, markdown_path = edit_diagnostics_paths(output_path)
    response_sections = error.response.get("sections")
    response_section_count = (
        len(response_sections) if isinstance(response_sections, list) else 0
    )
    payload = {
        "step": STEP.name,
        "failure_type": "edited_section_validation_failed",
        "validation_error": str(error),
        "failed_section_id": error.section_id,
        "review_evidence_map_json": str(evidence_map_path),
        "review_sections_json": str(review_sections_path),
        "attempted_output_json": str(output_path),
        "trace_paths": [str(path) for path in error.trace_paths],
        "response_section_count": response_section_count,
        "response": error.response,
        "draft_section": error.draft_section,
        "evidence_section_summary": {
            "section_id": error.evidence_section.get("section_id"),
            "section_type": error.evidence_section.get("section_type"),
            "paper_count": error.evidence_section.get("paper_count"),
            "paper_ids": error.evidence_section.get("paper_ids", []),
        },
    }
    write_json(json_path, payload)

    lines = [
        "# Review Edit Diagnostics",
        "",
        f"Step: `{STEP.name}`",
        f"Failed section: `{error.section_id}`",
        f"Validation error: `{error}`",
        f"Review evidence map: `{evidence_map_path}`",
        f"Draft review sections: `{review_sections_path}`",
        f"Attempted edited output: `{output_path}`",
        "",
        "## Trace Files",
        "",
    ]
    lines.extend(f"- `{path}`" for path in error.trace_paths)
    lines.extend(
        [
            "",
            "## Why This Failed",
            "",
            (
                "The editor response passed through the same strict section "
                "validator used by review synthesis. The validator rejected the "
                "edited section because it violated the section contract."
            ),
            "",
            "## Response Shape",
            "",
            f"- Returned sections: `{response_section_count}`",
            f"- Draft section id: `{error.draft_section.get('section_id', '')}`",
            f"- Evidence section type: `{error.evidence_section.get('section_type', '')}`",
            "",
        ]
    )
    markdown_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {
        "edit_diagnostics_json": json_path,
        "edit_diagnostics_md": markdown_path,
    }


def edit_sections(
    evidence_map: dict[str, Any],
    draft_payload: dict[str, Any],
    model: str,
    client: JSONLLMClient,
    trace_writer: LLMTraceWriter | None = None,
) -> tuple[list[dict[str, Any]], list[Path], list[str]]:
    evidence_sections = sections_by_id(evidence_map)
    draft_sections = draft_payload.get("sections")
    if not isinstance(draft_sections, list):
        raise ValueError("Draft review sections JSON must contain sections list.")

    edited_sections = []
    trace_paths: list[Path] = []
    warnings: list[str] = []
    for draft_section in draft_sections:
        if not isinstance(draft_section, dict):
            continue
        section_id = clean_text(draft_section.get("section_id"))
        evidence_section = evidence_sections.get(section_id)
        if evidence_section is None:
            raise ValueError(
                f"Evidence map is missing section {section_id!r} for editing."
            )
        edited, paths, section_warnings = call_llm_for_section(
            evidence_map,
            draft_payload,
            evidence_section,
            draft_section,
            model,
            client,
            trace_writer,
        )
        edited_sections.extend(edited)
        trace_paths.extend(paths)
        warnings.extend(section_warnings)
    return edited_sections, trace_paths, warnings


def run(
    evidence_map_path: Path,
    review_sections_path: Path,
    output_path: Path,
    model: str,
    client: JSONLLMClient | None = None,
    trace_dir: Path | None = None,
) -> StepResult:
    evidence_map = read_json_object(evidence_map_path)
    draft_payload = read_json_object(review_sections_path)
    llm_client = client or OpenAIResponsesClient()
    trace_writer = LLMTraceWriter(trace_dir) if trace_dir is not None else None
    try:
        sections, trace_paths, warnings = edit_sections(
            evidence_map,
            draft_payload,
            model,
            llm_client,
            trace_writer,
        )
    except ReviewEditValidationError as error:
        paths = write_edit_diagnostics(
            evidence_map_path,
            review_sections_path,
            output_path,
            error,
        )
        raise ValueError(
            f"{error} Diagnostics: {paths['edit_diagnostics_md']}"
        ) from error
    clear_edit_diagnostics(output_path)
    write_json(
        output_path,
        {
            **draft_payload,
            "source_review_sections": str(review_sections_path),
            "source_evidence_map": str(evidence_map_path),
            "sections": sections,
        },
    )
    return StepResult(
        step_name=STEP.name,
        inputs={
            "review_evidence_map_json": evidence_map_path,
            "review_sections_json": review_sections_path,
        },
        outputs={"review_edited_sections_json": output_path},
        row_counts={"review_sections": len(sections)},
        warnings=warnings,
        trace_paths=trace_paths,
    )


def main() -> None:
    load_dotenv()
    parser = argparse.ArgumentParser(
        description="Edit generated literature-review sections."
    )
    parser.add_argument("--evidence-map", required=True)
    parser.add_argument("--sections", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument(
        "--model",
        default=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
        help="OpenAI model. Defaults to OPENAI_MODEL or gpt-4o-mini.",
    )
    parser.add_argument("--trace-dir", default=None)
    args = parser.parse_args()

    run(
        Path(args.evidence_map),
        Path(args.sections),
        Path(args.output),
        args.model,
        trace_dir=Path(args.trace_dir) if args.trace_dir else None,
    )


if __name__ == "__main__":
    main()
