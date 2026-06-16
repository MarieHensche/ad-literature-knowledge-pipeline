#Topic contract: defines the ontology
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ad_lit_pipeline.io.yaml_io import read_yaml_object
from ad_lit_pipeline.topics.matching import (
    DEFAULT_TOPIC_FIELD,
    RETRIEVAL_TERMS_LIMIT,
    VALID_TOPIC_FIELDS,
    secondary_topic_groups_from_structure,
)


LEGACY_TOPIC_FIT_CATEGORY_ID = "main_topic_category"
LEGACY_RESEARCH_TARGET_CATEGORY_ID = "research_target"
REQUIRED_TOPIC_CATEGORY_IDS: tuple[str, ...] = ()
VALID_CATEGORY_SELECTIONS = {"single", "multi"}
GENERATED_TAGGING_MIN_CATEGORIES = 6
GENERATED_TAG_LABEL_PATTERN = re.compile(r"^[a-z][a-z0-9]*(?:_[a-z0-9]+)*$")
RETIRED_TAGGING_CATEGORY_IDS = {
    "knowledge_goal",
}

FALLBACK_TAG_VALUES = {
    "ambiguous",
    "mixed",
    "mixed_or_unclear",
    "none",
    "not_applicable",
    "not_reported",
    "other",
    "unclear",
    "unknown",
}
META_TAGGING_CATEGORY_IDS = {
    "category",
    "category_type",
    "dimension",
    "dimension_type",
    "knowledge_area",
    "knowledge_category",
    "knowledge_dimension",
    "knowledge_label",
    "knowledge_type",
    "label_type",
    "paper_focus",
    "paper_type",
    "research_area",
    "tag_dimension",
    "tag_type",
}
META_TAGGING_VALUES = {
    "application",
    "approach",
    "category",
    "claim",
    "context",
    "data",
    "dimension",
    "domain",
    "equity",
    "evidence",
    "intervention",
    "mechanism",
    "method",
    "outcome",
    "phenomenon",
    "population",
    "research_area",
    "setting",
    "target",
    "technology",
    "tool",
}

BOILERPLATE_CATEGORY_IDS = {
    "data_source_type",
    "population_group",
    "study_design",
    "study_population",
    "study_type",
    "target_population",
}
BOILERPLATE_CATEGORY_VALUES = {
    "case_control",
    "cohort",
    "cross_sectional",
    "experimental",
    "longitudinal",
    "meta_analysis",
    "mixed_methods",
    "observational",
    "patients",
    "review",
    "survey",
    "systematic_review",
}
GENERATED_CATCHALL_TAG_VALUES = {
    *FALLBACK_TAG_VALUES,
    "miscellaneous",
    "other",
    "not_specified",
}
MERGED_TOPIC_ID_CONNECTORS = (
    "_and_",
    "_in_",
    "_for_",
    "_with_",
    "_using_",
    "_use_of_",
    "_impact_on_",
    "_effect_on_",
    "_effects_on_",
    "_outcomes_in_",
)
MERGED_TOPIC_PHRASE_CONNECTORS = (
    " and ",
    " in ",
    " for ",
    " with ",
    " using ",
    " use of ",
    " impact on ",
    " effect on ",
    " effects on ",
    " outcomes in ",
)
GENERIC_TOPIC_STRUCTURE_TERMS = {
    "area",
    "areas",
    "context",
    "contexts",
    "domain",
    "domains",
    "education",
    "educational context",
    "educational contexts",
    "educational setting",
    "educational settings",
    "field",
    "fields",
    "learning",
    "learning environment",
    "learning environments",
    "method",
    "methods",
    "outcome",
    "outcomes",
    "performance metric",
    "performance metrics",
    "population",
    "populations",
    "research",
    "setting",
    "settings",
    "student outcomes",
    "students",
    "studies",
    "study",
    "digital technology",
    "digital technologies",
    "edtech",
    "educational technology",
    "educational technologies",
    "technology",
    "technologies",
    "tool",
    "tools",
    "topic",
    "topics",
}
BROAD_UMBRELLA_TOPIC_STRUCTURE_TERMS = {
    "analysis",
    "approach",
    "condition",
    "data analysis",
    "disease",
    "disorder",
    "method",
    "neurological disorder",
    "research",
    "science",
    "technology",
}
TITLE_FIELD_COMPONENT_WORDS = {
    "classroom",
    "classrooms",
    "community",
    "communities",
    "context",
    "contexts",
    "environment",
    "environments",
    "hospital",
    "hospitals",
    "patient",
    "patients",
    "population",
    "populations",
    "school",
    "schools",
    "setting",
    "settings",
    "workplace",
    "workplaces",
}
TITLE_OR_ABSTRACT_EXCEPTION_TOPIC_WORDS = {
    "adoption",
    "calibration",
    "deployment",
    "evaluation",
    "evidence",
    "explanation",
    "explanatory",
    "feasibility",
    "implementation",
    "integration",
    "mechanism",
    "mechanisms",
    "mechanistic",
    "mediation",
    "mediator",
    "mediators",
    "metric",
    "metrics",
    "moderation",
    "moderator",
    "moderators",
    "pathway",
    "pathways",
    "process",
    "processes",
    "protocol",
    "protocols",
    "signal",
    "signals",
    "threshold",
    "thresholds",
    "usability",
    "validation",
    "workflow",
    "workflows",
}
BROAD_UMBRELLA_TOPIC_WORDS = {
    "ability",
    "abilities",
    "behavior",
    "behaviors",
    "cognition",
    "cognitive",
    "effect",
    "effects",
    "function",
    "functions",
    "impact",
    "impacts",
    "outcome",
    "outcomes",
    "performance",
}
METHOD_TOPIC_WORDS = {
    "analysis",
    "approach",
    "approaches",
    "computational",
    "method",
    "methods",
    "model",
    "modeling",
    "modelling",
    "models",
    "technique",
    "techniques",
}
METHOD_INTERNAL_SUBTYPE_TERMS = {
    "a.i.",
    "ai",
    "algorithm",
    "algorithm development",
    "algorithms",
    "artificial intelligence",
    "bioinformatics",
    "classification",
    "computational biology",
    "computational genomics",
    "computational modeling",
    "deep learning",
    "ensemble learning",
    "machine learning",
    "mathematical modeling",
    "ml",
    "modeling",
    "network analysis",
    "predictive modeling",
    "statistical modeling",
    "supervised learning",
    "systems biology",
    "unsupervised learning",
}
METHOD_TOPIC_BARE_DOMAIN_TERMS = {
    "amyloid plaques",
    "biomarker",
    "biomarkers",
    "cancer",
    "cognitive decline",
    "dementia",
    "gene expression",
    "genomics",
    "parkinson",
    "parkinson's disease",
    "parkinsons disease",
    "patient cohort",
    "patient cohorts",
    "tau tangles",
}
ALZHEIMER_DISEASE_SIGNAL_TERMS = {
    "ad",
    "alzheimer disease",
    "alzheimer's disease",
    "alzheimers disease",
}
ALZHEIMER_DISEASE_FAMILY_TERMS = {
    "ad",
    "alzheimer disease",
    "alzheimer's disease",
    "alzheimers disease",
    "cognitive decline",
    "dementia",
    "dementia-related cognitive impairment",
    "dementia related cognitive impairment",
    "mci",
    "mild cognitive impairment",
    "preclinical ad",
    "preclinical alzheimer disease",
    "preclinical alzheimer's disease",
    "preclinical alzheimers disease",
    "preclinical disease",
    "prodromal ad",
    "prodromal alzheimer disease",
    "prodromal alzheimer's disease",
    "prodromal alzheimers disease",
    "prodromal disease",
}
ALZHEIMER_DISEASE_NON_FAMILY_TERMS = {
    "amyloid plaque",
    "amyloid plaques",
    "amyloid pathology",
    "memory loss",
    "neurodegeneration",
    "tau pathology",
    "tau tangles",
}
PARKINSONS_DISEASE_SIGNAL_TERMS = {
    "parkinson disease",
    "parkinson's disease",
    "parkinsons disease",
    "pd",
}
PARKINSONS_DISEASE_NON_FAMILY_TERMS = {
    "movement disorder",
    "movement disorders",
}
EXPERIMENTAL_METHODS_SIGNAL_TERMS = {
    "clinical method",
    "clinical methods",
    "experimental method",
    "experimental methods",
    "laboratory method",
    "laboratory methods",
    "wet lab method",
    "wet lab methods",
}
EXPERIMENTAL_METHODS_NON_FAMILY_TERMS = {
    "clinical trial",
    "clinical trials",
    "data collection",
    "experimental design",
    "experimental designs",
}
GENERIC_SECONDARY_TOPIC_BUCKET_IDS = {
    "adjacent diseases",
    "dementia types",
    "disease types",
    "neurodegenerative diseases",
    "neurodegenerative disorders",
    "other diseases",
    "related diseases",
}
GENERIC_SECONDARY_TOPIC_TERMS = {
    "cognitive impairments",
    "dementia types",
    "disease types",
    "diseases",
    "neurodegenerative diseases",
    "neurodegenerative disorders",
    "other diseases",
    "related diseases",
}
COMMON_SURFACE_FORM_GROUPS = (
    {
        "label": "artificial intelligence",
        "abbreviations": {"ai", "a.i."},
        "full_forms": {"artificial intelligence"},
    },
    {
        "label": "machine learning",
        "abbreviations": {"ml"},
        "full_forms": {"machine learning"},
    },
    {
        "label": "large language models",
        "abbreviations": {"llm", "llms"},
        "full_forms": {"large language model", "large language models"},
    },
    {
        "label": "Alzheimer's disease",
        "abbreviations": {"ad"},
        "full_forms": {"alzheimer's disease", "alzheimer disease"},
    },
    {
        "label": "mild cognitive impairment",
        "abbreviations": {"mci"},
        "full_forms": {"mild cognitive impairment"},
    },
    {
        "label": "electroencephalography",
        "abbreviations": {"eeg"},
        "full_forms": {"electroencephalography"},
    },
    {
        "label": "magnetic resonance imaging",
        "abbreviations": {"mri"},
        "full_forms": {"magnetic resonance imaging"},
    },
    {
        "label": "positron emission tomography",
        "abbreviations": {"pet"},
        "full_forms": {"positron emission tomography"},
    },
    {
        "label": "electronic health records",
        "abbreviations": {"ehr", "ehrs"},
        "full_forms": {
            "electronic health record",
            "electronic health records",
        },
    },
)
BROAD_CRITERION_TOPIC_WORDS = {
    "ecological",
    "eco",
    "environment",
    "environmental",
    "green",
    "renewable",
    "sustainability",
    "sustainable",
}
GENERIC_APPLICATION_TOPIC_WORDS = {
    "advanced",
    "innovation",
    "innovations",
    "innovative",
    "novel",
    "science",
    "technology",
}
APPLICATION_PROCESS_OR_PROPERTY_WORDS = {
    "approach",
    "approaches",
    "efficiency",
    "efficient",
    "impact",
    "impacts",
    "improvement",
    "improvements",
    "innovation",
    "innovations",
    "integrity",
    "method",
    "methods",
    "performance",
    "practice",
    "practices",
    "process",
    "processes",
    "strategy",
    "strategies",
    "technique",
    "techniques",
}
BROAD_MATERIAL_FAMILY_WORDS = {
    "biodegradable",
    "biomaterial",
    "biomaterials",
    "bioplastic",
    "bioplastics",
    "bio",
    "based",
    "hybrid",
    "material",
    "materials",
}
MAIN_TOPIC_MIN_TERMS = 4
REPLACEMENT_ROLE_WORDS = {
    "alternative",
    "alternatives",
    "replace",
    "replacement",
    "replacements",
    "substitute",
    "substitutes",
    "substitution",
}
CONCRETE_COMPARATOR_TOPIC_WORDS = {
    "alternative",
    "alternatives",
    "application",
    "applications",
    "comparator",
    "concrete",
    "material",
    "materials",
    "replace",
    "replacement",
    "replacements",
    "substitute",
    "substitutes",
}
CONCRETE_COMPARATOR_COVERAGE_WORDS = {
    "alternative",
    "alternatives",
    "comparator",
    "concrete",
    "replace",
    "replacement",
    "replacements",
    "substitute",
    "substitutes",
}
REPLACEMENT_TARGET_STOPWORDS = {
    "a",
    "an",
    "and",
    "application",
    "applications",
    "area",
    "areas",
    "case",
    "cases",
    "certain",
    "for",
    "in",
    "of",
    "some",
    "the",
    "to",
    "use",
    "uses",
    "with",
}
APPLICATION_COMPONENT_QUALIFIERS = {
    "architectural",
    "building",
    "classroom",
    "clinical",
    "construction",
    "educational",
    "housing",
    "industrial",
    "medical",
    "school",
    "structural",
    "workplace",
}
APPLICATION_COMPONENT_HEADS = {
    "application",
    "applications",
    "context",
    "contexts",
    "environment",
    "environments",
    "lesson",
    "lessons",
    "material",
    "materials",
    "product",
    "products",
    "practice",
    "practices",
    "setting",
    "settings",
}
SOURCE_ANCHOR_STOPWORDS = {
    "a",
    "an",
    "and",
    "as",
    "be",
    "could",
    "for",
    "in",
    "of",
    "the",
    "to",
    "use",
    "used",
    "using",
    "with",
}
SOURCE_ANCHOR_MODIFIERS = {
    "chronic",
    "environmental",
    "green",
    "renewable",
    "sustainable",
}
CRUCIAL_TOPIC_STRUCTURE_ISSUE_CODES = {
    "abstract_only_main_topic_field",
    "anchor_field_not_title",
    "application_topic_criterion_term",
    "application_secondary_criterion_term",
    "cross_topic_retrieval_term",
    "cross_topic_term",
    "criterion_topic_instead_of_comparator",
    "explicit_pair_buried_in_umbrella_topic",
    "generic_secondary_topic_bucket",
    "generic_secondary_topic_term",
    "merged_topic_id",
    "merged_topic_label",
    "missing_secondary_topic",
    "non_exception_topic_field_not_title",
    "parent_secondary_term_overlap",
    "replacement_application_not_main_topic",
    "replacement_secondary_application_term",
    "replacement_secondary_criterion_term",
    "replacement_secondary_foreign_component_term",
    "replacement_secondary_material_family_term",
    "replacement_target_not_main_topic",
    "replacement_topic_application_term",
    "replacement_topic_criterion_term",
    "replacement_topic_foreign_component_term",
    "replacement_topic_material_family_term",
    "source_anchor_expected",
    "disease_research_anchor_expected",
}


