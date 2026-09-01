from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.metadata
import json
import os
import re
from dataclasses import dataclass
from html.parser import HTMLParser
from http.client import InvalidURL
from io import BytesIO
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urljoin, urlsplit
from urllib.request import Request, urlopen

from ad_lit_pipeline.core.step import StepResult, StepSpec
from ad_lit_pipeline.steps.full_text.evidence import MIN_USABLE_FULL_TEXT_CHARS
from ad_lit_pipeline.steps.full_text.identity import (
    IDENTITY_MISMATCH,
    IDENTITY_TRUSTED_LOCAL,
    DocumentIdentityMismatch,
    REMOTE_EXTRACTION_STATUSES,
    assess_document_identity,
    requires_remote_identity_validation,
)


STEP = StepSpec(
    name="prepare_full_text",
    inputs=["scope_screened_csv"],
    outputs=["scope_screened_full_text_csv", "full_text_manifest_csv"],
    uses_llm=False,
    description="Resolve, cache, and extract full text for papers selected for tagging.",
)

USER_AGENT = "ad-literature-knowledge-pipeline/0.1"
MIN_FULL_TEXT_CHARS = MIN_USABLE_FULL_TEXT_CHARS
FULL_TEXT_EXTRACTION_CONTRACT_VERSION = "2.0.0"
DEFAULT_REQUEST_TIMEOUT_SECONDS = 20.0

FULL_TEXT_COLUMNS = [
    "full_text_status",
    # full_text_source is retained as a compatibility alias for the resolved source.
    "full_text_source",
    "full_text_resolved_source",
    "full_text_resolved_url",
    "full_text_resolved_license",
    "full_text_text_path",
    "full_text_chars",
    "full_text_usable_for_tagging",
    "full_text_identity_status",
    "full_text_identity_evidence",
    "full_text_text_sha256",
    "full_text_extraction_engine",
    "full_text_extraction_engine_version",
    "full_text_extraction_contract_version",
    "full_text_error",
    "full_text_manual_lookup_url",
]

AVAILABILITY_COLUMNS = [
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

REMOTE_FETCH_ERRORS = (
    HTTPError,
    URLError,
    OSError,
    RuntimeError,
    ValueError,
    InvalidURL,
)

MANIFEST_COLUMNS = [
    "paper_id",
    "title",
    "doi",
    *AVAILABILITY_COLUMNS,
    *FULL_TEXT_COLUMNS,
]


@dataclass(frozen=True)
class FullTextLocation:
    source: str
    url: str
    license: str = ""


@dataclass(frozen=True)
class FullTextResult:
    status: str
    source: str = ""
    url: str = ""
    license: str = ""
    text_path: str = ""
    chars: int = 0
    identity_status: str = ""
    identity_evidence: str = ""
    text_sha256: str = ""
    extraction_engine: str = ""
    extraction_engine_version: str = ""
    extraction_contract_version: str = FULL_TEXT_EXTRACTION_CONTRACT_VERSION
    error: str = ""
    manual_lookup_url: str = ""


class SimpleHTMLTextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.skip_depth = 0
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style", "nav", "footer", "header"}:
            self.skip_depth += 1
        if tag in {"p", "div", "section", "article", "br", "li", "h1", "h2", "h3"}:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "nav", "footer", "header"} and self.skip_depth:
            self.skip_depth -= 1
        if tag in {"p", "div", "section", "article", "li", "h1", "h2", "h3"}:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self.skip_depth:
            return
        text = data.strip()
        if text:
            self.parts.append(text)

    def text(self) -> str:
        joined = " ".join(self.parts)
        joined = re.sub(r"\s*\n\s*", "\n", joined)
        joined = re.sub(r"[ \t]+", " ", joined)
        return re.sub(r"\n{3,}", "\n\n", joined).strip()


