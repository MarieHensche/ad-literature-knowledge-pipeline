from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from pathlib import Path
from typing import Any

from ad_lit_pipeline.core.step import StepResult, StepSpec
from ad_lit_pipeline.io.json_io import read_json_object, write_json
from ad_lit_pipeline.steps.review.citations import (
    enrich_paper_citations,
    harvard_narrative,
)
from ad_lit_pipeline.steps.review.label_values import split_multi_value


STEP = StepSpec(
    name="build_review_evidence_map",
    inputs=[
        "review_labels_raw_csv",
        "review_label_values_json",
        "review_quality_report_csv",
    ],
    outputs=["review_evidence_map_json"],
    uses_llm=False,
    description="Aggregate review labels into compact, citation-linked evidence.",
)

METADATA_COLUMNS = ["paper_id", "title", "year", "doi", "authors", "venue", "source"]
PRIMARY_SECTION_LABEL = "main_topic"
PREFERRED_SECTION_LABELS = ["methodology", "main_topic"]
DEFAULT_SECTION_ID = "unassigned"
BACKGROUND_CHAPTER = {
    "chapter_id": "background_and_related_literature",
    "chapter_label": "Background and Related Literature",
}
METHODS_CHAPTER = {
    "chapter_id": "methods_and_analytical_approaches",
    "chapter_label": "Methods and Analytical Approaches",
}
DATA_CHAPTER = {
    "chapter_id": "data_foundations_and_study_designs",
    "chapter_label": "Data Foundations and Study Designs",
}
OUTLOOK_CHAPTER = {
    "chapter_id": "limitations_and_research_outlook",
    "chapter_label": "Limitations and Research Outlook",
}
STABLE_SUBSECTIONS = [
    {
        **METHODS_CHAPTER,
        "section_id": "methodological_landscape",
        "label": "Methodological Landscape",
        "section_type": "methodological_landscape",
        "purpose": (
            "Describe the distribution and hierarchy of computational, "
            "analytical, experimental, qualitative, or conceptual approaches "
            "used across the included papers. Distinguish broad method families "
            "from their subtypes."
        ),
    },
    {
        **METHODS_CHAPTER,
        "section_id": "comparison_of_approaches",
        "label": "Comparison of Approaches",
        "section_type": "comparison_of_approaches",
        "purpose": (
            "Critically compare how approaches differ in purpose, assumptions, "
            "strengths, trade-offs, and applicability using only supported "
            "cross-paper evidence. Do not rank incomparable performance scores."
        ),
    },
    {
        **METHODS_CHAPTER,
        "section_id": "evidence_patterns_across_approaches",
        "label": "Evidence Patterns Across Approaches",
        "section_type": "evidence_patterns_across_approaches",
        "purpose": (
            "Synthesize where findings across approaches converge, differ, or "
            "remain uncertain. Interpret results in the context of each paper's "
            "data, task, outcome, and validation setting."
        ),
    },
    {
        **DATA_CHAPTER,
        "section_id": "datasets_and_data_sources",
        "label": "Datasets and Data Sources",
        "section_type": "datasets_and_data_sources",
        "purpose": (
            "Compare named datasets, newly collected data, secondary data, and "
            "other data origins used by the included papers. Note reuse, "
            "availability, and diversity only when supported."
        ),
    },
    {
        **DATA_CHAPTER,
        "section_id": "samples_cohorts_and_populations",
        "label": "Samples, Cohorts, and Study Populations",
        "section_type": "samples_cohorts_and_populations",
        "purpose": (
            "Synthesize the samples, cohorts, populations, or experimental "
            "units represented in the evidence, including important differences "
            "in size, composition, setting, or provenance when available."
        ),
    },
    {
        **DATA_CHAPTER,
        "section_id": "study_designs_and_validation_strategies",
        "label": "Study Designs and Validation Strategies",
        "section_type": "study_designs_and_validation_strategies",
        "purpose": (
            "Compare study designs and validation strategies, explaining how "
            "they shape evidential strength and comparability without inferring "
            "details absent from the papers."
        ),
    },
    {
        **OUTLOOK_CHAPTER,
        "section_id": "paper_reported_limitations",
        "label": "Paper-Reported Limitations",
        "section_type": "paper_reported_limitations",
        "purpose": (
            "Synthesize only limitations explicitly reported by the included "
            "papers. Prioritize recurring and consequential limitations and do "
            "not introduce limitations of this review."
        ),
    },
    {
        **OUTLOOK_CHAPTER,
        "section_id": "explicit_research_gaps",
        "label": "Explicit Research Gaps",
        "section_type": "explicit_research_gaps",
        "purpose": (
            "Synthesize only research gaps explicitly identified by the papers. "
            "Reject generic calls for more research unless the missing data, "
            "population, method, validation, or question is specified."
        ),
    },
    {
        **OUTLOOK_CHAPTER,
        "section_id": "future_research_directions",
        "label": "Future Research Directions",
        "section_type": "future_research_directions",
        "purpose": (
            "Synthesize only future research directions explicitly stated by "
            "the included papers. Do not invent recommendations or transform "
            "the review writer's interpretation into paper-reported future work."
        ),
    },
]
TEXT_EVIDENCE_LABELS = {
    "key_finding",
    "paper_limitation",
    "future_work_or_gap",
}
METHOD_PARENT_HINTS = {
    "artificial_intelligence": {
        "machine_learning",
        "deep_learning",
        "neural_network",
        "convolutional_neural_network",
        "transformer",
    },
    "machine_learning": {
        "deep_learning",
        "support_vector_machine",
        "random_forest",
        "decision_tree",
        "gradient_boosting",
        "neural_network",
        "convolutional_neural_network",
        "pattern_recognition",
    },
    "deep_learning": {
        "convolutional_neural_network",
        "recurrent_neural_network",
        "transformer",
        "autoencoder",
    },
    "network_analysis": {
        "graph_analysis",
        "graph_theory",
        "large_scale_network_analysis",
        "functional_connectivity_analysis",
    },
}
MAX_TEXT_ITEMS_PER_SECTION = 50
MAX_QUOTES_PER_SECTION = 20


