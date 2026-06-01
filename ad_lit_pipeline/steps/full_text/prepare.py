from __future__ import annotations

import argparse
import csv
import hashlib
import html
import os
import re
import shutil
import tempfile
import urllib.parse
import urllib.request
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from typing import Protocol

from ad_lit_pipeline.core.step import StepResult, StepSpec
from ad_lit_pipeline.providers.full_text import (
    FullTextLocation,
    NetworkFullTextResolver,
)
from ad_lit_pipeline.steps.full_text.evidence import MIN_FULL_TEXT_CHARS, clean_text


STEP = StepSpec(
    name="prepare_full_text",
    inputs=["scope_screened_csv"],
    outputs=["scope_screened_full_text_csv", "full_text_manifest_csv"],
    uses_llm=False,
    description="Resolve, cache, and extract full text for papers selected for tagging.",
)

FULL_TEXT_COLUMNS = [
    "full_text_status",
    "full_text_source",
    "full_text_url",
    "full_text_license",
    "full_text_text_path",
    "full_text_chars",
    "full_text_error",
    "full_text_manual_lookup_url",
]


class FullTextResolver(Protocol):
    def resolve(self, row: dict[str, str]) -> FullTextLocation:
        """Resolve a row to a local path or remote full-text URL."""


@dataclass(frozen=True)
class PreparedFullText:
    status: str
    source: str = ""
    url: str = ""
    license: str = ""
    text_path: str = ""
    text_chars: int = 0
    error: str = ""
    manual_lookup_url: str = ""


class HtmlTextExtractor(HTMLParser):
    """Small stdlib HTML-to-text extractor for open landing pages."""

    def __init__(self) -> None:
        super().__init__()
        self.skip = False
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style", "nav", "footer", "header"}:
            self.skip = True

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "nav", "footer", "header"}:
            self.skip = False

    def handle_data(self, data: str) -> None:
        if self.skip:
            return
        text = data.strip()
        if text:
            self.parts.append(text)

    def text(self) -> str:
        raw = " ".join(self.parts)
        raw = html.unescape(raw)
        return clean_text(re.sub(r"\s+", " ", raw))


def default_cache_dir() -> Path:
    configured = os.getenv("AD_LIT_FULL_TEXT_CACHE")
    if configured:
        return Path(configured).expanduser()
    return Path.home() / ".cache" / "ad_lit_pipeline" / "full_text"


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


