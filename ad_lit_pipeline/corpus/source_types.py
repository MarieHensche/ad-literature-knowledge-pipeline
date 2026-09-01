from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from ad_lit_pipeline.records.models import WorkKind


CLASSIFICATION_RESOLVED = "resolved"
CLASSIFICATION_PROVISIONAL = "provisional"
CLASSIFICATION_NEEDS_REVIEW = "needs_review"

_RAW_TYPE_FIELDS = (
    "source_type",
    "provider_source_type",
    "publication_type",
    "work_type",
    "type",
)
_TITLE_FIELDS = ("title", "display_name")
_TYPE_MAP: dict[str, tuple[WorkKind, str]] = {
    "article": (WorkKind.RESEARCH_ARTICLE, "article"),
    "journal_article": (WorkKind.RESEARCH_ARTICLE, "journal_article"),
    "research_article": (WorkKind.RESEARCH_ARTICLE, "research_article"),
    "primary_study": (WorkKind.RESEARCH_ARTICLE, "primary_study"),
    "posted_content": (WorkKind.RESEARCH_ARTICLE, "preprint"),
    "preprint": (WorkKind.RESEARCH_ARTICLE, "preprint"),
    "review": (WorkKind.REVIEW, "review"),
    "systematic_review": (WorkKind.REVIEW, "systematic_review"),
    "meta_analysis": (WorkKind.REVIEW, "meta_analysis"),
    "protocol": (WorkKind.PROTOCOL, "protocol"),
    "study_protocol": (WorkKind.PROTOCOL, "study_protocol"),
    "clinical_trial": (WorkKind.CLINICAL_TRIAL, "clinical_trial"),
    "trial": (WorkKind.CLINICAL_TRIAL, "clinical_trial"),
    "dataset": (WorkKind.DATASET, "dataset"),
    "data_set": (WorkKind.DATASET, "dataset"),
    "patent": (WorkKind.PATENT, "patent"),
    "dissertation": (WorkKind.THESIS, "thesis"),
    "thesis": (WorkKind.THESIS, "thesis"),
    "book": (WorkKind.BOOK, "book"),
    "book_chapter": (WorkKind.BOOK_CHAPTER, "book_chapter"),
    "chapter": (WorkKind.BOOK_CHAPTER, "book_chapter"),
    "conference_paper": (WorkKind.CONFERENCE_OUTPUT, "conference_paper"),
    "proceedings_article": (
        WorkKind.CONFERENCE_OUTPUT,
        "proceedings_article",
    ),
    "proceedings": (WorkKind.CONFERENCE_OUTPUT, "proceedings"),
    "retraction": (WorkKind.OTHER, "retraction_notice"),
    "retraction_notice": (WorkKind.OTHER, "retraction_notice"),
    "correction": (WorkKind.OTHER, "correction"),
    "erratum": (WorkKind.OTHER, "correction"),
}


@dataclass(frozen=True)
class SourceTypeAssessment:
    """Provider-neutral source classification with explicit uncertainty."""

    work_kind: WorkKind
    source_type: str
    status: str
    evidence: tuple[str, ...]
    review_reasons: tuple[str, ...]


def normalize_source_type(value: Any) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "_", str(value or "").casefold())
    return re.sub(r"_+", "_", normalized).strip("_")


def _first_value(row: Mapping[str, Any], fields: tuple[str, ...]) -> tuple[str, str]:
    for field in fields:
        value = str(row.get(field) or "").strip()
        if value:
            return field, value
    return "", ""


def _title_classification(title: str) -> tuple[WorkKind, str, str] | None:
    normalized = re.sub(r"\s+", " ", title.casefold()).strip()
    if not normalized:
        return None
    if re.search(r"\b(systematic review|scoping review)\b", normalized):
        return WorkKind.REVIEW, "systematic_review", "title_review_phrase"
    if re.search(r"\bmeta[- ]analysis\b", normalized):
        return WorkKind.REVIEW, "meta_analysis", "title_meta_analysis_phrase"
    if re.search(r"\b(study )?protocol\b", normalized):
        return WorkKind.PROTOCOL, "study_protocol", "title_protocol_phrase"
    if normalized.startswith(("retraction:", "retracted:")) or (
        "retraction notice" in normalized
    ):
        return WorkKind.OTHER, "retraction_notice", "title_retraction_phrase"
    if normalized.startswith(("correction:", "correction to", "erratum:")):
        return WorkKind.OTHER, "correction", "title_correction_phrase"
    if re.search(r"\breview\b", normalized):
        return WorkKind.REVIEW, "review", "title_review_phrase"
    return None


def classify_source_type(row: Mapping[str, Any]) -> SourceTypeAssessment:
    """Classify source type once for collection, knowledge, and record bridges."""
    raw_field, raw_value = _first_value(row, _RAW_TYPE_FIELDS)
    raw_type = normalize_source_type(raw_value)
    title_field, title = _first_value(row, _TITLE_FIELDS)
    title_assessment = _title_classification(title)

    if raw_type in _TYPE_MAP:
        work_kind, canonical_type = _TYPE_MAP[raw_type]
        if raw_type in {"article", "journal_article", "research_article"} and (
            title_assessment is not None
        ):
            title_kind, title_type, title_evidence = title_assessment
            return SourceTypeAssessment(
                work_kind=title_kind,
                source_type=title_type,
                status=CLASSIFICATION_PROVISIONAL,
                evidence=(
                    f"provider_type:{raw_field}={raw_type}",
                    f"{title_evidence}:{title_field}",
                ),
                review_reasons=(
                    "generic_provider_type_refined_from_title",
                ),
            )
        return SourceTypeAssessment(
            work_kind=work_kind,
            source_type=canonical_type,
            status=CLASSIFICATION_RESOLVED,
            evidence=(f"provider_type:{raw_field}={raw_type}",),
            review_reasons=(),
        )

    if raw_type:
        return SourceTypeAssessment(
            work_kind=WorkKind.OTHER,
            source_type=raw_type,
            status=CLASSIFICATION_NEEDS_REVIEW,
            evidence=(f"unmapped_provider_type:{raw_field}={raw_type}",),
            review_reasons=("unmapped_source_type",),
        )

    if title_assessment is not None:
        work_kind, source_type, title_evidence = title_assessment
        return SourceTypeAssessment(
            work_kind=work_kind,
            source_type=source_type,
            status=CLASSIFICATION_PROVISIONAL,
            evidence=(f"{title_evidence}:{title_field}",),
            review_reasons=("source_type_inferred_from_title",),
        )

    return SourceTypeAssessment(
        work_kind=WorkKind.RESEARCH_ARTICLE,
        source_type="primary_study",
        status=CLASSIFICATION_PROVISIONAL,
        evidence=("compatibility_default:primary_study",),
        review_reasons=("provider_source_type_missing",),
    )