def read_csv_rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def clean_text(value: object) -> str:
    return " ".join(str(value or "").split()).strip()


def labels_by_id(label_values: dict[str, Any]) -> dict[str, dict[str, Any]]:
    labels = label_values.get("review", {}).get("label_values")
    if not isinstance(labels, list):
        raise ValueError("review_label_values JSON must contain review.label_values.")
    return {
        str(label["label_id"]): label
        for label in labels
        if isinstance(label, dict) and label.get("label_id")
    }


def value_labels(label: dict[str, Any]) -> dict[str, str]:
    labels = {}
    for value in label.get("values", []):
        if not isinstance(value, dict):
            continue
        value_id = str(value.get("value") or "").strip()
        if value_id:
            labels[value_id] = str(value.get("label") or value_id)
    return labels


def allowed_values(label: dict[str, Any]) -> set[str]:
    return {
        str(value.get("value"))
        for value in label.get("values", [])
        if isinstance(value, dict) and value.get("value")
    }


def value_mappings(label: dict[str, Any]) -> dict[str, str]:
    mappings = {}
    for item in label.get("value_mappings", []):
        if not isinstance(item, dict):
            continue
        source = clean_text(item.get("from"))
        target = clean_text(item.get("to"))
        if source and target:
            mappings[source] = target
    return mappings


def dropped_values(label: dict[str, Any]) -> set[str]:
    return {
        clean_text(value)
        for value in label.get("dropped_values", [])
        if clean_text(value)
    }


def paper_citation(row: dict[str, str]) -> str:
    return harvard_narrative(row) or clean_text(row.get("paper_id"))


