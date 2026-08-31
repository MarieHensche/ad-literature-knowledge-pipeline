from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from ad_lit_pipeline.core.step import StepResult, StepSpec
from ad_lit_pipeline.io.csv_io import read_csv_rows, write_csv_rows
from ad_lit_pipeline.io.json_io import read_json_object
from ad_lit_pipeline.io.jsonl_io import read_jsonl_objects, write_jsonl
from ad_lit_pipeline.providers.base import candidate_provider_dates
from ad_lit_pipeline.steps.collection import (
    deduplicate,
    fetch_candidates,
    verify_full_text_availability,
)
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
    description=(
        "Fetch and screen replacement candidates when relevance or full-text "
        "eligibility drops too many papers."
    ),
)

def included_count(screening_rows: list[dict[str, str]]) -> int:
    return sum(
        1 for row in screening_rows if row.get("screening_decision") == "include"
    )


def should_backfill(included: int, max_results: int) -> tuple[bool, int]:
    return included < max_results, max_results


def availability_rows(path: Path | None) -> list[dict[str, str]]:
    if path is None or not path.exists():
        return []
    return read_csv_rows(path)


def availability_key(row: dict[str, str]) -> tuple[str, str]:
    return (
        str(row.get("doi") or "").strip().lower(),
        str(row.get("provider_id") or "").strip(),
    )


def verified_full_text_count(
    screening_rows: list[dict[str, str]],
    rows: list[dict[str, str]],
) -> int:
    included_keys = {
        availability_key(row)
        for row in screening_rows
        if row.get("screening_decision") == "include"
    }
    return sum(
        1
        for row in rows
        if availability_key(row) in included_keys
        and row.get("full_text_availability_status")
        == verify_full_text_availability.STATUS_VERIFIED
    )


def eligible_count(
    screening_rows: list[dict[str, str]],
    rows: list[dict[str, str]],
    require_full_text: bool,
) -> int:
    if require_full_text:
        return verified_full_text_count(screening_rows, rows)
    return included_count(screening_rows)


def verify_availability_if_required(
    deduped_path: Path,
    screening_path: Path,
    availability_path: Path | None,
    topic_contract_path: Path,
    require_full_text: bool,
    timeout_seconds: float,
    workers: int,
    checker: verify_full_text_availability.URLChecker = (
        verify_full_text_availability.check_location
    ),
    unpaywall_email: str | None = None,
    core_api_key: str | None = None,
) -> list[dict[str, str]]:
    if not require_full_text:
        return []
    if availability_path is None:
        raise ValueError(
            "availability_path is required when full-text availability is required."
        )
    verify_full_text_availability.run(
        deduped_path,
        screening_path,
        availability_path,
        topic_contract_path,
        require_full_text_availability=True,
        timeout_seconds=timeout_seconds,
        workers=workers,
        checker=checker,
        unpaywall_email=unpaywall_email,
        core_api_key=core_api_key,
    )
    return availability_rows(availability_path)


def finalize_verified_pending_llm_rows(
    deduped_path: Path,
    screening_path: Path,
    availability_rows: list[dict[str, str]],
    topic_contract_path: Path,
    model: str,
    client: JSONLLMClient | None,
    trace_dir: Path | None,
) -> tuple[list[dict[str, str]], list[Path], list[str], dict[str, int]]:
    candidates = read_jsonl_objects(deduped_path)
    screening_rows = read_csv_rows(screening_path)
    finalized_rows, trace_paths, warnings, counts = (
        title_relevance.finalize_pending_llm_rows(
            candidates,
            screening_rows,
            availability_rows,
            topic_contract_path,
            model,
            client=client,
            trace_dir=trace_dir,
        )
    )
    write_csv_rows(screening_path, finalized_rows, title_relevance.OUTPUT_COLUMNS)
    return finalized_rows, trace_paths, warnings, counts


