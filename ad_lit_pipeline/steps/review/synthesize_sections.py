from __future__ import annotations

import argparse
from difflib import get_close_matches
import os
from pathlib import Path
from typing import Any

from ad_lit_pipeline.core.env import load_dotenv
from ad_lit_pipeline.core.step import StepResult, StepSpec
from ad_lit_pipeline.io.json_io import read_json_object, write_json
from ad_lit_pipeline.llm.client import JSONLLMClient, OpenAIResponsesClient
from ad_lit_pipeline.llm.schemas import review_section_schema
from ad_lit_pipeline.llm.trace import LLMTraceWriter
from ad_lit_pipeline.prompts.render import render_synthesize_review_section_prompt
from ad_lit_pipeline.steps.review.citations import enrich_paper_citations


STEP = StepSpec(
    name="synthesize_review_sections",
    inputs=["review_evidence_map_json"],
    outputs=["review_sections_json"],
    uses_llm=True,
    description="Draft literature-review sections from evidence packets.",
)

SYSTEM_MESSAGE = (
    "You write grounded scientific literature-review sections from structured "
    "evidence packets."
)


def sections_from_evidence_map(evidence_map: dict[str, Any]) -> list[dict[str, Any]]:
    sections = evidence_map.get("sections")
    if not isinstance(sections, list):
        raise ValueError("review_evidence_map JSON must contain sections list.")
    return [section for section in sections if isinstance(section, dict)]


def allowed_paper_ids(section: dict[str, Any]) -> set[str]:
    paper_ids = section.get("paper_ids", [])
    if not isinstance(paper_ids, list):
        return set()
    return {str(paper_id) for paper_id in paper_ids if str(paper_id).strip()}


def resolve_paper_id(paper_id: object, known_paper_ids: set[str]) -> str:
    raw_id = str(paper_id or "").strip()
    if raw_id in known_paper_ids:
        return raw_id
    if not raw_id:
        return ""

    matches = get_close_matches(raw_id, sorted(known_paper_ids), n=2, cutoff=0.94)
    if len(matches) == 1:
        return matches[0]
    return raw_id


def validate_section_response(
    section: dict[str, Any],
    response: dict[str, Any],
) -> dict[str, Any]:
    section_id = str(section.get("section_id") or "")
    if response.get("section_id") != section_id:
        raise ValueError(
            "Review section response used wrong section_id: "
            f"{response.get('section_id')!r}, expected {section_id!r}."
        )

    known_paper_ids = allowed_paper_ids(section)
    cited_paper_ids = response.get("cited_paper_ids")
    if not isinstance(cited_paper_ids, list):
        raise ValueError("cited_paper_ids must be a list.")
    repaired_cited_ids = []
    for paper_id in cited_paper_ids:
        resolved_id = resolve_paper_id(paper_id, known_paper_ids)
        if resolved_id not in known_paper_ids:
            raise ValueError(
                f"cited_paper_ids references paper_id {paper_id!r}, which is "
                f"not present in section {section_id!r}."
            )
        if resolved_id not in repaired_cited_ids:
            repaired_cited_ids.append(resolved_id)
    response["cited_paper_ids"] = repaired_cited_ids

    for group_name in ["citation_support", "quote_uses"]:
        group = response.get(group_name)
        if not isinstance(group, list):
            raise ValueError(f"{group_name} must be a list.")
        for item in group:
            if not isinstance(item, dict):
                raise ValueError(f"{group_name} items must be objects.")
            paper_id = str(item.get("paper_id") or "")
            resolved_id = resolve_paper_id(paper_id, known_paper_ids)
            if not resolved_id or resolved_id not in known_paper_ids:
                raise ValueError(
                    f"{group_name} references paper_id {paper_id!r}, which is "
                    f"not present in section {section_id!r}."
                )
            item["paper_id"] = resolved_id
            if resolved_id not in response["cited_paper_ids"]:
                response["cited_paper_ids"].append(resolved_id)

    return response


