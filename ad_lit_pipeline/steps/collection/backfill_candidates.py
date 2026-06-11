from __future__ import annotations

import argparse
import math
from pathlib import Path
from typing import Any

from ad_lit_pipeline.core.step import StepResult, StepSpec
from ad_lit_pipeline.io.csv_io import read_csv_rows, write_csv_rows
from ad_lit_pipeline.io.json_io import read_json_object
from ad_lit_pipeline.io.jsonl_io import read_jsonl_objects, write_jsonl
from ad_lit_pipeline.steps.collection import deduplicate, fetch_candidates
from ad_lit_pipeline.steps.collection.candidate_identity import dedupe_key
from ad_lit_pipeline.steps.screening import title_relevance
from ad_lit_pipeline.llm.client import JSONLLMClient


STEP = StepSpec(
    name="backfill_candidates",
    inputs=[
        "search_plan_json",
        "candidates_jsonl",
        "deduped_candidates_jsonl",
        "candidate_screening_csv",
        "topic_contract_yaml",
    ],
    outputs=[
        "candidates_jsonl",
        "deduped_candidates_jsonl",
        "candidate_screening_csv",
    ],
    uses_llm=True,
    description="Fetch and screen replacement candidates when title screening drops too many papers.",
)

BACKFILL_TRIGGER_RATIO = 0.9
BACKFILL_CANDIDATE_BUDGET_MULTIPLIER = 1


def included_count(screening_rows: list[dict[str, str]]) -> int:
    return sum(
        1 for row in screening_rows if row.get("screening_decision") == "include"
    )


def should_backfill(included: int, max_results: int) -> tuple[bool, int]:
    minimum_without_backfill = math.ceil(max_results * BACKFILL_TRIGGER_RATIO)
    return included < minimum_without_backfill, minimum_without_backfill


