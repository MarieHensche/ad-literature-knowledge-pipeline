from __future__ import annotations

import argparse
import csv
import json
import os
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timezone
from http.client import HTTPException
from pathlib import Path
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urlsplit, urlunsplit
from urllib.request import Request, urlopen

from ad_lit_pipeline.core.env import load_dotenv
from ad_lit_pipeline.core.step import StepResult, StepSpec
from ad_lit_pipeline.io.yaml_io import read_yaml_object


STEP = StepSpec(
    name="verify_full_text_availability",
    inputs=["deduped_candidates_jsonl", "candidate_screening_csv", "topic_contract_yaml"],
    outputs=["full_text_availability_csv"],
    uses_llm=False,
    description="Verify lightweight full-text URL availability for collected candidates.",
)

STATUS_VERIFIED = "verified"
STATUS_PROVIDER_CLAIM_ONLY = "provider_claim_only"
STATUS_NOT_AVAILABLE = "not_available"
STATUS_UNVERIFIED = "unverified"
STATUS_SKIPPED = "skipped_not_included"
STATUS_CANDIDATE_MISSING = "candidate_missing"

DEFAULT_TIMEOUT_SECONDS = 5.0

AVAILABILITY_COLUMNS = [
    "paper_id",
    "title",
    "doi",
    "provider",
    "provider_id",
    "screening_decision",
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


@dataclass(frozen=True)
class FullTextLocation:
    source: str
    url: str
    kind: str = ""
    license: str = ""
    is_open_access: str = ""


@dataclass(frozen=True)
class AvailabilityResult:
    status: str
    source: str = ""
    url: str = ""
    kind: str = ""
    checked_at: str = ""
    content_type: str = ""
    license: str = ""
    is_open_access: str = ""
    error: str = ""


URLChecker = Callable[[FullTextLocation, float], AvailabilityResult]


def full_text_required_from_contract(path: Path) -> bool:
    contract = read_yaml_object(path)
    collection = contract.get("collection")
    if not isinstance(collection, dict):
        return False
    policy = str(collection.get("full_text_availability_policy") or "").strip()
    return (
        collection.get("require_full_text_availability") is True
        or policy == "verified_url"
    )


def normalized_bool(value: object) -> str:
    if isinstance(value, bool):
        return "yes" if value else "no"
    text = str(value or "").strip().lower()
    if text in {"yes", "true", "1"}:
        return "yes"
    if text in {"no", "false", "0"}:
        return "no"
    return ""


def normalize_url(value: object) -> str:
    url = str(value or "").strip()
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return ""
    return url


def cache_url_key(value: object) -> str:
    url = normalize_url(value)
    if not url:
        return ""
    parts = urlsplit(url)
    return urlunsplit(
        (
            parts.scheme.lower(),
            parts.netloc.lower(),
            parts.path,
            parts.query,
            "",
        )
    )


def infer_kind(url: str, raw_kind: object = "") -> str:
    kind = str(raw_kind or "").strip().lower()
    if kind in {"pdf", "html", "landing_page"}:
        return kind
    lower = url.lower().split("?", 1)[0]
    if lower.endswith(".pdf") or "/pdf" in lower:
        return "pdf"
    return "landing_page"


def location_from_mapping(value: object) -> FullTextLocation | None:
    if not isinstance(value, dict):
        return None
    url = normalize_url(value.get("url"))
    if not url:
        return None
    return FullTextLocation(
        source=str(value.get("source") or "provider_metadata"),
        url=url,
        kind=infer_kind(url, value.get("kind")),
        license=str(value.get("license") or ""),
        is_open_access=normalized_bool(value.get("is_open_access")),
    )


def generic_locations(candidate: dict[str, Any]) -> list[FullTextLocation]:
    locations = []
    for column, kind in (("full_text_url", "html"), ("pdf_url", "pdf")):
        url = normalize_url(candidate.get(column))
        if url:
            locations.append(
                FullTextLocation(
                    source="candidate_metadata",
                    url=url,
                    kind=infer_kind(url, kind),
                )
            )
    return locations


def full_text_locations(candidate: dict[str, Any]) -> list[FullTextLocation]:
    locations = []
    raw_locations = candidate.get("full_text_locations")
    if isinstance(raw_locations, list):
        for value in raw_locations:
            location = location_from_mapping(value)
            if location is not None:
                locations.append(location)
    locations.extend(generic_locations(candidate))

    seen = set()
    deduped = []
    for location in locations:
        if location.url in seen:
            continue
        seen.add(location.url)
        deduped.append(location)
    return deduped


def request_url(
    url: str,
    method: str,
    timeout_seconds: float,
) -> tuple[int, str, str]:
    headers = {"User-Agent": "ad-literature-knowledge-pipeline/0.1"}
    if method == "GET":
        headers["Range"] = "bytes=0-2047"
    request = Request(request_safe_url(url), headers=headers, method=method)
    with urlopen(request, timeout=timeout_seconds) as response:
        content_type = response.headers.get("Content-Type", "")
        final_url = response.geturl()
        if method == "GET":
            response.read(2048)
        return response.status, content_type, final_url


def request_json(
    url: str,
    timeout_seconds: float,
    headers: dict[str, str] | None = None,
) -> dict[str, Any]:
    request_headers = {"User-Agent": "ad-literature-knowledge-pipeline/0.1"}
    if headers:
        request_headers.update(headers)
    request = Request(request_safe_url(url), headers=request_headers)
    with urlopen(request, timeout=timeout_seconds) as response:
        data = json.loads(response.read().decode("utf-8"))
    if not isinstance(data, dict):
        raise ValueError("Full-text resolver response was not a JSON object.")
    return data


def is_success_status(status: int) -> bool:
    return 200 <= status < 400


def request_safe_url(url: str) -> str:
    parts = urlsplit(url)
    path = quote(parts.path, safe="/%:@!$&'()*+,;=")
    query = quote(parts.query, safe="=&%/:;+?,@!$'()*")
    return urlunsplit((parts.scheme, parts.netloc, path, query, parts.fragment))


def check_location(
    location: FullTextLocation,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
) -> AvailabilityResult:
    checked_at = datetime.now(timezone.utc).isoformat()
    errors = []
    for method in ("HEAD", "GET"):
        try:
            status, content_type, final_url = request_url(
                location.url,
                method,
                timeout_seconds,
            )
        except (
            HTTPError,
            URLError,
            HTTPException,
            TimeoutError,
            OSError,
            ValueError,
        ) as error:
            errors.append(f"{method}: {type(error).__name__}: {error}")
            continue
        if is_success_status(status):
            return AvailabilityResult(
                status=STATUS_VERIFIED,
                source=location.source,
                url=final_url or location.url,
                kind=location.kind,
                checked_at=checked_at,
                content_type=content_type,
                license=location.license,
                is_open_access=location.is_open_access,
            )
        errors.append(f"{method}: HTTP {status}")

    return AvailabilityResult(
        status=STATUS_UNVERIFIED,
        source=location.source,
        url=location.url,
        kind=location.kind,
        checked_at=checked_at,
        license=location.license,
        is_open_access=location.is_open_access,
        error=" | ".join(errors),
    )


def normalize_doi(value: object) -> str:
    doi = str(value or "").strip()
    doi = doi.replace("https://doi.org/", "")
    doi = doi.replace("http://doi.org/", "")
    doi = doi.replace("doi:", "")
    return doi.strip()


def dedupe_locations(locations: list[FullTextLocation]) -> list[FullTextLocation]:
    deduped = []
    seen = set()
    for location in locations:
        if location.url in seen:
            continue
        seen.add(location.url)
        deduped.append(location)
    return deduped


def unpaywall_locations(
    doi: str,
    email: str | None,
    timeout_seconds: float,
) -> list[FullTextLocation]:
    if not doi or not email:
        return []

    url = f"https://api.unpaywall.org/v2/{quote(doi)}?{urlencode({'email': email})}"
    data = request_json(url, timeout_seconds)
    locations = []
    for key in ("best_oa_location", "oa_locations"):
        value = data.get(key)
        values = value if isinstance(value, list) else [value]
        for item in values:
            if not isinstance(item, dict):
                continue
            license_value = str(item.get("license") or "")
            pdf_url = item.get("url_for_pdf")
            landing_url = item.get("url")
            if isinstance(pdf_url, str) and pdf_url:
                locations.append(
                    FullTextLocation(
                        "unpaywall",
                        pdf_url,
                        infer_kind(pdf_url, "pdf"),
                        license_value,
                        "yes",
                    )
                )
            if isinstance(landing_url, str) and landing_url:
                locations.append(
                    FullTextLocation(
                        "unpaywall",
                        landing_url,
                        infer_kind(landing_url, "landing_page"),
                        license_value,
                        "yes",
                    )
                )
    return dedupe_locations(locations)


def urls_from_core_result(result: dict[str, Any]) -> list[str]:
    urls = []
    for key in ("downloadUrl", "fullTextLink", "pdfUrl", "sourceFulltextUrls"):
        value = result.get(key)
        if isinstance(value, str):
            urls.append(value)
        elif isinstance(value, list):
            urls.extend(str(item) for item in value if item)
    links = result.get("links")
    if isinstance(links, list):
        for link in links:
            if isinstance(link, dict) and isinstance(link.get("url"), str):
                urls.append(link["url"])
    deduped = []
    seen = set()
    for url in urls:
        normalized = normalize_url(url)
        if normalized and normalized not in seen:
            deduped.append(normalized)
            seen.add(normalized)
    return deduped


def core_locations(
    doi: str,
    title: str,
    api_key: str | None,
    timeout_seconds: float,
) -> list[FullTextLocation]:
    if not api_key or not (doi or title):
        return []

    query = f'doi:"{doi}"' if doi else f'title:"{title}"'
    params = urlencode({"q": query, "limit": "5"})
    data = request_json(
        f"https://api.core.ac.uk/v3/search/works?{params}",
        timeout_seconds,
        headers={"Authorization": f"Bearer {api_key}"},
    )
    results = data.get("results")
    if not isinstance(results, list):
        return []

    locations = []
    for result in results:
        if not isinstance(result, dict):
            continue
        for url in urls_from_core_result(result):
            locations.append(
                FullTextLocation("core", url, infer_kind(url), is_open_access="yes")
            )
    return dedupe_locations(locations)


def external_locations(
    candidate: dict[str, Any],
    timeout_seconds: float,
    unpaywall_email: str | None = None,
    core_api_key: str | None = None,
) -> list[FullTextLocation]:
    doi = normalize_doi(candidate.get("doi"))
    title = str(candidate.get("title") or "")
    locations = []
    try:
        locations.extend(unpaywall_locations(doi, unpaywall_email, timeout_seconds))
    except (
        HTTPError,
        URLError,
        HTTPException,
        TimeoutError,
        OSError,
        ValueError,
    ):
        pass
    try:
        locations.extend(core_locations(doi, title, core_api_key, timeout_seconds))
    except (
        HTTPError,
        URLError,
        HTTPException,
        TimeoutError,
        OSError,
        ValueError,
    ):
        pass
    return dedupe_locations(locations)


def candidate_key(candidate: dict[str, Any]) -> tuple[str, str]:
    doi = str(candidate.get("doi") or "").strip().lower()
    provider_id = str(candidate.get("provider_id") or "").strip()
    return doi, provider_id


def screening_key(row: dict[str, str]) -> tuple[str, str]:
    doi = str(row.get("doi") or "").strip().lower()
    provider_id = str(row.get("provider_id") or "").strip()
    return doi, provider_id


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows = []
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            line = line.strip()
            if not line:
                continue
            value = json.loads(line)
            if not isinstance(value, dict):
                raise ValueError(f"Expected JSON object in {path}:{line_number}")
            rows.append(value)
    return rows


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=AVAILABILITY_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)


