from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any, Iterable

from ad_lit_pipeline.core.step import StepResult, StepSpec
from ad_lit_pipeline.io.json_io import read_json_object
from ad_lit_pipeline.io.jsonl_io import write_jsonl
from ad_lit_pipeline.llm.client import JSONLLMClient, OpenAIResponsesClient
from ad_lit_pipeline.llm.trace import LLMTraceWriter
from ad_lit_pipeline.steps.collection import deduplicate, export_included
from ad_lit_pipeline.steps.collection.fetch_candidates import (
    get_provider,
    provider_name_from_plan,
)
from ad_lit_pipeline.steps.screening import llm_candidate_screening
from ad_lit_pipeline.topics.contract import load_topic_contract


STEP = StepSpec(
    name="collect_targeted_candidates",
    inputs=["search_plan_json", "topic_contract_yaml"],
    outputs=[
        "candidates_jsonl",
        "deduped_candidate_jsonl",
        "candidate_screening_csv",
        "papers_csv",
    ],
    uses_llm=True,
    description=(
        "Fetch candidates incrementally, deduplicate as they arrive, screen topic "
        "fit, and export core-topic papers before adjacent papers."
    ),
)


def default_candidate_budget(target_results: int) -> int:
    """Return an adaptive safety budget without a large multiplier for big runs."""
    buffer = min(max(target_results * 4, 20), 1000)
    return target_results + buffer


def iter_provider_candidates(
    provider: Any,
    plan: dict[str, Any],
    candidate_budget: int,
    per_page: int,
    mailto: str | None,
    sleep_seconds: float,
) -> Iterable[dict[str, Any]]:
    if hasattr(provider, "iter_candidates"):
        count = 0
        for candidate in provider.iter_candidates(  # type: ignore[attr-defined]
            plan,
            per_page,
            mailto,
            sleep_seconds,
        ):
            yield candidate
            count += 1
            if count >= candidate_budget:
                break
        return

    for candidate in provider.fetch_candidates(
        plan=plan,
        max_results=candidate_budget,
        per_page=per_page,
        mailto=mailto,
        sleep_seconds=sleep_seconds,
    ):
        yield candidate


def add_duplicate(
    representative: dict[str, Any],
    duplicate: dict[str, Any],
) -> None:
    representative["duplicate_count"] = (
        int(representative.get("duplicate_count") or 1) + 1
    )
    provenance = representative.setdefault("duplicate_provenance", [])
    if isinstance(provenance, list):
        provenance.append(deduplicate.duplicate_summary(duplicate))


def make_unique_candidate(candidate: dict[str, Any], key: str) -> dict[str, Any]:
    unique = dict(candidate)
    unique["dedupe_key"] = key
    unique["duplicate_count"] = 1
    unique["duplicate_provenance"] = [deduplicate.duplicate_summary(candidate)]
    return unique


def should_stop_with_core_target(core_rows: list[dict[str, str]], target: int) -> bool:
    return len(core_rows) >= target


