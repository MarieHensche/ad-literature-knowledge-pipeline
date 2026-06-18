from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

from ad_lit_pipeline.core.step import StepResult, StepSpec
from ad_lit_pipeline.io.json_io import write_json
from ad_lit_pipeline.steps.full_text.evidence import SECTION_PATTERNS
from ad_lit_pipeline.topics.contract import (
    load_topic_contract,
    normalize_tagging_label,
    require_mapping,
)


STEP = StepSpec(
    name="normalize_review_config",
    inputs=["topic_contract_yaml"],
    outputs=["review_config_normalized_json"],
    uses_llm=False,
    description="Normalize optional literature-review settings.",
)

VALID_VALUE_MODES = {
    "controlled_fixed",
    "controlled_auto",
    "free_text",
    "evidence_quote",
}
VALID_SELECTIONS = {"single", "multi"}
DEFAULT_OUTPUT_FORMATS = ["markdown"]
DEFAULT_CITATION_STYLE = "apa"
DEFAULT_MAX_QUOTE_WORDS = 40
DEFAULT_EVIDENCE_SECTIONS = ["abstract", "results", "discussion", "conclusion"]
DEFAULT_STUDY_DESIGN_VALUES = [
    "observational_study",
    "experimental_study",
    "randomized_controlled_trial",
    "quasi_experimental_study",
    "cohort_study",
    "case_control_study",
    "cross_sectional_study",
    "longitudinal_study",
    "qualitative_study",
    "survey_study",
    "case_study",
    "mixed_methods_study",
    "validation_study",
    "simulation_study",
    "benchmark_study",
    "model_development_study",
    "secondary_data_analysis",
    "unclear",
]


DEFAULT_REVIEW_LABELS: dict[str, dict[str, Any]] = {
    "methodology": {
        "description": (
            "Main operational method(s) the paper used to generate or analyze "
            "its evidence."
        ),
        "value_mode": "controlled_auto",
        "selection": "multi",
        "values": "auto",
        "max_values_per_paper": 2,
        "max_words_per_value": 5,
        "extraction_rule": (
            "Extract only the main operational methods, procedures, techniques, "
            "instruments, analytic approaches, or interventions used to generate "
            "or analyze evidence. Keep values compact and normalize equivalent "
            "wording to the same lowercase snake_case concept. Do not extract "
            "study design, dataset/sample names, findings, or research aims."
        ),
        "evidence_sections": [
            "title",
            "abstract",
            "methods",
            "methodology",
            "materials_and_methods",
            "study_design",
            "procedure",
            "approach",
            "analysis",
        ],
        "required": False,
    },
    "study_design": {
        "description": "Overall research design or evidence structure of the paper.",
        "value_mode": "controlled_fixed",
        "selection": "single",
        "values": DEFAULT_STUDY_DESIGN_VALUES,
        "max_values_per_paper": 1,
        "max_words_per_value": 4,
        "extraction_rule": (
            "Choose the closest allowed study-design value based on the paper's "
            "overall research design or evidence structure. Map equivalent "
            "wording to the closest allowed value even when the exact phrase is "
            "not present. Use unclear only when the design is genuinely not "
            "inferable from the available evidence. Do not extract methods, "
            "datasets, samples, findings, or outcomes."
        ),
        "evidence_sections": [
            "title",
            "abstract",
            "introduction",
            "methods",
            "methodology",
            "materials_and_methods",
            "study_design",
            "procedure",
            "approach",
        ],
        "required": False,
    },
    "dataset_or_sample": {
        "description": (
            "Dataset, cohort, sample, data source, corpus, population, or "
            "material used as evidence in the paper."
        ),
        "value_mode": "free_text",
        "max_items_per_paper": 2,
        "max_words_per_item": 18,
        "missing_value": "unclear",
        "extraction_rule": (
            "Extract only dataset, cohort, sample, data source, corpus, "
            "population, material name, or origin. If named, use the name. If "
            "not named but described, use a short origin phrase. Do not extract "
            "methods, study design, findings, or aims."
        ),
        "evidence_sections": [
            "abstract",
            "methods",
            "methodology",
            "materials_and_methods",
            "study_design",
            "data",
            "sample",
            "participants",
            "population",
            "cohort",
        ],
        "required": False,
    },
    "key_finding": {
        "description": (
            "Main result or conclusion reported by the paper that is relevant "
            "to the review topic."
        ),
        "value_mode": "free_text",
        "max_items_per_paper": 1,
        "max_words_per_item": 35,
        "missing_value": "unclear",
        "extraction_rule": (
            "Extract one compact neutral claim stating the paper's main result "
            "or conclusion relevant to the review topic. Prefer reported "
            "findings over aims, background, methods, or dataset descriptions."
        ),
        "evidence_sections": ["results", "findings", "discussion", "conclusion"],
        "required": True,
    },
    "paper_limitation": {
        "description": (
            "Most important limitations explicitly reported by the paper."
        ),
        "value_mode": "free_text",
        "max_items_per_paper": 2,
        "max_words_per_item": 25,
        "missing_value": "unclear",
        "extraction_rule": (
            "Extract up to two of the most important and most limiting "
            "limitations explicitly reported by this paper. Use compact, "
            "neutral sentences. Do not infer limitations. Do not extract broad "
            "review-level statements such as more research is needed unless "
            "they are specifically tied to this paper's limitation."
        ),
        "evidence_sections": [
            "limitations",
            "discussion",
            "conclusion",
            "abstract",
        ],
        "required": False,
    },
    "direct_quote": {
        "description": (
            "Short direct quotation that could support the review narrative."
        ),
        "value_mode": "evidence_quote",
        "evidence_sections": [
            "introduction",
            "results",
            "findings",
            "discussion",
            "conclusion",
        ],
        "required": False,
    },
    "future_work_or_gap": {
        "description": (
            "Future work, unresolved question, or research gap explicitly "
            "stated by the paper."
        ),
        "value_mode": "free_text",
        "max_items_per_paper": 2,
        "max_words_per_item": 25,
        "missing_value": "unclear",
        "extraction_rule": (
            "Extract up to two important future-work directions or research "
            "gaps only when the paper clearly states them as future work, an "
            "unresolved question, or a gap. Do not infer or invent gaps. Broad "
            "field-level gaps are allowed only when explicitly stated by the "
            "paper. Reject generic statements such as more studies are needed "
            "unless they specify the study type, data, population, method, or "
            "question needed."
        ),
        "evidence_sections": [
            "future_work",
            "discussion",
            "conclusion",
            "limitations",
        ],
        "required": False,
    },
}


