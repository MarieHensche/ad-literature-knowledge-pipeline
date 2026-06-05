from __future__ import annotations

import argparse
import csv
import os
from pathlib import Path
from typing import Any

from ad_lit_pipeline.core.env import load_dotenv
from ad_lit_pipeline.core.step import StepResult, StepSpec
from ad_lit_pipeline.io.yaml_io import write_yaml_object
from ad_lit_pipeline.llm.client import JSONLLMClient, OpenAIResponsesClient
from ad_lit_pipeline.llm.schemas import topic_contract_schema
from ad_lit_pipeline.llm.trace import LLMTraceWriter
from ad_lit_pipeline.prompts.render import render_calibrate_topic_contract_prompt
from ad_lit_pipeline.steps.collection.fetch_review_overviews import meaningful_tokens
from ad_lit_pipeline.steps.collection.generate_topic_contract import (
    MAX_CONTRACT_VALIDATION_ATTEMPTS,
    SUPPORTED_PROVIDERS,
    contract_from_model_payload,
    prompt_with_validation_feedback,
)
from ad_lit_pipeline.steps.collection.refine_topic_contract import merge_refined_tagging
from ad_lit_pipeline.steps.full_text.evidence import read_text_evidence
from ad_lit_pipeline.topics.contract import (
    load_topic_contract,
    validate_generated_tagging_quality,
    validate_topic_contract,
)


STEP = StepSpec(
    name="calibrate_topic_contract",
    inputs=["scope_screened_full_text_csv", "topic_contract_yaml"],
    outputs=["topic_contract_yaml"],
    uses_llm=True,
    description="Calibrate topic-contract tags against selected primary papers.",
)

SYSTEM_MESSAGE = "You calibrate literature-pipeline topic contracts as strict JSON."
DEFAULT_MAX_PRIMARY_PAPERS = 8
MAX_PRIMARY_PAPER_EVIDENCE_CHARS = 8_000
NO_PRIMARY_FULL_TEXT_WARNING = (
    "No included primary papers had readable extracted full text; topic-contract "
    "calibration was skipped and the existing tagging ontology was left unchanged."
)

GENERIC_PRIMARY_TOPIC_TOKENS = {
    "academic",
    "adaptive",
    "affects",
    "algorithmic",
    "analyses",
    "analysis",
    "analyzing",
    "application",
    "applications",
    "approach",
    "approaches",
    "aspects",
    "artificial",
    "automated",
    "based",
    "borderline",
    "chatbot",
    "chatbots",
    "chatgpt",
    "clearly",
    "deep",
    "directly",
    "discuss",
    "effect",
    "effects",
    "evidence",
    "empirical",
    "exclude",
    "explore",
    "exploring",
    "focused",
    "generative",
    "impact",
    "impacts",
    "include",
    "implementation",
    "intelligent",
    "intelligence",
    "language",
    "large",
    "learning",
    "literature",
    "llm",
    "machine",
    "method",
    "methodologies",
    "methods",
    "meta",
    "model",
    "models",
    "outcome",
    "outcomes",
    "paper",
    "papers",
    "performance",
    "processes",
    "relevant",
    "research",
    "role",
    "review",
    "reviews",
    "smart",
    "study",
    "studies",
    "studying",
    "systematic",
    "system",
    "systems",
    "technology",
    "technologies",
    "they",
    "tool",
    "tools",
    "unrelated",
}


