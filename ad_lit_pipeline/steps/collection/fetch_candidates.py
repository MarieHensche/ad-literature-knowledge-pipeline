from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from ad_lit_pipeline.core.errors import UnsupportedProviderError
from ad_lit_pipeline.core.step import StepResult, StepSpec
from ad_lit_pipeline.io.json_io import read_json_object
from ad_lit_pipeline.io.jsonl_io import write_jsonl
from ad_lit_pipeline.providers.base import CandidateProvider
from ad_lit_pipeline.providers.openalex import OpenAlexProvider


STEP = StepSpec(
    name="fetch_candidates",
    inputs=["search_plan_json"],
    outputs=["candidates_jsonl"],
    uses_llm=False,
    description="Fetch candidate papers from the provider selected in a search plan.",
)


PROVIDERS: dict[str, CandidateProvider] = {
    "openalex": OpenAlexProvider(),
}


def provider_name_from_plan(plan: dict[str, Any]) -> str:
    provider = str(plan.get("recommended_provider") or "")
    provider_plan = plan.get("provider_specific_plan")
    if isinstance(provider_plan, dict) and provider_plan.get("provider"):
        provider = str(provider_plan["provider"])
    if not provider:
        raise ValueError("Plan must include a recommended_provider.")
    return provider


def get_provider(name: str) -> CandidateProvider:
    provider = PROVIDERS.get(name)
    if provider is None:
        raise UnsupportedProviderError(f"No candidate provider implemented for: {name}")
    return provider


def run(
    plan_path: Path,
    output_path: Path,
    max_results: int | None = None,
    per_page: int = 25,
    mailto: str | None = None,
    sleep_seconds: float = 0.2,
) -> StepResult:
    plan = read_json_object(plan_path)
    provider_plan = plan.get("provider_specific_plan")
    if not isinstance(provider_plan, dict):
        raise ValueError("Plan must contain provider_specific_plan.")

    provider_name = provider_name_from_plan(plan)
    provider = get_provider(provider_name)
    provider.validate_plan(plan)
    search_query_count = 1
    query_groups = plan.get("query_groups")
    if isinstance(query_groups, list):
        search_query_count = sum(
            len(group.get("queries", []))
            for group in query_groups
            if isinstance(group, dict) and isinstance(group.get("queries"), list)
        )
    elif hasattr(provider, "search_queries_from_plan"):
        search_query_count = len(provider.search_queries_from_plan(plan))
    resolved_max_results = max_results or int(
        provider_plan.get("max_results_recommendation") or 100
    )
    candidates = provider.fetch_candidates(
        plan=plan,
        max_results=resolved_max_results,
        per_page=per_page,
        mailto=mailto,
        sleep_seconds=sleep_seconds,
    )
    diagnostics = getattr(provider, "last_fetch_diagnostics", {})
    if not isinstance(diagnostics, dict):
        diagnostics = {}
    warnings = []
    if len(candidates) < resolved_max_results:
        warnings.append(
            "Fetched fewer unique candidates than requested after all available "
            f"query groups: requested={resolved_max_results} fetched={len(candidates)}."
        )

    write_jsonl(output_path, candidates)
    row_counts = {"fetched_candidates": len(candidates)}
    for key in [
        "target_candidates",
        "raw_provider_candidates_seen",
        "in_fetch_duplicates_removed",
        "unique_candidates",
        "exhausted_query_count",
        "logical_query_count",
        "execution_query_count",
    ]:
        value = diagnostics.get(key)
        if isinstance(value, int):
            row_counts[key] = value
    tier_counts = diagnostics.get("tier_counts")
    if isinstance(tier_counts, dict):
        for tier, count in tier_counts.items():
            if isinstance(count, int):
                row_counts[f"tier_{tier}_candidates"] = count

    return StepResult(
        step_name=STEP.name,
        inputs={"search_plan_json": plan_path},
        outputs={"candidates_jsonl": output_path},
        row_counts=row_counts,
        warnings=warnings,
        metadata={
            "provider": provider_name,
            "search_queries": search_query_count,
            "fetch_diagnostics": diagnostics,
        },
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch candidate papers.")
    parser.add_argument("--plan", required=True, help="Input search plan JSON.")
    parser.add_argument("--output", required=True, help="Output candidates JSONL.")
    parser.add_argument("--max-results", type=int, default=None, help="Override max result count.")
    parser.add_argument("--per-page", type=int, default=25, help="Provider page size.")
    parser.add_argument("--mailto", default=None, help="Optional email for provider polite pool.")
    parser.add_argument("--sleep", type=float, default=0.2, help="Delay between API pages.")
    args = parser.parse_args()

    result = run(
        Path(args.plan),
        Path(args.output),
        args.max_results,
        args.per_page,
        args.mailto,
        args.sleep,
    )

    print(f"Fetched candidates: {result.row_counts['fetched_candidates']}")
    print(f"Wrote {args.output}")