def clean_text(value: object) -> str:
    return " ".join(str(value or "").split()).strip()


def normalized_section(value: object) -> str:
    return normalize_tagging_label(str(value or ""))


def normalize_sections(raw_sections: object, label_id: str) -> list[str]:
    if raw_sections is None:
        return list(DEFAULT_EVIDENCE_SECTIONS)
    if not isinstance(raw_sections, list):
        raise ValueError(f"review.labels.{label_id}.evidence_sections must be a list.")

    sections = []
    seen = set()
    for section in raw_sections:
        normalized = normalized_section(section)
        if not normalized or normalized in seen:
            continue
        sections.append(normalized)
        seen.add(normalized)

    if not sections:
        raise ValueError(
            f"review.labels.{label_id}.evidence_sections must not be empty."
        )
    return sections


def normalize_values(values: object, label_id: str) -> tuple[str, list[str]]:
    if values in (None, "auto"):
        return "controlled_auto", []
    if not isinstance(values, list):
        raise ValueError(f"review.labels.{label_id}.values must be a list or 'auto'.")

    normalized = []
    seen = set()
    for value in values:
        normalized_value = normalize_tagging_label(str(value or ""))
        if not normalized_value or normalized_value in seen:
            continue
        normalized.append(normalized_value)
        seen.add(normalized_value)

    if not normalized:
        return "controlled_auto", []
    return "controlled_fixed", normalized


def optional_positive_int(value: object, field_name: str) -> int | None:
    if value in (None, ""):
        return None
    if not isinstance(value, int) or value < 1:
        raise ValueError(f"{field_name} must be a positive integer when present.")
    return value


