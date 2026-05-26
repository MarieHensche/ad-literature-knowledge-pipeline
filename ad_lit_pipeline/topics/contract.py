from __future__ import annotations

from pathlib import Path
from typing import Any

from ad_lit_pipeline.io.yaml_io import read_yaml_object


DEFAULT_TOPIC_CONTRACT_PATH = Path("configs/topics/early_detection_ad.yaml")


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


def validate_topic_contract(contract: dict[str, Any]) -> None:
    """Validate the topic contract shape needed by current pipeline steps."""
    require_non_empty_string(contract.get("topic_id"), "topic_id")

    research_topic = require_mapping(contract.get("research_topic"), "research_topic")
    require_non_empty_string(research_topic.get("title"), "research_topic.title")
    require_non_empty_string(
        research_topic.get("description"), "research_topic.description"
    )

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
        require_non_empty_string(candidate_screening.get(key), f"candidate_screening.{key}")

    tagging = require_mapping(contract.get("tagging"), "tagging")
    require_mapping(tagging.get("fallback_policy"), "tagging.fallback_policy")
    categories = require_mapping(tagging.get("categories"), "tagging.categories")
    if not categories:
        raise ValueError("tagging.categories must not be empty.")
    for category_id, category in categories.items():
        require_non_empty_string(category_id, "tagging category id")
        category_map = require_mapping(category, f"tagging.categories.{category_id}")
        values = require_list(
            category_map.get("values"), f"tagging.categories.{category_id}.values"
        )
        if not values:
            raise ValueError(f"tagging.categories.{category_id}.values is empty.")
        if not all(isinstance(value, str) and value.strip() for value in values):
            raise ValueError(
                f"tagging.categories.{category_id}.values must contain strings."
            )

    collection = require_mapping(contract.get("collection"), "collection")
    allowed_providers = require_list(
        collection.get("allowed_providers"), "collection.allowed_providers"
    )
    if not allowed_providers:
        raise ValueError("collection.allowed_providers must not be empty.")
    if not all(isinstance(provider, str) and provider.strip() for provider in allowed_providers):
        raise ValueError("collection.allowed_providers must contain strings.")
    preferred_provider = require_non_empty_string(
        collection.get("preferred_provider"), "collection.preferred_provider"
    )
    if preferred_provider not in allowed_providers:
        raise ValueError("collection.preferred_provider must be allowed.")


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
    return require_mapping(contract["rule_based_screening"], "rule_based_screening")


def collection_from_contract(contract: dict[str, Any]) -> dict[str, Any]:
    """Return collection settings from a validated topic contract."""
    validate_topic_contract(contract)
    return require_mapping(contract["collection"], "collection")
