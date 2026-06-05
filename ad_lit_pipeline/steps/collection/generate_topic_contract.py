from __future__ import annotations

import argparse
import json
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
from ad_lit_pipeline.topics.contract import (
    normalize_tagging_label,
    validate_topic_contract,
)


STEP = StepSpec(
    name="generate_topic_contract",
    inputs=["topic_description", "base_topic_contract_yaml"],
    outputs=["topic_contract_yaml"],
    uses_llm=True,
    description="Generate a topic contract draft from a research question.",
)

SYSTEM_MESSAGE = "You draft configurable literature-pipeline topic contracts as strict JSON."
MAX_CONTRACT_VALIDATION_ATTEMPTS = 3

DEFAULT_BASE_CONTRACT = (
    Path(__file__).resolve().parents[3]
    / "configs"
    / "topics"
    / "topic_contract_template.yaml"
)

SUPPORTED_PROVIDERS = ["openalex"]


def prompt_with_validation_feedback(
    prompt: str,
    error: ValueError,
    best_contract: dict[str, Any] | None = None,
) -> str:
    """Append validation feedback for one LLM correction attempt."""
    feedback = (
        prompt
        + "\n\nYour previous JSON response failed validation:\n"
        + str(error)
        + "\n\nReturn a corrected complete JSON response. Before returning, "
        "check every validation path above and make sure the rejected category "
        "ids and values are gone or corrected.\n"
        "- Replace weak, meta, or generic boilerplate categories with concrete "
        "topic-specific knowledge categories that can be answered from "
        "individual papers.\n"
        "- Do not keep generic category ids such as `target_population`, "
        "`study_design`, `study_type`, or `data_source_type`. If the distinction "
        "is truly central, replace it with a review-derived category id whose "
        "words name the topic concept, setting, signal, intervention, exposure, "
        "or outcome.\n"
        "- Use compact lowercase snake_case category ids and values. Convert "
        "hyphens, spaces, slashes, punctuation, and title case; for example, "
        "`self-help_resources` must become `self_help_resources` or a more "
        "specific topic-derived value.\n"
        "- The `knowledge_goal` category must be an exhaustive root partition "
        "with role-like values, not vague benefit phrases such as "
        "`improving_x`, `enhancing_y`, or `supporting_z`."
    )
    if best_contract is None:
        return feedback

    return (
        feedback
        + "\n\nBest response so far, after deterministic snake_case cleanup:\n"
        + json.dumps(best_contract, indent=2, ensure_ascii=False)
        + "\n\nRepair this best response minimally. Keep the valid topic-specific "
        "categories and replace only the categories or values named in the "
        "validation feedback above."
    )


def validation_error_score(error: ValueError) -> int:
    """Prefer retry feedback from the smallest semantic validation failure."""
    message = str(error)
    issue_count = message.count("\n- ")
    if issue_count:
        return issue_count
    return 1000


def read_topic(args: argparse.Namespace) -> str:
    if args.topic:
        return args.topic.strip()

    if args.topic_file:
        return Path(args.topic_file).read_text(encoding="utf-8").strip()

    raise ValueError("Provide either --topic or --topic-file.")