def main_topic_values(topic_contract: dict[str, Any]) -> list[dict[str, str]]:
    topic_structure = require_mapping(
        topic_contract.get("topic_structure"),
        "topic_structure",
    )
    main_topics = topic_structure.get("main_topics")
    if not isinstance(main_topics, list):
        raise ValueError("topic_structure.main_topics must be a list.")

    values = []
    seen = set()
    for index, topic in enumerate(main_topics, start=1):
        topic_map = require_mapping(topic, f"topic_structure.main_topics[{index}]")
        topic_id = normalize_tagging_label(str(topic_map.get("topic_id") or ""))
        if not topic_id or topic_id in seen:
            continue
        values.append(
            {
                "value": topic_id,
                "label": clean_text(topic_map.get("label")) or topic_id,
            }
        )
        seen.add(topic_id)

    if not values:
        raise ValueError("topic_structure.main_topics must contain at least one topic.")
    return values


def topic_structure_term_hints(topic_contract: dict[str, Any]) -> list[dict[str, Any]]:
    topic_structure = require_mapping(
        topic_contract.get("topic_structure"),
        "topic_structure",
    )
    anchor_topic_id = normalize_tagging_label(
        str(topic_structure.get("anchor_topic_id") or "")
    )
    main_topics = topic_structure.get("main_topics")
    if not isinstance(main_topics, list):
        raise ValueError("topic_structure.main_topics must be a list.")

    hints = []
    for index, topic in enumerate(main_topics, start=1):
        topic_map = require_mapping(topic, f"topic_structure.main_topics[{index}]")
        topic_id = normalize_tagging_label(str(topic_map.get("topic_id") or ""))
        if not topic_id:
            continue
        terms = []
        seen = set()
        for key in ["terms", "retrieval_terms", "matching_terms"]:
            raw_terms = topic_map.get(key, [])
            if not isinstance(raw_terms, list):
                continue
            for term in raw_terms:
                label = clean_text(term)
                value = normalize_tagging_label(label)
                if not value or value in seen:
                    continue
                terms.append({"value": value, "label": label})
                seen.add(value)
        hints.append(
            {
                "topic_id": topic_id,
                "label": clean_text(topic_map.get("label")) or topic_id,
                "is_anchor": topic_id == anchor_topic_id,
                "terms": terms,
            }
        )
    return hints


def normalize_label(
    label_id: str,
    label: dict[str, Any],
    topic_contract: dict[str, Any],
) -> dict[str, Any]:
    normalized_id = normalize_tagging_label(label_id)
    if not normalized_id:
        raise ValueError("review label ids must not be empty.")

    value_mode = clean_text(label.get("value_mode"))
    values_from = clean_text(label.get("values_from"))
    allowed_values: list[dict[str, str]] = []

    if values_from == "topic_structure.main_topics":
        value_mode = "controlled_fixed"
        allowed_values = main_topic_values(topic_contract)
    else:
        inferred_mode, values = normalize_values(label.get("values"), normalized_id)
        value_mode = value_mode or inferred_mode
        allowed_values = [{"value": value, "label": value} for value in values]

    if value_mode not in VALID_VALUE_MODES:
        allowed = ", ".join(sorted(VALID_VALUE_MODES))
        raise ValueError(
            f"review.labels.{normalized_id}.value_mode must be one of: {allowed}"
        )

    selection = clean_text(label.get("selection"))
    if value_mode.startswith("controlled"):
        selection = selection or "multi"
        if selection not in VALID_SELECTIONS:
            allowed = ", ".join(sorted(VALID_SELECTIONS))
            raise ValueError(
                f"review.labels.{normalized_id}.selection must be one of: {allowed}"
            )
    else:
        selection = ""

    if value_mode == "controlled_fixed" and not allowed_values:
        raise ValueError(
            f"review.labels.{normalized_id} needs fixed values or values_from."
        )

    return {
        "label_id": normalized_id,
        "label": clean_text(label.get("label")) or normalized_id.replace("_", " "),
        "description": clean_text(label.get("description")),
        "extraction_rule": clean_text(label.get("extraction_rule")),
        "value_mode": value_mode,
        "selection": selection,
        "required": bool(label.get("required", False)),
        "allowed_values": allowed_values,
        "values_from": values_from,
        "max_values_per_paper": optional_positive_int(
            label.get("max_values_per_paper"),
            f"review.labels.{normalized_id}.max_values_per_paper",
        ),
        "max_words_per_value": optional_positive_int(
            label.get("max_words_per_value"),
            f"review.labels.{normalized_id}.max_words_per_value",
        ),
        "max_items_per_paper": optional_positive_int(
            label.get("max_items_per_paper"),
            f"review.labels.{normalized_id}.max_items_per_paper",
        ),
        "max_words_per_item": optional_positive_int(
            label.get("max_words_per_item"),
            f"review.labels.{normalized_id}.max_words_per_item",
        ),
        "missing_value": clean_text(label.get("missing_value")),
        "evidence_sections": normalize_sections(
            label.get("evidence_sections"),
            normalized_id,
        ),
    }


