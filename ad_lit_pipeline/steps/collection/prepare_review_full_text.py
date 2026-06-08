from __future__ import annotations

import argparse
import os
from pathlib import Path
from typing import Any

from ad_lit_pipeline.core.step import StepResult, StepSpec
from ad_lit_pipeline.io.jsonl_io import read_jsonl_objects, write_jsonl
from ad_lit_pipeline.steps.full_text.prepare import (
    FullTextResult,
    MANIFEST_COLUMNS,
    default_cache_dir,
    resolve_full_text,
    result_to_columns,
    write_csv,
)


STEP = StepSpec(
    name="prepare_review_full_text",
    inputs=["review_overviews_jsonl"],
    outputs=["review_overviews_full_text_jsonl", "review_full_text_manifest_csv"],
    uses_llm=False,
    description="Resolve, cache, and extract full text for review candidates.",
)


def as_mapping(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def as_list(value: object) -> list[Any]:
    return value if isinstance(value, list) else []


def append_url(urls: list[str], value: object) -> None:
    url = str(value or "").strip()
    if url.startswith(("http://", "https://")) and url not in urls:
        urls.append(url)


def review_full_text_urls(record: dict[str, Any]) -> list[str]:
    """Return likely full-text locations from OpenAlex and enriched metadata."""
    raw = as_mapping(record.get("raw_record"))
    best_oa_location = as_mapping(
        record.get("best_oa_location") or raw.get("best_oa_location")
    )
    open_access = as_mapping(record.get("open_access") or raw.get("open_access"))
    primary_location = as_mapping(raw.get("primary_location"))
    content_urls = as_mapping(raw.get("content_urls"))

    urls: list[str] = []
    for key in ["full_text_url", "pdf_url"]:
        append_url(urls, record.get(key))

    append_url(urls, content_urls.get("pdf"))
    append_url(urls, best_oa_location.get("pdf_url"))
    append_url(urls, open_access.get("oa_url"))
    append_url(urls, best_oa_location.get("landing_page_url"))
    append_url(urls, primary_location.get("pdf_url"))
    append_url(urls, primary_location.get("landing_page_url"))

    for location in as_list(raw.get("locations")):
        location_map = as_mapping(location)
        append_url(urls, location_map.get("pdf_url"))
        append_url(urls, location_map.get("landing_page_url"))

    append_url(urls, record.get("url"))
    return urls


def review_paper_id(record: dict[str, Any], index: int) -> str:
    for key in ["paper_id", "provider_id", "doi"]:
        value = str(record.get(key) or "").strip()
        if value:
            return value
    return f"review_{index}"


def review_to_full_text_row(record: dict[str, Any], index: int) -> dict[str, str]:
    """Adapt a review JSONL record to the row shape used by full-text prep."""
    urls = review_full_text_urls(record)
    url = str(record.get("url") or "").strip()
    if not url and len(urls) >= 3:
        url = urls[2]
    elif not url and urls:
        url = urls[-1]

    return {
        "paper_id": review_paper_id(record, index),
        "title": str(record.get("title") or ""),
        "doi": str(record.get("doi") or ""),
        "abstract": str(record.get("abstract") or ""),
        "url": url,
        "full_text_path": str(record.get("full_text_path") or ""),
        "full_text_url": urls[0] if urls else "",
        "pdf_url": urls[1] if len(urls) > 1 else "",
    }


def int_value(value: object) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def existing_full_text_result(record: dict[str, Any]) -> FullTextResult | None:
    text_path = str(record.get("full_text_text_path") or "").strip()
    chars = int_value(record.get("full_text_chars"))
    if not text_path or chars <= 0:
        return None
    if not Path(text_path).expanduser().exists():
        return None

    return FullTextResult(
        status=str(record.get("full_text_status") or "cached_text_available"),
        source=str(record.get("full_text_source") or ""),
        url=str(record.get("full_text_url") or ""),
        license=str(record.get("full_text_license") or ""),
        text_path=text_path,
        chars=chars,
        error=str(record.get("full_text_error") or ""),
        manual_lookup_url=str(record.get("full_text_manual_lookup_url") or ""),
    )


def prepare_review_records(
    records: list[dict[str, Any]],
    cache_dir: Path,
    unpaywall_email: str | None,
    core_api_key: str | None,
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    enriched_records: list[dict[str, Any]] = []
    manifest_rows: list[dict[str, str]] = []

    for index, record in enumerate(records, start=1):
        row = review_to_full_text_row(record, index)
        print(f"Preparing review full text {index}/{len(records)}: {row['paper_id']}")
        result = existing_full_text_result(record)
        if result is None:
            result = resolve_full_text(
                row,
                cache_dir,
                unpaywall_email,
                core_api_key,
            )

        full_text_columns = result_to_columns(result)
        enriched_records.append({**record, **full_text_columns})
        manifest_rows.append(
            {
                "paper_id": row["paper_id"],
                "title": row["title"],
                "doi": row["doi"],
                **full_text_columns,
            }
        )

    return enriched_records, manifest_rows


def run(
    input_path: Path,
    output_path: Path,
    manifest_path: Path,
    cache_dir: Path,
    unpaywall_email: str | None = None,
    core_api_key: str | None = None,
) -> StepResult:
    records = read_jsonl_objects(input_path)
    enriched_records, manifest_rows = prepare_review_records(
        records,
        cache_dir.expanduser(),
        unpaywall_email,
        core_api_key,
    )
    write_jsonl(output_path, enriched_records)
    write_csv(manifest_path, manifest_rows, MANIFEST_COLUMNS)

    local_texts = sum(
        1
        for row in manifest_rows
        if row.get("full_text_text_path") and int_value(row.get("full_text_chars")) > 0
    )
    manual_lookup_needed = sum(
        1
        for row in manifest_rows
        if row.get("full_text_status") == "manual_lookup_needed"
    )

    return StepResult(
        step_name=STEP.name,
        inputs={"review_overviews_jsonl": input_path},
        outputs={
            "review_overviews_full_text_jsonl": output_path,
            "review_full_text_manifest_csv": manifest_path,
        },
        row_counts={
            "review_overviews": len(records),
            "local_texts": local_texts,
            "manual_lookup_needed": manual_lookup_needed,
        },
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Resolve and extract full text for review/overview seed papers."
    )
    parser.add_argument("--input", required=True, help="Review/overview JSONL.")
    parser.add_argument("--output", required=True, help="Enriched review JSONL.")
    parser.add_argument("--manifest", required=True, help="Full-text manifest CSV.")
    parser.add_argument(
        "--cache-dir",
        default=str(default_cache_dir()),
        help="External directory for extracted full-text cache.",
    )
    parser.add_argument("--unpaywall-email", default=os.getenv("UNPAYWALL_EMAIL"))
    parser.add_argument("--core-api-key", default=os.getenv("CORE_API_KEY"))
    args = parser.parse_args()

    result = run(
        Path(args.input),
        Path(args.output),
        Path(args.manifest),
        Path(args.cache_dir),
        args.unpaywall_email,
        args.core_api_key,
    )

    print(f"Review/overview records: {result.row_counts['review_overviews']}")
    print(f"Local full texts: {result.row_counts['local_texts']}")
    print(f"Wrote {args.output}")


if __name__ == "__main__":
    main()
