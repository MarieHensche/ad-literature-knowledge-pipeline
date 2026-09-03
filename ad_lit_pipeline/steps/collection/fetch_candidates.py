from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from ad_lit_pipeline.core.errors import UnsupportedProviderError
from ad_lit_pipeline.core.step import StepResult, StepSpec
from ad_lit_pipeline.io.json_io import read_json_object
from ad_lit_pipeline.io.jsonl_io import write_jsonl
from ad_lit_pipeline.providers.base import CandidateProvider, candidate_provider_dates
from ad_lit_pipeline.providers.evidence import (
    ProviderEvidenceArchive,
    candidate_evidence_errors,
    read_provider_evidence_index,
    sha256_bytes,
    unavailable_provider_evidence,
    verify_provider_evidence,
)
from ad_lit_pipeline.providers.openalex import OpenAlexProvider


STEP = StepSpec(
    name="fetch_candidates",
    inputs=["search_plan_json"],
    outputs=[
        "candidates_jsonl",
        "provider_evidence_index_jsonl",
        "provider_response_pages_dir",
    ],
    uses_llm=False,
    description="Fetch candidate papers from the provider selected in a search plan.",
)


PROVIDERS: dict[str, CandidateProvider] = {
    "openalex": OpenAlexProvider(),
}

CORPUS_PUBLICATION_WINDOW_START = "corpus_publication_window_start"
CORPUS_PUBLICATION_WINDOW_END = "corpus_publication_window_end"
CORPUS_PUBLICATION_WINDOW_INCLUSIVE = "corpus_publication_window_inclusive"


@dataclass(frozen=True)
class PublicationWindow:
    start: date
    end: date
    requires_exact_date: bool


def publication_window_from_plan(
    plan: dict[str, Any],
) -> PublicationWindow | None:
    """Return the resolved inclusive publication window from a search plan."""
    constraints = plan.get("corpus_constraints")
    if isinstance(constraints, dict):
        window = constraints.get("publication_window")
        if isinstance(window, dict):
            return PublicationWindow(
                start=date.fromisoformat(str(window["start"])),
                end=date.fromisoformat(str(window["end"])),
                requires_exact_date=True,
            )

    provider_plan = plan.get("provider_specific_plan")
    provider_filters = (
        provider_plan.get("filters") if isinstance(provider_plan, dict) else None
    )
    exact_dates: dict[str, date] = {}
    if isinstance(provider_filters, list):
        for item in provider_filters:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or "").strip()
            if name not in {"from_publication_date", "to_publication_date"}:
                continue
            try:
                exact_dates[name] = date.fromisoformat(str(item.get("value") or ""))
            except ValueError:
                continue
    if {
        "from_publication_date",
        "to_publication_date",
    }.issubset(exact_dates):
        return PublicationWindow(
            start=exact_dates["from_publication_date"],
            end=exact_dates["to_publication_date"],
            requires_exact_date=True,
        )

    filters = plan.get("filters")
    if not isinstance(filters, dict):
        return None
    year_from = filters.get("year_from")
    year_to = filters.get("year_to")
    if not isinstance(year_from, int) and not isinstance(year_to, int):
        return None
    start_year = year_from if isinstance(year_from, int) else 1
    end_year = year_to if isinstance(year_to, int) else 9999
    return PublicationWindow(
        start=date(start_year, 1, 1),
        end=date(end_year, 12, 31),
        requires_exact_date=False,
    )


def candidate_publication_date(candidate: dict[str, Any]) -> date | None:
    raw_record = candidate.get("raw_record")
    raw = raw_record if isinstance(raw_record, dict) else {}
    value = candidate.get("publication_date") or raw.get("publication_date")
    if value:
        try:
            return date.fromisoformat(str(value))
        except ValueError:
            return None
    return None