def read_rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def included_rows(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    return [row for row in rows if row.get("scope_decision") == "include"]


def topic_description_from_contract(topic_contract: dict[str, Any]) -> str:
    research_topic = topic_contract["research_topic"]
    return (
        f"{research_topic.get('title', '')}\n\n"
        f"{research_topic.get('description', '')}"
    ).strip()


def topic_specific_terms(topic_contract: dict[str, Any]) -> set[str]:
    texts = []
    research_topic = topic_contract.get("research_topic", {})
    if isinstance(research_topic, dict):
        texts.extend(
            str(research_topic.get(field) or "")
            for field in ["title", "description"]
        )

    topic_structure = topic_contract.get("topic_structure", {})
    main_topics = (
        topic_structure.get("main_topics")
        if isinstance(topic_structure, dict)
        else []
    )
    if isinstance(main_topics, list):
        for topic in main_topics:
            if not isinstance(topic, dict):
                continue
            texts.append(str(topic.get("label") or ""))
            terms = topic.get("terms")
            if isinstance(terms, list):
                texts.extend(str(term) for term in terms)

    scope = topic_contract.get("scope", {})
    if isinstance(scope, dict):
        for key in ["include_criteria", "boundary_rules"]:
            values = scope.get(key)
            if isinstance(values, list):
                texts.extend(str(value) for value in values)

    tokens = set()
    for text in texts:
        tokens.update(meaningful_tokens(text))
    return {
        token
        for token in tokens
        if len(token) >= 4 and token not in GENERIC_PRIMARY_TOPIC_TOKENS
    }


def paper_identity(row: dict[str, str], index: int) -> str:
    for key in ["doi", "paper_id", "title"]:
        value = str(row.get(key) or "").strip().lower()
        if value:
            return value
    return f"paper_{index}"


def full_text_evidence(row: dict[str, str]) -> str:
    return read_text_evidence(
        row.get("full_text_text_path", ""),
        max_chars=MAX_PRIMARY_PAPER_EVIDENCE_CHARS,
    )


def primary_paper_score(
    topic_contract: dict[str, Any],
    row: dict[str, str],
    evidence: str,
) -> int:
    specific_terms = topic_specific_terms(topic_contract)
    title_tokens = meaningful_tokens(row.get("title", ""))
    abstract_tokens = meaningful_tokens(row.get("abstract", ""))
    evidence_tokens = meaningful_tokens(evidence)
    return (
        len(title_tokens & specific_terms) * 10
        + len(abstract_tokens & specific_terms) * 4
        + len(evidence_tokens & specific_terms)
    )


def select_primary_papers_for_calibration(
    topic_contract: dict[str, Any],
    rows: list[dict[str, str]],
    max_papers: int,
) -> tuple[list[dict[str, str]], list[dict[str, Any]]]:
    if max_papers < 1:
        raise ValueError("max_primary_papers must be at least 1.")

    scored = []
    seen: set[str] = set()
    for index, row in enumerate(included_rows(rows), start=1):
        identity = paper_identity(row, index)
        if identity in seen:
            continue
        seen.add(identity)

        evidence = full_text_evidence(row)
        if not evidence:
            continue

        scored.append(
            (primary_paper_score(topic_contract, row, evidence), row, evidence)
        )

    scored.sort(key=lambda item: item[0], reverse=True)
    selected_rows = [row for _score, row, _evidence in scored[:max_papers]]
    compact = [
        {
            "paper_id": row.get("paper_id", "") or f"paper_{index}",
            "full_text_evidence": evidence,
        }
        for index, (_score, row, evidence) in enumerate(scored[:max_papers], start=1)
    ]
    return selected_rows, compact


def call_llm(
    topic_description: str,
    current_contract: dict[str, Any],
    primary_papers: list[dict[str, Any]],
    model: str,
    client: JSONLLMClient,
    trace_writer: LLMTraceWriter | None = None,
) -> tuple[dict[str, Any], list[Path]]:
    prompt = render_calibrate_topic_contract_prompt(
        topic_description,
        current_contract,
        primary_papers,
    )
    trace_paths: list[Path] = []
    last_error: ValueError | None = None

    for attempt in range(1, MAX_CONTRACT_VALIDATION_ATTEMPTS + 1):
        attempt_prompt = (
            prompt
            if last_error is None
            else prompt_with_validation_feedback(prompt, last_error)
        )
        call_id = (
            "contract_calibration"
            if attempt == 1
            else f"contract_calibration_retry_{attempt}"
        )
        result = client.create_json(
            model=model,
            system_message=SYSTEM_MESSAGE,
            prompt=attempt_prompt,
            schema_name="topic_contract",
            schema=topic_contract_schema(SUPPORTED_PROVIDERS),
            step_name=STEP.name,
            call_id=call_id,
            trace_writer=trace_writer,
        )
        if result.trace_paths:
            trace_paths.extend(result.trace_paths.as_list())

        try:
            proposed_contract = contract_from_model_payload(result.parsed)
            validate_topic_contract(proposed_contract)
            contract = merge_refined_tagging(current_contract, proposed_contract)
            validate_topic_contract(contract)
            validate_generated_tagging_quality(
                contract,
                label="Calibrated topic contract",
            )
            return contract, trace_paths
        except ValueError as error:
            last_error = error
            if attempt == MAX_CONTRACT_VALIDATION_ATTEMPTS:
                raise ValueError(
                    "Calibrated topic contract failed validation after "
                    f"{MAX_CONTRACT_VALIDATION_ATTEMPTS} attempts: {error}"
                ) from error

    raise ValueError("Calibrated topic contract failed validation.")


def run(
    scope_screened_full_text_csv: Path,
    topic_contract_path: Path,
    model: str,
    client: JSONLLMClient | None = None,
    trace_dir: Path | None = None,
    max_primary_papers: int = DEFAULT_MAX_PRIMARY_PAPERS,
) -> StepResult:
    current_contract = load_topic_contract(topic_contract_path)
    rows = read_rows(scope_screened_full_text_csv)
    selected_rows, compact_papers = select_primary_papers_for_calibration(
        current_contract,
        rows,
        max_primary_papers,
    )
    if not compact_papers:
        return StepResult(
            step_name=STEP.name,
            inputs={
                "scope_screened_full_text_csv": scope_screened_full_text_csv,
                "topic_contract_yaml": topic_contract_path,
            },
            outputs={"topic_contract_yaml": topic_contract_path},
            row_counts={
                "primary_papers": len(included_rows(rows)),
                "primary_full_texts_selected": 0,
                "tagging_categories": len(
                    current_contract["tagging"]["categories"]
                ),
            },
            warnings=[NO_PRIMARY_FULL_TEXT_WARNING],
            metadata={
                "topic_id": current_contract["topic_id"],
                "title": current_contract["research_topic"]["title"],
                "calibration_skipped": True,
            },
        )

    trace_writer = LLMTraceWriter(trace_dir) if trace_dir is not None else None
    calibrated_contract, trace_paths = call_llm(
        topic_description_from_contract(current_contract),
        current_contract,
        compact_papers,
        model,
        client or OpenAIResponsesClient(),
        trace_writer,
    )
    write_yaml_object(topic_contract_path, calibrated_contract)
    categories = calibrated_contract["tagging"]["categories"]

    return StepResult(
        step_name=STEP.name,
        inputs={
            "scope_screened_full_text_csv": scope_screened_full_text_csv,
            "topic_contract_yaml": topic_contract_path,
        },
        outputs={"topic_contract_yaml": topic_contract_path},
        row_counts={
            "primary_papers": len(included_rows(rows)),
            "primary_full_texts_selected": len(selected_rows),
            "tagging_categories": len(categories),
        },
        trace_paths=trace_paths,
        metadata={
            "topic_id": calibrated_contract["topic_id"],
            "title": calibrated_contract["research_topic"]["title"],
            "calibration_skipped": False,
        },
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Calibrate topic-contract tags with primary-paper full text."
    )
    parser.add_argument(
        "--papers",
        required=True,
        help="Scope-screened full-text CSV from prepare_full_text.",
    )
    parser.add_argument("--topic-contract", required=True, help="Topic contract YAML.")
    parser.add_argument(
        "--model",
        default=None,
        help="OpenAI model. Defaults to OPENAI_MODEL or gpt-4o-mini.",
    )
    parser.add_argument(
        "--trace-dir",
        default=None,
        help="Optional directory where prompt/response traces are written.",
    )
    parser.add_argument(
        "--max-primary-papers",
        type=int,
        default=DEFAULT_MAX_PRIMARY_PAPERS,
        help="Maximum included primary-paper full texts used for calibration.",
    )
    args = parser.parse_args()

    load_dotenv()
    model = args.model or os.getenv("OPENAI_MODEL", "gpt-4o-mini")
    trace_dir = Path(args.trace_dir) if args.trace_dir else None
    result = run(
        Path(args.papers),
        Path(args.topic_contract),
        model,
        trace_dir=trace_dir,
        max_primary_papers=args.max_primary_papers,
    )

    print(f"Topic id: {result.metadata['topic_id']}")
    print(f"Title: {result.metadata['title']}")
    print(
        "Selected primary-paper full texts: "
        f"{result.row_counts['primary_full_texts_selected']}"
    )
    print(f"Tagging categories: {result.row_counts['tagging_categories']}")
    print(f"Wrote {args.topic_contract}")


if __name__ == "__main__":
    main()
