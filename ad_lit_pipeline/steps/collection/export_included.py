from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path
from typing import Any

from ad_lit_pipeline.core.step import StepResult, StepSpec
from ad_lit_pipeline.records.ids import canonical_json
from ad_lit_pipeline.steps.collection import verify_full_text_availability
from ad_lit_pipeline.topics.matching import (
    format_secondary_group_value_map,
    format_topic_value_map,
)


STEP = StepSpec(
    name="export_included_candidates",
    inputs=["deduped_candidates_jsonl", "candidate_screening_csv"],
    outputs=["papers_csv"],
    uses_llm=False,
    description="Export included screened candidates to canonical paper CSV.",
)

OUTPUT_COLUMNS = [
    "paper_id",
    "title",
    "year",
    "doi",
    "abstract",
    "authors",
    "venue",
    "url",
    "source",
    "provider",
    "provider_id",
    "publication_date",
    "corpus_publication_window_start",
    "corpus_publication_window_end",
    "corpus_publication_window_inclusive",
    "provider_record_updated_at",
    "provider_source_type",
    "provider_crossref_type",
    "language",
    "is_retracted",
    "cited_by_count",
    "source_rank",
    "retrieval_date",
    "retrieved_at",
    "source_query",
    "source_query_index",
    "source_query_rank",
    "source_query_reason",
    "source_query_url",
    "retrieval_group_id",
    "retrieval_tier",
    "retrieval_query_id",
    "retrieval_logical_query_id",
    "retrieval_iteration",
    "retrieval_phase",
    "dedupe_key",
    "duplicate_count",
    "in_fetch_duplicate_count",
    "duplicate_provenance_json",
    "in_fetch_duplicate_provenance_json",
    "retrieval_query_blocks_json",
    "full_text_locations_json",
    "candidate_observation_sha256",
    "raw_record_sha256",
    "raw_record_source_path",
    "raw_record_source_line",
    "raw_record_source_file_sha256",
    "full_text_path",
    "full_text_availability_status",
    "full_text_availability_source",
    "full_text_url",
    "full_text_url_kind",
    "full_text_url_checked_at",
    "full_text_url_content_type",
    "full_text_license",
    "full_text_is_open_access",
    "full_text_availability_error",
    "notes",
]

_SOURCE_PATH_KEY = "_raw_record_source_path"
_SOURCE_LINE_KEY = "_raw_record_source_line"
_SOURCE_FILE_HASH_KEY = "_raw_record_source_file_sha256"
_OBSERVATION_HASH_KEY = "_candidate_observation_sha256"

AVAILABILITY_OUTPUT_COLUMNS = [
    "full_text_availability_status",
    "full_text_availability_source",
    "full_text_url",
    "full_text_url_kind",
    "full_text_url_checked_at",
    "full_text_url_content_type",
    "full_text_license",
    "full_text_is_open_access",
    "full_text_availability_error",
]


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows = []
    source_file_hash = hashlib.sha256(path.read_bytes()).hexdigest()
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            line = line.strip()
            if not line:
                continue

            row = json.loads(line)
            if not isinstance(row, dict):
                raise ValueError(f"Expected JSON object in {path}:{line_number}")

            row[_OBSERVATION_HASH_KEY] = hashlib.sha256(
                canonical_json(row).encode("utf-8")
            ).hexdigest()
            row[_SOURCE_PATH_KEY] = str(path)
            row[_SOURCE_LINE_KEY] = line_number
            row[_SOURCE_FILE_HASH_KEY] = source_file_hash
            rows.append(row)

    return rows


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)

    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=OUTPUT_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)


def candidate_key(candidate: dict[str, Any]) -> tuple[str, str]:
    doi = str(candidate.get("doi") or "").strip().lower()
    provider_id = str(candidate.get("provider_id") or "").strip()
    return doi, provider_id


def screening_key(row: dict[str, str]) -> tuple[str, str]:
    doi = str(row.get("doi") or "").strip().lower()
    provider_id = str(row.get("provider_id") or "").strip()
    return doi, provider_id


def availability_key(row: dict[str, str]) -> tuple[str, str]:
    doi = str(row.get("doi") or "").strip().lower()
    provider_id = str(row.get("provider_id") or "").strip()
    return doi, provider_id


def availability_by_key(
    availability_rows: list[dict[str, str]] | None,
) -> dict[tuple[str, str], dict[str, str]]:
    return {
        availability_key(row): row
        for row in availability_rows or []
        if availability_key(row) != ("", "")
    }


def is_verified_availability(row: dict[str, str] | None) -> bool:
    return (
        row is not None
        and row.get("full_text_availability_status")
        == verify_full_text_availability.STATUS_VERIFIED
    )


