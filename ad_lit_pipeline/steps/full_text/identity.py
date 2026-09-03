from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass


IDENTITY_VERIFIED_DOI = "verified_doi"
IDENTITY_VERIFIED_TITLE = "verified_title"
IDENTITY_TRUSTED_LOCAL = "trusted_local"
IDENTITY_MISMATCH = "mismatch"
IDENTITY_FRONT_MATTER_CHARS = 20_000
IDENTITY_DOI_SCAN_CHARS = 6_000

REMOTE_EXTRACTION_STATUSES = {
    "pdf_text_extracted",
    "landing_pdf_text_extracted",
    "html_text_extracted",
}

TITLE_STOP_WORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "by",
    "for",
    "from",
    "in",
    "into",
    "is",
    "of",
    "on",
    "or",
    "the",
    "to",
    "use",
    "used",
    "using",
    "via",
    "with",
}


@dataclass(frozen=True)
class DocumentIdentityAssessment:
    matched: bool
    status: str
    evidence: str


class DocumentIdentityMismatch(ValueError):
    def __init__(
        self,
        url: str,
        assessment: DocumentIdentityAssessment,
    ) -> None:
        self.url = url
        self.assessment = assessment
        super().__init__(
            f"Extracted document identity mismatch for {url}: "
            f"{assessment.evidence}"
        )


def normalize_doi(value: str) -> str:
    doi = str(value or "").strip().lower()
    for prefix in ("https://doi.org/", "http://doi.org/", "doi:"):
        if doi.startswith(prefix):
            doi = doi[len(prefix) :]
    return doi.strip()


def front_matter_contains_doi(front_matter: str, doi: str) -> bool:
    if not doi:
        return False
    return bool(
        re.search(
            rf"(?<![a-z0-9]){re.escape(doi)}(?![a-z0-9._;()/:-])",
            front_matter.casefold(),
        )
    )


def stem_token(token: str) -> str:
    if len(token) > 5 and token.endswith("ies"):
        return f"{token[:-3]}y"
    if len(token) > 5 and token.endswith("ing"):
        stem = token[:-3]
        if len(stem) > 2 and stem[-1] == stem[-2]:
            stem = stem[:-1]
        return stem
    if len(token) > 4 and token.endswith("ed"):
        return token[:-2]
    if len(token) > 4 and token.endswith("s") and not token.endswith(
        ("ss", "us", "is")
    ):
        return token[:-1]
    return token


def word_tokens(value: str) -> list[str]:
    normalized = unicodedata.normalize("NFKD", str(value or ""))
    normalized = "".join(
        character for character in normalized if not unicodedata.combining(character)
    ).lower()
    return [stem_token(token) for token in re.findall(r"[a-z0-9]+", normalized)]


def significant_title_tokens(title: str) -> list[str]:
    tokens = []
    for token in word_tokens(title):
        if len(token) < 2 or token in TITLE_STOP_WORDS or token in tokens:
            continue
        tokens.append(token)
    return tokens


def compact_ordered_title_match(
    text_tokens: list[str],
    title_tokens: list[str],
) -> tuple[bool, int | None]:
    """Return whether all title tokens occur in a compact ordered window."""
    if len(title_tokens) < 3:
        return False, None

    allowed_extra_tokens = max(2, len(title_tokens) // 3)
    maximum_span = len(title_tokens) + allowed_extra_tokens
    for start, token in enumerate(text_tokens):
        if token != title_tokens[0]:
            continue
        title_index = 1
        end_limit = min(len(text_tokens), start + maximum_span)
        for index in range(start + 1, end_limit):
            if text_tokens[index] != title_tokens[title_index]:
                continue
            title_index += 1
            if title_index == len(title_tokens):
                return True, index - start + 1
    return False, None


def assess_document_identity(
    row: dict[str, str],
    text: str,
) -> DocumentIdentityAssessment:
    """Verify an extracted remote document against DOI or title evidence."""

    front_matter = str(text or "")[:IDENTITY_FRONT_MATTER_CHARS]
    doi = normalize_doi(row.get("doi", ""))
    doi_scan = front_matter[:IDENTITY_DOI_SCAN_CHARS]
    if front_matter_contains_doi(doi_scan, doi):
        return DocumentIdentityAssessment(
            matched=True,
            status=IDENTITY_VERIFIED_DOI,
            evidence=(
                f"front_matter_doi_match={doi};"
                f"scan_chars={min(len(str(text or '')), IDENTITY_DOI_SCAN_CHARS)}"
            ),
        )

    title_tokens = significant_title_tokens(row.get("title", ""))
    text_tokens = [
        token
        for token in word_tokens(front_matter)
        if token not in TITLE_STOP_WORDS
    ]
    matched, span = compact_ordered_title_match(text_tokens, title_tokens)
    text_token_set = set(text_tokens)
    matched_tokens = [token for token in title_tokens if token in text_token_set]
    evidence = (
        f"front_matter_compact_ordered_title_match={'yes' if matched else 'no'};"
        f"title_tokens={len(title_tokens)};span={span or 0};"
        f"unordered_overlap={len(matched_tokens)}_of_{len(title_tokens)};"
        f"matched={','.join(matched_tokens[:12]) or 'none'};"
        f"scan_chars={min(len(str(text or '')), IDENTITY_FRONT_MATTER_CHARS)}"
    )
    if matched:
        return DocumentIdentityAssessment(
            matched=True,
            status=IDENTITY_VERIFIED_TITLE,
            evidence=evidence,
        )

    return DocumentIdentityAssessment(
        matched=False,
        status=IDENTITY_MISMATCH,
        evidence=evidence,
    )


def requires_remote_identity_validation(row: dict[str, str]) -> bool:
    status = str(row.get("full_text_status") or "").strip()
    if status in REMOTE_EXTRACTION_STATUSES:
        return True

    resolved_url = str(
        row.get("full_text_resolved_url")
        or row.get("full_text_extracted_url")
        or ""
    ).strip()
    source = str(
        row.get("full_text_resolved_source")
        or row.get("full_text_source")
        or ""
    ).strip()
    return resolved_url.startswith(("http://", "https://")) and source not in {
        "local_file",
        "existing_text_path",
    }