def availability_key(row: dict[str, str]) -> tuple[str, str]:
    return (
        str(row.get("doi") or "").strip().lower(),
        str(row.get("provider_id") or "").strip(),
    )


def reusable_existing_row(row: dict[str, str]) -> bool:
    return row.get("full_text_availability_status") in {
        STATUS_VERIFIED,
        STATUS_PROVIDER_CLAIM_ONLY,
        STATUS_NOT_AVAILABLE,
        STATUS_UNVERIFIED,
        STATUS_CANDIDATE_MISSING,
    }


def result_from_availability_row(row: dict[str, str]) -> AvailabilityResult:
    return AvailabilityResult(
        status=row.get("full_text_availability_status", ""),
        source=row.get("full_text_availability_source", ""),
        url=row.get("full_text_url", ""),
        kind=row.get("full_text_url_kind", ""),
        checked_at=row.get("full_text_url_checked_at", ""),
        content_type=row.get("full_text_url_content_type", ""),
        license=row.get("full_text_license", ""),
        is_open_access=row.get("full_text_is_open_access", ""),
        error=row.get("full_text_availability_error", ""),
    )


def result_for_location(
    result: AvailabilityResult,
    location: FullTextLocation,
) -> AvailabilityResult:
    return AvailabilityResult(
        status=result.status,
        source=location.source or result.source,
        url=result.url or location.url,
        kind=location.kind or result.kind,
        checked_at=result.checked_at,
        content_type=result.content_type,
        license=location.license or result.license,
        is_open_access=location.is_open_access or result.is_open_access,
        error=result.error,
    )


