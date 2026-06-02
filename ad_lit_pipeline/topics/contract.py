#Topic contract: defines the ontology
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from ad_lit_pipeline.io.yaml_io import read_yaml_object


LEGACY_TOPIC_FIT_CATEGORY_ID = "main_topic_category"
LEGACY_RESEARCH_TARGET_CATEGORY_ID = "research_target"
REQUIRED_TOPIC_CATEGORY_IDS: tuple[str, ...] = ()
VALID_CATEGORY_SELECTIONS = {"single", "multi"}
GENERATED_TAGGING_MIN_CATEGORIES = 4

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
    "evidence_kind",
    "evidence_type",
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

    if anchor_topic_id not in main_topic_ids:
        raise ValueError(
            "topic_structure.anchor_topic_id must match one main topic id."
        )

    secondary_topics = require_mapping(
        topic_structure.get("secondary_topics"), "topic_structure.secondary_topics"
    )
    for topic_id, terms_value in secondary_topics.items():
        if topic_id not in main_topic_ids:
            raise ValueError(
                "topic_structure.secondary_topics contains unknown main topic id: "
                f"{topic_id}"
            )
        terms = require_list(
            terms_value, f"topic_structure.secondary_topics.{topic_id}"
        )
        if topic_id == anchor_topic_id and terms:
            raise ValueError(
                "topic_structure.secondary_topics must not define replacements "
                "for the anchor topic."
            )
        if not terms:
            raise ValueError(
                f"topic_structure.secondary_topics.{topic_id} must not be empty."
            )
        if not all(isinstance(term, str) and term.strip() for term in terms):
            raise ValueError(
                f"topic_structure.secondary_topics.{topic_id} must contain strings."
            )


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


def generated_tagging_quality_issues(contract: dict[str, Any]) -> list[str]:
    """Find weak LLM-generated tagging ontologies before paper tagging starts.

    These checks are intentionally not part of general topic-contract loading:
    legacy contracts may contain operational categories, while newly generated
    contracts should contain concrete knowledge dimensions discovered for the
    topic.
    """
    issues: list[str] = []
    tagging = require_mapping(contract.get("tagging"), "tagging")
    categories = require_mapping(tagging.get("categories"), "tagging.categories")

    if len(categories) < GENERATED_TAGGING_MIN_CATEGORIES:
        issues.append(
            "tagging.categories must contain at least "
            f"{GENERATED_TAGGING_MIN_CATEGORIES} concrete knowledge categories; "
            f"found {len(categories)}."
        )

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
        meta_values = [
            value
            for value, normalized in zip(substantive_values, normalized_values)
            if normalized in META_TAGGING_VALUES
        ]

        if category_label in META_TAGGING_CATEGORY_IDS:
            issues.append(
                f"tagging.categories.{category_id} is a meta-category. "
                "Use separate concrete categories instead."
            )

        if len(substantive_values) < 2:
            issues.append(
                f"tagging.categories.{category_id} needs at least two substantive "
                "non-fallback values."
            )

        if len(meta_values) >= 2 or (
            meta_values and len(meta_values) == len(substantive_values)
        ):
            issues.append(
                f"tagging.categories.{category_id}.values contains broad "
                f"category-type values {meta_values}. Split these into concrete "
                "categories with topic-specific values."
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
                f"tagging.categories.{category_id}.applies_when depends on "
                f"meta-category {parent_id}. Conditional categories should depend "
                "on concrete parent values."
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
                f"tagging.categories.{category_id}.applies_when uses broad "
                f"trigger value(s) {broad_trigger_values}. Use concrete parent "
                "values for sub-category dependencies."
            )

    return issues


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

    return {
        "research_topic": contract["research_topic"],
        "categories": categories,
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

    secondary_topics = require_mapping(
        topic_structure.get("secondary_topics"), "topic_structure.secondary_topics"
    )
    for terms_value in secondary_topics.values():
        terms = require_list(terms_value, "topic_structure secondary terms")
        include_terms.extend(str(term).strip() for term in terms if str(term).strip())

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
