from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from ad_lit_pipeline.steps.full_text.evidence import (
    MIN_USABLE_FULL_TEXT_CHARS,
    build_knowledge_evidence,
)
from ad_lit_pipeline.steps.full_text.identity import (
    assess_document_identity,
    requires_remote_identity_validation,
)
from ad_lit_pipeline.topics.contract import (
    TAGGING_EVIDENCE_POLICY_ABSTRACT_OR_FULL_TEXT,
    TAGGING_EVIDENCE_POLICY_FULL_TEXT_REQUIRED,
)


TAGGING_STATUS_COLUMN = "tagging_status"
TAGGING_EVIDENCE_BASIS_COLUMN = "tagging_evidence_basis"
TAGGING_ERROR_COLUMN = "tagging_error"
TAGGING_PROVENANCE_COLUMNS = [
    TAGGING_STATUS_COLUMN,
    TAGGING_EVIDENCE_BASIS_COLUMN,
    TAGGING_ERROR_COLUMN,
]

TAGGING_STATUS_TAGGED = "tagged"
TAGGING_STATUS_SKIPPED_INSUFFICIENT_EVIDENCE = (
    "skipped_insufficient_evidence"
)
TAGGING_STATUS_FAILED = "failed"

TAGGING_EVIDENCE_FULL_TEXT = "full_text"
TAGGING_EVIDENCE_ABSTRACT = "abstract"
TAGGING_EVIDENCE_NONE = "none"
VALID_TAGGING_EVIDENCE_BASES = {
    TAGGING_EVIDENCE_FULL_TEXT,
    TAGGING_EVIDENCE_ABSTRACT,
}
EVIDENCE_POLICY_ABSTRACT_OR_FULL_TEXT = (
    TAGGING_EVIDENCE_POLICY_ABSTRACT_OR_FULL_TEXT
)
EVIDENCE_POLICY_FULL_TEXT_REQUIRED = TAGGING_EVIDENCE_POLICY_FULL_TEXT_REQUIRED

MIN_USABLE_ABSTRACT_CHARS = 12
MIN_USABLE_ABSTRACT_WORDS = 3
ABSTRACT_SENTINELS = {
    "n a",
    "na",
    "no abstract",
    "no abstract available",
    "not available",
    "none",
    "null",
    "unknown",
}


@dataclass(frozen=True)
class TaggingEvidenceAssessment:
    eligible: bool
    basis: str
    full_text_evidence: str = ""
    reason: str = ""
    warning: str = ""


def clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def usable_abstract(value: str) -> str:
    abstract = clean_text(value)
    normalized = re.sub(r"[^a-z0-9]+", " ", abstract.casefold()).strip()
    words = normalized.split()
    if (
        normalized in ABSTRACT_SENTINELS
        or len(abstract) < MIN_USABLE_ABSTRACT_CHARS
        or len(words) < MIN_USABLE_ABSTRACT_WORDS
    ):
        return ""
    return abstract


def assess_tagging_evidence(
    paper: dict[str, str],
    evidence_policy: str = EVIDENCE_POLICY_ABSTRACT_OR_FULL_TEXT,
) -> TaggingEvidenceAssessment:
    """Decide whether a paper has evidence beyond its title for tagging.

    A verified or reachable full-text URL is discovery metadata, not usable
    evidence. Extracted text is preferred; a non-empty abstract remains an
    accepted compatibility fallback for legacy paper inputs.
    """

    text_path_value = paper.get("full_text_text_path", "").strip()
    raw_full_text = ""
    warnings = []
    explicitly_unusable = (
        paper.get("full_text_usable_for_tagging", "").strip().casefold() == "no"
    )
    if text_path_value and not explicitly_unusable:
        text_path = Path(text_path_value).expanduser()
        try:
            raw_full_text = text_path.read_text(encoding="utf-8", errors="ignore")
        except OSError as error:
            warnings.append(
                "could not read extracted full text "
                f"({type(error).__name__}: {error})"
            )
    elif text_path_value and explicitly_unusable:
        warnings.append("ignored full text marked unusable by prepare_full_text")

    if raw_full_text and len(raw_full_text) < MIN_USABLE_FULL_TEXT_CHARS:
        warnings.append(
            "ignored extracted full text shorter than the minimum usable length "
            f"({len(raw_full_text)} < {MIN_USABLE_FULL_TEXT_CHARS} chars)"
        )
        raw_full_text = ""

    if raw_full_text and requires_remote_identity_validation(paper):
        identity = assess_document_identity(paper, raw_full_text)
        if not identity.matched:
            warnings.append(
                "ignored extracted full text because document identity did not "
                f"match ({identity.evidence})"
            )
            raw_full_text = ""

    full_text_evidence = build_knowledge_evidence(raw_full_text)
    if full_text_evidence:
        return TaggingEvidenceAssessment(
            eligible=True,
            basis=TAGGING_EVIDENCE_FULL_TEXT,
            full_text_evidence=full_text_evidence,
            warning="; ".join(warnings),
        )

    abstract = usable_abstract(paper.get("abstract", ""))
    if abstract and evidence_policy != EVIDENCE_POLICY_FULL_TEXT_REQUIRED:
        return TaggingEvidenceAssessment(
            eligible=True,
            basis=TAGGING_EVIDENCE_ABSTRACT,
            warning="; ".join(warnings),
        )

    if abstract and evidence_policy == EVIDENCE_POLICY_FULL_TEXT_REQUIRED:
        warnings.append("abstract fallback is disabled by full_text_required policy")
    elif clean_text(paper.get("abstract", "")):
        warnings.append("abstract is a placeholder or too short to be usable")

    status = clean_text(paper.get("full_text_status", "")) or "not_available"
    return TaggingEvidenceAssessment(
        eligible=False,
        basis=TAGGING_EVIDENCE_NONE,
        reason=(
            (
                "no usable trusted-local or identity-verified remote extracted "
                "full text is available"
                if evidence_policy == EVIDENCE_POLICY_FULL_TEXT_REQUIRED
                else "no usable abstract or extracted full text is available"
            )
            + f" (full_text_status={status})"
        ),
        warning="; ".join(warnings),
    )
