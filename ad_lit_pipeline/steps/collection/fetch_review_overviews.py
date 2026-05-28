from __future__ import annotations

import argparse
import math
import re
from dataclasses import dataclass
from datetime import date
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
REVIEW_POOL_LIMIT = 100

STOPWORDS = {
    "about", "across", "after", "also", "among", "and", "are", "based",
    "application", "applications", "been", "being", "between", "both",
    "can", "could", "does", "evidence", "explores", "for", "from",
    "has", "have", "how", "impact", "into", "its", "may", "methods",
    "more", "not", "outcomes", "research", "settings", "that", "the",
    "their", "these", "this", "through", "use", "used", "using",
    "what", "when", "where", "which", "with", "within",
}

REVIEW_EVIDENCE_TERMS = (
    "systematic review",
    "scoping review",
    "rapid review",
    "umbrella review",
    "meta-analysis",
    "review",
    "overview",
    "survey",
)


@dataclass(frozen=True)
class ReviewScore:
    score: float
    cited_by_count: int
    citation_rate_per_year: float
    topic_evidence: list[str]
    reasons: list[str]


def review_pool_size(max_results: int) -> int:
    if max_results < 1:
        raise ValueError("max_results must be at least 1.")
    return min(max(max_results * 5, max_results + 10), REVIEW_POOL_LIMIT)


def normalize_text(value: object) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(value or "").lower()).strip()


def meaningful_tokens(value: object) -> set[str]:
    tokens = set()
    for token in normalize_text(value).split():
        if token not in STOPWORDS and (len(token) >= 3 or token == "ai"):
            tokens.add(token)
    return tokens


def matched_phrases(text: str, terms: list[str]) -> list[str]:
    normalized = normalize_text(text)
    matches = []
    for term in terms:
        normalized_term = normalize_text(term)
        if normalized_term and normalized_term in normalized:
            matches.append(term)
    return matches


def candidate_evidence_text(candidate: dict[str, Any]) -> str:
    return " ".join(
        str(candidate.get(field) or "")
        for field in ["title", "abstract", "venue"]
    )


def raw_record(candidate: dict[str, Any]) -> dict[str, Any]:
    raw = candidate.get("raw_record")
    return raw if isinstance(raw, dict) else {}


def int_value(value: object) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def publication_year(candidate: dict[str, Any]) -> int:
    raw = raw_record(candidate)
    return int_value(candidate.get("year") or raw.get("publication_year"))


def cited_by_count(candidate: dict[str, Any]) -> int:
    raw = raw_record(candidate)
    return int_value(candidate.get("cited_by_count") or raw.get("cited_by_count"))


def citation_rate_per_year(candidate: dict[str, Any]) -> float:
    citations = cited_by_count(candidate)
    year = publication_year(candidate)
    if not year:
        return 0.0
    age = max(1, date.today().year - year + 1)
    return citations / age


def recency_score(candidate: dict[str, Any]) -> float:
    year = publication_year(candidate)
    if not year:
        return 0.0
    age = max(0, date.today().year - year)
    if age <= 2:
        return 15.0
    if age <= 5:
        return 12.0
    if age <= 10:
        return 8.0
    if age <= 20:
        return 4.0
    return 1.0


def contract_scope_text(topic_contract: dict[str, Any]) -> str:
    scope = topic_contract.get("scope", {})
    if not isinstance(scope, dict):
        return ""
    values = []
    for key in ["include_criteria", "exclude_criteria", "boundary_rules"]:
        items = scope.get(key, [])
        if isinstance(items, list):
            values.extend(str(item) for item in items)
    return " ".join(values)