def normalize_output(raw_output: object) -> dict[str, Any]:
    output = raw_output if isinstance(raw_output, dict) else {}
    formats = output.get("formats", DEFAULT_OUTPUT_FORMATS)
    if not isinstance(formats, list) or not formats:
        raise ValueError("review.output.formats must be a non-empty list.")
    normalized_formats = []
    for value in formats:
        normalized = normalize_tagging_label(str(value or ""))
        if normalized:
            normalized_formats.append(normalized)
    if "markdown" not in normalized_formats:
        normalized_formats.insert(0, "markdown")

    citation_style = normalize_tagging_label(
        str(output.get("citation_style") or DEFAULT_CITATION_STYLE)
    )
    max_quote_words = output.get("max_quote_words", DEFAULT_MAX_QUOTE_WORDS)
    if not isinstance(max_quote_words, int) or max_quote_words < 1:
        raise ValueError("review.output.max_quote_words must be a positive integer.")

    return {
        "formats": normalized_formats,
        "citation_style": citation_style or DEFAULT_CITATION_STYLE,
        "max_quote_words": max_quote_words,
    }


def default_review_config() -> dict[str, Any]:
    return {
        "enabled": True,
        "output": {
            "formats": DEFAULT_OUTPUT_FORMATS,
            "citation_style": DEFAULT_CITATION_STYLE,
            "max_quote_words": DEFAULT_MAX_QUOTE_WORDS,
        },
        "labels": deepcopy(DEFAULT_REVIEW_LABELS),
    }


def review_config_from_contract(topic_contract: dict[str, Any]) -> dict[str, Any]:
    raw_review = topic_contract.get("review")
    if raw_review is None:
        return default_review_config()
    if not isinstance(raw_review, dict):
        raise ValueError("review must be a mapping when present.")

    config = default_review_config()
    config["enabled"] = bool(raw_review.get("enabled", config["enabled"]))
    if "output" in raw_review:
        config["output"] = raw_review["output"]
    if "labels" in raw_review:
        labels = raw_review["labels"]
        if not isinstance(labels, dict) or not labels:
            raise ValueError("review.labels must be a non-empty mapping.")
        config["labels"] = labels
    return config


def normalize_review_config(topic_contract: dict[str, Any]) -> dict[str, Any]:
    review_config = review_config_from_contract(topic_contract)
    labels = review_config["labels"]
    if not isinstance(labels, dict):
        raise ValueError("review.labels must be a mapping.")

    normalized_labels = []
    seen = set()
    for raw_label_id, label in labels.items():
        label_map = require_mapping(label, f"review.labels.{raw_label_id}")
        normalized = normalize_label(str(raw_label_id), label_map, topic_contract)
        label_id = normalized["label_id"]
        if label_id in seen:
            raise ValueError(f"Duplicate review label id after normalization: {label_id}")
        normalized_labels.append(normalized)
        seen.add(label_id)

    return {
        "research_topic": topic_contract["research_topic"],
        "topic_structure": {
            "anchor_topic_id": topic_contract["topic_structure"].get(
                "anchor_topic_id",
                "",
            ),
            "main_topics": main_topic_values(topic_contract),
            "term_hints": topic_structure_term_hints(topic_contract),
        },
        "review": {
            "enabled": bool(review_config.get("enabled", False)),
            "output": normalize_output(review_config.get("output")),
            "label_count": len(normalized_labels),
            "labels": normalized_labels,
            "known_section_keys": sorted(SECTION_PATTERNS),
        },
    }


def run(topic_contract_path: Path, output_path: Path) -> StepResult:
    topic_contract = load_topic_contract(topic_contract_path)
    normalized = normalize_review_config(topic_contract)
    write_json(
        output_path,
        {
            "source_config": str(topic_contract_path),
            "source_type": "topic_contract",
            **normalized,
        },
    )
    return StepResult(
        step_name=STEP.name,
        inputs={"topic_contract_yaml": topic_contract_path},
        outputs={"review_config_normalized_json": output_path},
        row_counts={"review_labels": int(normalized["review"]["label_count"])},
    )