def make_notes(candidate: dict[str, Any], screening: dict[str, str]) -> str:
    notes = [
        f"provider={candidate.get('provider', '')}",
        f"provider_id={candidate.get('provider_id', '')}",
        f"source_rank={candidate.get('rank', '')}",
        f"retrieval_date={candidate.get('retrieval_date', '')}",
        f"screening_confidence={screening.get('screening_confidence', '')}",
        f"screening_reason={screening.get('screening_reason', '')}",
    ]
    screening_status = screening.get("screening_status")
    if screening_status:
        notes.append(f"screening_status={screening_status}")
    for key in [
        "title_anchor_present",
        "title_relevance_tier",
        "title_matched_main_topics",
        "title_matched_secondary_topics",
        "title_missing_main_topics",
    ]:
        value = screening.get(key)
        if value:
            notes.append(f"{key}={value}")

    query = candidate.get("query")
    if query:
        notes.append(f"source_query={query}")

    query_reason = candidate.get("query_reason")
    if query_reason:
        notes.append(f"source_query_reason={query_reason}")

    dedupe_key = candidate.get("dedupe_key")
    if dedupe_key:
        notes.append(f"dedupe_key={dedupe_key}")

    duplicate_count = candidate.get("duplicate_count")
    if duplicate_count:
        notes.append(f"duplicate_count={duplicate_count}")

    in_fetch_duplicate_count = candidate.get("in_fetch_duplicate_count")
    if in_fetch_duplicate_count:
        notes.append(f"in_fetch_duplicate_count={in_fetch_duplicate_count}")

    topic_matches = candidate.get("topic_matches")
    if isinstance(topic_matches, dict):
        main_matches = format_topic_value_map(topic_matches.get("main_topic_values"))
        if main_matches:
            notes.append(f"topic_main_matches={main_matches}")
        secondary_matches = format_topic_value_map(
            topic_matches.get("secondary_topic_values")
        )
        if secondary_matches:
            notes.append(f"topic_secondary_matches={secondary_matches}")
        secondary_group_matches = format_secondary_group_value_map(
            topic_matches.get("secondary_topic_group_values")
        )
        if secondary_group_matches:
            notes.append(f"topic_secondary_group_matches={secondary_group_matches}")

    return "; ".join(str(note) for note in notes if str(note).strip())


def scalar_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def raw_record(candidate: dict[str, Any]) -> dict[str, Any]:
    value = candidate.get("raw_record")
    return value if isinstance(value, dict) else {}


def raw_record_sha256(candidate: dict[str, Any]) -> str:
    record = raw_record(candidate)
    if not record:
        return ""
    payload = canonical_json(record).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def structured_provenance_fields(candidate: dict[str, Any]) -> dict[str, str]:
    raw = raw_record(candidate)
    return {
        "provider": scalar_text(candidate.get("provider")),
        "provider_id": scalar_text(candidate.get("provider_id")),
        "publication_date": scalar_text(
            candidate.get("publication_date") or raw.get("publication_date")
        ),
        "corpus_publication_window_start": scalar_text(
            candidate.get("corpus_publication_window_start")
        ),
        "corpus_publication_window_end": scalar_text(
            candidate.get("corpus_publication_window_end")
        ),
        "corpus_publication_window_inclusive": scalar_text(
            candidate.get("corpus_publication_window_inclusive")
        ),
        "provider_record_updated_at": scalar_text(
            candidate.get("provider_record_updated_at")
            or raw.get("updated_date")
            or raw.get("updated_at")
        ),
        "provider_source_type": scalar_text(
            candidate.get("source_type") or raw.get("type")
        ),
        "provider_crossref_type": scalar_text(
            candidate.get("crossref_type") or raw.get("type_crossref")
        ),
        "language": scalar_text(candidate.get("language") or raw.get("language")),
        "is_retracted": scalar_text(raw.get("is_retracted")),
        "cited_by_count": scalar_text(raw.get("cited_by_count")),
        "source_rank": scalar_text(candidate.get("rank")),
        "retrieval_date": scalar_text(candidate.get("retrieval_date")),
        "retrieved_at": scalar_text(candidate.get("retrieved_at")),
        "source_query": scalar_text(candidate.get("query")),
        "source_query_index": scalar_text(candidate.get("query_index")),
        "source_query_rank": scalar_text(candidate.get("query_rank")),
        "source_query_reason": scalar_text(candidate.get("query_reason")),
        "source_query_url": scalar_text(candidate.get("query_url")),
        "retrieval_group_id": scalar_text(candidate.get("retrieval_group_id")),
        "retrieval_tier": scalar_text(candidate.get("retrieval_tier")),
        "retrieval_query_id": scalar_text(candidate.get("retrieval_query_id")),
        "retrieval_logical_query_id": scalar_text(
            candidate.get("retrieval_logical_query_id")
        ),
        "retrieval_iteration": scalar_text(candidate.get("retrieval_iteration")),
        "retrieval_phase": scalar_text(candidate.get("retrieval_phase")),
        "dedupe_key": scalar_text(candidate.get("dedupe_key")),
        "duplicate_count": scalar_text(candidate.get("duplicate_count")),
        "in_fetch_duplicate_count": scalar_text(
            candidate.get("in_fetch_duplicate_count")
        ),
        "duplicate_provenance_json": canonical_json(
            candidate.get("duplicate_provenance") or []
        ),
        "in_fetch_duplicate_provenance_json": canonical_json(
            candidate.get("in_fetch_duplicate_provenance") or []
        ),
        "retrieval_query_blocks_json": canonical_json(
            candidate.get("retrieval_query_blocks") or []
        ),
        "full_text_locations_json": canonical_json(
            candidate.get("full_text_locations") or []
        ),
        "candidate_observation_sha256": scalar_text(
            candidate.get(_OBSERVATION_HASH_KEY)
        ),
        "raw_record_sha256": raw_record_sha256(candidate),
        "raw_record_source_path": scalar_text(candidate.get(_SOURCE_PATH_KEY)),
        "raw_record_source_line": scalar_text(candidate.get(_SOURCE_LINE_KEY)),
        "raw_record_source_file_sha256": scalar_text(
            candidate.get(_SOURCE_FILE_HASH_KEY)
        ),
    }