def review_score(
    topic_contract: dict[str, Any],
    candidate: dict[str, Any],
) -> ReviewScore:
    research_topic = topic_contract["research_topic"]
    rule_based = topic_contract.get("rule_based_screening", {})
    include_terms = list(rule_based.get("include_terms", []))
    exclude_terms = list(rule_based.get("exclude_terms", []))

    research_text = (
        f"{research_topic.get('title', '')} "
        f"{research_topic.get('description', '')}"
    )
    research_title = str(research_topic.get("title") or "")
    scope_text = contract_scope_text(topic_contract)
    evidence_text = candidate_evidence_text(candidate)
    candidate_tokens = meaningful_tokens(evidence_text)

    title_overlap = sorted(candidate_tokens & meaningful_tokens(research_title))
    research_overlap = sorted(candidate_tokens & meaningful_tokens(research_text))
    include_token_overlap = sorted(
        candidate_tokens & meaningful_tokens(" ".join(include_terms))
    )
    scope_overlap = sorted(candidate_tokens & meaningful_tokens(scope_text))
    include_matches = matched_phrases(evidence_text, include_terms)
    exclude_matches = matched_phrases(evidence_text, exclude_terms)
    review_matches = matched_phrases(evidence_text, list(REVIEW_EVIDENCE_TERMS))

    has_topic_anchor = bool(include_matches or include_token_overlap or title_overlap)
    topic_score = (
        len(title_overlap) * 30
        + len(include_token_overlap) * 18
        + len(research_overlap) * 6
        + len(scope_overlap) * 2
        + min(180, len(include_matches) * 60)
        - len(exclude_matches) * 120
    )
    if not has_topic_anchor:
        topic_score -= 120

    citation_score = min(8.0, math.log1p(cited_by_count(candidate)) * 1.2)
    rate_score = min(6.0, math.log1p(citation_rate_per_year(candidate)) * 1.5)
    metadata_score = 5.0 if candidate.get("abstract") else 0.0
    review_type_score = min(12.0, len(review_matches) * 4.0)
    total = topic_score + citation_score + rate_score + recency_score(candidate)
    total += metadata_score + review_type_score

    topic_evidence = [
        *(f"matched include term: {term}" for term in include_matches),
        *(f"matched title token: {token}" for token in title_overlap[:8]),
        *(f"matched include token: {token}" for token in include_token_overlap[:12]),
        *(f"matched topic token: {token}" for token in research_overlap[:12]),
    ]
    reasons = []
    if title_overlap:
        reasons.append(f"title token overlap: {', '.join(title_overlap[:8])}")
    if include_token_overlap:
        reasons.append(
            f"include token overlap: {', '.join(include_token_overlap[:12])}"
        )
    if research_overlap:
        reasons.append(f"topic token overlap: {', '.join(research_overlap[:12])}")
    if include_matches:
        reasons.append(f"matched include terms: {', '.join(include_matches)}")
    if not has_topic_anchor:
        reasons.append("no strong topic anchor matched")
    if exclude_matches:
        reasons.append(f"matched exclude terms: {', '.join(exclude_matches)}")
    if review_matches:
        reasons.append(f"review evidence terms: {', '.join(review_matches)}")
    if cited_by_count(candidate):
        reasons.append(f"cited_by_count={cited_by_count(candidate)}")
    if publication_year(candidate):
        reasons.append(f"publication_year={publication_year(candidate)}")

    return ReviewScore(
        score=total,
        cited_by_count=cited_by_count(candidate),
        citation_rate_per_year=round(citation_rate_per_year(candidate), 3),
        topic_evidence=topic_evidence,
        reasons=reasons,
    )


def review_query_key(candidate: dict[str, Any]) -> str:
    return str(candidate.get("query_index") or candidate.get("query") or "").lower()


def review_identity(candidate: dict[str, Any], index: int) -> str:
    return str(candidate.get("doi") or candidate.get("provider_id") or index)


def annotate_review_candidate(
    candidate: dict[str, Any],
    score: ReviewScore,
) -> dict[str, Any]:
    annotated = dict(candidate)
    annotated["review_selection_score"] = round(score.score, 3)
    annotated["review_topic_evidence"] = score.topic_evidence
    annotated["review_selection_reasons"] = score.reasons
    annotated["cited_by_count"] = score.cited_by_count
    annotated["citation_rate_per_year"] = score.citation_rate_per_year
    return annotated


def select_best_review_overviews(
    topic_contract: dict[str, Any],
    candidates: list[dict[str, Any]],
    max_results: int,
) -> list[dict[str, Any]]:
    scored = [
        (review_score(topic_contract, candidate), index, candidate)
        for index, candidate in enumerate(candidates)
    ]
    scored.sort(key=lambda item: item[0].score, reverse=True)

    selected = []
    selected_ids: set[str] = set()
    seen_queries: set[str] = set()

    for require_new_query in [True, False]:
        for score, index, candidate in scored:
            identity = review_identity(candidate, index)
            query_key = review_query_key(candidate)
            if identity in selected_ids:
                continue
            if require_new_query and query_key and query_key in seen_queries:
                continue

            selected.append(annotate_review_candidate(candidate, score))
            selected_ids.add(identity)
            if query_key:
                seen_queries.add(query_key)
            if len(selected) >= max_results:
                return selected

    return selected


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
    pool_size = review_pool_size(max_results)
    candidates = provider.fetch_candidates(
        plan=plan,
        max_results=pool_size,
        per_page=per_page,
        mailto=mailto,
        sleep_seconds=sleep_seconds,
    )
    selected = select_best_review_overviews(topic_contract, candidates, max_results)

    write_jsonl(output_path, selected)
    return StepResult(
        step_name=STEP.name,
        inputs={"topic_contract_yaml": topic_contract_path},
        outputs={"review_overviews_jsonl": output_path},
        row_counts={
            "review_overviews": len(selected),
            "review_overview_candidates": len(candidates),
        },
        metadata={
            "provider": provider.name,
            "search_queries": len(plan["search_queries"]),
            "review_pool_size": pool_size,
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