def provider_queues_exhausted(diagnostics: dict[str, Any]) -> bool:
    try:
        exhausted_count = int(diagnostics.get("exhausted_query_count") or 0)
        execution_count = int(diagnostics.get("execution_query_count") or 0)
    except (TypeError, ValueError):
        return False
    return execution_count > 0 and exhausted_count >= execution_count


def fetch_additional_candidates(
    plan: dict[str, Any],
    existing_candidates: list[dict[str, Any]],
    missing: int,
    per_page: int | None,
    mailto: str | None,
    sleep_seconds: float,
    backfill_round: int,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    provider_name = fetch_candidates.provider_name_from_plan(plan)
    provider = fetch_candidates.get_provider(provider_name)
    provider.validate_plan(plan)
    resolved_per_page = fetch_candidates.resolve_per_page(provider, per_page)

    fetch_additional = getattr(provider, "fetch_additional_candidates", None)
    if callable(fetch_additional):
        additional = fetch_additional(
            plan,
            existing_candidates,
            missing,
            resolved_per_page,
            mailto,
            sleep_seconds,
            backfill_round=backfill_round,
        )
    else:
        existing_keys = {dedupe_key(candidate) for candidate in existing_candidates}
        expanded = provider.fetch_candidates(
            plan,
            len(existing_candidates) + missing,
            resolved_per_page,
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
    diagnostics.setdefault("per_page", resolved_per_page)
    diagnostics.setdefault(
        "provider_max_per_page",
        fetch_candidates.provider_max_per_page(provider),
    )
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


def unseen_candidates(
    candidates: list[dict[str, Any]],
    existing_candidates: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    existing_keys = {dedupe_key(candidate) for candidate in existing_candidates}
    seen_new_keys = set()
    rows = []
    for candidate in candidates:
        key = dedupe_key(candidate)
        if key in existing_keys or key in seen_new_keys:
            continue
        seen_new_keys.add(key)
        rows.append(candidate)
    return rows


def screen_new_candidates(
    new_candidates: list[dict[str, Any]],
    screening_path: Path,
    topic_contract_path: Path,
    model: str,
    client: JSONLLMClient | None,
    trace_dir: Path | None,
    backfill_round: int,
    defer_llm_until_full_text: bool,
) -> tuple[list[dict[str, str]], list[Path], list[str], dict[str, int]]:
    if not new_candidates:
        return [], [], [], {
            "screened_candidates": 0,
            "included": 0,
            "excluded": 0,
            "deterministic_tier0_included": 0,
            "deterministic_local_excluded": 0,
            "llm_screened": 0,
            "llm_error_rows": 0,
            "llm_error_auto_excluded": 0,
            "manual_review_rows": 0,
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
        defer_llm_until_full_text=defer_llm_until_full_text,
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
    per_page: int | None = None,
    sleep_seconds: float = 0.2,
    client: JSONLLMClient | None = None,
    trace_dir: Path | None = None,
    availability_path: Path | None = None,
    require_full_text_availability: bool = False,
    full_text_availability_timeout: float = 5.0,
    full_text_availability_workers: int = 8,
    unpaywall_email: str | None = None,
    core_api_key: str | None = None,
    availability_checker: verify_full_text_availability.URLChecker = (
        verify_full_text_availability.check_location
    ),
) -> StepResult:
    screening_rows = read_csv_rows(screening_path)
    initial_included = included_count(screening_rows)
    initial_screened = len(screening_rows)
    full_text_required = (
        require_full_text_availability
        or verify_full_text_availability.full_text_required_from_contract(
            topic_contract_path
        )
    )
    initial_availability_rows = verify_availability_if_required(
        deduped_path,
        screening_path,
        availability_path,
        topic_contract_path,
        full_text_required,
        full_text_availability_timeout,
        full_text_availability_workers,
        availability_checker,
        unpaywall_email,
        core_api_key,
    )
    initial_finalize_counts = {
        "llm_screened": 0,
        "llm_error_rows": 0,
        "llm_error_auto_excluded": 0,
        "pending_llm_without_verified_full_text": 0,
    }
    if full_text_required:
        (
            screening_rows,
            initial_trace_paths,
            initial_warnings,
            initial_finalize_counts,
        ) = finalize_verified_pending_llm_rows(
            deduped_path,
            screening_path,
            initial_availability_rows,
            topic_contract_path,
            model,
            client,
            trace_dir,
        )
        trace_paths = initial_trace_paths
        warnings = initial_warnings
    else:
        trace_paths = []
        warnings = []
    initial_included = included_count(screening_rows)
    initial_eligible = eligible_count(
        screening_rows,
        initial_availability_rows,
        full_text_required,
    )

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
                "initial_verified_full_text_rows": initial_eligible
                if full_text_required
                else 0,
            },
            metadata={"reason": "No positive max_results value supplied."},
        )

    needs_backfill, target = should_backfill(initial_eligible, max_results)
    missing = max(0, target - initial_eligible)
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
                "initial_verified_full_text_rows": initial_eligible
                if full_text_required
                else 0,
                "target_included_rows": target,
            },
            metadata={
                "max_results": max_results,
                "backfill_target_policy": "requested_max_results",
                "backfill_stop_reason": "target_already_reached",
                "require_full_text_availability": full_text_required,
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
    total_backfill_manual_review = 0
    total_backfill_llm_errors = 0
    total_backfill_llm_error_auto_excluded = 0
    backfill_stop_reason = "target_reached"

    combined_availability_rows = initial_availability_rows

    while (
        eligible_count(
            combined_screening_rows,
            combined_availability_rows,
            full_text_required,
        )
        < target
    ):
        backfill_rounds += 1
        current_eligible = eligible_count(
            combined_screening_rows,
            combined_availability_rows,
            full_text_required,
        )
        missing_to_target = target - current_eligible
        fetch_count = missing_to_target
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
        new_candidates = unseen_candidates(new_candidates, existing_candidates)
        diagnostics["new_candidates_after_seen_filter"] = len(new_candidates)
        diagnostics_by_round.append(diagnostics)
        if not new_candidates:
            backfill_stop_reason = "exhausted_no_new_candidates"
            warnings.append(
                "Backfill stopped before reaching the requested paper count because "
                f"no new candidates were returned: target={target} "
                f"eligible={current_eligible}."
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
                full_text_required,
            )
        )
        trace_paths.extend(new_trace_paths)
        warnings.extend(screening_warnings)
        total_backfill_screened += screening_counts.get("screened_candidates", 0)
        total_backfill_included += screening_counts.get("included", 0)
        total_backfill_excluded += screening_counts.get("excluded", 0)
        total_backfill_manual_review += screening_counts.get("manual_review_rows", 0)
        total_backfill_llm_errors += screening_counts.get("llm_error_rows", 0)
        total_backfill_llm_error_auto_excluded += screening_counts.get(
            "llm_error_auto_excluded",
            0,
        )
        combined_screening_rows = append_screening_rows(
            screening_path,
            new_screening_rows,
        )
        combined_availability_rows = verify_availability_if_required(
            deduped_path,
            screening_path,
            availability_path,
            topic_contract_path,
            full_text_required,
            full_text_availability_timeout,
            full_text_availability_workers,
            availability_checker,
            unpaywall_email,
            core_api_key,
        )
        (
            combined_screening_rows,
            finalize_trace_paths,
            finalize_warnings,
            finalize_counts,
        ) = finalize_verified_pending_llm_rows(
            deduped_path,
            screening_path,
            combined_availability_rows,
            topic_contract_path,
            model,
            client,
            trace_dir,
        )
        trace_paths.extend(finalize_trace_paths)
        warnings.extend(finalize_warnings)
        total_backfill_llm_errors += finalize_counts.get("llm_error_rows", 0)
        total_backfill_llm_error_auto_excluded += finalize_counts.get(
            "llm_error_auto_excluded",
            0,
        )
        total_backfill_included = (
            included_count(combined_screening_rows) - initial_included
        )
        total_backfill_excluded = (
            sum(
                1
                for row in combined_screening_rows
                if row.get("screening_decision") == "exclude"
            )
            - sum(
                1
                for row in screening_rows
                if row.get("screening_decision") == "exclude"
            )
        )
        current_eligible = eligible_count(
            combined_screening_rows,
            combined_availability_rows,
            full_text_required,
        )
        if (
            current_eligible < target
            and len(new_candidates) < fetch_count
            and provider_queues_exhausted(diagnostics)
        ):
            backfill_stop_reason = "exhausted_all_provider_queries"
            break

    final_included = included_count(combined_screening_rows)
    final_verified_full_text = eligible_count(
        combined_screening_rows,
        combined_availability_rows,
        full_text_required,
    )
    if final_verified_full_text < target:
        paper_label = (
            "verified-full-text papers" if full_text_required else "included papers"
        )
        warnings.append(
            f"Backfill completed with fewer {paper_label} than requested because "
            "candidate sources were exhausted before the target was reached: "
            f"target={target} eligible={final_verified_full_text}."
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
            "initial_verified_full_text_rows": initial_eligible
            if full_text_required
            else 0,
            "target_included_rows": target,
            "missing_to_target_before_backfill": missing,
            "backfill_candidates_fetched": total_backfill_fetched,
            "backfill_screened_rows": total_backfill_screened,
            "backfill_included_rows": total_backfill_included,
            "backfill_excluded_rows": total_backfill_excluded,
            "backfill_manual_review_rows": total_backfill_manual_review,
            "backfill_llm_error_rows": total_backfill_llm_errors,
            "backfill_llm_error_auto_excluded": total_backfill_llm_error_auto_excluded,
            "initial_pending_llm_finalized": initial_finalize_counts.get(
                "llm_screened",
                0,
            ),
            "final_screened_rows": len(combined_screening_rows),
            "final_included_rows": final_included,
            "final_verified_full_text_rows": final_verified_full_text
            if full_text_required
            else 0,
            "final_deduped_candidates": len(combined_deduped),
        },
        trace_paths=trace_paths,
        warnings=warnings,
        metadata={
            "max_results": max_results,
            "backfill_target_policy": "requested_max_results",
            "backfill_stop_reason": backfill_stop_reason,
            "require_full_text_availability": full_text_required,
            "fetch_diagnostics_by_round": diagnostics_by_round,
            "fetch_diagnostics": diagnostics_by_round[-1] if diagnostics_by_round else {},
            "provider_dates": candidate_provider_dates(combined_deduped),
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
    parser.add_argument(
        "--per-page",
        type=int,
        default=None,
        help="Provider page size. Defaults to the provider maximum.",
    )
    parser.add_argument("--sleep", type=float, default=0.2, help="Provider delay.")
    parser.add_argument("--trace-dir", default=None, help="Optional trace directory.")
    parser.add_argument("--availability", default=None, help="Full-text availability CSV.")
    parser.add_argument(
        "--require-full-text-availability",
        action="store_true",
        help="Count only included rows with verified full-text availability.",
    )
    parser.add_argument(
        "--full-text-availability-timeout",
        type=float,
        default=5.0,
        help="Per-URL timeout in seconds for lightweight availability checks.",
    )
    parser.add_argument(
        "--full-text-availability-workers",
        type=int,
        default=8,
        help="Parallel workers for full-text availability checks.",
    )
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
        availability_path=Path(args.availability) if args.availability else None,
        require_full_text_availability=args.require_full_text_availability,
        full_text_availability_timeout=args.full_text_availability_timeout,
        full_text_availability_workers=args.full_text_availability_workers,
    )
    print(f"Backfill triggered: {result.row_counts.get('backfill_triggered', 0)}")
    print(f"Final included rows: {result.row_counts.get('final_included_rows', 0)}")


if __name__ == "__main__":
    main()