def paper_record(row: dict[str, str]) -> dict[str, str]:
    record = {column: clean_text(row.get(column)) for column in METADATA_COLUMNS}
    record["citation_key"] = paper_citation(row)
    return enrich_paper_citations(record)


def problematic_paper_ids(
    quality_rows: list[dict[str, str]],
    labels: dict[str, dict[str, Any]] | None = None,
) -> set[str]:
    excluded = set()
    label_map = labels or {}
    for row in quality_rows:
        paper_id = clean_text(row.get("paper_id"))
        if not paper_id or row.get("severity") != "error":
            continue
        if row.get("issue") == "invalid_review_value":
            label = label_map.get(clean_text(row.get("field")), {})
            if str(label.get("value_mode") or "") == "controlled_auto":
                continue
        excluded.add(paper_id)
    return excluded


def issue_counts(quality_rows: list[dict[str, str]]) -> dict[str, int]:
    counts: Counter[str] = Counter()
    for row in quality_rows:
        issue_type = clean_text(row.get("issue"))
        if issue_type:
            counts[issue_type] += 1
    return dict(sorted(counts.items()))


def year_range(rows: list[dict[str, str]]) -> list[int]:
    years = []
    for row in rows:
        raw_year = clean_text(row.get("year"))
        if raw_year.isdigit():
            years.append(int(raw_year))
    if not years:
        return []
    return [min(years), max(years)]


def controlled_label_ids(labels: dict[str, dict[str, Any]]) -> list[str]:
    return [
        label_id
        for label_id, label in labels.items()
        if str(label.get("value_mode") or "") in {"controlled_fixed", "controlled_auto"}
    ]