def run(
    plan_path: Path,
    candidates_path: Path,
    deduped_path: Path,
    screening_path: Path,
    papers_path: Path,
    topic_description: str,
    topic_contract_path: Path,
    model: str,
    target_results: int,
    candidate_budget: int | None = None,
    per_page: int = 25,
    mailto: str | None = None,
    sleep_seconds: float = 0.2,
    client: JSONLLMClient | None = None,
    trace_dir: Path | None = None,
) -> StepResult:
    if target_results <= 0:
        raise ValueError("target_results must be greater than zero.")
    if candidate_budget is not None and candidate_budget <= 0:
        raise ValueError("candidate_budget must be greater than zero.")

    plan = read_json_object(plan_path)
    provider_name = provider_name_from_plan(plan)
    provider = get_provider(provider_name)
    provider.validate_plan(plan)
    topic_contract = load_topic_contract(topic_contract_path)
    llm_client = client or OpenAIResponsesClient()
    trace_writer = LLMTraceWriter(trace_dir) if trace_dir is not None else None
    resolved_candidate_budget = (
        candidate_budget
        if candidate_budget is not None
        else default_candidate_budget(target_results)
    )

    raw_candidates: list[dict[str, Any]] = []
    unique_candidates_by_key: dict[str, dict[str, Any]] = {}
    screening_rows: list[dict[str, str]] = []
    core_screening_rows: list[dict[str, str]] = []
    adjacent_screening_rows: list[dict[str, str]] = []
    all_trace_paths: list[Path] = []
    warnings: list[str] = []
    raw_seen = 0
    duplicates_removed = 0

    candidate_iterable = iter_provider_candidates(
        provider,
        plan,
        resolved_candidate_budget,
        per_page,
        mailto,
        sleep_seconds,
    )

    for candidate in candidate_iterable:
        raw_seen += 1
        raw_candidates.append(candidate)

        key = deduplicate.dedupe_key(candidate)
        representative = unique_candidates_by_key.get(key)
        if representative is not None:
            add_duplicate(representative, candidate)
            duplicates_removed += 1
            continue

        unique_candidate = make_unique_candidate(candidate, key)
        unique_candidates_by_key[key] = unique_candidate
        unique_index = len(unique_candidates_by_key)
        print(
            "Screening unique candidate "
            f"{unique_index}: {unique_candidate.get('title')}"
        )

        try:
            screening_row, trace_paths = llm_candidate_screening.screen_candidate(
                topic_description,
                topic_contract,
                unique_candidate,
                unique_index,
                model,
                llm_client,
                trace_writer,
            )
            all_trace_paths.extend(trace_paths)
        except ValueError as error:
            paper_id = llm_candidate_screening.make_paper_id(
                unique_candidate,
                unique_index,
            )
            warning = (
                f"Failed to screen candidate '{paper_id}' after retry "
                f"(auto-excluded): {error}"
            )
            warnings.append(warning)
            screening_row = {
                "paper_id": paper_id,
                "title": str(unique_candidate.get("title") or ""),
                "year": str(unique_candidate.get("year") or ""),
                "doi": str(unique_candidate.get("doi") or ""),
                "provider": str(unique_candidate.get("provider") or ""),
                "provider_id": str(unique_candidate.get("provider_id") or ""),
                "source_rank": str(unique_candidate.get("rank") or ""),
                "source_query": str(unique_candidate.get("query") or ""),
                "source_query_reason": str(unique_candidate.get("query_reason") or ""),
                "screening_decision": "exclude",
                "screening_topic_fit": "out_of_scope",
                "screening_confidence": "n/a",
                "screening_reason": f"Auto-excluded due to LLM error: {error}",
            }

        screening_rows.append(screening_row)
        if screening_row.get("screening_decision") == "include":
            if screening_row.get("screening_topic_fit") == "core_topic":
                core_screening_rows.append(screening_row)
            elif screening_row.get("screening_topic_fit") == "adjacent_but_relevant":
                adjacent_screening_rows.append(screening_row)

        if should_stop_with_core_target(core_screening_rows, target_results):
            break

        if raw_seen >= resolved_candidate_budget:
            break

    unique_candidates = list(unique_candidates_by_key.values())
    if len(core_screening_rows) >= target_results:
        final_screening_rows = core_screening_rows[:target_results]
    else:
        adjacent_slots = target_results - len(core_screening_rows)
        final_screening_rows = [
            *core_screening_rows,
            *adjacent_screening_rows[:adjacent_slots],
        ]

    write_jsonl(candidates_path, raw_candidates)
    write_jsonl(deduped_path, unique_candidates)
    llm_candidate_screening.write_csv(screening_path, screening_rows)
    papers = export_included.export_included(
        unique_candidates,
        final_screening_rows,
        target_results,
    )
    export_included.write_csv(papers_path, papers)

    return StepResult(
        step_name=STEP.name,
        inputs={
            "search_plan_json": plan_path,
            "topic_contract_yaml": topic_contract_path,
        },
        outputs={
            "candidates_jsonl": candidates_path,
            "deduped_candidate_jsonl": deduped_path,
            "candidate_screening_csv": screening_path,
            "papers_csv": papers_path,
        },
        row_counts={
            "target_results": target_results,
            "candidate_budget": resolved_candidate_budget,
            "raw_candidates_seen": raw_seen,
            "unique_candidates_screened": len(unique_candidates),
            "duplicates_removed": duplicates_removed,
            "core_topic_found": len(core_screening_rows),
            "adjacent_but_relevant_found": len(adjacent_screening_rows),
            "final_papers_exported": len(papers),
        },
        trace_paths=all_trace_paths,
        warnings=warnings,
        metadata={"provider": provider_name},
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Collect target papers core-first.")
    parser.add_argument("--plan", required=True, help="Input search plan JSON.")
    parser.add_argument("--candidates", required=True, help="Raw candidates JSONL.")
    parser.add_argument("--deduped", required=True, help="Deduped candidates JSONL.")
    parser.add_argument("--screening", required=True, help="Candidate screening CSV.")
    parser.add_argument("--output", required=True, help="Output papers CSV.")
    parser.add_argument("--topic", required=True, help="Topic description.")
    parser.add_argument("--topic-contract", required=True, help="Topic contract YAML.")
    parser.add_argument("--model", default="gpt-4o-mini", help="LLM model.")
    parser.add_argument("--target-results", type=int, required=True)
    parser.add_argument("--candidate-budget", type=int, default=None)
    parser.add_argument("--per-page", type=int, default=25)
    parser.add_argument("--mailto", default=None)
    parser.add_argument("--sleep", type=float, default=0.2)
    args = parser.parse_args()

    result = run(
        Path(args.plan),
        Path(args.candidates),
        Path(args.deduped),
        Path(args.screening),
        Path(args.output),
        args.topic,
        Path(args.topic_contract),
        args.model,
        args.target_results,
        args.candidate_budget,
        args.per_page,
        args.mailto,
        args.sleep,
    )
    print(f"Raw candidates seen: {result.row_counts['raw_candidates_seen']}")
    print(f"Unique screened: {result.row_counts['unique_candidates_screened']}")
    print(f"Core-topic found: {result.row_counts['core_topic_found']}")
    print(f"Final papers exported: {result.row_counts['final_papers_exported']}")


if __name__ == "__main__":
    main()