def clean_whitespace(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def clean_extracted_text(value: str) -> str:
    """Normalize horizontal whitespace while preserving headings and pages."""
    lines = [
        re.sub(r"[ \t\f\v]+", " ", line).strip()
        for line in value.splitlines()
    ]
    output: list[str] = []
    previous_blank = False
    for line in lines:
        if not line:
            if output and not previous_blank:
                output.append("")
            previous_blank = True
            continue
        output.append(line)
        previous_blank = False
    return "\n".join(output).strip()


def text_sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def package_version(name: str) -> str:
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return "unknown"


def normalize_doi(value: str) -> str:
    doi = clean_whitespace(value)
    doi = doi.replace("https://doi.org/", "")
    doi = doi.replace("http://doi.org/", "")
    doi = doi.replace("doi:", "")
    return doi.strip()


def safe_stem(row: dict[str, str], url: str = "") -> str:
    base = row.get("doi") or row.get("paper_id") or row.get("title") or "paper"
    base = normalize_doi(base).lower()
    base = re.sub(r"[^a-z0-9]+", "_", base).strip("_") or "paper"
    digest = hashlib.sha1(url.encode("utf-8")).hexdigest()[:16] if url else "local"
    return f"{base[:80]}_{digest}"


def default_cache_dir() -> Path:
    configured = os.getenv("AD_LIT_FULL_TEXT_CACHE")
    if configured:
        return Path(configured).expanduser()
    return Path.home() / ".cache" / "ad_lit_pipeline" / "full_text"


def manual_lookup_url(row: dict[str, str]) -> str:
    query = normalize_doi(row.get("doi", "")) or row.get("title", "")
    return f"https://scholar.google.com/scholar?q={quote(query)}" if query else ""


def request_timeout_seconds() -> float:
    value = os.getenv("AD_LIT_FULL_TEXT_TIMEOUT_SECONDS", "")
    if not value:
        return DEFAULT_REQUEST_TIMEOUT_SECONDS

    try:
        timeout = float(value)
    except ValueError:
        return DEFAULT_REQUEST_TIMEOUT_SECONDS

    return max(1.0, timeout)


def validate_http_url(url: str) -> str:
    cleaned = str(url or "").strip()
    if not cleaned:
        raise ValueError("URL is empty.")

    if any(marker in cleaned for marker in ("<", ">", "{{", "}}", "%=")):
        raise ValueError(f"URL appears to contain a template placeholder: {cleaned!r}")

    if re.search(r"[\x00-\x20\x7f]", cleaned):
        raise ValueError(f"URL contains control or whitespace characters: {cleaned!r}")

    parsed = urlsplit(cleaned)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError(f"URL must be absolute HTTP(S): {cleaned!r}")

    return cleaned


def is_valid_http_url(url: str) -> bool:
    try:
        validate_http_url(url)
        return True
    except ValueError:
        return False


def request_json(url: str, headers: dict[str, str] | None = None) -> dict[str, Any]:
    request_headers = {"User-Agent": USER_AGENT, **(headers or {})}
    request = Request(validate_http_url(url), headers=request_headers)
    with urlopen(request, timeout=request_timeout_seconds()) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Expected JSON object from {url}")
    return payload


def request_bytes(url: str) -> tuple[bytes, str, str]:
    request = Request(validate_http_url(url), headers={"User-Agent": USER_AGENT})
    with urlopen(request, timeout=request_timeout_seconds()) as response:
        data = response.read()
        content_type = response.headers.get("Content-Type", "")
        final_url = response.geturl()
    return data, content_type, final_url


def extract_pdf_text(data: bytes) -> str:
    try:
        from pypdf import PdfReader
    except ImportError as error:
        raise RuntimeError(
            "pypdf is required for PDF full-text extraction. "
            "Install dependencies from requirements.txt."
        ) from error

    try:
        reader = PdfReader(BytesIO(data))
        parts = []
        for page in reader.pages:
            parts.append(page.extract_text() or "")
        return clean_extracted_text("\n\n".join(parts))
    except Exception as error:
        raise ValueError(f"Could not extract PDF text: {error}") from error


def extract_html_text(data: bytes) -> str:
    parser = SimpleHTMLTextExtractor()
    parser.feed(data.decode("utf-8", errors="ignore"))
    return clean_extracted_text(parser.text())


def pdf_links_from_html(data: bytes, base_url: str) -> list[str]:
    html = data.decode("utf-8", errors="ignore")
    links = re.findall(r"""href=["']([^"']+)["']""", html, flags=re.IGNORECASE)
    urls = []
    for link in links:
        url = urljoin(base_url, link)
        lower = url.lower()
        if (
            is_valid_http_url(url)
            and (".pdf" in lower or "/pdf" in lower or "download" in lower)
        ):
            urls.append(url)
    return dedupe_strings(urls)


def is_pdf_response(url: str, content_type: str, data: bytes) -> bool:
    lower_type = content_type.lower()
    return (
        "pdf" in lower_type
        or url.lower().split("?", 1)[0].endswith(".pdf")
        or data.startswith(b"%PDF")
    )


def write_text_cache(
    row: dict[str, str],
    text: str,
    cache_dir: Path,
    url: str = "",
) -> Path:
    text_dir = cache_dir / "texts"
    text_dir.mkdir(parents=True, exist_ok=True)
    path = text_dir / f"{safe_stem(row, url)}.txt"
    path.write_text(text, encoding="utf-8")
    return path


def extract_local_file(row: dict[str, str], path: Path, cache_dir: Path) -> FullTextResult:
    if not path.exists():
        raise FileNotFoundError(path)

    if path.suffix.lower() == ".pdf":
        text = extract_pdf_text(path.read_bytes())
        status = "local_pdf_text_extracted"
    else:
        text = path.read_text(encoding="utf-8", errors="ignore")
        status = "local_text_extracted"

    if len(text) < MIN_FULL_TEXT_CHARS:
        raise ValueError(
            f"Extracted text too short for full-text tagging ({len(text)} chars)"
        )

    text_path = write_text_cache(row, text, cache_dir, str(path))
    return FullTextResult(
        status=status,
        source="local_file",
        url=str(path),
        text_path=str(text_path),
        chars=len(text),
        identity_status=IDENTITY_TRUSTED_LOCAL,
        identity_evidence="explicit_local_file",
        text_sha256=text_sha256(text),
        extraction_engine=(
            "pypdf" if path.suffix.lower() == ".pdf" else "local_text"
        ),
        extraction_engine_version=(
            package_version("pypdf") if path.suffix.lower() == ".pdf" else "1"
        ),
    )


def reuse_existing_text(row: dict[str, str]) -> FullTextResult | None:
    text_path = row.get("full_text_text_path", "").strip()
    if not text_path:
        return None

    path = Path(text_path).expanduser()
    if not path.exists():
        return None

    text = path.read_text(encoding="utf-8", errors="ignore")
    if len(text) < MIN_FULL_TEXT_CHARS:
        return None

    if (
        requires_remote_identity_validation(row)
        and row.get("full_text_extraction_contract_version", "").strip()
        != FULL_TEXT_EXTRACTION_CONTRACT_VERSION
    ):
        return None

    if requires_remote_identity_validation(row):
        identity = assess_document_identity(row, text)
        if not identity.matched:
            raise DocumentIdentityMismatch(str(path), identity)
    else:
        identity = None

    return FullTextResult(
        status=row.get("full_text_status") or "existing_text_available",
        source=row.get("full_text_source") or "existing_text_path",
        url=row.get("full_text_resolved_url") or row.get("full_text_url", ""),
        license=(
            row.get("full_text_resolved_license")
            or row.get("full_text_license", "")
        ),
        text_path=str(path),
        chars=len(text),
        identity_status=(
            identity.status if identity is not None else IDENTITY_TRUSTED_LOCAL
        ),
        identity_evidence=(
            identity.evidence if identity is not None else "existing_local_text_path"
        ),
        text_sha256=row.get("full_text_text_sha256") or text_sha256(text),
        extraction_engine=row.get("full_text_extraction_engine") or "existing_text",
        extraction_engine_version=(
            row.get("full_text_extraction_engine_version") or "unknown"
        ),
    )


def verify_remote_document_identity(
    row: dict[str, str],
    text: str,
    url: str,
) -> tuple[str, str]:
    identity = assess_document_identity(row, text)
    if not identity.matched:
        raise DocumentIdentityMismatch(url, identity)
    return identity.status, identity.evidence


def extract_remote_location(
    row: dict[str, str],
    location: FullTextLocation,
    cache_dir: Path,
) -> FullTextResult:
    data, content_type, final_url = request_bytes(location.url)

    if is_pdf_response(final_url, content_type, data):
        text = extract_pdf_text(data)
        status = "pdf_text_extracted"
    else:
        pdf_errors = []
        pdf_identity_mismatches: list[DocumentIdentityMismatch] = []
        for pdf_url in pdf_links_from_html(data, final_url)[:5]:
            try:
                pdf_data, pdf_type, pdf_final_url = request_bytes(pdf_url)
                if not is_pdf_response(pdf_final_url, pdf_type, pdf_data):
                    continue
                text = extract_pdf_text(pdf_data)
                if len(text) >= MIN_FULL_TEXT_CHARS:
                    identity_status, identity_evidence = (
                        verify_remote_document_identity(
                            row,
                            text,
                            pdf_final_url,
                        )
                    )
                    text_path = write_text_cache(row, text, cache_dir, pdf_final_url)
                    return FullTextResult(
                        status="landing_pdf_text_extracted",
                        source=location.source,
                        url=pdf_final_url,
                        license=location.license,
                        text_path=str(text_path),
                        chars=len(text),
                        identity_status=identity_status,
                        identity_evidence=identity_evidence,
                        text_sha256=text_sha256(text),
                        extraction_engine="pypdf",
                        extraction_engine_version=package_version("pypdf"),
                    )
            except DocumentIdentityMismatch as error:
                pdf_identity_mismatches.append(error)
                pdf_errors.append(f"{pdf_url}: {type(error).__name__}: {error}")
            except REMOTE_FETCH_ERRORS as error:
                pdf_errors.append(f"{pdf_url}: {type(error).__name__}: {error}")

        text = extract_html_text(data)
        status = "html_text_extracted"
        if len(text) < MIN_FULL_TEXT_CHARS and pdf_errors:
            raise ValueError(
                f"Extracted text too short for full-text tagging ({len(text)} chars); "
                + " | ".join(pdf_errors[:3])
            )

    if len(text) < MIN_FULL_TEXT_CHARS:
        raise ValueError(
            f"Extracted text too short for full-text tagging ({len(text)} chars) "
            f"from {final_url}"
        )

    try:
        identity_status, identity_evidence = verify_remote_document_identity(
            row,
            text,
            final_url,
        )
    except DocumentIdentityMismatch:
        if (
            not is_pdf_response(final_url, content_type, data)
            and pdf_identity_mismatches
        ):
            raise pdf_identity_mismatches[0]
        raise
    text_path = write_text_cache(row, text, cache_dir, final_url)
    return FullTextResult(
        status=status,
        source=location.source,
        url=final_url,
        license=location.license,
        text_path=str(text_path),
        chars=len(text),
        identity_status=identity_status,
        identity_evidence=identity_evidence,
        text_sha256=text_sha256(text),
        extraction_engine=(
            "pypdf" if status == "pdf_text_extracted" else "html_parser"
        ),
        extraction_engine_version=(
            package_version("pypdf") if status == "pdf_text_extracted" else "1"
        ),
    )


def dedupe_strings(values: list[str]) -> list[str]:
    seen = set()
    deduped = []
    for value in values:
        if value and value not in seen:
            deduped.append(value)
            seen.add(value)
    return deduped


def dedupe_locations(locations: list[FullTextLocation]) -> list[FullTextLocation]:
    seen = set()
    deduped = []
    for location in locations:
        key = location.url
        if key and key not in seen:
            deduped.append(location)
            seen.add(key)
    return deduped


def provider_metadata_locations(row: dict[str, str]) -> list[FullTextLocation]:
    locations = []
    for column in ["full_text_url", "pdf_url", "url"]:
        url = row.get(column, "").strip()
        if url.startswith(("http://", "https://")):
            locations.append(FullTextLocation("provider_metadata", url))
    doi = normalize_doi(row.get("doi", ""))
    if doi:
        locations.append(FullTextLocation("doi_landing", f"https://doi.org/{doi}"))
    return locations


def unpaywall_locations(doi: str, email: str | None) -> list[FullTextLocation]:
    if not doi or not email:
        return []

    url = f"https://api.unpaywall.org/v2/{quote(doi)}?{urlencode({'email': email})}"
    data = request_json(url)
    locations = []
    for key in ["best_oa_location", "oa_locations"]:
        value = data.get(key)
        values = value if isinstance(value, list) else [value]
        for item in values:
            if not isinstance(item, dict):
                continue
            license_value = str(item.get("license") or "")
            pdf_url = item.get("url_for_pdf")
            landing_url = item.get("url")
            if isinstance(pdf_url, str) and pdf_url:
                locations.append(FullTextLocation("unpaywall", pdf_url, license_value))
            if isinstance(landing_url, str) and landing_url:
                locations.append(
                    FullTextLocation("unpaywall", landing_url, license_value)
                )
    return locations


def europe_pmc_locations(doi: str) -> list[FullTextLocation]:
    if not doi:
        return []

    params = urlencode({"query": f'DOI:"{doi}"', "format": "json", "pageSize": "1"})
    data = request_json(f"https://www.ebi.ac.uk/europepmc/webservices/rest/search?{params}")
    results = ((data.get("resultList") or {}).get("result") or [])
    locations = []
    for result in results:
        if not isinstance(result, dict):
            continue
        urls = ((result.get("fullTextUrlList") or {}).get("fullTextUrl") or [])
        for entry in urls:
            if not isinstance(entry, dict):
                continue
            url = entry.get("url")
            if isinstance(url, str) and url:
                locations.append(FullTextLocation("europe_pmc", url))
        pmcid = result.get("pmcid")
        if isinstance(pmcid, str) and pmcid:
            locations.append(
                FullTextLocation(
                    "europe_pmc",
                    f"https://europepmc.org/articles/{pmcid}?pdf=render",
                )
            )
    return locations


def urls_from_core_result(result: dict[str, Any]) -> list[str]:
    urls = []
    for key in ["downloadUrl", "fullTextLink", "pdfUrl", "sourceFulltextUrls"]:
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
    return dedupe_strings(urls)


def core_locations(doi: str, title: str, api_key: str | None) -> list[FullTextLocation]:
    if not api_key or not (doi or title):
        return []

    query = f'doi:"{doi}"' if doi else f'title:"{title}"'
    params = urlencode({"q": query, "limit": "5"})
    data = request_json(
        f"https://api.core.ac.uk/v3/search/works?{params}",
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
            locations.append(FullTextLocation("core", url))
    return locations


def candidate_locations(
    row: dict[str, str],
    unpaywall_email: str | None,
    core_api_key: str | None,
) -> list[FullTextLocation]:
    doi = normalize_doi(row.get("doi", ""))
    locations = []
    locations.extend(provider_metadata_locations(row))
    try:
        locations.extend(unpaywall_locations(doi, unpaywall_email))
    except REMOTE_FETCH_ERRORS:
        pass
    try:
        locations.extend(europe_pmc_locations(doi))
    except REMOTE_FETCH_ERRORS:
        pass
    try:
        locations.extend(core_locations(doi, row.get("title", ""), core_api_key))
    except REMOTE_FETCH_ERRORS:
        pass
    return dedupe_locations(locations)


def resolve_full_text(
    row: dict[str, str],
    cache_dir: Path,
    unpaywall_email: str | None,
    core_api_key: str | None,
) -> FullTextResult:
    existing = row.get("full_text_path", "").strip()
    errors = []
    identity_mismatches: list[tuple[FullTextLocation, DocumentIdentityMismatch]] = []

    try:
        existing_text = reuse_existing_text(row)
    except DocumentIdentityMismatch as error:
        errors.append(f"existing_text: {type(error).__name__}: {error}")
        identity_mismatches.append(
            (FullTextLocation("existing_text_path", error.url), error)
        )
    else:
        if existing_text is not None:
            return existing_text

    if existing and not existing.startswith(("http://", "https://")):
        try:
            return extract_local_file(row, Path(existing).expanduser(), cache_dir)
        except (OSError, RuntimeError, ValueError) as error:
            errors.append(f"local_file {existing}: {type(error).__name__}: {error}")

    for location in candidate_locations(row, unpaywall_email, core_api_key):
        try:
            return extract_remote_location(row, location, cache_dir)
        except DocumentIdentityMismatch as error:
            identity_mismatches.append((location, error))
            errors.append(
                f"{location.source} {location.url}: {type(error).__name__}: {error}"
            )
        except REMOTE_FETCH_ERRORS as error:
            errors.append(
                f"{location.source} {location.url}: {type(error).__name__}: {error}"
            )

    if errors:
        if identity_mismatches:
            location, mismatch = identity_mismatches[0]
            return FullTextResult(
                status="identity_mismatch",
                source=location.source,
                url=mismatch.url,
                license=location.license,
                identity_status=IDENTITY_MISMATCH,
                identity_evidence=mismatch.assessment.evidence,
                error=" | ".join(errors),
                manual_lookup_url=manual_lookup_url(row),
            )
        return FullTextResult(
            status="extraction_failed",
            error=" | ".join(errors),
            manual_lookup_url=manual_lookup_url(row),
        )

    return FullTextResult(
        status="manual_lookup_needed",
        manual_lookup_url=manual_lookup_url(row),
    )


def read_rows(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        return list(reader.fieldnames or []), list(reader)


def output_columns(input_columns: list[str]) -> list[str]:
    columns = list(input_columns)
    for column in FULL_TEXT_COLUMNS:
        if column not in columns:
            columns.append(column)
    return columns


def result_to_columns(result: FullTextResult) -> dict[str, str]:
    remote_identity_verified = (
        result.status not in REMOTE_EXTRACTION_STATUSES
        or result.identity_status in {"verified_doi", "verified_title"}
    )
    usable_for_tagging = bool(
        result.text_path
        and result.chars >= MIN_FULL_TEXT_CHARS
        and remote_identity_verified
    )
    return {
        "full_text_status": result.status,
        "full_text_source": result.source,
        "full_text_resolved_source": result.source,
        "full_text_resolved_url": result.url,
        "full_text_resolved_license": result.license,
        "full_text_text_path": result.text_path,
        "full_text_chars": str(result.chars),
        "full_text_usable_for_tagging": "yes" if usable_for_tagging else "no",
        "full_text_identity_status": result.identity_status,
        "full_text_identity_evidence": result.identity_evidence,
        "full_text_text_sha256": result.text_sha256,
        "full_text_extraction_engine": result.extraction_engine,
        "full_text_extraction_engine_version": result.extraction_engine_version,
        "full_text_extraction_contract_version": (
            result.extraction_contract_version
        ),
        "full_text_error": result.error,
        "full_text_manual_lookup_url": result.manual_lookup_url,
    }


def write_csv(path: Path, rows: list[dict[str, str]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fieldnames})


def prepare_rows(
    rows: list[dict[str, str]],
    cache_dir: Path,
    unpaywall_email: str | None,
    core_api_key: str | None,
) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    enriched_rows = []
    manifest_rows = []
    included_rows = [row for row in rows if row.get("scope_decision") == "include"]
    included_index = 0

    for index, row in enumerate(rows, start=1):
        paper_id = row.get("paper_id") or f"row_{index}"
        if row.get("scope_decision") != "include":
            result = FullTextResult(status="skipped_not_in_scope")
        else:
            included_index += 1
            print(
                "Preparing full text "
                f"{included_index}/{len(included_rows)}: {paper_id}"
            )
            result = resolve_full_text(
                row,
                cache_dir,
                unpaywall_email,
                core_api_key,
            )

        full_text_columns = result_to_columns(result)
        enriched_rows.append({**row, **full_text_columns})
        manifest_rows.append(
            {
                "paper_id": paper_id,
                "title": row.get("title", ""),
                "doi": row.get("doi", ""),
                **{
                    column: row.get(column, "")
                    for column in AVAILABILITY_COLUMNS
                },
                **full_text_columns,
            }
        )

    return enriched_rows, manifest_rows


def run(
    input_path: Path,
    output_path: Path,
    manifest_path: Path,
    cache_dir: Path,
    unpaywall_email: str | None = None,
    core_api_key: str | None = None,
) -> StepResult:
    fieldnames, rows = read_rows(input_path)
    enriched_rows, manifest_rows = prepare_rows(
        rows,
        cache_dir.expanduser(),
        unpaywall_email,
        core_api_key,
    )
    write_csv(output_path, enriched_rows, output_columns(fieldnames))
    write_csv(manifest_path, manifest_rows, MANIFEST_COLUMNS)

    usable_full_texts = sum(
        1
        for row in manifest_rows
        if row.get("full_text_usable_for_tagging") == "yes"
    )
    manual_lookup_needed = sum(
        1 for row in manifest_rows if row.get("full_text_status") == "manual_lookup_needed"
    )
    extraction_failures = [
        row
        for row in manifest_rows
        if row.get("full_text_status") == "extraction_failed"
    ]
    identity_failures = [
        row
        for row in manifest_rows
        if row.get("full_text_status") == "identity_mismatch"
    ]
    warnings = [
        f"{row.get('paper_id') or '<unknown>'}: full-text extraction failed"
        for row in extraction_failures
    ]
    warnings.extend(
        f"{row.get('paper_id') or '<unknown>'}: extracted document identity mismatch"
        for row in identity_failures
    )

    return StepResult(
        step_name=STEP.name,
        inputs={"scope_screened_csv": input_path},
        outputs={
            "scope_screened_full_text_csv": output_path,
            "full_text_manifest_csv": manifest_path,
        },
        row_counts={
            "papers": len(rows),
            "included_papers": sum(
                1 for row in rows if row.get("scope_decision") == "include"
            ),
            # Kept as an alias for existing callers; texts may also be remote.
            "local_texts": usable_full_texts,
            "usable_full_texts": usable_full_texts,
            "extraction_failures": len(extraction_failures),
            "identity_failures": len(identity_failures),
            "manual_lookup_needed": manual_lookup_needed,
        },
        warnings=warnings,
        metadata={
            "full_text_extraction_contract_version": (
                FULL_TEXT_EXTRACTION_CONTRACT_VERSION
            ),
            "minimum_usable_full_text_chars": MIN_FULL_TEXT_CHARS,
            "remote_document_identity_required": True,
        },
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Resolve and extract paper full text.")
    parser.add_argument("--input", required=True, help="Scope-screened papers CSV.")
    parser.add_argument("--output", required=True, help="Enriched output CSV.")
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

    print(f"Rows processed: {result.row_counts['papers']}")
    print(f"Local full texts: {result.row_counts['local_texts']}")
    print(f"Wrote {args.output}")


if __name__ == "__main__":
    main()