def call_llm(
    evidence_map: dict[str, Any],
    section: dict[str, Any],
    model: str,
    client: JSONLLMClient,
    trace_writer: LLMTraceWriter | None = None,
) -> tuple[dict[str, Any], list[Path]]:
    prompt = render_synthesize_review_section_prompt(
        evidence_map_with_citations(evidence_map),
        section_with_citations(evidence_map, section),
    )
    section_id = str(section.get("section_id") or "section")
    result = client.create_json(
        model=model,
        system_message=SYSTEM_MESSAGE,
        prompt=prompt,
        schema_name="review_section",
        schema=review_section_schema(),
        step_name=STEP.name,
        call_id=section_id,
        trace_writer=trace_writer,
    )
    trace_paths = result.trace_paths.as_list() if result.trace_paths else []
    return validate_section_response(section, result.parsed), trace_paths


def paper_lookup(evidence_map: dict[str, Any]) -> dict[str, dict[str, Any]]:
    papers = evidence_map.get("papers", [])
    if not isinstance(papers, list):
        return {}
    return {
        str(paper.get("paper_id")): enrich_paper_citations(paper)
        for paper in papers
        if isinstance(paper, dict) and paper.get("paper_id")
    }


def evidence_map_with_citations(evidence_map: dict[str, Any]) -> dict[str, Any]:
    enriched = dict(evidence_map)
    enriched["papers"] = list(paper_lookup(evidence_map).values())
    return enriched


def section_with_citations(
    evidence_map: dict[str, Any],
    section: dict[str, Any],
) -> dict[str, Any]:
    lookup = paper_lookup(evidence_map)
    enriched = dict(section)
    enriched["citation_papers"] = [
        lookup[paper_id]
        for paper_id in section.get("paper_ids", [])
        if paper_id in lookup and lookup[paper_id].get("citation_metadata_complete")
    ]
    return enriched


def synthesize_review_sections(
    evidence_map: dict[str, Any],
    model: str,
    client: JSONLLMClient,
    trace_writer: LLMTraceWriter | None = None,
) -> tuple[list[dict[str, Any]], list[Path], list[str]]:
    drafted_sections = []
    trace_paths: list[Path] = []
    warnings = []
    for section in sections_from_evidence_map(evidence_map):
        section_id = str(section.get("section_id") or "")
        if not allowed_paper_ids(section):
            warnings.append(f"Skipped review section {section_id!r}: no papers.")
            continue
        drafted, paths = call_llm(
            evidence_map,
            section,
            model,
            client,
            trace_writer,
        )
        drafted_sections.append(drafted)
        trace_paths.extend(paths)
    return drafted_sections, trace_paths, warnings


def run(
    evidence_map_path: Path,
    output_path: Path,
    model: str,
    client: JSONLLMClient | None = None,
    trace_dir: Path | None = None,
) -> StepResult:
    evidence_map = read_json_object(evidence_map_path)
    llm_client = client or OpenAIResponsesClient()
    trace_writer = LLMTraceWriter(trace_dir) if trace_dir is not None else None
    sections, trace_paths, warnings = synthesize_review_sections(
        evidence_map,
        model,
        llm_client,
        trace_writer,
    )
    write_json(
        output_path,
        {
            "source_evidence_map": str(evidence_map_path),
            "research_topic": evidence_map.get("research_topic", {}),
            "scope": evidence_map.get("scope", {}),
            "collection": evidence_map.get("collection", {}),
            "topic_structure": evidence_map.get("topic_structure", {}),
            "overview": evidence_map.get("overview", {}),
            "quality": evidence_map.get("quality", {}),
            "sections": sections,
            "papers": list(paper_lookup(evidence_map).values()),
        },
    )
    return StepResult(
        step_name=STEP.name,
        inputs={"review_evidence_map_json": evidence_map_path},
        outputs={"review_sections_json": output_path},
        row_counts={
            "review_evidence_sections": len(sections_from_evidence_map(evidence_map)),
            "review_sections": len(sections),
        },
        warnings=warnings,
        trace_paths=trace_paths,
    )


def main() -> None:
    load_dotenv()
    parser = argparse.ArgumentParser(
        description="Synthesize literature-review sections from an evidence map."
    )
    parser.add_argument("--evidence-map", required=True)
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
        Path(args.output),
        args.model,
        trace_dir=Path(args.trace_dir) if args.trace_dir else None,
    )


if __name__ == "__main__":
    main()