def contract_from_model_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Convert the model-friendly categories list into contract YAML shape."""
    contract = deepcopy(payload)
    normalize_topic_structure(contract)
    tagging = contract.get("tagging")
    if not isinstance(tagging, dict):
        raise ValueError("Generated topic contract must contain tagging.")

    categories = tagging.get("categories")
    if isinstance(categories, dict):
        return contract

    if not isinstance(categories, list):
        raise ValueError("Generated tagging.categories must be a list.")

    category_map: dict[str, dict[str, Any]] = {}
    for category in categories:
        if not isinstance(category, dict):
            raise ValueError("Each generated tagging category must be an object.")

        category_id = normalize_tagging_label(str(category.get("category_id") or ""))
        if not category_id:
            raise ValueError("Each generated tagging category needs category_id.")
        if category_id in category_map:
            raise ValueError(f"Duplicate generated tagging category: {category_id}")

        values = category.get("values")
        if not isinstance(values, list):
            raise ValueError(f"Generated category {category_id} needs values.")
        normalized_values = [
            normalize_tagging_label(value) if isinstance(value, str) else value
            for value in values
        ]

        category_payload: dict[str, Any] = {
            "required": bool(category.get("required", False)),
            "values": normalized_values,
        }
        description = str(category.get("description") or "").strip()
        if description:
            category_payload["description"] = description
        selection = str(category.get("selection") or "").strip()
        if selection:
            category_payload["selection"] = selection
        applies_when = category.get("applies_when")
        if isinstance(applies_when, dict):
            normalized_applies_when = dict(applies_when)
            normalized_applies_when["category_id"] = normalize_tagging_label(
                str(applies_when.get("category_id") or "")
            )
            trigger_values = applies_when.get("values")
            if isinstance(trigger_values, list):
                normalized_applies_when["values"] = [
                    normalize_tagging_label(value) if isinstance(value, str) else value
                    for value in trigger_values
                ]
            category_payload["applies_when"] = normalized_applies_when
        category_map[category_id] = category_payload

    tagging["categories"] = category_map
    return contract


def normalize_topic_structure(contract: dict[str, Any]) -> None:
    topic_structure = contract.get("topic_structure")
    if not isinstance(topic_structure, dict):
        return

    anchor_topic_id = str(topic_structure.get("anchor_topic_id") or "").strip()
    secondary_topics = topic_structure.get("secondary_topics")
    normalized: dict[str, Any] = {}
    if isinstance(secondary_topics, dict):
        for main_topic_id, terms in secondary_topics.items():
            if not isinstance(terms, list):
                normalized[str(main_topic_id).strip()] = terms
                continue
            normalized[str(main_topic_id).strip()] = [
                str(term).strip() for term in terms if str(term).strip()
            ]
    elif isinstance(secondary_topics, list):
        for item in secondary_topics:
            if not isinstance(item, dict):
                continue
            main_topic_id = str(item.get("main_topic_id") or "").strip()
            terms = item.get("terms")
            if not main_topic_id or not isinstance(terms, list):
                continue
            normalized[main_topic_id] = [
                str(term).strip() for term in terms if str(term).strip()
            ]
    else:
        return

    if anchor_topic_id:
        normalized.pop(anchor_topic_id, None)
    topic_structure["secondary_topics"] = normalized


def call_llm(
    topic_description: str,
    base_contract: dict[str, Any],
    model: str,
    client: JSONLLMClient,
    trace_writer: LLMTraceWriter | None = None,
) -> tuple[dict[str, Any], list[Path]]:
    prompt = render_generate_topic_contract_prompt(topic_description, base_contract)
    trace_paths: list[Path] = []
    last_error: ValueError | None = None
    best_error: ValueError | None = None
    best_error_score = 1000
    best_contract: dict[str, Any] | None = None

    for attempt in range(1, MAX_CONTRACT_VALIDATION_ATTEMPTS + 1):
        attempt_prompt = (
            prompt
            if best_error is None
            else prompt_with_validation_feedback(prompt, best_error, best_contract)
        )
        call_id = "contract" if attempt == 1 else f"contract_retry_{attempt}"
        result = client.create_json(
            model=model,
            system_message=SYSTEM_MESSAGE,
            prompt=attempt_prompt,
            schema_name="topic_contract",
            schema=topic_contract_schema(
                SUPPORTED_PROVIDERS,
                min_tagging_categories=1,
            ),
            step_name=STEP.name,
            call_id=call_id,
            trace_writer=trace_writer,
        )
        if result.trace_paths:
            trace_paths.extend(result.trace_paths.as_list())

        try:
            contract: dict[str, Any] | None = None
            contract = contract_from_model_payload(result.parsed)
            validate_topic_contract(contract)
            return contract, trace_paths
        except ValueError as error:
            last_error = error
            score = validation_error_score(error)
            if score < best_error_score:
                best_error = error
                best_error_score = score
                if contract is not None:
                    best_contract = contract
            if attempt == MAX_CONTRACT_VALIDATION_ATTEMPTS:
                raise ValueError(
                    "Generated topic contract failed validation after "
                    f"{MAX_CONTRACT_VALIDATION_ATTEMPTS} attempts: "
                    f"{best_error or error}"
                ) from error

    raise ValueError("Generated topic contract failed validation.")


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
