from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from ad_lit_pipeline.core.step import StepResult, StepSpec
from ad_lit_pipeline.io.jsonl_io import write_jsonl
from ad_lit_pipeline.providers.base import CandidateProvider
from ad_lit_pipeline.providers.openalex import OpenAlexProvider
from ad_lit_pipeline.topics.contract import collection_from_contract, load_topic_contract


STEP = StepSpec(
    name="fetch_review_overviews",
    inputs=["topic_contract_yaml"],
    outputs=["review_overviews_jsonl"],
    uses_llm=False,
    description="Fetch review and overview papers to seed topic-contract tags.",
)


DEFAULT_MAX_REVIEWS = 5

REVIEW_QUERY_TERMS = ("review", "overview", "survey", "meta-analysis")


def review_query_text(query: str) -> str:
    """Bias a contract query toward review and overview literature."""
    lowered = query.lower()
    if any(term in lowered for term in REVIEW_QUERY_TERMS):
        return query
    return f"{query} review overview"


def review_search_queries(collection: dict[str, Any]) -> list[dict[str, str]]:
    """Build review-oriented query variants from topic-contract search queries."""
    raw_queries = collection.get("search_queries")
    queries: list[dict[str, str]] = []
    seen: set[str] = set()

    if isinstance(raw_queries, list):
        for item in raw_queries:
            if isinstance(item, dict):
                query = str(item.get("query") or "").strip()
                reason = str(item.get("reason") or "Topic-contract search query.")
            else:
                query = str(item or "").strip()
                reason = "Topic-contract search query."

            if not query:
                continue

            review_query = review_query_text(query)
            key = review_query.lower()
            if key in seen:
                continue
            seen.add(key)
            queries.append(
                {
                    "query": review_query,
                    "reason": f"Review/overview seed based on: {reason}",
                }
            )

    return queries


def build_review_plan(topic_contract: dict[str, Any], max_results: int) -> dict[str, Any]:
    """Create an executable OpenAlex plan for review/overview seeding."""
    collection = collection_from_contract(topic_contract)
    preferred_provider = collection["preferred_provider"]
    if preferred_provider != "openalex":
        raise ValueError(
            "Review/overview scouting currently supports only the openalex provider."
        )

    queries = review_search_queries(collection)
    if not queries:
        title = topic_contract["research_topic"]["title"]
        queries = [
            {
                "query": review_query_text(str(title)),
                "reason": "Review/overview seed based on the research topic title.",
            }
        ]

    primary_query = queries[0]["query"]
    return {
        "recommended_provider": "openalex",
        "main_search_string": primary_query,
        "alternate_search_strings": [item["query"] for item in queries[1:]],
        "search_queries": queries,
        "filters": {
            "publication_types": ["review"],
            "open_access_only": True,
            "has_abstract": True,
            "has_full_text": True,
        },
        "provider_specific_plan": {
            "provider": "openalex",
            "query": primary_query,
            "filters": [
                {
                    "name": "type",
                    "value": "review",
                    "reason": "Seed only review and overview works before collection.",
                },
                {
                    "name": "open_access",
                    "value": "true",
                    "reason": "Prefer openly accessible synthesis papers.",
                },
            ],
            "sort": None,
            "max_results_recommendation": max_results,
        },
    }


def run(
    topic_contract_path: Path,
    output_path: Path,
    max_results: int = DEFAULT_MAX_REVIEWS,
    per_page: int = 10,
    mailto: str | None = None,
    sleep_seconds: float = 0.2,
    provider: CandidateProvider | None = None,
) -> StepResult:
    topic_contract = load_topic_contract(topic_contract_path)
    plan = build_review_plan(topic_contract, max_results)
    provider = provider or OpenAlexProvider()
    provider.validate_plan(plan)
    candidates = provider.fetch_candidates(
        plan=plan,
        max_results=max_results,
        per_page=per_page,
        mailto=mailto,
        sleep_seconds=sleep_seconds,
    )

    write_jsonl(output_path, candidates)
    return StepResult(
        step_name=STEP.name,
        inputs={"topic_contract_yaml": topic_contract_path},
        outputs={"review_overviews_jsonl": output_path},
        row_counts={"review_overviews": len(candidates)},
        metadata={
            "provider": provider.name,
            "search_queries": len(plan["search_queries"]),
        },
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Fetch review and overview papers for topic-contract bootstrapping."
    )
    parser.add_argument("--topic-contract", required=True, help="Input topic contract YAML.")
    parser.add_argument("--output", required=True, help="Output review-overview JSONL.")
    parser.add_argument(
        "--max-results",
        type=int,
        default=DEFAULT_MAX_REVIEWS,
        help="Maximum review/overview records to fetch.",
    )
    parser.add_argument("--per-page", type=int, default=10, help="Provider page size.")
    parser.add_argument("--mailto", default=None, help="Optional email for OpenAlex.")
    parser.add_argument("--sleep", type=float, default=0.2, help="Delay between pages.")
    args = parser.parse_args()

    result = run(
        Path(args.topic_contract),
        Path(args.output),
        args.max_results,
        args.per_page,
        args.mailto,
        args.sleep,
    )
    print(f"Fetched review/overview papers: {result.row_counts['review_overviews']}")
    print(f"Wrote {args.output}")


if __name__ == "__main__":
    main()