def cached_url_checker(
    checker: URLChecker,
    existing_rows: list[dict[str, str]] | None = None,
) -> tuple[URLChecker, Callable[[], int]]:
    cache = {
        cache_url_key(row.get("full_text_url")): result_from_availability_row(row)
        for row in existing_rows or []
        if reusable_existing_row(row) and cache_url_key(row.get("full_text_url"))
    }
    lock = threading.Lock()
    url_locks: dict[str, threading.Lock] = {}
    cache_hits = 0

    def check(location: FullTextLocation, timeout_seconds: float) -> AvailabilityResult:
        nonlocal cache_hits
        key = cache_url_key(location.url)
        if key:
            with lock:
                cached = cache.get(key)
                url_lock = url_locks.setdefault(key, threading.Lock())
            if cached is not None:
                with lock:
                    cache_hits += 1
                return result_for_location(cached, location)

            with url_lock:
                with lock:
                    cached = cache.get(key)
                if cached is not None:
                    with lock:
                        cache_hits += 1
                    return result_for_location(cached, location)

                result = checker(location, timeout_seconds)
                with lock:
                    cache[key] = result
                return result

        result = checker(location, timeout_seconds)
        return result

    def hit_count() -> int:
        with lock:
            return cache_hits

    return check, hit_count


def result_to_row(
    screening: dict[str, str],
    candidate: dict[str, Any] | None,
    result: AvailabilityResult,
) -> dict[str, str]:
    return {
        "paper_id": screening.get("paper_id", ""),
        "title": str(
            (candidate or {}).get("title")
            or screening.get("title")
            or ""
        ),
        "doi": str((candidate or {}).get("doi") or screening.get("doi") or ""),
        "provider": str((candidate or {}).get("provider") or screening.get("provider") or ""),
        "provider_id": str(
            (candidate or {}).get("provider_id")
            or screening.get("provider_id")
            or ""
        ),
        "screening_decision": screening.get("screening_decision", ""),
        "full_text_availability_status": result.status,
        "full_text_availability_source": result.source,
        "full_text_url": result.url,
        "full_text_url_kind": result.kind,
        "full_text_url_checked_at": result.checked_at,
        "full_text_url_content_type": result.content_type,
        "full_text_license": result.license,
        "full_text_is_open_access": result.is_open_access,
        "full_text_availability_error": result.error,
    }


