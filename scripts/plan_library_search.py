#!/usr/bin/env python3
"""Use an LLM to plan a digital-library paper search."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from openai import OpenAI


PROVIDERS = [
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


PLAN_SCHEMA = {
    "type": "object",
    "properties": {
        "topic_description": {"type": "string"},
        "recommended_provider": {
            "type": "string",
            "enum": ["openalex", "semantic_scholar", "europe_pmc", "crossref"],
        },
        "provider_reason": {"type": "string"},
        "search_goal": {"type": "string"},
        "main_search_string": {"type": "string"},
        "alternate_search_strings": {
            "type": "array",
            "items": {"type": "string"},
        },
        "filters": {
            "type": "object",
            "properties": {
                "year_from": {"type": ["integer", "null"]},
                "year_to": {"type": ["integer", "null"]},
                "publication_types": {
                    "type": "array",
                    "items": {"type": "string"},
                },
                "open_access_only": {"type": ["boolean", "null"]},
                "has_abstract": {"type": ["boolean", "null"]},
                "has_full_text": {"type": ["boolean", "null"]},
                "language": {"type": ["string", "null"]},
                "venue_or_source": {
                    "type": "array",
                    "items": {"type": "string"},
                },
                "field_or_domain": {
                    "type": "array",
                    "items": {"type": "string"},
                },
            },
            "required": [
                "year_from",
                "year_to",
                "publication_types",
                "open_access_only",
                "has_abstract",
                "has_full_text",
                "language",
                "venue_or_source",
                "field_or_domain",
            ],
            "additionalProperties": False,
        },
        "provider_specific_plan": {
            "type": "object",
            "properties": {
                "provider": {"type": "string"},
                "query": {"type": "string"},
                "filters": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string"},
                            "value": {"type": "string"},
                            "reason": {"type": "string"},
                        },
                        "required": ["name", "value", "reason"],
                        "additionalProperties": False,
                    },
                },
                "sort": {"type": ["string", "null"]},
                "max_results_recommendation": {"type": "integer"},
            },
            "required": [
                "provider",
                "query",
                "filters",
                "sort",
                "max_results_recommendation",
            ],
            "additionalProperties": False,
        },
        "screening_notes": {"type": "string"},
        "risks_or_ambiguities": {
            "type": "array",
            "items": {"type": "string"},
        },
    },
    "required": [
        "topic_description",
        "recommended_provider",
        "provider_reason",
        "search_goal",
        "main_search_string",
        "alternate_search_strings",
        "filters",
        "provider_specific_plan",
        "screening_notes",
        "risks_or_ambiguities",
    ],
    "additionalProperties": False,
}


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


def build_prompt(topic_description: str, max_results: int | None) -> str:
    max_results_text = (
        f"The user requested about {max_results} candidates."
        if max_results
        else "No explicit max result count was provided."
    )

    return f"""
You are planning a scholarly literature search for an automated paper-collection pipeline.

User topic description:
{topic_description}

{max_results_text}

Available digital libraries:
{json.dumps(PROVIDERS, indent=2)}

Task:
Choose the best provider and create a provider-specific search plan.

Rules:
- Do not fetch papers.
- Do not invent providers.
- Prefer OpenAlex for broad cross-disciplinary topics.
- Prefer Semantic Scholar for computer science, machine learning, AI, or citation-graph-heavy topics.
- Prefer Europe PMC for biomedical, clinical, PubMed, or life-science-heavy topics.
- Prefer Crossref only when the task is mainly DOI/publisher metadata lookup.
- Extract year constraints from the topic. For example, "all papers from 2018" means year_from=2018 and year_to=2018.
- If the topic says "from 2018 to 2022", use year_from=2018 and year_to=2022.
- If the topic says "since 2020", use year_from=2020 and year_to=null.
- If no filter is mentioned, use null or empty arrays.
- Make the main search string precise but not too narrow.
- Add alternate search strings that could be tested manually.
- Provider-specific filters must use only filters supported by the chosen provider.
- The output is a plan for human inspection, not a final API URL.
""".strip()


def call_openai(topic_description: str, max_results: int | None, model: str) -> dict[str, object]:
    client = OpenAI()

    response = client.responses.create(
        model=model,
        input=[
            {
                "role": "system",
                "content": "You create careful, inspectable digital-library search plans as strict JSON.",
            },
            {
                "role": "user",
                "content": build_prompt(topic_description, max_results),
            },
        ],
        text={
            "format": {
                "type": "json_schema",
                "name": "digital_library_search_plan",
                "strict": True,
                "schema": PLAN_SCHEMA,
            }
        },
    )

    return json.loads(response.output_text)


def write_output(output_path: Path, plan: dict[str, object]) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(plan, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
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
    args = parser.parse_args()

    load_dotenv()

    topic_description = read_topic(args)
    model = args.model or os.getenv("OPENAI_MODEL", "gpt-4o-mini")

    plan = call_openai(topic_description, args.max_results, model)
    write_output(Path(args.output), plan)

    print(f"Recommended provider: {plan['recommended_provider']}")
    print(f"Search string: {plan['main_search_string']}")
    print(f"Wrote {args.output}")


if __name__ == "__main__":
    main()