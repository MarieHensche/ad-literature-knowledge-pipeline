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
) -> list[dict[str, Any]]:
    draft_sections = sections_by_id(draft_payload)
    evidence_sections = sections_by_id(evidence_map)
    edited = response.get("sections")
    if not isinstance(edited, list):
        raise ValueError("Edited review response must contain sections list.")

    edited_by_id = {
        clean_text(section.get("section_id")): section
        for section in edited
        if isinstance(section, dict)
    }
    if set(edited_by_id) != set(draft_sections):
        raise ValueError(
            "Edited review response changed section ids. "
            f"Expected {sorted(draft_sections)}, got {sorted(edited_by_id)}."
        )

    validated = []
    for section_id in draft_sections:
        evidence_section = evidence_sections.get(section_id)
        if evidence_section is None:
            raise ValueError(
                f"Evidence map is missing section {section_id!r} for editing."
            )
        validated.append(
            validate_section_response(evidence_section, edited_by_id[section_id])
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
) -> tuple[list[dict[str, Any]], list[Path]]:
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
    return validate_edited_sections(
        payload_with_one_section(evidence_map, evidence_section),
        payload_with_one_section(draft_payload, draft_section),
        result.parsed,
    ), trace_paths


def edit_sections(
    evidence_map: dict[str, Any],
    draft_payload: dict[str, Any],
    model: str,
    client: JSONLLMClient,
    trace_writer: LLMTraceWriter | None = None,
) -> tuple[list[dict[str, Any]], list[Path]]:
    evidence_sections = sections_by_id(evidence_map)
    draft_sections = draft_payload.get("sections")
    if not isinstance(draft_sections, list):
        raise ValueError("Draft review sections JSON must contain sections list.")

    edited_sections = []
    trace_paths: list[Path] = []
    for draft_section in draft_sections:
        if not isinstance(draft_section, dict):
            continue
        section_id = clean_text(draft_section.get("section_id"))
        evidence_section = evidence_sections.get(section_id)
        if evidence_section is None:
            raise ValueError(
                f"Evidence map is missing section {section_id!r} for editing."
            )
        edited, paths = call_llm_for_section(
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
    return edited_sections, trace_paths


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
    sections, trace_paths = edit_sections(
        evidence_map,
        draft_payload,
        model,
        llm_client,
        trace_writer,
    )
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