def fetch_additional_candidates(
    plan: dict[str, Any],
    existing_candidates: list[dict[str, Any]],
    missing: int,
    per_page: int,
    mailto: str | None,
    sleep_seconds: float,
    backfill_round: int,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    provider_name = fetch_candidates.provider_name_from_plan(plan)
    provider = fetch_candidates.get_provider(provider_name)
    provider.validate_plan(plan)

    fetch_additional = getattr(provider, "fetch_additional_candidates", None)
    if callable(fetch_additional):
        additional = fetch_additional(
            plan,
            existing_candidates,
            missing,
            per_page,
            mailto,
            sleep_seconds,
            backfill_round=backfill_round,
        )
    else:
        existing_keys = {dedupe_key(candidate) for candidate in existing_candidates}
        expanded = provider.fetch_candidates(
            plan,
            len(existing_candidates) + missing,
            per_page,
            mailto,
            sleep_seconds,
        )
        additional = [
            candidate
            for candidate in expanded
            if dedupe_key(candidate) not in existing_keys
        ][:missing]

    diagnostics = getattr(provider, "last_fetch_diagnostics", {})
    if not isinstance(diagnostics, dict):
        diagnostics = {}
    return additional, diagnostics


def write_combined_candidates(
    candidates_path: Path,
    deduped_path: Path,
    new_candidates: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    raw_candidates = (
        read_jsonl_objects(candidates_path)
        if candidates_path.exists()
        else read_jsonl_objects(deduped_path)
    )
    combined_raw = [*raw_candidates, *new_candidates]
    write_jsonl(candidates_path, combined_raw)
    combined_deduped = deduplicate.deduplicate(combined_raw)
    write_jsonl(deduped_path, combined_deduped)
    return combined_deduped


def screen_new_candidates(
    new_candidates: list[dict[str, Any]],
    screening_path: Path,
    topic_contract_path: Path,
    model: str,
    client: JSONLLMClient | None,
    trace_dir: Path | None,
    backfill_round: int,
) -> tuple[list[dict[str, str]], list[Path], list[str], dict[str, int]]:
    if not new_candidates:
        return [], [], [], {
            "screened_candidates": 0,
            "included": 0,
            "excluded": 0,
            "deterministic_tier0_included": 0,
            "llm_screened": 0,
        }

    work_dir = trace_dir if trace_dir is not None else screening_path.parent
    work_dir.mkdir(parents=True, exist_ok=True)
    new_candidates_path = (
        work_dir / f"{screening_path.stem}_backfill_{backfill_round}_candidates.jsonl"
    )
    new_screening_path = (
        work_dir / f"{screening_path.stem}_backfill_{backfill_round}_screening.csv"
    )
    write_jsonl(new_candidates_path, new_candidates)

    result = title_relevance.run(
        new_candidates_path,
        new_screening_path,
        model,
        topic_contract_path,
        client=client,
        trace_dir=trace_dir,
    )
    return (
        read_csv_rows(new_screening_path),
        result.trace_paths,
        result.warnings,
        result.row_counts,
    )


def append_screening_rows(
    screening_path: Path,
    new_rows: list[dict[str, str]],
) -> list[dict[str, str]]:
    existing_rows = read_csv_rows(screening_path)
    combined_rows = [*existing_rows, *new_rows]
    write_csv_rows(screening_path, combined_rows, title_relevance.OUTPUT_COLUMNS)
    return combined_rows


def run(
    plan_path: Path,
    candidates_path: Path,
    deduped_path: Path,
    screening_path: Path,
    topic_contract_path: Path,
    model: str,
    max_results: int | None,
    mailto: str | None = None,
    per_page: int = 25,
    sleep_seconds: float = 0.2,
    client: JSONLLMClient | None = None,
    trace_dir: Path | None = None,
) -> StepResult:
    screening_rows = read_csv_rows(screening_path)
    initial_included = included_count(screening_rows)
    initial_screened = len(screening_rows)
    warnings: list[str] = []
    trace_paths: list[Path] = []

    if max_results is None or max_results <= 0:
        return StepResult(
            step_name=STEP.name,
            inputs={
                "search_plan_json": plan_path,
                "deduped_candidates_jsonl": deduped_path,
                "candidate_screening_csv": screening_path,
                "topic_contract_yaml": topic_contract_path,
            },
            outputs={
                "candidates_jsonl": candidates_path,
                "deduped_candidates_jsonl": deduped_path,
                "candidate_screening_csv": screening_path,
            },
            row_counts={
                "backfill_triggered": 0,
                "initial_screened_rows": initial_screened,
                "initial_included_rows": initial_included,
            },
            metadata={"reason": "No positive max_results value supplied."},
        )

    needs_backfill, threshold = should_backfill(initial_included, max_results)
    missing = max(0, max_results - initial_included)
    if not needs_backfill or missing <= 0:
        return StepResult(
            step_name=STEP.name,
            inputs={
                "search_plan_json": plan_path,
                "deduped_candidates_jsonl": deduped_path,
                "candidate_screening_csv": screening_path,
                "topic_contract_yaml": topic_contract_path,
            },
            outputs={
                "candidates_jsonl": candidates_path,
                "deduped_candidates_jsonl": deduped_path,
                "candidate_screening_csv": screening_path,
            },
            row_counts={
                "backfill_triggered": 0,
                "initial_screened_rows": initial_screened,
                "initial_included_rows": initial_included,
                "minimum_included_without_backfill": threshold,
            },
            metadata={
                "max_results": max_results,
                "backfill_trigger_ratio": BACKFILL_TRIGGER_RATIO,
            },
        )

    plan = read_json_object(plan_path)
    combined_screening_rows = screening_rows
    combined_deduped = read_jsonl_objects(deduped_path)
    diagnostics_by_round: list[dict[str, Any]] = []
    backfill_rounds = 0
    total_backfill_fetched = 0
    total_backfill_screened = 0
    total_backfill_included = 0
    total_backfill_excluded = 0
    max_backfill_candidates = max_results * BACKFILL_CANDIDATE_BUDGET_MULTIPLIER

    while included_count(combined_screening_rows) < threshold:
        remaining_budget = max_backfill_candidates - total_backfill_fetched
        if remaining_budget <= 0:
            warnings.append(
                "Backfill stopped before reaching the inclusion threshold because "
                f"the backfill candidate budget was exhausted: threshold={threshold} "
                f"included={included_count(combined_screening_rows)}."
            )
            break

        backfill_rounds += 1
        missing_to_threshold = threshold - included_count(combined_screening_rows)
        fetch_count = min(missing_to_threshold, remaining_budget)
        existing_candidates = read_jsonl_objects(deduped_path)
        new_candidates, diagnostics = fetch_additional_candidates(
            plan,
            existing_candidates,
            fetch_count,
            per_page,
            mailto,
            sleep_seconds,
            backfill_rounds,
        )
        diagnostics_by_round.append(diagnostics)
        if not new_candidates:
            warnings.append(
                "Backfill stopped before reaching the inclusion threshold because "
                f"no new candidates were returned: threshold={threshold} "
                f"included={included_count(combined_screening_rows)}."
            )
            break

        total_backfill_fetched += len(new_candidates)
        combined_deduped = write_combined_candidates(
            candidates_path,
            deduped_path,
            new_candidates,
        )
        new_screening_rows, new_trace_paths, screening_warnings, screening_counts = (
            screen_new_candidates(
                new_candidates,
                screening_path,
                topic_contract_path,
                model,
                client,
                trace_dir,
                backfill_rounds,
            )
        )
        trace_paths.extend(new_trace_paths)
        warnings.extend(screening_warnings)
        total_backfill_screened += screening_counts.get("screened_candidates", 0)
        total_backfill_included += screening_counts.get("included", 0)
        total_backfill_excluded += screening_counts.get("excluded", 0)
        combined_screening_rows = append_screening_rows(
            screening_path,
            new_screening_rows,
        )

    final_included = included_count(combined_screening_rows)
    if final_included < threshold:
        warnings.append(
            "Backfill completed but fewer included papers than the threshold are "
            f"available: threshold={threshold} included={final_included}."
        )

    return StepResult(
        step_name=STEP.name,
        inputs={
            "search_plan_json": plan_path,
            "candidates_jsonl": candidates_path,
            "deduped_candidates_jsonl": deduped_path,
            "candidate_screening_csv": screening_path,
            "topic_contract_yaml": topic_contract_path,
        },
        outputs={
            "candidates_jsonl": candidates_path,
            "deduped_candidates_jsonl": deduped_path,
            "candidate_screening_csv": screening_path,
        },
        row_counts={
            "backfill_triggered": 1,
            "backfill_rounds": backfill_rounds,
            "initial_screened_rows": initial_screened,
            "initial_included_rows": initial_included,
            "minimum_included_without_backfill": threshold,
            "missing_to_target_before_backfill": missing,
            "missing_to_threshold_before_backfill": max(0, threshold - initial_included),
            "backfill_candidates_fetched": total_backfill_fetched,
            "backfill_screened_rows": total_backfill_screened,
            "backfill_included_rows": total_backfill_included,
            "backfill_excluded_rows": total_backfill_excluded,
            "final_screened_rows": len(combined_screening_rows),
            "final_included_rows": final_included,
            "final_deduped_candidates": len(combined_deduped),
        },
        trace_paths=trace_paths,
        warnings=warnings,
        metadata={
            "max_results": max_results,
            "backfill_trigger_ratio": BACKFILL_TRIGGER_RATIO,
            "backfill_candidate_budget": max_backfill_candidates,
            "fetch_diagnostics_by_round": diagnostics_by_round,
            "fetch_diagnostics": diagnostics_by_round[-1] if diagnostics_by_round else {},
        },
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill candidate collection.")
    parser.add_argument("--plan", required=True, help="Search plan JSON.")
    parser.add_argument("--candidates", required=True, help="Raw candidates JSONL.")
    parser.add_argument("--deduped", required=True, help="Deduped candidates JSONL.")
    parser.add_argument("--screening", required=True, help="Title screening CSV.")
    parser.add_argument("--topic-contract", required=True, help="Topic contract YAML.")
    parser.add_argument("--model", required=True, help="LLM model for title screening.")
    parser.add_argument("--max-results", type=int, required=True, help="Final target.")
    parser.add_argument("--mailto", default=None, help="Provider polite-pool email.")
    parser.add_argument("--per-page", type=int, default=25, help="Provider page size.")
    parser.add_argument("--sleep", type=float, default=0.2, help="Provider delay.")
    parser.add_argument("--trace-dir", default=None, help="Optional trace directory.")
    args = parser.parse_args()

    result = run(
        Path(args.plan),
        Path(args.candidates),
        Path(args.deduped),
        Path(args.screening),
        Path(args.topic_contract),
        args.model,
        args.max_results,
        mailto=args.mailto,
        per_page=args.per_page,
        sleep_seconds=args.sleep,
        trace_dir=Path(args.trace_dir) if args.trace_dir else None,
    )
    print(f"Backfill triggered: {result.row_counts.get('backfill_triggered', 0)}")
    print(f"Final included rows: {result.row_counts.get('final_included_rows', 0)}")


if __name__ == "__main__":
    main()