def write_csv(path: Path, rows: list[dict[str, str]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({column: row.get(column, "") for column in fieldnames})


def cache_key(row: dict[str, str]) -> str:
    stable = row.get("doi") or row.get("paper_id") or row.get("title") or repr(row)
    digest = hashlib.sha256(stable.encode("utf-8")).hexdigest()[:16]
    stem = re.sub(r"[^A-Za-z0-9_.-]+", "_", stable)[:80].strip("_")
    return f"{stem}_{digest}" if stem else digest


def request_url(url: str, timeout_seconds: int, user_agent: str) -> tuple[bytes, str, str]:
    request = urllib.request.Request(url, headers={"User-Agent": user_agent})
    with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
        return (
            response.read(),
            response.headers.get("content-type", ""),
            response.geturl(),
        )


def extract_pdf_text(path: Path) -> str:
    try:
        from pypdf import PdfReader
    except ImportError as error:
        raise RuntimeError(
            "pypdf is required to extract PDF full text. Install it with "
            "`python -m pip install pypdf`."
        ) from error

    reader = PdfReader(str(path))
    parts: list[str] = []
    for page in reader.pages:
        try:
            text = page.extract_text() or ""
        except Exception:
            text = ""
        if text.strip():
            parts.append(text.strip())
    return clean_text("\n\n".join(parts))


def extract_html_text(content: bytes) -> str:
    parser = HtmlTextExtractor()
    parser.feed(content.decode("utf-8", errors="ignore"))
    return parser.text()


def candidate_pdf_links(content: bytes, base_url: str) -> list[str]:
    text = content.decode("utf-8", errors="ignore")
    patterns = [
        r'<meta[^>]+name=["\']citation_pdf_url["\'][^>]+content=["\']([^"\']+)["\']',
        r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+name=["\']citation_pdf_url["\']',
        r'href=["\']([^"\']+\.pdf(?:\?[^"\']*)?)["\']',
        r'href=["\']([^"\']*(?:download|pdf)[^"\']*)["\']',
    ]
    links: list[str] = []
    seen: set[str] = set()
    for pattern in patterns:
        for match in re.findall(pattern, text, flags=re.IGNORECASE):
            url = urllib.parse.urljoin(base_url, html.unescape(match))
            if url and url not in seen:
                links.append(url)
                seen.add(url)
    return links[:5]


def write_cached_text(path: Path, text: str) -> PreparedFullText:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return PreparedFullText(
        status="text_extracted",
        text_path=str(path),
        text_chars=len(text),
    )


def text_too_short(text: str) -> bool:
    return len(clean_text(text)) < MIN_FULL_TEXT_CHARS


def extract_local_path(
    path: Path,
    text_path: Path,
    location: FullTextLocation,
) -> PreparedFullText:
    if path.suffix.lower() in {".txt", ".text", ".md"}:
        text = clean_text(path.read_text(encoding="utf-8", errors="ignore"))
    elif path.suffix.lower() == ".pdf":
        text = extract_pdf_text(path)
    else:
        text = extract_html_text(path.read_bytes())

    if not text:
        return PreparedFullText(
            status="extraction_failed",
            source=location.source,
            error=f"No text extracted from local file: {path}",
        )

    prepared = write_cached_text(text_path, text)
    return PreparedFullText(
        status="local_text_extracted",
        source=location.source,
        license=location.license,
        text_path=prepared.text_path,
        text_chars=prepared.text_chars,
    )


def extract_remote_url(
    url: str,
    text_path: Path,
    location: FullTextLocation,
    timeout_seconds: int,
    user_agent: str,
) -> PreparedFullText:
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir) / "download"
        content, content_type, final_url = request_url(url, timeout_seconds, user_agent)
        tmp_path.write_bytes(content)
        is_pdf = (
            ".pdf" in final_url.lower()
            or "pdf" in content_type.lower()
            or content[:4] == b"%PDF"
        )

        if is_pdf:
            pdf_path = tmp_path.with_suffix(".pdf")
            shutil.move(str(tmp_path), pdf_path)
            text = extract_pdf_text(pdf_path)
            status = "pdf_text_extracted"
        else:
            text = ""
            for pdf_url in candidate_pdf_links(content, final_url):
                try:
                    pdf_content, pdf_type, pdf_final_url = request_url(
                        pdf_url, timeout_seconds, user_agent
                    )
                    pdf_path = Path(tmp_dir) / "landing.pdf"
                    pdf_path.write_bytes(pdf_content)
                    if pdf_content[:4] == b"%PDF" or "pdf" in pdf_type.lower():
                        text = extract_pdf_text(pdf_path)
                        final_url = pdf_final_url
                        content_type = pdf_type
                        if text:
                            break
                except Exception:
                    continue

            status = "landing_pdf_text_extracted" if text else "html_text_extracted"
            if not text:
                text = extract_html_text(content)

        if not text:
            return PreparedFullText(
                status="extraction_failed",
                source=location.source,
                url=url,
                license=location.license,
                error=f"No text extracted from {final_url or url}",
            )
        if text_too_short(text):
            return PreparedFullText(
                status="extraction_failed",
                source=location.source,
                url=final_url or url,
                license=location.license,
                error=(
                    f"Extracted text too short for full-text tagging "
                    f"({len(clean_text(text))} chars) from {final_url or url}"
                ),
            )

        prepared = write_cached_text(text_path, text)
        return PreparedFullText(
            status=status,
            source=location.source,
            url=final_url or url,
            license=location.license,
            text_path=prepared.text_path,
            text_chars=prepared.text_chars,
        )


def prepare_one(
    row: dict[str, str],
    resolver: FullTextResolver,
    cache_dir: Path,
    timeout_seconds: int,
    user_agent: str,
) -> PreparedFullText:
    key = cache_key(row)
    text_path = cache_dir / "texts" / f"{key}.txt"
    if text_path.exists() and text_path.stat().st_size > 0:
        text = text_path.read_text(encoding="utf-8", errors="ignore")
        if not text_too_short(text):
            return PreparedFullText(
                status="cached_text_found",
                text_path=str(text_path),
                text_chars=len(text),
            )

    if hasattr(resolver, "resolve_all"):
        locations = resolver.resolve_all(row)  # type: ignore[attr-defined]
    else:
        locations = [resolver.resolve(row)]

    fallback_manual_url = ""
    failures: list[str] = []

    for location in locations:
        if location.status == "manual_lookup_needed":
            fallback_manual_url = location.manual_lookup_url
            continue
        if location.status == "not_found":
            continue

        try:
            if location.local_path:
                prepared = extract_local_path(Path(location.local_path), text_path, location)
            elif location.url:
                prepared = extract_remote_url(
                    location.url,
                    text_path,
                    location,
                    timeout_seconds,
                    user_agent,
                )
            else:
                continue
        except Exception as error:
            prepared = PreparedFullText(
                status="extraction_failed",
                source=location.source,
                url=location.url,
                license=location.license,
                error=f"{type(error).__name__}: {error}",
                manual_lookup_url=location.manual_lookup_url,
            )

        if prepared.text_path:
            return prepared
        if prepared.error:
            failures.append(
                f"{location.source or 'unknown'} {location.url or location.local_path}: "
                f"{prepared.error}"
            )

    if failures:
        visible_failures = failures[:10]
        hidden_failures = len(failures) - len(visible_failures)
        error = (
            f"Exhausted {len(failures)} resolved full-text locations. "
            + " | ".join(visible_failures)
        )
        if hidden_failures:
            error += f" | ... {hidden_failures} more failures"
        return PreparedFullText(
            status="extraction_failed",
            error=error,
            manual_lookup_url=fallback_manual_url,
        )

    return PreparedFullText(
        status="manual_lookup_needed" if fallback_manual_url else "not_found",
        manual_lookup_url=fallback_manual_url,
    )


def apply_prepared(row: dict[str, str], prepared: PreparedFullText) -> dict[str, str]:
    return {
        **row,
        "full_text_status": prepared.status,
        "full_text_source": prepared.source,
        "full_text_url": prepared.url,
        "full_text_license": prepared.license,
        "full_text_text_path": prepared.text_path,
        "full_text_chars": str(prepared.text_chars),
        "full_text_error": prepared.error,
        "full_text_manual_lookup_url": prepared.manual_lookup_url,
    }


def run(
    input_path: Path,
    output_path: Path,
    manifest_path: Path,
    cache_dir: Path | None = None,
    email: str | None = None,
    resolver: FullTextResolver | None = None,
    timeout_seconds: int = 45,
) -> StepResult:
    input_columns, rows = read_rows(input_path)
    resolved_cache_dir = cache_dir or default_cache_dir()
    resolved_cache_dir.mkdir(parents=True, exist_ok=True)
    user_agent = (
        "ad-literature-knowledge-pipeline/0.1"
        f" ({email or os.getenv('UNPAYWALL_EMAIL') or 'no-email'})"
    )
    full_text_resolver = resolver or NetworkFullTextResolver(
        email=email,
        timeout_seconds=timeout_seconds,
    )

    output_rows: list[dict[str, str]] = []
    manifest_rows: list[dict[str, str]] = []

    for index, row in enumerate(rows, start=1):
        paper_id = row.get("paper_id") or f"row_{index}"
        if row.get("scope_decision") != "include":
            prepared = PreparedFullText(status="skipped_scope_excluded")
        else:
            print(f"Preparing full text {index}/{len(rows)}: {paper_id}")
            prepared = prepare_one(
                row,
                full_text_resolver,
                resolved_cache_dir,
                timeout_seconds,
                user_agent,
            )

        enriched = apply_prepared(row, prepared)
        output_rows.append(enriched)
        manifest_rows.append(
            {
                "paper_id": paper_id,
                "title": row.get("title", ""),
                "doi": row.get("doi", ""),
                **{column: enriched.get(column, "") for column in FULL_TEXT_COLUMNS},
            }
        )

    fieldnames = output_columns(input_columns)
    write_csv(output_path, output_rows, fieldnames)
    write_csv(
        manifest_path,
        manifest_rows,
        ["paper_id", "title", "doi", *FULL_TEXT_COLUMNS],
    )

    included = [row for row in output_rows if row.get("scope_decision") == "include"]
    local_texts = [row for row in included if row.get("full_text_text_path")]
    manual = [
        row
        for row in included
        if not row.get("full_text_text_path") and row.get("full_text_manual_lookup_url")
    ]

    return StepResult(
        step_name=STEP.name,
        inputs={"scope_screened_csv": input_path},
        outputs={
            "scope_screened_full_text_csv": output_path,
            "full_text_manifest_csv": manifest_path,
        },
        row_counts={
            "papers": len(output_rows),
            "included_papers": len(included),
            "local_texts": len(local_texts),
            "manual_lookup_needed": len(manual),
        },
        metadata={"cache_dir": str(resolved_cache_dir)},
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Resolve and extract full text for scope-included papers."
    )
    parser.add_argument("--input", required=True, help="Scope-screened input CSV.")
    parser.add_argument("--output", required=True, help="Enriched output CSV.")
    parser.add_argument("--manifest", required=True, help="Full-text manifest CSV.")
    parser.add_argument(
        "--cache-dir",
        default=None,
        help="External full-text cache directory. Defaults to AD_LIT_FULL_TEXT_CACHE or ~/.cache.",
    )
    parser.add_argument("--email", default=None, help="Email for polite API requests.")
    parser.add_argument("--timeout", type=int, default=45, help="HTTP timeout seconds.")
    args = parser.parse_args()

    result = run(
        Path(args.input),
        Path(args.output),
        Path(args.manifest),
        Path(args.cache_dir).expanduser() if args.cache_dir else None,
        args.email,
        timeout_seconds=args.timeout,
    )
    print(f"Prepared full text for {result.row_counts['included_papers']} included papers")
    print(f"Local texts available: {result.row_counts['local_texts']}")
    print(f"Manual lookup needed: {result.row_counts['manual_lookup_needed']}")
    print(f"Wrote {args.output}")