@dataclass(frozen=True)
class TaggingQualityIssue:
    """Programmatic description of a generated tagging quality problem."""

    code: str
    category_id: str | None
    values: tuple[str, ...] = ()
    message: str = ""


@dataclass(frozen=True)
class TopicStructureQualityIssue:
    """Programmatic description of a generated topic-structure problem."""

    code: str
    topic_id: str | None
    value: str = ""
    message: str = ""


def require_mapping(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a mapping.")
    return value


def require_list(value: Any, label: str) -> list[Any]:
    if not isinstance(value, list):
        raise ValueError(f"{label} must be a list.")
    return value


def require_non_empty_string(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a non-empty string.")
    return value.strip()


def validate_required_topic_categories(categories: dict[str, Any]) -> None:
    """Backward-compatible no-op for callers from older scripts."""
    require_mapping(categories, "tagging.categories")


def validate_category_dependency(
    category_id: str,
    category: dict[str, Any],
    categories: dict[str, Any],
) -> None:
    """Validate an optional conditional category dependency."""
    applies_when = category.get("applies_when")
    if applies_when in (None, {}):
        return

    dependency = require_mapping(
        applies_when, f"tagging.categories.{category_id}.applies_when"
    )
    parent_id = require_non_empty_string(
        dependency.get("category_id"),
        f"tagging.categories.{category_id}.applies_when.category_id",
    )
    if parent_id == category_id:
        raise ValueError(
            f"tagging.categories.{category_id}.applies_when cannot reference itself."
        )
    if parent_id not in categories:
        raise ValueError(
            f"tagging.categories.{category_id}.applies_when references unknown "
            f"category: {parent_id}"
        )

    parent_map = require_mapping(
        categories[parent_id], f"tagging.categories.{parent_id}"
    )
    parent_values = set(
        require_list(
            parent_map.get("values"), f"tagging.categories.{parent_id}.values"
        )
    )
    values = require_list(
        dependency.get("values"),
        f"tagging.categories.{category_id}.applies_when.values",
    )
    if not values:
        raise ValueError(
            f"tagging.categories.{category_id}.applies_when.values must not be empty."
        )
    invalid_values = [
        value
        for value in values
        if not isinstance(value, str) or not value.strip() or value not in parent_values
    ]
    if invalid_values:
        raise ValueError(
            f"tagging.categories.{category_id}.applies_when contains invalid "
            f"value(s) for {parent_id}: {invalid_values}"
        )


def validate_topic_structure(contract: dict[str, Any]) -> None:
    """Validate title-selection topic decomposition."""
    topic_structure = require_mapping(
        contract.get("topic_structure"), "topic_structure"
    )
    anchor_topic_id = require_non_empty_string(
        topic_structure.get("anchor_topic_id"), "topic_structure.anchor_topic_id"
    )
    require_non_empty_string(
        topic_structure.get("anchor_reason"), "topic_structure.anchor_reason"
    )

    main_topics = require_list(
        topic_structure.get("main_topics"), "topic_structure.main_topics"
    )
    if len(main_topics) < 2:
        raise ValueError("topic_structure.main_topics must contain at least two topics.")

    main_topic_ids = set()
    for index, topic in enumerate(main_topics, start=1):
        topic_map = require_mapping(
            topic, f"topic_structure.main_topics[{index}]"
        )
        topic_id = require_non_empty_string(
            topic_map.get("topic_id"),
            f"topic_structure.main_topics[{index}].topic_id",
        )
        if topic_id in main_topic_ids:
            raise ValueError(f"Duplicate topic_structure main topic id: {topic_id}")
        main_topic_ids.add(topic_id)
        require_non_empty_string(
            topic_map.get("label"),
            f"topic_structure.main_topics[{index}].label",
        )
        field = topic_map.get("field")
        if field is not None and field not in VALID_TOPIC_FIELDS:
            raise ValueError(
                f"topic_structure.main_topics[{index}].field must be one of "
                f"{sorted(VALID_TOPIC_FIELDS)}."
            )
        terms = require_list(
            topic_map.get("terms"),
            f"topic_structure.main_topics[{index}].terms",
        )
        if not terms:
            raise ValueError(
                f"topic_structure.main_topics[{index}].terms must not be empty."
            )
        if not all(isinstance(term, str) and term.strip() for term in terms):
            raise ValueError(
                f"topic_structure.main_topics[{index}].terms must contain strings."
            )
        retrieval_terms = topic_map.get("retrieval_terms")
        if retrieval_terms is not None:
            retrieval_terms_list = require_list(
                retrieval_terms,
                f"topic_structure.main_topics[{index}].retrieval_terms",
            )
            if len(retrieval_terms_list) > RETRIEVAL_TERMS_LIMIT:
                raise ValueError(
                    "topic_structure.main_topics"
                    f"[{index}].retrieval_terms must contain at most "
                    f"{RETRIEVAL_TERMS_LIMIT} terms."
                )
            if not all(
                isinstance(term, str) and term.strip()
                for term in retrieval_terms_list
            ):
                raise ValueError(
                    "topic_structure.main_topics"
                    f"[{index}].retrieval_terms must contain strings."
                )
        matching_terms = topic_map.get("matching_terms")
        if matching_terms is not None:
            matching_terms_list = require_list(
                matching_terms,
                f"topic_structure.main_topics[{index}].matching_terms",
            )
            if not all(
                isinstance(term, str) and term.strip() for term in matching_terms_list
            ):
                raise ValueError(
                    "topic_structure.main_topics"
                    f"[{index}].matching_terms must contain strings."
                )

    if anchor_topic_id not in main_topic_ids:
        raise ValueError(
            "topic_structure.anchor_topic_id must match one main topic id."
        )

    validate_secondary_topics(
        topic_structure.get("secondary_topics"),
        main_topic_ids,
        anchor_topic_id,
    )


def validate_secondary_group(group: object, path: str) -> None:
    group_map = require_mapping(group, path)
    require_non_empty_string(
        group_map.get("secondary_topic_id"),
        f"{path}.secondary_topic_id",
    )
    require_non_empty_string(group_map.get("label"), f"{path}.label")
    field = group_map.get("field")
    if field is not None and field not in VALID_TOPIC_FIELDS:
        raise ValueError(f"{path}.field must be one of {sorted(VALID_TOPIC_FIELDS)}.")

    terms = require_list(group_map.get("terms"), f"{path}.terms")
    if not terms:
        raise ValueError(f"{path}.terms must not be empty.")
    if not all(isinstance(term, str) and term.strip() for term in terms):
        raise ValueError(f"{path}.terms must contain strings.")

    retrieval_terms = group_map.get("retrieval_terms")
    if retrieval_terms is not None:
        retrieval_terms_list = require_list(
            retrieval_terms,
            f"{path}.retrieval_terms",
        )
        if len(retrieval_terms_list) > RETRIEVAL_TERMS_LIMIT:
            raise ValueError(
                f"{path}.retrieval_terms must contain at most "
                f"{RETRIEVAL_TERMS_LIMIT} terms."
            )
        if not all(
            isinstance(term, str) and term.strip() for term in retrieval_terms_list
        ):
            raise ValueError(f"{path}.retrieval_terms must contain strings.")

    matching_terms = group_map.get("matching_terms")
    if matching_terms is not None:
        matching_terms_list = require_list(
            matching_terms,
            f"{path}.matching_terms",
        )
        if not all(
            isinstance(term, str) and term.strip() for term in matching_terms_list
        ):
            raise ValueError(f"{path}.matching_terms must contain strings.")


def validate_secondary_topics(
    secondary_topics: object,
    main_topic_ids: set[str],
    anchor_topic_id: str,
) -> None:
    _ = anchor_topic_id
    if isinstance(secondary_topics, dict):
        for topic_id, groups_value in secondary_topics.items():
            if topic_id not in main_topic_ids:
                raise ValueError(
                    "topic_structure.secondary_topics contains unknown main topic id: "
                    f"{topic_id}"
                )
            groups = require_list(
                groups_value,
                f"topic_structure.secondary_topics.{topic_id}",
            )
            if not groups:
                raise ValueError(
                    f"topic_structure.secondary_topics.{topic_id} must not be empty."
                )
            if all(not isinstance(group, dict) for group in groups):
                if not all(isinstance(term, str) and term.strip() for term in groups):
                    raise ValueError(
                        f"topic_structure.secondary_topics.{topic_id} "
                        "must contain strings."
                    )
                continue
            for index, group in enumerate(groups, start=1):
                validate_secondary_group(
                    group,
                    f"topic_structure.secondary_topics.{topic_id}[{index}]",
                )
        return

    if isinstance(secondary_topics, list):
        for index, group in enumerate(secondary_topics, start=1):
            group_map = require_mapping(
                group,
                f"topic_structure.secondary_topics[{index}]",
            )
            topic_id = require_non_empty_string(
                group_map.get("main_topic_id"),
                f"topic_structure.secondary_topics[{index}].main_topic_id",
            )
            if topic_id not in main_topic_ids:
                raise ValueError(
                    "topic_structure.secondary_topics contains unknown main topic id: "
                    f"{topic_id}"
                )
            validate_secondary_group(
                group_map,
                f"topic_structure.secondary_topics[{index}]",
            )
        return

    raise ValueError("topic_structure.secondary_topics must be a mapping or list.")


def validate_topic_contract(contract: dict[str, Any]) -> None:
    """Validate the topic contract shape needed by current pipeline steps."""
    require_non_empty_string(contract.get("topic_id"), "topic_id")

    research_topic = require_mapping(contract.get("research_topic"), "research_topic")
    require_non_empty_string(research_topic.get("title"), "research_topic.title")
    require_non_empty_string(
        research_topic.get("description"), "research_topic.description"
    )
    validate_topic_structure(contract)

    scope = require_mapping(contract.get("scope"), "scope")
    require_list(scope.get("include_criteria"), "scope.include_criteria")
    require_list(scope.get("exclude_criteria"), "scope.exclude_criteria")
    require_list(scope.get("boundary_rules"), "scope.boundary_rules")

    rule_based = require_mapping(
        contract.get("rule_based_screening"), "rule_based_screening"
    )
    include_terms = require_list(
        rule_based.get("include_terms"), "rule_based_screening.include_terms"
    )
    exclude_terms = require_list(
        rule_based.get("exclude_terms"), "rule_based_screening.exclude_terms"
    )
    if not all(isinstance(term, str) and term.strip() for term in include_terms):
        raise ValueError("rule_based_screening.include_terms must contain strings.")
    if not all(isinstance(term, str) and term.strip() for term in exclude_terms):
        raise ValueError("rule_based_screening.exclude_terms must contain strings.")
    if not isinstance(rule_based.get("exclude_wins"), bool):
        raise ValueError("rule_based_screening.exclude_wins must be boolean.")

    candidate_screening = require_mapping(
        contract.get("candidate_screening"), "candidate_screening"
    )
    for key in ["missing_abstract_policy", "borderline_policy", "human_review_policy"]:
        require_non_empty_string(
            candidate_screening.get(key), f"candidate_screening.{key}"
        )

    tagging = require_mapping(contract.get("tagging"), "tagging")
    require_mapping(tagging.get("fallback_policy"), "tagging.fallback_policy")
    categories = require_mapping(tagging.get("categories"), "tagging.categories")
    if not categories:
        raise ValueError("tagging.categories must not be empty.")
    for category_id, category in categories.items():
        require_non_empty_string(category_id, "tagging category id")
        category_map = require_mapping(category, f"tagging.categories.{category_id}")
        if "required" in category_map and not isinstance(
            category_map.get("required"), bool
        ):
            raise ValueError(f"tagging.categories.{category_id}.required must be bool.")
        selection = category_map.get("selection")
        if selection is not None and selection not in VALID_CATEGORY_SELECTIONS:
            allowed = ", ".join(sorted(VALID_CATEGORY_SELECTIONS))
            raise ValueError(
                f"tagging.categories.{category_id}.selection must be one of: "
                f"{allowed}"
            )
        values = require_list(
            category_map.get("values"), f"tagging.categories.{category_id}.values"
        )
        if not values:
            raise ValueError(f"tagging.categories.{category_id}.values is empty.")
        if not all(isinstance(value, str) and value.strip() for value in values):
            raise ValueError(
                f"tagging.categories.{category_id}.values must contain strings."
            )
        if len(set(values)) != len(values):
            raise ValueError(
                f"tagging.categories.{category_id}.values must not contain duplicates."
            )

    for category_id, category in categories.items():
        category_map = require_mapping(category, f"tagging.categories.{category_id}")
        validate_category_dependency(category_id, category_map, categories)

    collection = require_mapping(contract.get("collection"), "collection")
    allowed_providers = require_list(
        collection.get("allowed_providers"), "collection.allowed_providers"
    )
    if not allowed_providers:
        raise ValueError("collection.allowed_providers must not be empty.")
    if not all(
        isinstance(provider, str) and provider.strip() for provider in allowed_providers
    ):
        raise ValueError("collection.allowed_providers must contain strings.")
    preferred_provider = require_non_empty_string(
        collection.get("preferred_provider"), "collection.preferred_provider"
    )
    if preferred_provider not in allowed_providers:
        raise ValueError("collection.preferred_provider must be allowed.")

    if "search_queries" in collection:
        search_queries = require_list(
            collection.get("search_queries"), "collection.search_queries"
        )
        for index, item in enumerate(search_queries, start=1):
            if isinstance(item, str):
                require_non_empty_string(item, f"collection.search_queries[{index}]")
                continue
            item_map = require_mapping(item, f"collection.search_queries[{index}]")
            require_non_empty_string(
                item_map.get("query"), f"collection.search_queries[{index}].query"
            )
            if "reason" in item_map:
                require_non_empty_string(
                    item_map.get("reason"),
                    f"collection.search_queries[{index}].reason",
                )


def normalize_tagging_label(value: str) -> str:
    """Normalize category ids and values for topic-agnostic quality checks."""
    normalized = re.sub(r"[^a-z0-9]+", "_", value.casefold()).strip("_")
    return re.sub(r"_+", "_", normalized)


def is_retired_tagging_category_id(category_id: object) -> bool:
    """Return whether a generated category id has been removed from the pipeline."""
    return normalize_tagging_label(str(category_id)) in RETIRED_TAGGING_CATEGORY_IDS


def is_generated_tag_label(value: str) -> bool:
    """Return whether a generated tag id/value is stable lowercase snake_case."""
    return GENERATED_TAG_LABEL_PATTERN.fullmatch(value) is not None


def substantive_tag_values(values: list[Any]) -> list[str]:
    """Return non-fallback values from a category value list."""
    substantive = []
    for value in values:
        if not isinstance(value, str):
            continue
        normalized = normalize_tagging_label(value)
        if normalized not in FALLBACK_TAG_VALUES:
            substantive.append(value)
    return substantive


def generated_tagging_quality_issue_records(
    contract: dict[str, Any],
) -> list[TaggingQualityIssue]:
    """Find weak LLM-generated tagging ontologies as structured records.

    These checks are intentionally not part of general topic-contract loading:
    legacy contracts may contain operational categories, while newly generated
    or refined contracts should contain concrete knowledge dimensions discovered
    for the topic.
    """
    issues: list[TaggingQualityIssue] = []
    tagging = require_mapping(contract.get("tagging"), "tagging")
    categories = require_mapping(tagging.get("categories"), "tagging.categories")

    if len(categories) < GENERATED_TAGGING_MIN_CATEGORIES:
        issues.append(
            TaggingQualityIssue(
                code="too_few_categories",
                category_id=None,
                message=(
                    "tagging.categories must contain at least "
                    f"{GENERATED_TAGGING_MIN_CATEGORIES} concrete knowledge "
                    f"categories; found {len(categories)}."
                ),
            )
        )

    for category_id, category in categories.items():
        category_label = normalize_tagging_label(str(category_id))
        category_map = require_mapping(category, f"tagging.categories.{category_id}")
        values = require_list(
            category_map.get("values"), f"tagging.categories.{category_id}.values"
        )
        normalized_all_values = [
            normalize_tagging_label(value)
            for value in values
            if isinstance(value, str)
        ]
        substantive_values = substantive_tag_values(values)
        normalized_values = [
            normalize_tagging_label(value)
            for value in substantive_values
            if isinstance(value, str)
        ]
        catchall_values = [
            value
            for value, normalized in zip(values, normalized_all_values)
            if normalized in GENERATED_CATCHALL_TAG_VALUES
        ]
        meta_values = [
            value
            for value, normalized in zip(substantive_values, normalized_values)
            if normalized in META_TAGGING_VALUES
        ]

        if category_label in META_TAGGING_CATEGORY_IDS:
            issues.append(
                TaggingQualityIssue(
                    code="meta_category_id",
                    category_id=str(category_id),
                    message=(
                        f"tagging.categories.{category_id} is a meta-category. "
                        "Use separate concrete categories instead."
                    ),
                )
            )
        if category_label in RETIRED_TAGGING_CATEGORY_IDS:
            issues.append(
                TaggingQualityIssue(
                    code="retired_category_id",
                    category_id=str(category_id),
                    message=(
                        f"tagging.categories.{category_id} is retired and must "
                        "not be generated. Use topic-specific categories "
                        "directly instead of a root focus category."
                    ),
                )
            )
        if not is_generated_tag_label(str(category_id)):
            issues.append(
                TaggingQualityIssue(
                    code="non_snake_category_id",
                    category_id=str(category_id),
                    message=(
                        f"tagging.categories.{category_id} must use lowercase "
                        "snake_case so generated tags stay stable in CSV exports "
                        "and downstream analysis."
                    ),
                )
            )
        if category_label in BOILERPLATE_CATEGORY_IDS:
            issues.append(
                TaggingQualityIssue(
                    code="boilerplate_category_id",
                    category_id=str(category_id),
                    message=(
                        f"tagging.categories.{category_id} is a generic "
                        "boilerplate category. Use a review-derived, "
                        "topic-specific category id and values instead, or omit "
                        "the category."
                    ),
                )
            )
        if len(substantive_values) < 2:
            issues.append(
                TaggingQualityIssue(
                    code="too_few_values",
                    category_id=str(category_id),
                    values=tuple(str(value) for value in substantive_values),
                    message=(
                        f"tagging.categories.{category_id} needs at least two "
                        "substantive non-fallback values."
                    ),
                )
            )
        if catchall_values:
            issues.append(
                TaggingQualityIssue(
                    code="catchall_values",
                    category_id=str(category_id),
                    values=tuple(str(value) for value in catchall_values),
                    message=(
                        f"tagging.categories.{category_id}.values contains "
                        f"catch-all value(s) {catchall_values}. Generated "
                        "knowledge category values should be concrete, "
                        "exhaustive, and mutually distinct; make categories "
                        "optional or conditional instead of adding "
                        "unclear/not_reported/other values."
                    ),
                )
            )

        if len(meta_values) >= 2 or (
            meta_values and len(meta_values) == len(substantive_values)
        ):
            issues.append(
                TaggingQualityIssue(
                    code="meta_values",
                    category_id=str(category_id),
                    values=tuple(str(value) for value in meta_values),
                    message=(
                        f"tagging.categories.{category_id}.values contains broad "
                        f"category-type values {meta_values}. Split these into "
                        "concrete categories with topic-specific values."
                    ),
                )
            )
        non_snake_values = [
            value for value in substantive_values if not is_generated_tag_label(value)
        ]
        if non_snake_values:
            issues.append(
                TaggingQualityIssue(
                    code="non_snake_values",
                    category_id=str(category_id),
                    values=tuple(str(value) for value in non_snake_values),
                    message=(
                        f"tagging.categories.{category_id}.values contains "
                        f"non-snake-case value(s) {non_snake_values}. Use "
                        "compact lowercase snake_case values such as "
                        "intervention_effectiveness."
                    ),
                )
            )
        applies_when = category_map.get("applies_when")
        if applies_when in (None, {}):
            continue
        dependency = require_mapping(
            applies_when, f"tagging.categories.{category_id}.applies_when"
        )
        parent_id = str(dependency.get("category_id") or "")
        if normalize_tagging_label(parent_id) in META_TAGGING_CATEGORY_IDS:
            issues.append(
                TaggingQualityIssue(
                    code="meta_dependency",
                    category_id=str(category_id),
                    values=(parent_id,),
                    message=(
                        f"tagging.categories.{category_id}.applies_when depends "
                        f"on meta-category {parent_id}. Conditional categories "
                        "should depend on concrete parent values."
                    ),
                )
            )
        trigger_values = require_list(
            dependency.get("values"),
            f"tagging.categories.{category_id}.applies_when.values",
        )
        broad_trigger_values = [
            value
            for value in trigger_values
            if isinstance(value, str)
            and normalize_tagging_label(value) in META_TAGGING_VALUES
        ]
        if broad_trigger_values:
            issues.append(
                TaggingQualityIssue(
                    code="broad_dependency_values",
                    category_id=str(category_id),
                    values=tuple(str(value) for value in broad_trigger_values),
                    message=(
                        f"tagging.categories.{category_id}.applies_when uses "
                        f"broad trigger value(s) {broad_trigger_values}. Use "
                        "concrete parent values for sub-category dependencies."
                    ),
                )
            )

    return issues


def generated_tagging_quality_issues(contract: dict[str, Any]) -> list[str]:
    """Return human-readable generated tagging quality issue messages."""
    return [
        issue.message for issue in generated_tagging_quality_issue_records(contract)
    ]


def generated_tagging_quality_warnings(contract: dict[str, Any]) -> list[str]:
    """Find soft quality concerns in generated tagging ontologies.

    These warnings identify generic-looking labels that should be avoided by the
    prompt, but should not block a run. Some topics can legitimately need a
    population or design dimension when the values are review-derived.
    """
    warnings: list[str] = []
    tagging = require_mapping(contract.get("tagging"), "tagging")
    categories = require_mapping(tagging.get("categories"), "tagging.categories")

    for category_id, category in categories.items():
        category_label = normalize_tagging_label(str(category_id))
        category_map = require_mapping(category, f"tagging.categories.{category_id}")
        values = require_list(
            category_map.get("values"), f"tagging.categories.{category_id}.values"
        )
        substantive_values = substantive_tag_values(values)
        normalized_values = [
            normalize_tagging_label(value)
            for value in substantive_values
            if isinstance(value, str)
        ]

        if category_label in BOILERPLATE_CATEGORY_IDS:
            warnings.append(
                f"tagging.categories.{category_id} looks like a generic "
                "boilerplate category. Prefer a review-derived, topic-specific "
                "category id when possible."
            )

        if substantive_values and all(
            value in BOILERPLATE_CATEGORY_VALUES for value in normalized_values
        ):
            warnings.append(
                f"tagging.categories.{category_id}.values look like generic "
                "boilerplate values. Prefer values grounded in the topic and "
                "review evidence."
            )

    return warnings


def normalized_topic_words(value: object) -> set[str]:
    """Return non-trivial words used for conservative topic-overlap checks."""
    normalized = re.sub(r"[^a-z0-9]+", " ", str(value or "").casefold())
    words = set()
    for word in normalized.split():
        if word in {"ai", "ml"}:
            words.add(word)
            continue
        if len(word) < 3 or word in {
            "and",
            "for",
            "from",
            "into",
            "the",
            "use",
            "using",
            "with",
        }:
            continue
        words.add(word)
        if len(word) > 3 and word.endswith("s"):
            words.add(word[:-1])
        if word == "educational":
            words.add("education")
    return words


def normalized_topic_term(value: object) -> str:
    """Normalize a term for literal generic-vocabulary checks."""
    return re.sub(
        r"\s+",
        " ",
        str(value or "").casefold().replace("_", " ").strip(),
    )


def topic_component_words(topic: dict[str, Any]) -> set[str]:
    words = set()
    for key in ("topic_id", "label"):
        words.update(normalized_topic_words(topic.get(key)))
    terms = topic.get("terms")
    if isinstance(terms, list):
        for term in terms:
            words.update(normalized_topic_words(term))
    return words


def topic_core_words(topic: dict[str, Any]) -> set[str]:
    """Return words from topic id and label, excluding broad role words."""
    words = set()
    for key in ("topic_id", "label"):
        words.update(normalized_topic_words(topic.get(key)))
    return {
        word
        for word in words
        if word
        not in {
            "area",
            "context",
            "domain",
            "family",
            "focus",
            "outcome",
            "setting",
            "target",
            "topic",
        }
    }


def is_replacement_topic(topic_id: str, topic: dict[str, Any]) -> bool:
    words = normalized_topic_words(f"{topic_id} {topic.get('label') or ''}")
    return bool(words.intersection(REPLACEMENT_ROLE_WORDS))


def is_application_topic(topic_id: str, topic: dict[str, Any]) -> bool:
    words = normalized_topic_words(f"{topic_id} {topic.get('label') or ''}")
    return bool(
        words.intersection(APPLICATION_COMPONENT_QUALIFIERS)
        and words.intersection(APPLICATION_COMPONENT_HEADS)
    )


def is_method_topic(topic_id: str, topic: dict[str, Any]) -> bool:
    words = normalized_topic_words(f"{topic_id} {topic.get('label') or ''}")
    return bool(words.intersection(METHOD_TOPIC_WORDS))


def is_title_or_abstract_exception_topic(
    topic_id: str,
    topic: dict[str, Any],
) -> bool:
    """Return whether a main topic is a detail/explanatory dimension."""
    words = normalized_topic_words(f"{topic_id} {topic.get('label') or ''}")
    return bool(words.intersection(TITLE_OR_ABSTRACT_EXCEPTION_TOPIC_WORDS))


def replacement_term_allowed_words(
    topic_id: str,
    topic: dict[str, Any],
    replacement_targets: list[str],
) -> set[str]:
    words = normalized_topic_words(f"{topic_id} {topic.get('label') or ''}")
    words.update(REPLACEMENT_ROLE_WORDS)
    words.update(replacement_targets)
    if "concrete" in words:
        words.add("cement")
    if "cement" in words:
        words.add("concrete")
    return words


def broad_material_family_words(term_words: set[str]) -> set[str]:
    """Return broad material/source words, ignoring plain material(s) alone."""
    material_words = term_words.intersection(BROAD_MATERIAL_FAMILY_WORDS)
    specific_material_words = material_words - {"material", "materials"}
    if specific_material_words:
        return material_words
    return set()


def unique_string_count(values: object) -> int:
    if not isinstance(values, list):
        return 0
    return len(
        {
            normalized_topic_term(value)
            for value in values
            if str(value or "").strip()
        }
    )


def topic_surface_form_terms(topic: dict[str, Any]) -> set[str]:
    """Return normalized terms across all topic term lists."""
    terms = set()
    for key in ("terms", "retrieval_terms", "matching_terms"):
        values = topic.get(key)
        if not isinstance(values, list):
            continue
        for value in values:
            term = normalized_topic_term(value)
            if term:
                terms.add(term)
    return terms


def method_internal_subtype_matches(value: object) -> list[str]:
    """Return known method-subtype phrases contained in a term."""
    normalized = normalized_topic_term(value)
    padded = f" {normalized} "
    return sorted(
        subtype
        for subtype in METHOD_INTERNAL_SUBTYPE_TERMS
        if normalized == subtype or f" {subtype} " in padded
    )


def is_alzheimer_disease_topic(topic_id: str, topic: dict[str, Any]) -> bool:
    """Return whether a topic represents the Alzheimer disease family."""
    surface_terms = topic_surface_form_terms(topic)
    surface_terms.add(normalized_topic_term(topic_id))
    surface_terms.add(normalized_topic_term(topic.get("label")))
    return bool(surface_terms.intersection(ALZHEIMER_DISEASE_SIGNAL_TERMS))


def disease_family_variant_matches(
    parent_topic_id: str,
    parent_topic: dict[str, Any],
    value: object,
) -> list[str]:
    """Return known in-family disease variants contained in a term."""
    if not is_alzheimer_disease_topic(parent_topic_id, parent_topic):
        return []
    normalized = normalized_topic_term(value)
    if normalized in ALZHEIMER_DISEASE_FAMILY_TERMS:
        return [normalized]
    return []


def alzheimer_disease_non_family_term_matches(value: object) -> bool:
    """Return whether a term names pathology/process, not the disease family."""
    return normalized_topic_term(value) in ALZHEIMER_DISEASE_NON_FAMILY_TERMS


def parkinsons_disease_non_family_term_matches(value: object) -> bool:
    """Return whether a Parkinson secondary term is an umbrella descriptor."""
    return normalized_topic_term(value) in PARKINSONS_DISEASE_NON_FAMILY_TERMS


def experimental_methods_non_family_term_matches(value: object) -> bool:
    """Return whether an experimental-method secondary term is not a method family."""
    return normalized_topic_term(value) in EXPERIMENTAL_METHODS_NON_FAMILY_TERMS


def generic_secondary_topic_bucket_matches(value: object) -> bool:
    """Return whether a secondary topic id/label is a vague bucket."""
    return normalized_topic_term(value) in GENERIC_SECONDARY_TOPIC_BUCKET_IDS


def generic_secondary_topic_term_matches(value: object) -> bool:
    """Return whether a secondary term is a generic neighborhood descriptor."""
    return normalized_topic_term(value) in GENERIC_SECONDARY_TOPIC_TERMS


EXPLICIT_PAIR_STOPWORDS = {
    "a",
    "an",
    "and",
    "effect",
    "effects",
    "for",
    "impact",
    "impacts",
    "in",
    "its",
    "of",
    "on",
    "research",
    "the",
    "their",
    "to",
    "use",
    "using",
    "with",
}


def explicit_and_concept_pairs(topic_description: str | None) -> list[tuple[str, str]]:
    """Return conservative adjacent concept pairs explicitly joined by 'and'."""
    if not topic_description:
        return []
    raw_tokens = re.findall(r"[A-Za-z][A-Za-z0-9'-]*", topic_description.casefold())
    pairs: list[tuple[str, str]] = []
    seen = set()
    for index, token in enumerate(raw_tokens):
        if token != "and":
            continue

        left = ""
        for candidate in reversed(raw_tokens[:index]):
            if candidate not in EXPLICIT_PAIR_STOPWORDS and len(candidate) >= 3:
                left = candidate
                break
        right = ""
        for candidate in raw_tokens[index + 1 :]:
            if candidate not in EXPLICIT_PAIR_STOPWORDS and len(candidate) >= 3:
                right = candidate
                break
        if not left or not right or left == right:
            continue
        key = (left, right)
        if key in seen:
            continue
        pairs.append(key)
        seen.add(key)
    return pairs


def topic_description_words(topic_description: str | None) -> set[str]:
    if not topic_description:
        return set()
    return normalized_topic_words(topic_description)


def topic_mentions_concrete_comparator(topic_description: str | None) -> bool:
    words = topic_description_words(topic_description)
    if words.intersection(CONCRETE_COMPARATOR_TOPIC_WORDS):
        return True
    text = f" {str(topic_description or '').casefold()} "
    return any(
        phrase in text
        for phrase in (
            " instead of ",
            " replace ",
            " replaces ",
            " replacing ",
            " replacement for ",
            " substitute for ",
            " alternative to ",
        )
    )


def explicit_replacement_targets(topic_description: str | None) -> list[str]:
    """Return concrete concepts named as replacement targets in the user topic."""
    if not topic_description:
        return []
    text = str(topic_description).casefold()
    patterns = (
        (
            r"\b(?:replace|replaces|replacing)\s+"
            r"([a-z][a-z0-9'-]*(?:\s+[a-z][a-z0-9'-]*){0,2})"
        ),
        (
            r"\b(?:replacement|alternative|alternatives|substitute|substitutes)"
            r"\s+(?:for|to)\s+"
            r"([a-z][a-z0-9'-]*(?:\s+[a-z][a-z0-9'-]*){0,2})"
        ),
        (
            r"\binstead\s+of\s+"
            r"([a-z][a-z0-9'-]*(?:\s+[a-z][a-z0-9'-]*){0,2})"
        ),
    )
    targets: list[str] = []
    seen = set()
    for pattern in patterns:
        for match in re.finditer(pattern, text):
            for word in normalized_topic_words(match.group(1)):
                if word in REPLACEMENT_TARGET_STOPWORDS or len(word) < 3:
                    continue
                if word in seen:
                    continue
                targets.append(word)
                seen.add(word)
                break
    return targets


def explicit_application_components(
    topic_description: str | None,
) -> list[tuple[str, str, set[str]]]:
    """Return named application/domain components from replacement questions."""
    if not topic_description:
        return []
    text = str(topic_description).casefold()
    tokens = re.findall(r"[a-z][a-z0-9'-]*", text)
    components: list[tuple[str, str, set[str]]] = []
    seen = set()
    for qualifier, head in zip(tokens, tokens[1:]):
        if qualifier not in APPLICATION_COMPONENT_QUALIFIERS:
            continue
        if head not in APPLICATION_COMPONENT_HEADS:
            continue
        words = normalized_topic_words(f"{qualifier} {head}")
        if len(words) < 2:
            continue
        display = f"{qualifier} {head}"
        label = "_".join(display.split())
        if label in seen:
            continue
        components.append((label, display, words))
        seen.add(label)
    return components


def explicit_source_anchor_candidates(
    topic_description: str | None,
) -> list[tuple[str, set[str]]]:
    """Return likely non-replaceable sources from use/application questions."""
    if not topic_description:
        return []
    text = str(topic_description).casefold()
    token_group = r"([a-z][a-z0-9'-]*(?:\s+[a-z][a-z0-9'-]*){0,4})"
    patterns = (
        rf"\b(?:could|can|should|may|might|would)\s+{token_group}\s+be\s+used\s+to\b",
        rf"\buse\s+of\s+{token_group}\b",
        rf"\busing\s+{token_group}\s+(?:to|for|in)\b",
    )
    candidates: list[tuple[str, set[str]]] = []
    seen = set()
    for pattern in patterns:
        for match in re.finditer(pattern, text):
            raw_words = re.findall(r"[a-z][a-z0-9'-]*", match.group(1))
            source_words = []
            for word in raw_words:
                if word in {"as", "for", "in", "into", "of", "on", "to", "with"}:
                    break
                source_words.append(word)
            words = []
            for word in source_words:
                normalized_words = normalized_topic_words(word)
                for normalized in normalized_words:
                    if normalized in SOURCE_ANCHOR_STOPWORDS:
                        continue
                    if normalized in SOURCE_ANCHOR_MODIFIERS:
                        continue
                    words.append(normalized)
            if not words:
                continue
            display = " ".join(words)
            key = tuple(sorted(words))
            if key in seen:
                continue
            candidates.append((display, set(words)))
            seen.add(key)
    return candidates


def topic_text_words(topic: dict[str, Any]) -> set[str]:
    """Return words from ids, labels, and terms for explicit-pair checks."""
    texts = [topic.get("topic_id"), topic.get("label")]
    for key in ("terms", "retrieval_terms", "matching_terms"):
        values = topic.get(key)
        if isinstance(values, list):
            texts.extend(values)
    words = set()
    for text in texts:
        words.update(normalized_topic_words(text))
    return words


def generated_topic_structure_quality_issue_records(
    contract: dict[str, Any],
    topic_description: str | None = None,
) -> list[TopicStructureQualityIssue]:
    """Find weak LLM-generated topic decompositions.

    These checks are intentionally conservative. They catch obvious merged
    component labels such as ``ai_in_school`` while allowing multi-word concepts
    that function as one area, such as ``early_detection`` or ``climate_change``.
    """
    issues: list[TopicStructureQualityIssue] = []
    topic_structure = require_mapping(
        contract.get("topic_structure"), "topic_structure"
    )
    main_topics = require_list(
        topic_structure.get("main_topics"), "topic_structure.main_topics"
    )
    topic_maps = [
        require_mapping(topic, f"topic_structure.main_topics[{index}]")
        for index, topic in enumerate(main_topics, start=1)
    ]
    topic_by_id = {
        str(topic.get("topic_id") or "").strip(): topic
        for topic in topic_maps
        if str(topic.get("topic_id") or "").strip()
    }
    words_by_topic_id: dict[str, set[str]] = {}
    core_words_by_topic_id: dict[str, set[str]] = {}
    for topic in topic_maps:
        topic_id = str(topic.get("topic_id") or "").strip()
        if topic_id:
            words_by_topic_id[topic_id] = topic_component_words(topic)
            core_words_by_topic_id[topic_id] = topic_core_words(topic)

    main_topic_text_words = {
        str(topic.get("topic_id") or "").strip(): topic_text_words(topic)
        for topic in topic_maps
        if str(topic.get("topic_id") or "").strip()
    }
    main_topic_core_words = set()
    for words in core_words_by_topic_id.values():
        main_topic_core_words.update(words)
    for left, right in explicit_and_concept_pairs(topic_description):
        if left in main_topic_core_words and right in main_topic_core_words:
            continue
        for topic_id, words in main_topic_text_words.items():
            if left not in words or right not in words:
                continue
            topic_core = core_words_by_topic_id.get(topic_id, set())
            if not topic_core.intersection(BROAD_UMBRELLA_TOPIC_WORDS):
                continue
            issues.append(
                TopicStructureQualityIssue(
                    code="explicit_pair_buried_in_umbrella_topic",
                    topic_id=topic_id,
                    value=f"{left} and {right}",
                    message=(
                        "User topic explicitly names separate concepts "
                        f"`{left}` and `{right}`, but both are buried under "
                        f"umbrella main topic `{topic_id}`. Split them into "
                        "separate main topics when each is a meaningful "
                        "required concept."
                    ),
                )
            )

    description_words = topic_description_words(topic_description)
    has_concrete_comparator = topic_mentions_concrete_comparator(topic_description)
    comparator_covered = bool(
        main_topic_core_words.intersection(CONCRETE_COMPARATOR_COVERAGE_WORDS)
    )
    if has_concrete_comparator and not comparator_covered:
        for topic_id, core_words in core_words_by_topic_id.items():
            if not core_words.intersection(BROAD_CRITERION_TOPIC_WORDS):
                continue
            if not description_words.intersection(BROAD_CRITERION_TOPIC_WORDS):
                continue
            issues.append(
                TopicStructureQualityIssue(
                    code="criterion_topic_instead_of_comparator",
                    topic_id=topic_id,
                    message=(
                        f"topic_structure.main_topics.{topic_id} looks like a "
                        "broad criterion or motivation topic, while the user "
                        "question names a concrete replacement, comparator, "
                        "material, or application concept. Prefer a concrete "
                        "main topic such as the replacement/comparator or "
                        "application, and keep broad criteria in scope, "
                        "screening, or tagging."
                    ),
                )
            )
    replacement_targets = explicit_replacement_targets(topic_description)
    for target in replacement_targets:
        if target in main_topic_core_words:
            continue
        issues.append(
            TopicStructureQualityIssue(
                code="replacement_target_not_main_topic",
                topic_id=None,
                value=target,
                message=(
                    "User topic explicitly asks about replacing, substituting, "
                    f"or using an alternative to `{target}`, but no main topic "
                    "id or label represents that comparator/replacement "
                    "target. Create a main topic such as "
                    f"`{target}` or `{target}_replacement`; do not bury the "
                    "target only as a term under a broader application topic."
                ),
            )
        )
    if replacement_targets:
        for label, display, component_words in explicit_application_components(
            topic_description
        ):
            if any(
                component_words.issubset(core_words)
                for core_words in core_words_by_topic_id.values()
            ):
                continue
            issues.append(
                TopicStructureQualityIssue(
                    code="replacement_application_not_main_topic",
                    topic_id=None,
                    value=label,
                    message=(
                        "User topic names both a replacement target and an "
                        f"application/domain component `{display}`, but no "
                        "main topic id or label represents that application "
                        "component. Keep the replacement target and the "
                        "application/domain as separate main topics when both "
                        "are explicit; do not let the replacement topic absorb "
                        "the application context into its terms."
                    ),
                )
            )

    anchor_topic_id = str(topic_structure.get("anchor_topic_id") or "").strip()
    anchor_core_words = core_words_by_topic_id.get(anchor_topic_id, set())
    alzheimer_topic_ids = [
        topic_id
        for topic_id, topic in topic_by_id.items()
        if is_alzheimer_disease_topic(topic_id, topic)
    ]
    anchor_topic = topic_by_id.get(anchor_topic_id)
    if (
        alzheimer_topic_ids
        and anchor_topic is not None
        and not is_alzheimer_disease_topic(anchor_topic_id, anchor_topic)
        and is_method_topic(anchor_topic_id, anchor_topic)
    ):
        issues.append(
            TopicStructureQualityIssue(
                code="disease_research_anchor_expected",
                topic_id=anchor_topic_id or None,
                value=alzheimer_topic_ids[0],
                message=(
                    "topic_structure.anchor_topic_id is "
                    f"`{anchor_topic_id}`, a method component, while "
                    f"`{alzheimer_topic_ids[0]}` represents Alzheimer's "
                    "disease. For disease-specific method research, the "
                    "disease is the non-replaceable title anchor; method "
                    "components can have adjacent method secondaries."
                ),
            )
        )
    for display, candidate_words in explicit_source_anchor_candidates(
        topic_description
    ):
        if candidate_words.intersection(anchor_core_words):
            continue
        matching_topic_ids = [
            topic_id
            for topic_id, core_words in core_words_by_topic_id.items()
            if topic_id != anchor_topic_id and candidate_words.intersection(core_words)
        ]
        if not matching_topic_ids:
            continue
        expected_topic_id = matching_topic_ids[0]
        issues.append(
            TopicStructureQualityIssue(
                code="source_anchor_expected",
                topic_id=anchor_topic_id or None,
                value=expected_topic_id,
                message=(
                    "User topic asks whether or how a source, tool, "
                    f"intervention, or material `{display}` can be used. "
                    f"Main topic `{expected_topic_id}` represents that "
                    "non-replaceable source, so it should be the "
                    "`anchor_topic_id` instead of anchoring on an application, "
                    "outcome, or replacement/comparator goal."
                ),
            )
        )
    rich_term_topic_ids: dict[str, str] = {}
    for display, candidate_words in explicit_source_anchor_candidates(
        topic_description
    ):
        for topic_id, core_words in core_words_by_topic_id.items():
            if candidate_words.intersection(core_words):
                rich_term_topic_ids[topic_id] = display
                break
    for topic in topic_maps:
        topic_id = str(topic.get("topic_id") or "").strip()
        normalized_id = normalize_tagging_label(topic_id)
        field = str(topic.get("field") or DEFAULT_TOPIC_FIELD).strip()
        if topic_id == anchor_topic_id and field != "title":
            issues.append(
                TopicStructureQualityIssue(
                    code="anchor_field_not_title",
                    topic_id=topic_id,
                    value=field,
                    message=(
                        f"topic_structure.main_topics.{topic_id}.field is "
                        f"`{field}`. The anchor topic is the non-replaceable "
                        "retrieval focus and should use `title` so collected "
                        "papers visibly contain the anchor concept."
                    ),
                )
            )
        if field == "abstract":
            issues.append(
                TopicStructureQualityIssue(
                    code="abstract_only_main_topic_field",
                    topic_id=topic_id,
                    value=field,
                    message=(
                        f"topic_structure.main_topics.{topic_id}.field is "
                        "`abstract`. Generated main topics should not be "
                        "abstract-only retrieval gates; use `title` for "
                        "high-precision visible concepts or `title_or_abstract` "
                        "only for detail or explanatory dimensions."
                    ),
                )
            )
        component_words = normalized_topic_words(
            f"{topic_id} {topic.get('label') or ''}"
        )
        if (
            topic_id != anchor_topic_id
            and field != "title"
            and component_words.intersection(TITLE_FIELD_COMPONENT_WORDS)
        ):
            issues.append(
                TopicStructureQualityIssue(
                    code="context_topic_field_not_title",
                    topic_id=topic_id,
                    value=field,
                    message=(
                        f"topic_structure.main_topics.{topic_id}.field is "
                        f"`{field}`, but this component looks like a setting, "
                        "context, or population gate. Use `title` so the "
                        "retrieval result visibly names that component."
                    ),
                )
            )
        if (
            topic_id != anchor_topic_id
            and field == "title_or_abstract"
            and not is_title_or_abstract_exception_topic(topic_id, topic)
        ):
            issues.append(
                TopicStructureQualityIssue(
                    code="non_exception_topic_field_not_title",
                    topic_id=topic_id,
                    value=field,
                    message=(
                        f"topic_structure.main_topics.{topic_id}.field is "
                        "`title_or_abstract`, but this main topic does not "
                        "look like a mechanism, validation, workflow, "
                        "measurement-detail, implementation-detail, or "
                        "explanatory-process dimension. Generated main topics "
                        "should default to `title` unless the component is a "
                        "detail that can be absent from the title without "
                        "weakening collection relevance."
                    ),
                )
            )

        if any(connector in normalized_id for connector in MERGED_TOPIC_ID_CONNECTORS):
            issues.append(
                TopicStructureQualityIssue(
                    code="merged_topic_id",
                    topic_id=topic_id,
                    value=topic_id,
                    message=(
                        f"topic_structure.main_topics.{topic_id}.topic_id looks "
                        "like it merges multiple concept areas. Split required "
                        "areas into separate main topics, for example `ai`, "
                        "`school`, and `student_performance` instead of "
                        "`ai_in_school`."
                    ),
                )
            )

        label = str(topic.get("label") or "").strip()
        label_key = f" {label.casefold()} "
        if " and " in label_key and not any(
            phrase in label_key for phrase in ("research and development",)
        ):
            issues.append(
                TopicStructureQualityIssue(
                    code="merged_topic_label",
                    topic_id=topic_id,
                    value=label,
                    message=(
                        f"topic_structure.main_topics.{topic_id}.label appears "
                        "to combine areas with `and`. Each main topic should "
                        "name one conceptual area only."
                    ),
                )
            )

        if (
            topic_id in rich_term_topic_ids
            and not is_replacement_topic(topic_id, topic)
            and unique_string_count(topic.get("terms")) < MAIN_TOPIC_MIN_TERMS
        ):
            issues.append(
                TopicStructureQualityIssue(
                    code="too_few_main_topic_terms",
                    topic_id=topic_id,
                    value=str(unique_string_count(topic.get("terms"))),
                    message=(
                        f"topic_structure.main_topics.{topic_id}.terms has "
                        f"fewer than {MAIN_TOPIC_MIN_TERMS} terms for explicit "
                        f"source/application component "
                        f"`{rich_term_topic_ids[topic_id]}`. Add more "
                        "component-pure synonyms, variants, abbreviations, "
                        "or named subtypes when the vocabulary supports it; "
                        "do not pad with broad background words."
                    ),
                )
            )

        other_topic_words = set()
        other_core_words = set()
        own_core_words = core_words_by_topic_id.get(topic_id, set())
        replacement_topic = is_replacement_topic(topic_id, topic)
        application_topic = is_application_topic(topic_id, topic)
        method_topic = is_method_topic(topic_id, topic)
        replacement_allowed_words = replacement_term_allowed_words(
            topic_id,
            topic,
            replacement_targets,
        )
        surface_terms = topic_surface_form_terms(topic)
        for group in COMMON_SURFACE_FORM_GROUPS:
            abbreviations = group["abbreviations"]
            full_forms = group["full_forms"]
            has_abbreviation = bool(surface_terms.intersection(abbreviations))
            has_full_form = bool(surface_terms.intersection(full_forms))
            if has_abbreviation == has_full_form:
                continue
            missing_kind = "full form" if has_abbreviation else "abbreviation"
            present_terms = sorted(
                surface_terms.intersection(abbreviations.union(full_forms))
            )
            issues.append(
                TopicStructureQualityIssue(
                    code="missing_common_surface_form",
                    topic_id=topic_id,
                    value=str(group["label"]),
                    message=(
                        "topic_structure.main_topics."
                        f"{topic_id} uses common surface form(s) "
                        f"{present_terms} for {group['label']} but is missing "
                        f"the common {missing_kind}. Include commonly used "
                        "abbreviations, full forms, spelling/punctuation "
                        "variants, and synonyms explicitly when they matter; "
                        "do not invent rare variants."
                    ),
                )
            )
        for other_topic_id, words in words_by_topic_id.items():
            if other_topic_id != topic_id:
                other_topic_words.update(words)
                other_core_words.update(core_words_by_topic_id.get(other_topic_id, set()))

        for key in ("terms", "retrieval_terms", "matching_terms"):
            values = topic.get(key)
            if not isinstance(values, list):
                continue
            for value in values:
                term = str(value or "").strip()
                if not term:
                    continue
                if normalized_topic_term(term) in GENERIC_TOPIC_STRUCTURE_TERMS:
                    issues.append(
                        TopicStructureQualityIssue(
                            code="generic_topic_term",
                            topic_id=topic_id,
                            value=term,
                            message=(
                                "topic_structure.main_topics."
                                f"{topic_id}.{key} contains generic term "
                                f"`{term}`. Use specific synonyms, subtypes, "
                                "or concrete indicators for this component "
                                "instead of broad background vocabulary."
                            ),
                        )
                    )

                term_words = normalized_topic_words(term)
                if (
                    method_topic
                    and normalized_topic_term(term) in METHOD_TOPIC_BARE_DOMAIN_TERMS
                ):
                    issues.append(
                        TopicStructureQualityIssue(
                            code="method_topic_bare_domain_term",
                            topic_id=topic_id,
                            value=term,
                            message=(
                                "topic_structure.main_topics."
                                f"{topic_id}.{key} contains bare domain/object "
                                f"term `{term}`. Method-topic terms should "
                                "name methods, submethods, approaches, models, "
                                "or method-qualified applications. Use phrases "
                                "such as computational genomics or genomic "
                                "analysis instead of bare domain terms when "
                                "they are intended as methods."
                            ),
                        )
                    )
                if (
                    key in {"terms", "retrieval_terms"}
                    and normalized_topic_term(term)
                    in BROAD_UMBRELLA_TOPIC_STRUCTURE_TERMS
                    and not term_words.intersection(component_words)
                ):
                    issues.append(
                        TopicStructureQualityIssue(
                            code="broad_umbrella_topic_term",
                            topic_id=topic_id,
                            value=term,
                            message=(
                                "topic_structure.main_topics."
                                f"{topic_id}.{key} contains broad umbrella "
                                f"term `{term}`. Use a more specific synonym, "
                                "subtype, named method, target, or concrete "
                                "indicator for this component; keep broad "
                                "background terms out of retrieval structure."
                            ),
                        )
                    )
                material_family_words = broad_material_family_words(term_words)
                own_component_words = words_by_topic_id.get(topic_id, own_core_words)
                if material_family_words and not term_words.intersection(
                    own_component_words
                ):
                    issues.append(
                        TopicStructureQualityIssue(
                            code="broad_material_family_term",
                            topic_id=topic_id,
                            value=term,
                            message=(
                                "topic_structure.main_topics."
                                f"{topic_id}.{key} contains `{term}`, which "
                                "uses broad source/material-family vocabulary "
                                "without naming this component. Keep broad "
                                "material-source or material-property terms "
                                "under their own component or make them "
                                "specific to this topic."
                            ),
                        )
                    )
                if replacement_topic:
                    if material_family_words and not term_words.intersection(
                        replacement_allowed_words
                    ):
                        issues.append(
                            TopicStructureQualityIssue(
                                code="replacement_topic_material_family_term",
                                topic_id=topic_id,
                                value=term,
                                message=(
                                    "topic_structure.main_topics."
                                    f"{topic_id}.{key} contains `{term}`, "
                                    "which is broad material-family or "
                                    "material-property wording. Replacement "
                                    "topics should use target-specific "
                                    "substitution terms instead."
                                ),
                            )
                        )
                    if term_words.intersection(BROAD_CRITERION_TOPIC_WORDS):
                        issues.append(
                            TopicStructureQualityIssue(
                                code="replacement_topic_criterion_term",
                                topic_id=topic_id,
                                value=term,
                                message=(
                                    "topic_structure.main_topics."
                                    f"{topic_id}.{key} contains `{term}`, "
                                    "which uses broad criterion or motivation "
                                    "language. Replacement/comparator topics "
                                    "should stay focused on substitution terms, "
                                    "such as concrete replacement, concrete "
                                    "alternative, cement substitute, or the "
                                    "equivalent target-specific wording."
                                ),
                            )
                        )
                    foreign_words = term_words.intersection(other_core_words)
                    foreign_words.difference_update(replacement_allowed_words)
                    if foreign_words:
                        issues.append(
                            TopicStructureQualityIssue(
                                code="replacement_topic_foreign_component_term",
                                topic_id=topic_id,
                                value=term,
                                message=(
                                    "topic_structure.main_topics."
                                    f"{topic_id}.{key} contains `{term}`, "
                                    "which appears to include application, "
                                    "domain, or source vocabulary from another "
                                    "main topic. Keep replacement/comparator "
                                    "topics focused on the target and "
                                    "substitution relation only."
                                ),
                            )
                        )
                    has_application_head = bool(
                        term_words.intersection(APPLICATION_COMPONENT_HEADS)
                    )
                    has_application_qualifier = bool(
                        term_words.intersection(APPLICATION_COMPONENT_QUALIFIERS)
                    )
                    has_target_word = bool(
                        term_words.intersection(replacement_allowed_words)
                        - REPLACEMENT_ROLE_WORDS
                    )
                    if has_application_head and (
                        has_application_qualifier or not has_target_word
                    ):
                        issues.append(
                            TopicStructureQualityIssue(
                                code="replacement_topic_application_term",
                                topic_id=topic_id,
                                value=term,
                                message=(
                                    "topic_structure.main_topics."
                                    f"{topic_id}.{key} contains `{term}`, "
                                    "which looks like application/domain "
                                    "vocabulary. Put application terms under "
                                    "their own main topic instead of the "
                                    "replacement/comparator topic."
                                ),
                            )
                        )
                if application_topic:
                    if term_words.intersection(GENERIC_APPLICATION_TOPIC_WORDS):
                        issues.append(
                            TopicStructureQualityIssue(
                                code="application_topic_generic_term",
                                topic_id=topic_id,
                                value=term,
                                message=(
                                    "topic_structure.main_topics."
                                    f"{topic_id}.{key} contains `{term}`, "
                                    "which is generic application/domain "
                                    "language. Use concrete domain synonyms or "
                                    "product/application names instead of broad "
                                    "terms such as innovative, technology, or "
                                    "materials science."
                                ),
                            )
                        )
                    if term_words.intersection(
                        APPLICATION_PROCESS_OR_PROPERTY_WORDS
                    ) and not term_words.intersection(APPLICATION_COMPONENT_HEADS):
                        issues.append(
                            TopicStructureQualityIssue(
                                code="application_topic_process_or_property_term",
                                topic_id=topic_id,
                                value=term,
                                message=(
                                    "topic_structure.main_topics."
                                    f"{topic_id}.{key} contains `{term}`, "
                                    "which names a process, property, or "
                                    "evaluation angle instead of the "
                                    "application/domain object itself. "
                                    "Application/domain terms should name "
                                    "the use area, product family, setting, "
                                    "or domain; keep process and property "
                                    "language in scope, screening, or tagging "
                                    "unless it is the user's actual required "
                                    "concept."
                                ),
                            )
                        )
                    if term_words.intersection(BROAD_CRITERION_TOPIC_WORDS):
                        issues.append(
                            TopicStructureQualityIssue(
                                code="application_topic_criterion_term",
                                topic_id=topic_id,
                                value=term,
                                message=(
                                    "topic_structure.main_topics."
                                    f"{topic_id}.{key} contains `{term}`, "
                                    "which uses broad criterion or motivation "
                                    "language. Application/domain topics "
                                    "should name the application area itself; "
                                    "keep sustainability or green criteria in "
                                    "scope, screening, or tagging unless they "
                                    "are part of the user's exact required "
                                    "domain phrase."
                                ),
                            )
                        )
                if key == "retrieval_terms" and term_words.intersection(
                    other_core_words
                ) and term_words.intersection(own_core_words):
                    issues.append(
                        TopicStructureQualityIssue(
                            code="cross_topic_retrieval_term",
                            topic_id=topic_id,
                            value=term,
                            message=(
                                "topic_structure.main_topics."
                                f"{topic_id}.retrieval_terms contains `{term}`, "
                                "which appears to include vocabulary from "
                                "another main topic. Retrieval terms should "
                                "stay inside one component; combine components "
                                "through separate query blocks, not one term."
                            ),
                        )
                    )

                term_key = f" {term.casefold()} "
                if not any(
                    connector in term_key
                    for connector in MERGED_TOPIC_PHRASE_CONNECTORS
                ):
                    continue
                if term_words.intersection(other_topic_words):
                    issues.append(
                        TopicStructureQualityIssue(
                            code="cross_topic_term",
                            topic_id=topic_id,
                            value=term,
                            message=(
                                "topic_structure.main_topics."
                                f"{topic_id}.{key} contains `{term}`, which "
                                "appears to combine this topic with another "
                                "main topic. Keep terms inside one concept "
                                "area; put the other area in its own main "
                                "topic."
                            ),
                        )
                    )

    main_topic_fields = {
        str(topic.get("topic_id") or "").strip(): str(
            topic.get("field") or DEFAULT_TOPIC_FIELD
        )
        for topic in topic_maps
        if str(topic.get("topic_id") or "").strip()
    }
    topic_by_id = {
        str(topic.get("topic_id") or "").strip(): topic
        for topic in topic_maps
        if str(topic.get("topic_id") or "").strip()
    }
    secondary_groups = secondary_topic_groups_from_structure(
        topic_structure,
        main_topic_fields,
    )
    groups_by_main_topic_id: dict[str, list[dict[str, Any]]] = {
        topic_id: [] for topic_id in topic_by_id
    }
    for group in secondary_groups:
        main_topic_id = str(group.get("main_topic_id") or "").strip()
        if main_topic_id in groups_by_main_topic_id:
            groups_by_main_topic_id[main_topic_id].append(group)
        parent_topic = topic_by_id.get(main_topic_id)
        if parent_topic is None:
            continue
        parent_is_replacement = is_replacement_topic(main_topic_id, parent_topic)
        parent_is_application = is_application_topic(main_topic_id, parent_topic)
        parent_is_method = is_method_topic(main_topic_id, parent_topic)
        parent_replacement_allowed_words = replacement_term_allowed_words(
            main_topic_id,
            parent_topic,
            replacement_targets,
        )
        group_id = str(group.get("secondary_topic_id") or "").strip()
        parent_terms = set()
        for key in ("terms", "retrieval_terms", "matching_terms"):
            values = parent_topic.get(key)
            if isinstance(values, list):
                parent_terms.update(normalized_topic_term(value) for value in values)

        group_terms = set()
        for key in ("secondary_topic_id", "label"):
            value = normalized_topic_term(group.get(key))
            if value:
                group_terms.add(value.replace("_", " "))
                group_terms.add(value)
        for key in ("terms", "retrieval_terms", "matching_terms"):
            values = group.get(key)
            if isinstance(values, list):
                group_terms.update(normalized_topic_term(value) for value in values)
        group_text_values: list[tuple[str, str]] = []
        for key in ("secondary_topic_id", "label"):
            value = str(group.get(key) or "").strip()
            if value:
                group_text_values.append((key, value))
        for key in ("terms", "retrieval_terms", "matching_terms"):
            values = group.get(key)
            if isinstance(values, list):
                for value in values:
                    term = str(value or "").strip()
                    if term:
                        group_text_values.append((key, term))

        for key, term in group_text_values:
            if key in {"secondary_topic_id", "label"} and (
                generic_secondary_topic_bucket_matches(term)
            ):
                issues.append(
                    TopicStructureQualityIssue(
                        code="generic_secondary_topic_bucket",
                        topic_id=main_topic_id,
                        value=term,
                        message=(
                            "topic_structure.secondary_topics."
                            f"{main_topic_id}.{group_id}.{key} is `{term}`, "
                            "which is a vague mixed secondary bucket. Each "
                            "secondary topic must name one adjacent concept, "
                            "and that secondary topic's terms must be aliases, "
                            "variants, or surface forms of that one secondary "
                            "concept. Use separate groups such as "
                            "`parkinsons_disease` and `cancer` instead of "
                            "`related_diseases` or `other_diseases`."
                        ),
                    )
                )
            if key in {"terms", "retrieval_terms", "matching_terms"} and (
                generic_secondary_topic_term_matches(term)
            ):
                issues.append(
                    TopicStructureQualityIssue(
                        code="generic_secondary_topic_term",
                        topic_id=main_topic_id,
                        value=term,
                        message=(
                            "topic_structure.secondary_topics."
                            f"{main_topic_id}.{group_id}.{key} contains "
                            f"`{term}`, which is a generic neighborhood "
                            "descriptor rather than a term for this secondary "
                            "topic. Secondary-topic terms must belong to the "
                            "family of the secondary topic itself. For "
                            "example, a `parkinsons_disease` secondary can "
                            "use Parkinson's disease, Parkinson disease, or "
                            "PD; it should not use dementia types, "
                            "neurodegenerative diseases, or cognitive "
                            "impairments."
                        ),
                    )
                )
            term_words = normalized_topic_words(term)
            if parent_is_replacement:
                material_family_words = broad_material_family_words(term_words)
                if material_family_words and not term_words.intersection(
                    parent_replacement_allowed_words
                ):
                    issues.append(
                        TopicStructureQualityIssue(
                            code="replacement_secondary_material_family_term",
                            topic_id=main_topic_id,
                            value=term,
                            message=(
                                "topic_structure.secondary_topics."
                                f"{main_topic_id}.{group_id}.{key} contains "
                                f"`{term}`, which is broad material-family or "
                                "material-property wording. Secondary "
                                "replacements for a replacement/comparator "
                                "topic should stay target-specific, such as "
                                "cement substitution or the equivalent "
                                "comparator wording."
                            ),
                        )
                    )
                if term_words.intersection(BROAD_CRITERION_TOPIC_WORDS):
                    issues.append(
                        TopicStructureQualityIssue(
                            code="replacement_secondary_criterion_term",
                            topic_id=main_topic_id,
                            value=term,
                            message=(
                                "topic_structure.secondary_topics."
                                f"{main_topic_id}.{group_id}.{key} contains "
                                f"`{term}`, which uses broad criterion or "
                                "motivation language. Secondary replacements "
                                "for a replacement/comparator topic should "
                                "stay focused on adjacent target-specific "
                                "substitution wording."
                            ),
                        )
                    )
                foreign_words = term_words.intersection(
                    main_topic_core_words - core_words_by_topic_id.get(main_topic_id, set())
                )
                foreign_words.difference_update(parent_replacement_allowed_words)
                if foreign_words:
                    issues.append(
                        TopicStructureQualityIssue(
                            code="replacement_secondary_foreign_component_term",
                            topic_id=main_topic_id,
                            value=term,
                            message=(
                                "topic_structure.secondary_topics."
                                f"{main_topic_id}.{group_id}.{key} contains "
                                f"`{term}`, which appears to include "
                                "application, domain, or source vocabulary "
                                "from another main topic. Keep secondary "
                                "replacement groups component-pure."
                            ),
                        )
                    )
                has_application_head = bool(
                    term_words.intersection(APPLICATION_COMPONENT_HEADS)
                )
                has_application_qualifier = bool(
                    term_words.intersection(APPLICATION_COMPONENT_QUALIFIERS)
                )
                has_target_word = bool(
                    term_words.intersection(parent_replacement_allowed_words)
                    - REPLACEMENT_ROLE_WORDS
                )
                if has_application_head and (
                    has_application_qualifier or not has_target_word
                ):
                    issues.append(
                        TopicStructureQualityIssue(
                            code="replacement_secondary_application_term",
                            topic_id=main_topic_id,
                            value=term,
                            message=(
                                "topic_structure.secondary_topics."
                                f"{main_topic_id}.{group_id}.{key} contains "
                                f"`{term}`, which looks like "
                                "application/domain vocabulary. Put that "
                                "wording under the application main topic, "
                                "not a replacement secondary group."
                            ),
                        )
                    )
            if parent_is_application:
                if term_words.intersection(GENERIC_APPLICATION_TOPIC_WORDS):
                    issues.append(
                        TopicStructureQualityIssue(
                            code="application_secondary_generic_term",
                            topic_id=main_topic_id,
                            value=term,
                            message=(
                                "topic_structure.secondary_topics."
                                f"{main_topic_id}.{group_id}.{key} contains "
                                f"`{term}`, which is generic "
                                "application/domain language. Use concrete "
                                "domain synonyms or product/application names "
                                "instead of broad terms such as innovative, "
                                "technology, or materials science."
                            ),
                        )
                    )
                if term_words.intersection(
                    APPLICATION_PROCESS_OR_PROPERTY_WORDS
                ) and not term_words.intersection(APPLICATION_COMPONENT_HEADS):
                    issues.append(
                        TopicStructureQualityIssue(
                            code="application_secondary_process_or_property_term",
                            topic_id=main_topic_id,
                            value=term,
                            message=(
                                "topic_structure.secondary_topics."
                                f"{main_topic_id}.{group_id}.{key} contains "
                                f"`{term}`, which names a process, property, "
                                "or evaluation angle instead of adjacent "
                                "application/domain wording. Secondary groups "
                                "for application/domain topics should name "
                                "nearby use areas, product families, settings, "
                                "or domains."
                            ),
                        )
                    )
                if term_words.intersection(BROAD_CRITERION_TOPIC_WORDS):
                    issues.append(
                        TopicStructureQualityIssue(
                            code="application_secondary_criterion_term",
                            topic_id=main_topic_id,
                            value=term,
                            message=(
                                "topic_structure.secondary_topics."
                                f"{main_topic_id}.{group_id}.{key} contains "
                                f"`{term}`, which uses broad criterion or "
                                "motivation language. Secondary groups for an "
                                "application/domain topic should use adjacent "
                                "application wording, not sustainability, "
                                "green, renewable, or eco-friendly criteria. "
                                "For building-material topics, use fallback "
                                "groups such as construction products, "
                                "building products, structural materials, or "
                                "insulation materials when appropriate."
                            ),
                        )
                    )
                material_family_words = broad_material_family_words(term_words)
                if material_family_words and not term_words.intersection(
                    core_words_by_topic_id.get(main_topic_id, set())
                ):
                    issues.append(
                        TopicStructureQualityIssue(
                            code="application_secondary_material_family_term",
                            topic_id=main_topic_id,
                            value=term,
                            message=(
                                "topic_structure.secondary_topics."
                                f"{main_topic_id}.{group_id}.{key} contains "
                                f"`{term}`, which is broad material-family or "
                                "material-property wording. Use adjacent "
                                "application/domain terms such as construction "
                                "products, building products, structural "
                                "materials, or insulation materials when "
                                "appropriate."
                            ),
                        )
                    )

        substantive_group_terms = {
            term for term in group_terms if term and term not in {main_topic_id}
        }
        duplicated = sorted(
            term for term in substantive_group_terms if term in parent_terms
        )
        if duplicated:
            issues.append(
                TopicStructureQualityIssue(
                    code="parent_secondary_term_overlap",
                    topic_id=main_topic_id,
                    value=group_id,
                    message=(
                        "topic_structure.secondary_topics."
                        f"{main_topic_id}.{group_id} overlaps parent term(s) "
                        f"{duplicated}. Secondary topics must be adjacent "
                        "sibling directions, not restatements, synonyms, or "
                        "subtypes of the parent main topic. Move in-family "
                        "subtypes into the parent topic and keep secondary "
                        "term groups disjoint from the parent."
                    ),
                )
            )
        if parent_is_method:
            subtype_terms = sorted(
                {
                    subtype
                    for term in substantive_group_terms
                    for subtype in method_internal_subtype_matches(term)
                }
            )
            if subtype_terms:
                issues.append(
                    TopicStructureQualityIssue(
                        code="secondary_topic_internal_subtype",
                        topic_id=main_topic_id,
                        value=group_id,
                        message=(
                            "topic_structure.secondary_topics."
                            f"{main_topic_id}.{group_id} contains method "
                            f"subtype term(s) {subtype_terms}. Secondary "
                            "topics should be adjacent sibling directions, "
                            "not narrower internal parts of the parent. Move "
                            "machine learning, deep learning, statistical "
                            "modeling, network analysis, and similar method "
                            "subtypes into the parent method topic."
                        ),
                    )
                )
        disease_family_terms = sorted(
            {
                variant
                for term in substantive_group_terms
                for variant in disease_family_variant_matches(
                    main_topic_id,
                    parent_topic,
                    term,
                )
            }
        )
        if disease_family_terms:
            issues.append(
                TopicStructureQualityIssue(
                    code="secondary_topic_disease_family_variant",
                    topic_id=main_topic_id,
                    value=group_id,
                    message=(
                        "topic_structure.secondary_topics."
                        f"{main_topic_id}.{group_id} contains in-family "
                        f"disease variant term(s) {disease_family_terms}. "
                        "Secondary topics should be adjacent sibling "
                        "directions, such as other diseases or application "
                        "areas, not other names, stages, variants, or "
                        "impairment states from the parent disease family. "
                        "Move Alzheimer's disease variants such as dementia, "
                        "MCI, mild cognitive impairment, cognitive decline, "
                        "prodromal disease, or preclinical disease into the "
                        "parent disease topic."
                    ),
                )
            )
    for main_topic_id, groups in groups_by_main_topic_id.items():
        if groups:
            continue
        issues.append(
            TopicStructureQualityIssue(
                code="missing_secondary_topic",
                topic_id=main_topic_id,
                message=(
                    "topic_structure.secondary_topics should include a "
                    f"controlled adjacent sibling group for main topic "
                    f"`{main_topic_id}`. Secondary topics should provide "
                    "a different neighboring direction for broader discovery "
                    "without duplicating parent terms or listing internal "
                    "subtypes."
                ),
            )
        )

    return issues


def generated_topic_structure_quality_issues(
    contract: dict[str, Any],
    topic_description: str | None = None,
) -> list[str]:
    """Return human-readable generated topic-structure issue messages."""
    return [
        issue.message
        for issue in generated_topic_structure_quality_issue_records(
            contract,
            topic_description=topic_description,
        )
    ]


def is_crucial_topic_structure_issue(
    issue: TopicStructureQualityIssue,
) -> bool:
    """Return whether an issue violates a non-negotiable structure criterion."""
    return issue.code in CRUCIAL_TOPIC_STRUCTURE_ISSUE_CODES


def generated_topic_structure_crucial_issue_records(
    contract: dict[str, Any],
    topic_description: str | None = None,
) -> list[TopicStructureQualityIssue]:
    """Return topic-structure issues that should block or force review."""
    return [
        issue
        for issue in generated_topic_structure_quality_issue_records(
            contract,
            topic_description=topic_description,
        )
        if is_crucial_topic_structure_issue(issue)
    ]


def generated_topic_structure_crucial_issues(
    contract: dict[str, Any],
    topic_description: str | None = None,
) -> list[str]:
    """Return human-readable crucial topic-structure issue messages."""
    return [
        issue.message
        for issue in generated_topic_structure_crucial_issue_records(
            contract,
            topic_description=topic_description,
        )
    ]


def validate_generated_topic_structure_quality(
    contract: dict[str, Any],
    label: str = "Generated topic contract",
    topic_description: str | None = None,
) -> None:
    """Raise when a generated/refined contract violates crucial structure rules."""
    issues = generated_topic_structure_crucial_issues(
        contract,
        topic_description=topic_description,
    )
    if issues:
        joined = "\n- ".join(issues)
        raise ValueError(f"{label} has weak topic_structure:\n- {joined}")


def validate_generated_tagging_quality(
    contract: dict[str, Any],
    label: str = "Generated topic contract",
) -> None:
    """Raise when a generated/refined contract has weak knowledge tags."""
    issues = generated_tagging_quality_issues(contract)
    if issues:
        joined = "\n- ".join(issues)
        raise ValueError(f"{label} has weak knowledge tagging categories:\n- {joined}")


def load_topic_contract(path: Path) -> dict[str, Any]:
    """Load and validate a topic contract from YAML."""
    contract = read_yaml_object(path)
    validate_topic_contract(contract)
    return contract


def tagging_config_from_contract(contract: dict[str, Any]) -> dict[str, Any]:
    """Convert a topic contract into the legacy tagging config input shape."""
    validate_topic_contract(contract)
    tagging = require_mapping(contract["tagging"], "tagging")
    categories = require_mapping(tagging["categories"], "tagging.categories")
    active_categories = {
        category_id: category
        for category_id, category in categories.items()
        if not is_retired_tagging_category_id(category_id)
    }
    removed_category_ids = set(categories) - set(active_categories)
    active_categories = {
        category_id: category
        for category_id, category in active_categories.items()
        if not (
            isinstance(category, dict)
            and isinstance(category.get("applies_when"), dict)
            and (
                category["applies_when"].get("category_id") in removed_category_ids
                or is_retired_tagging_category_id(
                    category["applies_when"].get("category_id")
                )
            )
        )
    }

    return {
        "research_topic": contract["research_topic"],
        "categories": active_categories,
    }


def rule_based_screening_from_contract(contract: dict[str, Any]) -> dict[str, Any]:
    """Return rule-based screening settings from a validated topic contract."""
    validate_topic_contract(contract)
    rule_based = dict(
        require_mapping(contract["rule_based_screening"], "rule_based_screening")
    )
    rule_based["include_terms"] = expanded_include_terms(contract)
    return rule_based


def expanded_include_terms(contract: dict[str, Any]) -> list[str]:
    """Add topic-structure terms to screening include terms."""
    rule_based = require_mapping(contract["rule_based_screening"], "rule_based_screening")
    include_terms = list(rule_based.get("include_terms", []))

    topic_structure = require_mapping(
        contract.get("topic_structure"), "topic_structure"
    )
    main_topics = require_list(
        topic_structure.get("main_topics"), "topic_structure.main_topics"
    )
    for topic in main_topics:
        topic_map = require_mapping(topic, "topic_structure.main_topics[]")
        terms = require_list(topic_map.get("terms"), "topic_structure main terms")
        include_terms.extend(str(term).strip() for term in terms if str(term).strip())

    secondary_topics = topic_structure.get("secondary_topics")
    if isinstance(secondary_topics, dict):
        for groups_value in secondary_topics.values():
            groups = require_list(groups_value, "topic_structure secondary terms")
            if all(not isinstance(group, dict) for group in groups):
                include_terms.extend(
                    str(term).strip() for term in groups if str(term).strip()
                )
                continue
            for group in groups:
                group_map = require_mapping(group, "topic_structure secondary group")
                for key in ("terms", "retrieval_terms", "matching_terms"):
                    terms = group_map.get(key)
                    if isinstance(terms, list):
                        include_terms.extend(
                            str(term).strip()
                            for term in terms
                            if str(term).strip()
                        )
    elif isinstance(secondary_topics, list):
        for group in secondary_topics:
            group_map = require_mapping(group, "topic_structure secondary group")
            for key in ("terms", "retrieval_terms", "matching_terms"):
                terms = group_map.get(key)
                if isinstance(terms, list):
                    include_terms.extend(
                        str(term).strip()
                        for term in terms
                        if str(term).strip()
                    )

    deduped = []
    seen = set()
    for term in include_terms:
        key = term.casefold()
        if key not in seen:
            deduped.append(term)
            seen.add(key)
    return deduped


def collection_from_contract(contract: dict[str, Any]) -> dict[str, Any]:
    """Return collection settings from a validated topic contract."""
    validate_topic_contract(contract)
    return require_mapping(contract["collection"], "collection")