def candidate_to_canonical_row(
    candidate: dict[str, Any],
    screening: dict[str, str],
    availability: dict[str, str] | None = None,
) -> dict[str, str]:
    availability_fields = {
        column: (availability or {}).get(column, "")
        for column in AVAILABILITY_OUTPUT_COLUMNS
    }
    return {
        "paper_id": screening.get("paper_id", ""),
        "title": str(candidate.get("title") or screening.get("title") or ""),
        "year": str(candidate.get("year") or screening.get("year") or ""),
        "doi": str(candidate.get("doi") or screening.get("doi") or ""),
        "abstract": str(candidate.get("abstract") or ""),
        "authors": str(candidate.get("authors") or ""),
        "venue": str(candidate.get("venue") or ""),
        "url": str(candidate.get("url") or ""),
        "source": f"collected:{candidate.get('provider', '')}",
        **structured_provenance_fields(candidate),
        "full_text_path": "",
        **availability_fields,
        "notes": make_notes(candidate, screening),
    }


def export_included(
    candidates: list[dict[str, Any]],
    screening_rows: list[dict[str, str]],
    limit: int | None = None,
    availability_rows: list[dict[str, str]] | None = None,
    require_verified_full_text: bool = False,
) -> list[dict[str, str]]:
    candidates_by_key = {candidate_key(candidate): candidate for candidate in candidates}
    full_text_availability = availability_by_key(availability_rows)

    output_rows = []

    for screening in sorted(screening_rows, key=screening_sort_key):
        if screening.get("screening_decision") != "include":
            continue

        key = screening_key(screening)
        candidate = candidates_by_key.get(key)
        availability = full_text_availability.get(key)

        if candidate is None:
            raise ValueError(
                "Could not match included screening row to candidate: "
                f"doi={key[0]} provider_id={key[1]}"
            )

        if require_verified_full_text and not is_verified_availability(availability):
            continue

        output_rows.append(candidate_to_canonical_row(candidate, screening, availability))
        if limit is not None and len(output_rows) >= limit:
            break

    return output_rows


def parse_int(value: str, default: int = 999999) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def screening_sort_key(row: dict[str, str]) -> tuple[int, int]:
    return (
        parse_int(row.get("title_relevance_tier", "")),
        parse_int(row.get("source_rank", "")),
    )


