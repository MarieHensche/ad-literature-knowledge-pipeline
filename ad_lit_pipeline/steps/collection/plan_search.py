from __future__ import annotations

import argparse
import os
from pathlib import Path
from typing import Any

from ad_lit_pipeline.core.step import StepResult, StepSpec
from ad_lit_pipeline.io.json_io import write_json
from ad_lit_pipeline.llm.client import JSONLLMClient, OpenAIResponsesClient
from ad_lit_pipeline.llm.schemas import plan_schema
from ad_lit_pipeline.llm.trace import LLMTraceWriter
from ad_lit_pipeline.prompts.render import render_plan_search_prompt
from ad_lit_pipeline.topics.contract import (
    DEFAULT_TOPIC_CONTRACT_PATH,
    collection_from_contract,
    load_topic_contract,
)


STEP = StepSpec(
    name="plan_search",
    inputs=["topic_description", "topic_contract_yaml"],
    outputs=["search_plan_json"],
    uses_llm=True,
    description="Use an LLM to plan a digital-library paper search.",
)

SYSTEM_MESSAGE = "You create careful, inspectable digital-library search plans as strict JSON."

ALL_PROVIDERS = [
    {
        "provider": "openalex",
        "best_for": "Broad scholarly search across disciplines; good default provider.",
        "search_style": "Keyword query plus API filters.",
        "supported_filters": [
            "from_publication_date",
            "to_publication_date",
            "publication_year",
            "open_access",
            "type",
            "language",
        ],
    },
    {
        "provider": "semantic_scholar",
        "best_for": "Computer science, AI, machine learning, citation-rich metadata.",
        "search_style": "Natural-language keyword query plus year/publication type filters.",
        "supported_filters": [
            "year",
            "publicationTypes",
            "venue",
            "fieldsOfStudy",
            "openAccessPdf",
        ],
    },
    {
        "provider": "europe_pmc",
        "best_for": "Biomedical, clinical, life-science, PubMed/PMC-style literature.",
        "search_style": "Boolean biomedical query syntax.",
        "supported_filters": [
            "publication_date_range",
            "open_access",
            "article_type",
            "source",
            "has_abstract",
            "has_full_text",
        ],
    },
    {
        "provider": "crossref",
        "best_for": "DOI and publisher metadata enrichment; not ideal as first discovery source.",
        "search_style": "Bibliographic metadata query plus filters.",
        "supported_filters": [
            "from_pub_date",
            "until_pub_date",
            "type",
            "has_abstract",
            "has_full_text",
        ],
    },
]


def load_dotenv(env_path: Path = Path(".env")) -> None:
    if not env_path.exists():
        return

    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())


def read_topic(args: argparse.Namespace) -> str:
    if args.topic:
        return args.topic.strip()

    if args.topic_file:
        return Path(args.topic_file).read_text(encoding="utf-8").strip()

    raise ValueError("Provide either --topic or --topic-file.")


def providers_for_contract(topic_contract: dict[str, Any]) -> list[dict[str, object]]:
    collection = collection_from_contract(topic_contract)
    allowed = set(collection["allowed_providers"])
    providers = [provider for provider in ALL_PROVIDERS if provider["provider"] in allowed]
    if not providers:
        raise ValueError("Topic contract does not enable any supported planner providers.")
    return providers


def provider_names(providers: list[dict[str, object]]) -> list[str]:
    return [str(provider["provider"]) for provider in providers]


def validate_plan(plan: dict[str, object], allowed_providers: list[str]) -> None:
    recommended = plan.get("recommended_provider")
    provider_plan = plan.get("provider_specific_plan")
    if recommended not in allowed_providers:
        raise ValueError(f"Unsupported recommended provider: {recommended}")
    if not isinstance(provider_plan, dict):
        raise ValueError("Plan must contain provider_specific_plan.")
    if provider_plan.get("provider") != recommended:
        raise ValueError("provider_specific_plan.provider must match recommended_provider.")


def call_llm(
    topic_description: str,
    max_results: int | None,
    model: str,
    providers: list[dict[str, object]],
    client: JSONLLMClient,
    trace_writer: LLMTraceWriter | None = None,
) -> tuple[dict[str, object], list[Path]]:
    prompt = render_plan_search_prompt(topic_description, providers, max_results)
    names = provider_names(providers)
    result = client.create_json(
        model=model,
        system_message=SYSTEM_MESSAGE,
        prompt=prompt,
        schema_name="digital_library_search_plan",
        schema=plan_schema(names),
        step_name=STEP.name,
        call_id="plan",
        trace_writer=trace_writer,
    )
    validate_plan(result.parsed, names)
    trace_paths = result.trace_paths.as_list() if result.trace_paths else []
    return result.parsed, trace_paths


def run(
    topic_description: str,
    output_path: Path,
    max_results: int | None,
    model: str,
    topic_contract_path: Path = DEFAULT_TOPIC_CONTRACT_PATH,
    client: JSONLLMClient | None = None,
    trace_dir: Path | None = None,
) -> StepResult:
    topic_contract = load_topic_contract(topic_contract_path)
    providers = providers_for_contract(topic_contract)
    trace_writer = LLMTraceWriter(trace_dir) if trace_dir is not None else None
    plan, trace_paths = call_llm(
        topic_description,
        max_results,
        model,
        providers,
        client or OpenAIResponsesClient(),
        trace_writer,
    )
    write_json(output_path, plan)
    return StepResult(
        step_name=STEP.name,
        inputs={"topic_contract_yaml": topic_contract_path},
        outputs={"search_plan_json": output_path},
        trace_paths=trace_paths,
        metadata={
            "recommended_provider": plan["recommended_provider"],
            "main_search_string": plan["main_search_string"],
        },
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Plan a digital-library paper search.")
    parser.add_argument("--topic", help="Topic description to search for.")
    parser.add_argument("--topic-file", help="Path to a text file containing the topic description.")
    parser.add_argument("--output", required=True, help="Output JSON search plan.")
    parser.add_argument("--max-results", type=int, default=None, help="Optional target candidate count.")
    parser.add_argument(
        "--model",
        default=None,
        help="OpenAI model. Defaults to OPENAI_MODEL or gpt-4o-mini.",
    )
    parser.add_argument(
        "--topic-contract",
        default=str(DEFAULT_TOPIC_CONTRACT_PATH),
        help="Topic contract YAML with enabled providers.",
    )
    parser.add_argument(
        "--trace-dir",
        default=None,
        help="Optional directory where prompt/response traces are written.",
    )
    args = parser.parse_args()

    load_dotenv()
    topic_description = read_topic(args)
    model = args.model or os.getenv("OPENAI_MODEL", "gpt-4o-mini")
    trace_dir = Path(args.trace_dir) if args.trace_dir else None

    result = run(
        topic_description,
        Path(args.output),
        args.max_results,
        model,
        Path(args.topic_contract),
        trace_dir=trace_dir,
    )

    print(f"Recommended provider: {result.metadata['recommended_provider']}")
    print(f"Search string: {result.metadata['main_search_string']}")
    print(f"Wrote {args.output}")