def verify_candidate(
    candidate: dict[str, Any],
    checker: URLChecker = check_location,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    unpaywall_email: str | None = None,
    core_api_key: str | None = None,
) -> AvailabilityResult:
    provider_locations = full_text_locations(candidate)
    last_error = ""
    for location in provider_locations:
        result = checker(location, timeout_seconds)
        if result.status == STATUS_VERIFIED:
            return result
        last_error = result.error or last_error

    resolver_locations = external_locations(
        candidate,
        timeout_seconds,
        unpaywall_email=unpaywall_email,
        core_api_key=core_api_key,
    )
    locations = dedupe_locations([*provider_locations, *resolver_locations])
    if not locations:
        return AvailabilityResult(status=STATUS_NOT_AVAILABLE)

    for location in resolver_locations:
        result = checker(location, timeout_seconds)
        if result.status == STATUS_VERIFIED:
            return result
        last_error = result.error or last_error

    first = locations[0]
    return AvailabilityResult(
        status=STATUS_PROVIDER_CLAIM_ONLY if not last_error else STATUS_UNVERIFIED,
        source=first.source,
        url=first.url,
        kind=first.kind,
        license=first.license,
        is_open_access=first.is_open_access,
        error=last_error,
    )


def verify_rows(
    candidates: list[dict[str, Any]],
    screening_rows: list[dict[str, str]],
    existing_rows: list[dict[str, str]] | None = None,
    checker: URLChecker = check_location,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    workers: int = 8,
    unpaywall_email: str | None = None,
    core_api_key: str | None = None,
    stats: dict[str, int] | None = None,
) -> list[dict[str, str]]:
    candidates_by_key = {candidate_key(candidate): candidate for candidate in candidates}
    cached_checker, cache_hit_count = cached_url_checker(checker, existing_rows)
    existing_by_key = {
        availability_key(row): row
        for row in existing_rows or []
        if reusable_existing_row(row)
    }
    rows: list[dict[str, str] | None] = [None] * len(screening_rows)
    pending: dict[object, tuple[int, dict[str, str], dict[str, Any] | None]] = {}
    max_workers = max(1, workers)

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        for index, screening in enumerate(screening_rows):
            key = screening_key(screening)
            existing = existing_by_key.get(key)
            if existing is not None:
                rows[index] = existing
                continue

            candidate = candidates_by_key.get(key)
            if screening.get("screening_decision") == "exclude":
                result = AvailabilityResult(status=STATUS_SKIPPED)
                rows[index] = result_to_row(screening, candidate, result)
                continue
            if candidate is None:
                result = AvailabilityResult(
                    status=STATUS_CANDIDATE_MISSING,
                    error="Could not match screening row to candidate metadata.",
                )
                rows[index] = result_to_row(screening, candidate, result)
                continue

            future = executor.submit(
                verify_candidate,
                candidate,
                cached_checker,
                timeout_seconds,
                unpaywall_email,
                core_api_key,
            )
            pending[future] = (index, screening, candidate)

        for future in as_completed(pending):
            index, screening, candidate = pending[future]
            result = future.result()
            rows[index] = result_to_row(screening, candidate, result)

    verified_rows = [row for row in rows if row is not None]
    if stats is not None:
        stats["url_cache_hits"] = cache_hit_count()
    return verified_rows