def run(
    candidates_path: Path,
    screening_path: Path,
    output_path: Path,
    max_results: int | None = None,
    availability_path: Path | None = None,
    require_full_text_availability: bool = False,
    fail_below_export_ratio: float | None = None,
) -> StepResult:
    if fail_below_export_ratio is not None and not 0 <= fail_below_export_ratio <= 1:
        raise ValueError("--fail-below-export-ratio must be between 0 and 1.")

    candidates = read_jsonl(candidates_path)
    screening_rows = read_csv(screening_path)
    availability_rows = (
        read_csv(availability_path)
        if availability_path is not None and availability_path.exists()
        else []
    )
    output_rows = export_included(
        candidates,
        screening_rows,
        max_results,
        availability_rows=availability_rows,
        require_verified_full_text=require_full_text_availability,
    )
    write_csv(output_path, output_rows)
    included_screening_rows = sum(
        1 for row in screening_rows if row.get("screening_decision") == "include"
    )
    excluded_screening_rows = sum(
        1 for row in screening_rows if row.get("screening_decision") == "exclude"
    )
    review_screening_rows = sum(
        1 for row in screening_rows if row.get("screening_decision") == "review"
    )
    availability_lookup = availability_by_key(availability_rows)
    included_rows = [
        row for row in screening_rows if row.get("screening_decision") == "include"
    ]
    verified_full_text_rows = sum(
        1
        for row in included_rows
        if is_verified_availability(availability_lookup.get(screening_key(row)))
    )
    skipped_full_text_unverified = (
        sum(
            1
            for row in included_rows
            if not is_verified_availability(availability_lookup.get(screening_key(row)))
        )
        if require_full_text_availability
        else 0
    )
    warnings = []
    export_ratio = (
        len(output_rows) / max_results
        if max_results is not None and max_results > 0
        else None
    )
    error = None
    if max_results is not None and len(output_rows) < max_results:
        if require_full_text_availability:
            warnings.append(
                "Exported fewer verified-full-text papers than requested; "
                "candidate sources may have been exhausted before the target "
                "was reached, or some included candidates did not have a "
                "reachable full-text URL: "
                f"requested={max_results} exported={len(output_rows)}."
            )
        else:
            warnings.append(
                "Exported fewer included papers than requested; candidate sources "
                "may have been exhausted before the target was reached: "
                f"requested={max_results} exported={len(output_rows)}."
            )

    if (
        fail_below_export_ratio is not None
        and export_ratio is not None
        and export_ratio < fail_below_export_ratio
    ):
        error = (
            "Export quality gate failed: "
            f"exported={len(output_rows)} requested={max_results} "
            f"ratio={export_ratio:.3f} "
            f"threshold={fail_below_export_ratio:.3f}."
        )

    inputs = {
        "deduped_candidates_jsonl": candidates_path,
        "candidate_screening_csv": screening_path,
    }
    if availability_path is not None:
        inputs["full_text_availability_csv"] = availability_path

    return StepResult(
        step_name=STEP.name,
        inputs=inputs,
        outputs={"papers_csv": output_path},
        row_counts={
            "screened_rows": len(screening_rows),
            "included_screening_rows": included_screening_rows,
            "excluded_screening_rows": excluded_screening_rows,
            "review_screening_rows": review_screening_rows,
            "verified_full_text_rows": verified_full_text_rows,
            "skipped_full_text_unverified": skipped_full_text_unverified,
            "included_rows_exported": len(output_rows),
            "skipped_by_export_cap": max(
                0,
                included_screening_rows
                - skipped_full_text_unverified
                - len(output_rows),
            ),
        },
        warnings=warnings,
        error=error,
        metadata={
            "max_results": max_results,
            "target_export_rows": max_results,
            "export_target_policy": "requested_max_results",
            "require_full_text_availability": require_full_text_availability,
            "export_ratio": export_ratio,
            "fail_below_export_ratio": fail_below_export_ratio,
        },
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Export included screened candidates to canonical CSV."
    )
    parser.add_argument("--candidates", required=True, help="Deduplicated candidates JSONL.")
    parser.add_argument("--screening", required=True, help="Candidate screening CSV.")
    parser.add_argument("--output", required=True, help="Output canonical paper CSV.")
    parser.add_argument(
        "--max-results",
        type=int,
        default=None,
        help="Optional maximum number of included rows to export.",
    )
    parser.add_argument(
        "--availability",
        default=None,
        help="Optional full-text availability CSV.",
    )
    parser.add_argument(
        "--require-full-text-availability",
        action="store_true",
        help="Export only included rows with verified full-text availability.",
    )
    parser.add_argument(
        "--fail-below-export-ratio",
        type=float,
        default=None,
        help=(
            "Fail the export step if exported rows divided by --max-results "
            "is below this ratio."
        ),
    )
    args = parser.parse_args()

    result = run(
        Path(args.candidates),
        Path(args.screening),
        Path(args.output),
        args.max_results,
        availability_path=Path(args.availability) if args.availability else None,
        require_full_text_availability=args.require_full_text_availability,
        fail_below_export_ratio=args.fail_below_export_ratio,
    )

    print(f"Screened rows: {result.row_counts['screened_rows']}")
    print(f"Included rows exported: {result.row_counts['included_rows_exported']}")
    if result.error:
        raise SystemExit(result.error)
    print(f"Wrote {args.output}")
