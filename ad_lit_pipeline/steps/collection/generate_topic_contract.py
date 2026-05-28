from __future__ import annotations

import argparse
import os
from copy import deepcopy
from pathlib import Path
from typing import Any

from ad_lit_pipeline.core.env import load_dotenv
from ad_lit_pipeline.core.step import StepResult, StepSpec
from ad_lit_pipeline.io.yaml_io import read_yaml_object, write_yaml_object
from ad_lit_pipeline.llm.client import JSONLLMClient, OpenAIResponsesClient
from ad_lit_pipeline.llm.schemas import topic_contract_schema
from ad_lit_pipeline.llm.trace import LLMTraceWriter
from ad_lit_pipeline.prompts.render import render_generate_topic_contract_prompt
from ad_lit_pipeline.topics.contract import validate_topic_contract


STEP = StepSpec(
    name="generate_topic_contract",
    inputs=["topic_description", "base_topic_contract_yaml"],
    outputs=["topic_contract_yaml"],
    uses_llm=True,
    description="Generate a topic contract draft from a research question.",
)

SYSTEM_MESSAGE = "You draft configurable literature-pipeline topic contracts as strict JSON."

DEFAULT_BASE_CONTRACT = (
    Path(__file__).resolve().parents[3]
    / "configs"
    / "topics"
    / "topic_contract_template.yaml"
)

SUPPORTED_PROVIDERS = ["openalex"]

REVIEW_STATUS_CATEGORY = {
    "values": [
        "ai_tagged",
        "human_reviewed",
        "full_text_needed",
        "excluded_from_scope",
    ],
    "required": True,
}

MAIN_TOPIC_CATEGORY = {
    "values": [
        "core_topic",
        "adjacent_but_relevant",
        "out_of_scope",
        "mixed_or_unclear",
        "unclear",
    ],
    "required": True,
}


def read_topic(args: argparse.Namespace) -> str:
    if args.topic:
        return args.topic.strip()

    if args.topic_file:
        return Path(args.topic_file).read_text(encoding="utf-8").strip()

    raise ValueError("Provide either --topic or --topic-file.")


def contract_from_model_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Convert the model-friendly categories list into contract YAML shape."""
    contract = deepcopy(payload)
    tagging = contract.get("tagging")
    if not isinstance(tagging, dict):
        raise ValueError("Generated topic contract must contain tagging.")

    categories = tagging.get("categories")
    if isinstance(categories, dict):
        ensure_required_categories(contract)
        return contract

    if not isinstance(categories, list):
        raise ValueError("Generated tagging.categories must be a list.")

    category_map: dict[str, dict[str, Any]] = {}
    for category in categories:
        if not isinstance(category, dict):
            raise ValueError("Each generated tagging category must be an object.")

        category_id = str(category.get("category_id") or "").strip()
        if not category_id:
            raise ValueError("Each generated tagging category needs category_id.")
        if category_id in category_map:
            raise ValueError(f"Duplicate generated tagging category: {category_id}")

        values = category.get("values")
        if not isinstance(values, list):
            raise ValueError(f"Generated category {category_id} needs values.")

        category_payload: dict[str, Any] = {"values": values}
        if bool(category.get("required")):
            category_payload["required"] = True
        category_map[category_id] = category_payload

    tagging["categories"] = category_map
    ensure_required_categories(contract)
    return contract


def ensure_required_categories(contract: dict[str, Any]) -> None:
    tagging = contract.get("tagging")
    if not isinstance(tagging, dict):
        raise ValueError("Generated topic contract must contain tagging.")

    categories = tagging.get("categories")
    if not isinstance(categories, dict):
        raise ValueError("Generated tagging.categories must be a mapping.")

    categories["main_topic_category"] = deepcopy(MAIN_TOPIC_CATEGORY)
    categories["review_status"] = deepcopy(REVIEW_STATUS_CATEGORY)

    fallback_policy = tagging.get("fallback_policy")
    if isinstance(fallback_policy, dict):
        fallback_policy["review_status"] = "ai_tagged"


def call_llm(
    topic_description: str,
    base_contract: dict[str, Any],
    model: str,
    client: JSONLLMClient,
    trace_writer: LLMTraceWriter | None = None,
) -> tuple[dict[str, Any], list[Path]]:
    prompt = render_generate_topic_contract_prompt(topic_description, base_contract)
    result = client.create_json(
        model=model,
        system_message=SYSTEM_MESSAGE,
        prompt=prompt,
        schema_name="topic_contract",
        schema=topic_contract_schema(SUPPORTED_PROVIDERS),
        step_name=STEP.name,
        call_id="contract",
        trace_writer=trace_writer,
    )
    contract = contract_from_model_payload(result.parsed)
    validate_topic_contract(contract)
    trace_paths = result.trace_paths.as_list() if result.trace_paths else []
    return contract, trace_paths


def run(
    topic_description: str,
    output_path: Path,
    model: str,
    base_contract_path: Path = DEFAULT_BASE_CONTRACT,
    client: JSONLLMClient | None = None,
    trace_dir: Path | None = None,
    overwrite: bool = False,
) -> StepResult:
    if output_path.exists() and not overwrite:
        raise ValueError(
            f"Topic contract already exists: {output_path}. "
            "Pass --overwrite-topic-contract to replace it."
        )

    base_contract = read_yaml_object(base_contract_path)
    trace_writer = LLMTraceWriter(trace_dir) if trace_dir is not None else None
    contract, trace_paths = call_llm(
        topic_description,
        base_contract,
        model,
        client or OpenAIResponsesClient(),
        trace_writer,
    )
    write_yaml_object(output_path, contract)

    categories = contract["tagging"]["categories"]
    collection = contract["collection"]
    search_queries = collection.get("search_queries", [])
    return StepResult(
        step_name=STEP.name,
        inputs={"base_topic_contract_yaml": base_contract_path},
        outputs={"topic_contract_yaml": output_path},
        row_counts={
            "tagging_categories": len(categories),
            "search_queries": (
                len(search_queries) if isinstance(search_queries, list) else 0
            ),
        },
        trace_paths=trace_paths,
        metadata={
            "topic_id": contract["topic_id"],
            "title": contract["research_topic"]["title"],
        },
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate a topic contract YAML draft from a research question."
    )
    parser.add_argument("--topic", help="Research question or topic description.")
    parser.add_argument("--topic-file", help="Path to a text file containing the topic.")
    parser.add_argument("--output", required=True, help="Output topic contract YAML.")
    parser.add_argument(
        "--base-contract",
        default=str(DEFAULT_BASE_CONTRACT),
        help="Base topic contract template YAML.",
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
    parser.add_argument(
        "--overwrite-topic-contract",
        action="store_true",
        help="Replace the output file if it already exists.",
    )
    args = parser.parse_args()

    load_dotenv()
    topic_description = read_topic(args)
    model = args.model or os.getenv("OPENAI_MODEL", "gpt-4o-mini")
    trace_dir = Path(args.trace_dir) if args.trace_dir else None
    result = run(
        topic_description,
        Path(args.output),
        model,
        Path(args.base_contract),
        trace_dir=trace_dir,
        overwrite=args.overwrite_topic_contract,
    )

    print(f"Topic id: {result.metadata['topic_id']}")
    print(f"Title: {result.metadata['title']}")
    print(f"Tagging categories: {result.row_counts['tagging_categories']}")
    print(f"Search queries: {result.row_counts['search_queries']}")
    print(f"Wrote {args.output}")


if __name__ == "__main__":
    main()