def status_counts(rows: list[dict[str, str]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        status = row.get("full_text_availability_status") or "unknown"
        counts[status] = counts.get(status, 0) + 1
    return counts


def verified_included_keys(
    rows: list[dict[str, str]],
    screening_rows: list[dict[str, str]],
) -> set[tuple[str, str]]:
    included_keys = {
        screening_key(row)
        for row in screening_rows
        if row.get("screening_decision") == "include"
    }
    return {
        availability_key(row)
        for row in rows
        if availability_key(row) in included_keys
        and row.get("full_text_availability_status") == STATUS_VERIFIED
    }


def run(
    candidates_path: Path,
    screening_path: Path,
    output_path: Path,
    topic_contract_path: Path,
    require_full_text_availability: bool = False,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    workers: int = 8,
    checker: URLChecker = check_location,
    unpaywall_email: str | None = None,
    core_api_key: str | None = None,
) -> StepResult:
    required = (
        require_full_text_availability
        or full_text_required_from_contract(topic_contract_path)
    )
    if not required:
        return StepResult(
            step_name=STEP.name,
            inputs={
                "deduped_candidates_jsonl": candidates_path,
                "candidate_screening_csv": screening_path,
                "topic_contract_yaml": topic_contract_path,
            },
            outputs={"full_text_availability_csv": output_path},
            row_counts={"verification_skipped": 1},
            metadata={"require_full_text_availability": False},
        )

    candidates = read_jsonl(candidates_path)
    screening_rows = read_csv(screening_path)
    existing_rows = read_csv(output_path)
    stats: dict[str, int] = {}
    rows = verify_rows(
        candidates,
        screening_rows,
        existing_rows,
        checker=checker,
        timeout_seconds=timeout_seconds,
        workers=workers,
        unpaywall_email=unpaywall_email or os.getenv("UNPAYWALL_EMAIL"),
        core_api_key=core_api_key or os.getenv("CORE_API_KEY"),
        stats=stats,
    )
    write_csv(output_path, rows)
    counts = status_counts(rows)
    verified_keys = verified_included_keys(rows, screening_rows)
    url_cache_hits = stats.get("url_cache_hits", 0)

    return StepResult(
        step_name=STEP.name,
        inputs={
            "deduped_candidates_jsonl": candidates_path,
            "candidate_screening_csv": screening_path,
            "topic_contract_yaml": topic_contract_path,
        },
        outputs={"full_text_availability_csv": output_path},
        row_counts={
            "screening_rows": len(screening_rows),
            "included_screening_rows": sum(
                1
                for row in screening_rows
                if row.get("screening_decision") == "include"
            ),
            "availability_rows": len(rows),
            "candidate_missing_rows": counts.get(STATUS_CANDIDATE_MISSING, 0),
            "verified_full_text_rows": len(verified_keys),
            "url_cache_hits": url_cache_hits,
            **{f"{status}_rows": count for status, count in counts.items()},
        },
        metadata={
            "require_full_text_availability": required,
            "timeout_seconds": timeout_seconds,
            "workers": workers,
            "uses_unpaywall": bool(unpaywall_email or os.getenv("UNPAYWALL_EMAIL")),
            "uses_core": bool(core_api_key or os.getenv("CORE_API_KEY")),
        },
    )


def main() -> None:
    load_dotenv()
    parser = argparse.ArgumentParser(
        description="Verify lightweight full-text availability for collected papers."
    )
    parser.add_argument("--candidates", required=True, help="Deduped candidates JSONL.")
    parser.add_argument("--screening", required=True, help="Candidate screening CSV.")
    parser.add_argument("--output", required=True, help="Output availability CSV.")
    parser.add_argument("--topic-contract", required=True, help="Topic contract YAML.")
    parser.add_argument(
        "--require-full-text-availability",
        action="store_true",
        help="Run verification even if the topic contract does not require it.",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=DEFAULT_TIMEOUT_SECONDS,
        help="Per-URL timeout in seconds.",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=8,
        help="Parallel workers for full-text URL checks.",
    )
    parser.add_argument("--unpaywall-email", default=os.getenv("UNPAYWALL_EMAIL"))
    parser.add_argument("--core-api-key", default=os.getenv("CORE_API_KEY"))
    args = parser.parse_args()

    result = run(
        Path(args.candidates),
        Path(args.screening),
        Path(args.output),
        Path(args.topic_contract),
        require_full_text_availability=args.require_full_text_availability,
        timeout_seconds=args.timeout,
        workers=args.workers,
        unpaywall_email=args.unpaywall_email,
        core_api_key=args.core_api_key,
    )
    if result.row_counts.get("verification_skipped"):
        print("Full-text availability verification skipped.")
    else:
        print(
            "Verified full-text rows: "
            f"{result.row_counts.get('verified_full_text_rows', 0)}"
        )
        print(f"Wrote {args.output}")


if __name__ == "__main__":
    main()