def count_controlled_values(
    rows: list[dict[str, str]],
    labels: dict[str, dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    distributions = {}
    for label_id in controlled_label_ids(labels):
        counts: Counter[str] = Counter()
        for row in rows:
            counts.update(
                clean_controlled_values(row.get(label_id, ""), labels[label_id])
            )
        names = value_labels(labels[label_id])
        distributions[label_id] = [
            {
                "value": value,
                "label": names.get(value, value),
                "paper_count": count,
            }
            for value, count in counts.most_common()
        ]
    return distributions


def label_coverage(
    rows: list[dict[str, str]],
    labels: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    coverage = []
    for label_id, label in labels.items():
        non_empty = 0
        for row in rows:
            value = clean_text(row.get(label_id))
            if value and value not in {"[]", "unclear"}:
                non_empty += 1
        coverage.append(
            {
                "label_id": label_id,
                "label": clean_text(label.get("label")) or label_id,
                "value_mode": clean_text(label.get("value_mode")),
                "papers_with_value": non_empty,
                "paper_count": len(rows),
                "coverage_ratio": round(non_empty / len(rows), 4) if rows else 0,
            }
        )
    return coverage


def method_hierarchy_hints(
    controlled_counts: dict[str, list[dict[str, Any]]],
) -> list[dict[str, str]]:
    methodology_counts = controlled_counts.get("methodology", [])
    present = {
        clean_text(item.get("value"))
        for item in methodology_counts
        if isinstance(item, dict) and clean_text(item.get("value"))
    }
    hints = []
    for parent, children in METHOD_PARENT_HINTS.items():
        if parent not in present:
            continue
        for child in sorted(children & present):
            hints.append(
                {
                    "parent_value": parent,
                    "child_value": child,
                    "use": (
                        "Treat the child as a more specific instance of the "
                        "parent when synthesizing methods."
                    ),
                }
            )
    return hints


def section_label_id(
    rows: list[dict[str, str]],
    labels: dict[str, dict[str, Any]],
) -> str:
    for label_id in PREFERRED_SECTION_LABELS:
        if label_id not in labels:
            continue
        if any(split_multi_value(row.get(label_id, "")) for row in rows):
            return label_id
    return PRIMARY_SECTION_LABEL


def clean_controlled_values(raw_value: str, label: dict[str, Any]) -> list[str]:
    values = split_multi_value(raw_value)
    if str(label.get("value_mode") or "") not in {
        "controlled_fixed",
        "controlled_auto",
    }:
        return values

    allowed = allowed_values(label)
    mappings = value_mappings(label)
    drops = dropped_values(label)
    cleaned = []
    seen = set()
    for value in values:
        mapped = mappings.get(value, value)
        if mapped in drops or value in drops:
            continue
        if allowed and mapped not in allowed:
            continue
        if mapped and mapped not in seen:
            cleaned.append(mapped)
            seen.add(mapped)
    return cleaned


def cleaned_section_ids(
    row: dict[str, str],
    label_id: str,
    labels: dict[str, dict[str, Any]],
) -> list[str]:
    values = clean_controlled_values(row.get(label_id, ""), labels.get(label_id, {}))
    return values or [DEFAULT_SECTION_ID]


def text_evidence_item(
    row: dict[str, str],
    label_id: str,
    text: str,
) -> dict[str, str]:
    return {
        "paper_id": clean_text(row.get("paper_id")),
        "citation_key": paper_citation(row),
        "text": text,
        "label_id": label_id,
    }


def collect_text_evidence(
    rows: list[dict[str, str]],
) -> dict[str, list[dict[str, str]]]:
    evidence: dict[str, list[dict[str, str]]] = {
        label_id: [] for label_id in sorted(TEXT_EVIDENCE_LABELS)
    }
    for row in rows:
        for label_id in TEXT_EVIDENCE_LABELS:
            text = clean_text(row.get(label_id))
            if text:
                evidence[label_id].append(text_evidence_item(row, label_id, text))
    return {
        label_id: items[:MAX_TEXT_ITEMS_PER_SECTION]
        for label_id, items in evidence.items()
        if items
    }


def parse_quote_items(raw_value: str) -> list[dict[str, str]]:
    if not clean_text(raw_value):
        return []
    try:
        payload = json.loads(raw_value)
    except json.JSONDecodeError:
        return []
    if not isinstance(payload, list):
        return []

    quotes = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        quote = clean_text(item.get("quote"))
        if not quote:
            continue
        quotes.append(
            {
                "quote": quote,
                "section": clean_text(item.get("section")),
                "reason": clean_text(item.get("reason")),
            }
        )
    return quotes


def collect_quotes(
    rows: list[dict[str, str]],
    labels: dict[str, dict[str, Any]],
) -> list[dict[str, str]]:
    quote_label_ids = [
        label_id
        for label_id, label in labels.items()
        if str(label.get("value_mode") or "") == "evidence_quote"
    ]
    quotes = []
    for row in rows:
        for label_id in quote_label_ids:
            for quote in parse_quote_items(row.get(label_id, "")):
                quotes.append(
                    {
                        "paper_id": clean_text(row.get("paper_id")),
                        "citation_key": paper_citation(row),
                        "label_id": label_id,
                        **quote,
                    }
                )
    return quotes[:MAX_QUOTES_PER_SECTION]


def build_section(
    section_id: str,
    rows: list[dict[str, str]],
    labels: dict[str, dict[str, Any]],
    section_label_id_value: str,
    label: str | None = None,
    section_type: str | None = None,
    purpose: str | None = None,
    topic_focus: dict[str, Any] | None = None,
    section_context: dict[str, Any] | None = None,
    chapter_id: str | None = None,
    chapter_label: str | None = None,
    heading_level: int = 1,
) -> dict[str, Any]:
    section_label = label or value_labels(labels.get(section_label_id_value, {})).get(
        section_id, section_id.replace("_", " ")
    )
    return {
        "section_id": section_id,
        "label": section_label,
        "section_type": section_type or "evidence_group",
        "purpose": purpose or "",
        "topic_focus": topic_focus or {},
        "section_context": section_context or {},
        "chapter_id": chapter_id or "",
        "chapter_label": chapter_label or "",
        "heading_level": heading_level,
        "source_label": section_label_id_value,
        "paper_count": len(rows),
        "paper_ids": [clean_text(row.get("paper_id")) for row in rows],
        "controlled_value_counts": count_controlled_values(rows, labels),
        "text_evidence": collect_text_evidence(rows),
        "quotes": collect_quotes(rows, labels),
    }


def main_topics_from_label_values(label_values: dict[str, Any]) -> list[dict[str, Any]]:
    topic_structure = label_values.get("topic_structure")
    if not isinstance(topic_structure, dict):
        return []
    main_topics = topic_structure.get("main_topics")
    if not isinstance(main_topics, list):
        return []
    return [topic for topic in main_topics if isinstance(topic, dict)]


def topic_section_id(topic: dict[str, Any]) -> str:
    topic_id = clean_text(topic.get("value") or topic.get("topic_id"))
    return f"main_topic_{topic_id}" if topic_id else "main_topic"


def topic_section_label(topic: dict[str, Any]) -> str:
    label = clean_text(topic.get("label") or topic.get("value") or topic.get("topic_id"))
    return f"{label} In The Included Literature" if label else "Main Topic"


def topic_focus(topic: dict[str, Any], label_values: dict[str, Any]) -> dict[str, Any]:
    topic_id = clean_text(topic.get("value") or topic.get("topic_id"))
    focus = dict(topic)
    topic_structure = label_values.get("topic_structure")
    if isinstance(topic_structure, dict):
        hints = topic_structure.get("term_hints")
        if isinstance(hints, list):
            for hint in hints:
                if isinstance(hint, dict) and hint.get("topic_id") == topic_id:
                    focus["term_hints"] = hint.get("terms", [])
                    focus["is_anchor"] = bool(hint.get("is_anchor", False))
                    break
    return focus


def build_planned_sections(
    usable_rows: list[dict[str, str]],
    labels: dict[str, dict[str, Any]],
    label_values: dict[str, Any],
    review_methodology: dict[str, Any],
) -> list[dict[str, Any]]:
    sections = [
        build_section(
            "abstract",
            usable_rows,
            labels,
            "review_plan",
            label="Abstract",
            section_type="abstract",
            purpose=(
                "Write a self-contained scientific literature-review abstract "
                "that briefly establishes the context, states the review "
                "objective and scope, summarizes the review approach and "
                "evidence base, reports the most important synthesis-level "
                "findings, identifies the principal supported limitations or "
                "gaps, and ends with the main conclusion or implication."
            ),
            section_context=abstract_context(
                label_values,
                usable_rows,
                review_methodology,
            ),
        ),
        build_section(
            "introduction",
            usable_rows,
            labels,
            "review_plan",
            label="Introduction",
            section_type="introduction",
            purpose=(
                "Introduce the broader research area and central problem using "
                "only supported evidence, explain why the topic matters, define "
                "the review objective and scope, clarify the main concepts from "
                "the topic contract, and orient the reader to the review's "
                "organization. Briefly characterize the evidence base without "
                "turning the introduction into a results or methods section."
            ),
            section_context=introduction_context(
                label_values,
                usable_rows,
                review_methodology,
            ),
        ),
        build_section(
            "review_methodology",
            usable_rows,
            labels,
            "review_plan",
            label="Review Methodology",
            section_type="review_methodology",
            purpose=(
                "Describe how the review evidence was assembled from the "
                "pipeline artifacts, including paper counts, review-paper "
                "exclusion, label coverage, and citation eligibility. Do not "
                "invent search details not present in the overview or quality "
                "metadata."
            ),
            section_context=review_methodology,
        )
    ]

    for topic in main_topics_from_label_values(label_values):
        sections.append(
            build_section(
                topic_section_id(topic),
                usable_rows,
                labels,
                "topic_structure.main_topics",
                label=topic_section_label(topic),
                section_type="main_topic_lens",
                purpose=(
                    "Discuss this topic-contract main concept as a focused "
                    "lens across the included literature. Explain how the "
                    "papers frame, study, measure, apply, or limit this concept."
                ),
                topic_focus=topic_focus(topic, label_values),
                chapter_id=BACKGROUND_CHAPTER["chapter_id"],
                chapter_label=BACKGROUND_CHAPTER["chapter_label"],
                heading_level=2,
            )
        )

    for section in STABLE_SUBSECTIONS:
        sections.append(
            build_section(
                section["section_id"],
                usable_rows,
                labels,
                "review_plan",
                label=section["label"],
                section_type=section["section_type"],
                purpose=section["purpose"],
                chapter_id=section["chapter_id"],
                chapter_label=section["chapter_label"],
                heading_level=2,
            )
        )

    sections.append(
        build_section(
            "conclusion",
            usable_rows,
            labels,
            "review_plan",
            label="Conclusion",
            section_type="conclusion",
            purpose=(
                "Conclude by integrating the main evidence, strengths, "
                "limitations, and implications of the included literature."
            ),
        )
    )

    return sections


def abstract_context(
    label_values: dict[str, Any],
    usable_rows: list[dict[str, str]],
    review_methodology: dict[str, Any],
) -> dict[str, Any]:
    selection = review_methodology.get("selection_summary", {})
    return {
        "research_topic": label_values.get("research_topic", {}),
        "review_type": review_type_from_label_values(label_values),
        "evidence_base": {
            "usable_paper_count": len(usable_rows),
            "year_range": year_range(usable_rows),
            "review_filter_counts": (
                selection.get("review_filter_counts", {})
                if isinstance(selection, dict)
                else {}
            ),
        },
        "scope_context": (
            label_values.get("scope")
            if isinstance(label_values.get("scope"), dict)
            else {}
        ),
        "content_requirements": [
            "Brief supported context and central problem.",
            "Review objective and scope.",
            "Review type, evidence source, and usable paper count.",
            "Most important cross-paper findings or patterns.",
            "Principal supported limitations or research gaps.",
            "Main conclusion or implication.",
        ],
        "style_requirements": [
            "One self-contained paragraph of approximately 150 to 250 words.",
            "No citations, direct quotations, headings, bullets, or internal ids.",
            "No unsupported background facts or claims of systematic review methods.",
        ],
    }


def introduction_context(
    label_values: dict[str, Any],
    usable_rows: list[dict[str, str]],
    review_methodology: dict[str, Any],
) -> dict[str, Any]:
    topic_structure = label_values.get("topic_structure")
    main_topics = []
    if isinstance(topic_structure, dict):
        configured_topics = topic_structure.get("main_topics")
        if isinstance(configured_topics, list):
            main_topics = [
                {
                    "topic_id": clean_text(topic.get("value") or topic.get("topic_id")),
                    "label": clean_text(
                        topic.get("label") or topic.get("value") or topic.get("topic_id")
                    ),
                }
                for topic in configured_topics
                if isinstance(topic, dict)
                and clean_text(topic.get("value") or topic.get("topic_id"))
            ]

    selection = review_methodology.get("selection_summary", {})
    scope = label_values.get("scope")
    return {
        "review_objective": (
            "Synthesize and critically orient the included literature around "
            "the configured research topic and its main concepts."
        ),
        "scope_context": scope if isinstance(scope, dict) else {},
        "main_topics": main_topics,
        "evidence_base": {
            "usable_paper_count": len(usable_rows),
            "year_range": year_range(usable_rows),
            "review_type": review_type_from_label_values(label_values),
            "review_filter_counts": (
                selection.get("review_filter_counts", {})
                if isinstance(selection, dict)
                else {}
            ),
        },
        "content_requirements": [
            "Establish the supported scholarly context and central problem.",
            "Explain the topic's significance without unsupported general claims.",
            "State the review objective, scope, and conceptual boundaries.",
            "Introduce the configured main topics as the review's organizing concepts.",
            "Preview the structure and broad evidence landscape without detailed results.",
        ],
        "content_exclusions": [
            "Detailed search procedures, which belong in Review Methodology.",
            "A paper-by-paper findings list or detailed performance comparisons.",
            "Unsupported historical claims, prevalence figures, or external facts.",
        ],
    }


def review_type_from_label_values(label_values: dict[str, Any]) -> str:
    review = label_values.get("review")
    if isinstance(review, dict):
        review_type = clean_text(review.get("review_type"))
        if review_type:
            return review_type
    return "narrative"


def review_methodology_context(
    label_values: dict[str, Any],
    review_rows: list[dict[str, str]],
    usable_rows: list[dict[str, str]],
    labels: dict[str, dict[str, Any]],
    quality_rows: list[dict[str, str]],
    controlled_counts: dict[str, list[dict[str, Any]]],
    filter_report: dict[str, Any] | None = None,
) -> dict[str, Any]:
    collection = label_values.get("collection")
    scope = label_values.get("scope")
    filter_counts = {}
    retention_rule = ""
    if isinstance(filter_report, dict):
        counts = filter_report.get("counts")
        if isinstance(counts, dict):
            filter_counts = counts
        retention_rule = clean_text(filter_report.get("retention_rule"))
    citation_ready = sum(
        1 for row in usable_rows if paper_record(row).get("citation_metadata_complete")
    )
    collection_context_value = collection if isinstance(collection, dict) else {}
    return {
        "review_type": review_type_from_label_values(label_values),
        "selection_summary": {
            "review_labeled_papers": len(review_rows),
            "usable_papers_after_quality_checks": len(usable_rows),
            "excluded_by_quality_checks": len(review_rows) - len(usable_rows),
            "citation_metadata_complete_papers": citation_ready,
            "year_range": year_range(usable_rows),
            "review_paper_filter": (
                "Review-type papers are removed before literature-review "
                "evidence synthesis when the pipeline can identify them. "
                "Retained papers should not be described as verified original "
                "studies unless the source metadata proves that status."
            ),
            "review_filter_counts": filter_counts,
        },
        "collection_context": collection_context_value,
        "search_strategy": {
            "providers": collection_context_value.get("allowed_providers", []),
            "preferred_provider": collection_context_value.get(
                "preferred_provider",
                "",
            ),
            "search_queries": collection_context_value.get("search_queries", []),
            "filters": {
                "full_text_required": True,
                "review_type_filter": retention_rule,
                "max_results_default": collection_context_value.get(
                    "max_results_default",
                    "",
                ),
            },
            "reproducibility_note": (
                "Use exact configured queries and available filter settings in "
                "the review method. If provider-side retrieved/screened counts "
                "are unavailable, state only the available included and labeled "
                "counts."
            ),
        },
        "scope_context": scope if isinstance(scope, dict) else {},
        "label_coverage": label_coverage(usable_rows, labels),
        "method_hierarchy_hints": method_hierarchy_hints(controlled_counts),
        "quality_issue_counts": issue_counts(quality_rows),
        "comparison_guidance": (
            "Do not directly rank or compare performance metrics across papers "
            "unless the papers use comparable data, tasks, outcomes, and "
            "validation settings. Otherwise compare trends qualitatively."
        ),
    }


def build_review_evidence_map(
    review_rows: list[dict[str, str]],
    label_values: dict[str, Any],
    quality_rows: list[dict[str, str]],
    filter_report: dict[str, Any] | None = None,
) -> dict[str, Any]:
    labels = labels_by_id(label_values)
    excluded_ids = problematic_paper_ids(quality_rows, labels)
    usable_rows = []
    for row in review_rows:
        paper_id = clean_text(row.get("paper_id"))
        if paper_id and paper_id not in excluded_ids:
            usable_rows.append(row)

    selected_section_label = section_label_id(usable_rows, labels)
    controlled_counts = count_controlled_values(usable_rows, labels)
    review_methodology = review_methodology_context(
        label_values,
        review_rows,
        usable_rows,
        labels,
        quality_rows,
        controlled_counts,
        filter_report,
    )
    sections = build_planned_sections(
        usable_rows,
        labels,
        label_values,
        review_methodology,
    )

    return {
        "research_topic": label_values.get("research_topic", {}),
        "scope": label_values.get("scope", {}),
        "collection": label_values.get("collection", {}),
        "topic_structure": label_values.get("topic_structure", {}),
        "overview": {
            "review_type": review_type_from_label_values(label_values),
            "paper_count": len(review_rows),
            "usable_paper_count": len(usable_rows),
            "excluded_paper_count": len(review_rows) - len(usable_rows),
            "year_range": year_range(usable_rows),
            "section_label": selected_section_label,
            "section_plan": "stable_skeleton_with_main_topic_sections",
            "controlled_value_counts": controlled_counts,
            "label_coverage": label_coverage(usable_rows, labels),
            "method_hierarchy_hints": method_hierarchy_hints(controlled_counts),
            "review_methodology": review_methodology,
        },
        "quality": {
            "issue_count": len(quality_rows),
            "issue_counts": issue_counts(quality_rows),
            "excluded_paper_ids": sorted(excluded_ids),
        },
        "papers": [paper_record(row) for row in usable_rows],
        "sections": sections,
    }


def run(
    review_labels_path: Path,
    review_label_values_path: Path,
    review_quality_report_path: Path,
    output_path: Path,
    review_filter_report_path: Path | None = None,
) -> StepResult:
    review_rows = read_csv_rows(review_labels_path)
    label_values = read_json_object(review_label_values_path)
    quality_rows = read_csv_rows(review_quality_report_path)
    filter_report = (
        read_json_object(review_filter_report_path)
        if review_filter_report_path is not None and review_filter_report_path.exists()
        else None
    )
    evidence_map = build_review_evidence_map(
        review_rows,
        label_values,
        quality_rows,
        filter_report,
    )
    write_json(
        output_path,
        {
            "source_labels": str(review_labels_path),
            "source_label_values": str(review_label_values_path),
            "source_quality_report": str(review_quality_report_path),
            "source_review_filter_report": (
                str(review_filter_report_path) if review_filter_report_path else ""
            ),
            **evidence_map,
        },
    )
    return StepResult(
        step_name=STEP.name,
        inputs={
            "review_labels_raw_csv": review_labels_path,
            "review_label_values_json": review_label_values_path,
            "review_quality_report_csv": review_quality_report_path,
            "review_filter_report_json": review_filter_report_path,
        },
        outputs={"review_evidence_map_json": output_path},
        row_counts={
            "review_label_rows": len(review_rows),
            "review_usable_papers": int(
                evidence_map["overview"]["usable_paper_count"]
            ),
            "review_sections": len(evidence_map["sections"]),
            "review_quality_issues": len(quality_rows),
        },
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build a compact evidence map for literature-review synthesis."
    )
    parser.add_argument("--labels", required=True, help="Raw review labels CSV.")
    parser.add_argument(
        "--label-values",
        required=True,
        help="Normalized review label values JSON.",
    )
    parser.add_argument(
        "--quality-report",
        required=True,
        help="Review quality report CSV.",
    )
    parser.add_argument(
        "--review-filter-report",
        default=None,
        help="Optional JSON report from review-paper filtering.",
    )
    parser.add_argument("--output", required=True, help="Evidence map JSON.")
    args = parser.parse_args()

    run(
        Path(args.labels),
        Path(args.label_values),
        Path(args.quality_report),
        Path(args.output),
        Path(args.review_filter_report) if args.review_filter_report else None,
    )


if __name__ == "__main__":
    main()