def enforce_candidate_publication_window(
    candidates: list[dict[str, Any]],
    plan: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    """Reject provider records that cannot prove temporal eligibility."""
    window = publication_window_from_plan(plan)
    if window is None:
        return candidates, []

    eligible = []
    rejected = []
    for candidate in candidates:
        publication_date = candidate_publication_date(candidate)
        raw_year = candidate.get("year")
        if publication_date is None and not window.requires_exact_date:
            try:
                publication_date = date(int(raw_year), 1, 1)
            except (TypeError, ValueError):
                publication_date = None

        publication_year_mismatch = False
        if publication_date is not None and str(raw_year or "").strip():
            try:
                publication_year_mismatch = int(raw_year) != publication_date.year
            except (TypeError, ValueError):
                publication_year_mismatch = True

        if publication_date is None:
            reason = (
                "missing_or_invalid_exact_publication_date"
                if window.requires_exact_date
                else "missing_or_invalid_publication_year"
            )
        elif publication_year_mismatch:
            reason = "publication_date_year_mismatch"
        elif publication_date < window.start:
            reason = "before_publication_window"
        elif publication_date > window.end:
            reason = "after_publication_window"
        else:
            candidate[CORPUS_PUBLICATION_WINDOW_START] = window.start.isoformat()
            candidate[CORPUS_PUBLICATION_WINDOW_END] = window.end.isoformat()
            candidate[CORPUS_PUBLICATION_WINDOW_INCLUSIVE] = True
            eligible.append(candidate)
            continue

        rejected.append(
            {
                "provider": str(candidate.get("provider") or ""),
                "provider_id": str(candidate.get("provider_id") or ""),
                "doi": str(candidate.get("doi") or ""),
                "publication_date": (
                    publication_date.isoformat() if publication_date else ""
                ),
                "year": str(raw_year or ""),
                "reason": reason,
            }
        )

    return eligible, rejected


def provider_max_per_page(provider: CandidateProvider) -> int:
    try:
        value = int(getattr(provider, "max_per_page"))
    except (AttributeError, TypeError, ValueError):
        value = 100
    return max(1, value)


def resolve_per_page(
    provider: CandidateProvider,
    requested_per_page: int | None = None,
) -> int:
    max_per_page = provider_max_per_page(provider)
    if requested_per_page is None:
        return max_per_page
    return max(1, min(int(requested_per_page), max_per_page))


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


def default_provider_evidence_paths(output_path: Path) -> tuple[Path, Path]:
    """Derive provider-neutral evidence paths for direct step invocation."""
    stem = output_path.stem
    for suffix in ("_provider_candidates", "_openalex_candidates", "_candidates"):
        if stem.endswith(suffix):
            stem = stem[: -len(suffix)]
            break
    index_path = output_path.with_name(f"{stem}_provider_evidence_index.jsonl")
    archive_root = output_path.with_name(f"{stem}_provider_response_pages")
    return index_path, archive_root


def run(
    plan_path: Path,
    output_path: Path,
    max_results: int | None = None,
    per_page: int | None = None,
    mailto: str | None = None,
    sleep_seconds: float = 0.2,
    provider_evidence_index_path: Path | None = None,
    provider_response_pages_dir: Path | None = None,
) -> StepResult:
    plan = read_json_object(plan_path)
    provider_plan = plan.get("provider_specific_plan")
    if not isinstance(provider_plan, dict):
        raise ValueError("Plan must contain provider_specific_plan.")

    provider_name = provider_name_from_plan(plan)
    provider = get_provider(provider_name)
    provider.validate_plan(plan)
    resolved_per_page = resolve_per_page(provider, per_page)
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
    default_index, default_archive = default_provider_evidence_paths(output_path)
    evidence_index = provider_evidence_index_path or default_index
    evidence_archive_root = provider_response_pages_dir or default_archive
    evidence_archive = ProviderEvidenceArchive(
        evidence_archive_root,
        evidence_index,
        append_existing=False,
    )
    evidence_archive.flush()
    evidence_supported = bool(
        getattr(provider, "supports_immutable_provider_evidence", False)
    )
    if evidence_supported:
        fetched_candidates = provider.fetch_candidates(
            plan=plan,
            max_results=resolved_max_results,
            per_page=resolved_per_page,
            mailto=mailto,
            sleep_seconds=sleep_seconds,
            evidence_archive=evidence_archive,
        )
    else:
        fetched_candidates = provider.fetch_candidates(
            plan=plan,
            max_results=resolved_max_results,
            per_page=resolved_per_page,
            mailto=mailto,
            sleep_seconds=sleep_seconds,
        )
    for candidate in fetched_candidates:
        candidate.setdefault(
            "provider_evidence",
            unavailable_provider_evidence(
                "provider_adapter_does_not_emit_immutable_evidence"
            ),
        )
    candidates, publication_window_rejections = (
        enforce_candidate_publication_window(fetched_candidates, plan)
    )
    publication_window = publication_window_from_plan(plan)
    diagnostics = getattr(provider, "last_fetch_diagnostics", {})
    if not isinstance(diagnostics, dict):
        diagnostics = {}
    warnings = []
    if publication_window_rejections:
        warnings.append(
            "Rejected provider candidates that did not prove publication-window "
            "eligibility: "
            f"rejected={len(publication_window_rejections)}."
        )
    if len(candidates) < resolved_max_results:
        warnings.append(
            "Fetched fewer unique candidates than requested after all available "
            f"query groups: requested={resolved_max_results} fetched={len(candidates)}."
        )
    planned_execution_queries = diagnostics.get("planned_execution_query_count")
    executed_queries = diagnostics.get("executed_query_count")
    if (
        len(candidates) >= resolved_max_results
        and isinstance(planned_execution_queries, int)
        and isinstance(executed_queries, int)
        and executed_queries < planned_execution_queries
    ):
        warnings.append(
            "Tiered retrieval reached the unique-candidate target before all "
            "planned execution queries ran: "
            f"executed={executed_queries} planned={planned_execution_queries}."
        )

    evidence_archive.flush()
    evidence_verification = verify_provider_evidence(
        evidence_index,
        evidence_archive_root,
    )
    if not evidence_verification.valid:
        raise ValueError(
            "fetch_candidates provider evidence verification failed: "
            + "; ".join(evidence_verification.errors)
        )
    link_errors = candidate_evidence_errors(
        candidates,
        read_provider_evidence_index(evidence_index),
        require_archived=evidence_supported,
    )
    if link_errors:
        raise ValueError(
            "fetch_candidates candidate evidence links failed: "
            + "; ".join(link_errors)
        )

    write_jsonl(output_path, candidates)
    row_counts = {
        "provider_candidates_returned": len(fetched_candidates),
        "publication_window_rejections": len(publication_window_rejections),
        "fetched_candidates": len(candidates),
        "provider_response_pages": evidence_verification.record_count,
        "provider_response_archive_files": (
            evidence_verification.archive_file_count
        ),
        "provider_response_bytes": evidence_verification.total_response_bytes,
    }
    for key in [
        "target_candidates",
        "raw_provider_candidates_seen",
        "in_fetch_duplicates_removed",
        "unique_candidates",
        "exhausted_query_count",
        "logical_query_count",
        "execution_query_count",
        "planned_logical_query_count",
        "planned_execution_query_count",
        "executed_logical_query_count",
        "executed_query_count",
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
        outputs={
            "candidates_jsonl": output_path,
            "provider_evidence_index_jsonl": evidence_index,
            "provider_response_pages_dir": evidence_archive_root,
        },
        row_counts=row_counts,
        warnings=warnings,
        metadata={
            "provider": provider_name,
            "per_page": resolved_per_page,
            "provider_max_per_page": provider_max_per_page(provider),
            "search_queries": search_query_count,
            "provider_dates": candidate_provider_dates(candidates),
            "publication_window": (
                {
                    "start": publication_window.start.isoformat(),
                    "end": publication_window.end.isoformat(),
                    "inclusive": True,
                }
                if publication_window is not None
                else None
            ),
            "publication_window_rejections": publication_window_rejections,
            "fetch_diagnostics": diagnostics,
            "provider_evidence": {
                "schema_version": "1.0.0",
                "status": "verified" if evidence_verification.valid else "failed",
                "adapter_supports_immutable_evidence": evidence_supported,
                "index_sha256": sha256_bytes(evidence_index.read_bytes()),
                "page_records": evidence_verification.record_count,
                "archive_files": evidence_verification.archive_file_count,
                "response_bytes": evidence_verification.total_response_bytes,
                "candidate_links_verified": len(candidates),
            },
        },
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch candidate papers.")
    parser.add_argument("--plan", required=True, help="Input search plan JSON.")
    parser.add_argument("--output", required=True, help="Output candidates JSONL.")
    parser.add_argument("--max-results", type=int, default=None, help="Override max result count.")
    parser.add_argument(
        "--per-page",
        type=int,
        default=None,
        help="Provider page size. Defaults to the provider maximum.",
    )
    parser.add_argument("--mailto", default=None, help="Optional email for provider polite pool.")
    parser.add_argument("--sleep", type=float, default=0.2, help="Delay between API pages.")
    parser.add_argument(
        "--provider-evidence-index",
        default=None,
        help="Provider-neutral immutable response-page index JSONL.",
    )
    parser.add_argument(
        "--provider-response-pages-dir",
        default=None,
        help="Content-addressed raw provider response-page directory.",
    )
    args = parser.parse_args()

    result = run(
        Path(args.plan),
        Path(args.output),
        args.max_results,
        args.per_page,
        args.mailto,
        args.sleep,
        (
            Path(args.provider_evidence_index)
            if args.provider_evidence_index
            else None
        ),
        (
            Path(args.provider_response_pages_dir)
            if args.provider_response_pages_dir
            else None
        ),
    )

    print(f"Fetched candidates: {result.row_counts['fetched_candidates']}")
    print(f"Wrote {args.output}")
