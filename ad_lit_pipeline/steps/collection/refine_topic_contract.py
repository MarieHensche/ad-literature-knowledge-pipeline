from __future__ import annotations

import argparse
import os
from pathlib import Path
from typing import Any

from ad_lit_pipeline.core.env import load_dotenv
from ad_lit_pipeline.core.step import StepResult, StepSpec
from ad_lit_pipeline.io.jsonl_io import read_jsonl_objects
from ad_lit_pipeline.io.yaml_io import write_yaml_object
from ad_lit_pipeline.llm.client import JSONLLMClient, OpenAIResponsesClient
from ad_lit_pipeline.llm.schemas import topic_contract_schema
from ad_lit_pipeline.llm.trace import LLMTraceWriter
from ad_lit_pipeline.prompts.render import render_refine_topic_contract_prompt
from ad_lit_pipeline.steps.collection.generate_topic_contract import (
    SUPPORTED_PROVIDERS,
    contract_from_model_payload,
)
from ad_lit_pipeline.topics.contract import load_topic_contract, validate_topic_contract


STEP = StepSpec(
    name="refine_topic_contract",
    inputs=["topic_description", "topic_contract_yaml", "review_overviews_jsonl"],
    outputs=["topic_contract_yaml"],
    uses_llm=True,
    description="Refine topic-contract tags from review and overview papers.",
)

SYSTEM_MESSAGE = "You refine literature-pipeline topic contracts as strict JSON."


def compact_review_overview(record: dict[str, Any]) -> dict[str, Any]:
    """Keep only prompt-useful review metadata."""
    raw = record.get("raw_record")
    open_access: object = {}
    best_oa_location: object = {}
    work_type = ""
    if isinstance(raw, dict):
        open_access = raw.get("open_access") or {}
        best_oa_location = raw.get("best_oa_location") or {}
        work_type = str(raw.get("type") or "")

    return {
        "provider_id": record.get("provider_id", ""),
        "doi": record.get("doi", ""),
        "title": record.get("title", ""),
        "year": record.get("year", ""),
        "venue": record.get("venue", ""),
        "type": work_type,
        "abstract": record.get("abstract", ""),
        "query": record.get("query", ""),
        "query_reason": record.get("query_reason", ""),
        "open_access": open_access,
        "best_oa_location": best_oa_location,
    }


def compact_review_overviews(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [compact_review_overview(record) for record in records]


def call_llm(
    topic_description: str,
    current_contract: dict[str, Any],
    review_overviews: list[dict[str, Any]],
    model: str,
    client: JSONLLMClient,
    trace_writer: LLMTraceWriter | None = None,
) -> tuple[dict[str, Any], list[Path]]:
    prompt = render_refine_topic_contract_prompt(
        topic_description,
        current_contract,
        compact_review_overviews(review_overviews),
    )
    result = client.create_json(
        model=model,
        system_message=SYSTEM_MESSAGE,
        prompt=prompt,
        schema_name="topic_contract",
        schema=topic_contract_schema(SUPPORTED_PROVIDERS),
        step_name=STEP.name,
        call_id="contract_refinement",
        trace_writer=trace_writer,
    )
    contract = contract_from_model_payload(result.parsed)
    validate_topic_contract(contract)
    trace_paths = result.trace_paths.as_list() if result.trace_paths else []
    return contract, trace_paths


def run(
    topic_description: str,
    topic_contract_path: Path,
    review_overviews_path: Path,
    model: str,
    client: JSONLLMClient | None = None,
    trace_dir: Path | None = None,
) -> StepResult:
    current_contract = load_topic_contract(topic_contract_path)
    review_overviews = read_jsonl_objects(review_overviews_path)
    warnings = []
    trace_paths: list[Path] = []

    if review_overviews:
        trace_writer = LLMTraceWriter(trace_dir) if trace_dir is not None else None
        refined_contract, trace_paths = call_llm(
            topic_description,
            current_contract,
            review_overviews,
            model,
            client or OpenAIResponsesClient(),
            trace_writer,
        )
        write_yaml_object(topic_contract_path, refined_contract)
        contract = refined_contract
    else:
        warnings.append(
            "No review/overview seed papers were available; left topic contract unchanged."
        )
        contract = current_contract

    categories = contract["tagging"]["categories"]
    return StepResult(
        step_name=STEP.name,
        inputs={
            "topic_contract_yaml": topic_contract_path,
            "review_overviews_jsonl": review_overviews_path,
        },
        outputs={"topic_contract_yaml": topic_contract_path},
        row_counts={
            "review_overviews": len(review_overviews),
            "tagging_categories": len(categories),
        },
        warnings=warnings,
        trace_paths=trace_paths,
        metadata={
            "topic_id": contract["topic_id"],
            "title": contract["research_topic"]["title"],
        },
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Refine topic-contract tags from review and overview papers."
    )
    parser.add_argument("--topic", required=True, help="Research question.")
    parser.add_argument("--topic-contract", required=True, help="Topic contract YAML.")
    parser.add_argument(
        "--review-overviews",
        required=True,
        help="Review/overview seed JSONL.",
    )
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
    args = parser.parse_args()

    load_dotenv()
    model = args.model or os.getenv("OPENAI_MODEL", "gpt-4o-mini")
    trace_dir = Path(args.trace_dir) if args.trace_dir else None
    result = run(
        args.topic,
        Path(args.topic_contract),
        Path(args.review_overviews),
        model,
        trace_dir=trace_dir,
    )

    print(f"Topic id: {result.metadata['topic_id']}")
    print(f"Title: {result.metadata['title']}")
    print(f"Review/overview seeds: {result.row_counts['review_overviews']}")
    print(f"Tagging categories: {result.row_counts['tagging_categories']}")
    print(f"Wrote {args.topic_contract}")


if __name__ == "__main__":
    main()
