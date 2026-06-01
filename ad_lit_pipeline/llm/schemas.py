from __future__ import annotations

from typing import Any


def plan_schema(provider_names: list[str]) -> dict[str, Any]:
    """Build the search-plan schema constrained to enabled providers."""
    return {
        "type": "object",
        "properties": {
            "topic_description": {"type": "string"},
            "recommended_provider": {
                "type": "string",
                "enum": provider_names,
            },
            "provider_reason": {"type": "string"},
            "search_goal": {"type": "string"},
            "main_search_string": {"type": "string"},
            "alternate_search_strings": {
                "type": "array",
                "items": {"type": "string"},
            },
            "search_queries": {
                "type": "array",
                "minItems": 1,
                "items": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"},
                        "reason": {"type": "string"},
                    },
                    "required": ["query", "reason"],
                    "additionalProperties": False,
                },
            },
            "filters": {
                "type": "object",
                "properties": {
                    "year_from": {"type": ["integer", "null"]},
                    "year_to": {"type": ["integer", "null"]},
                    "publication_types": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                    "open_access_only": {"type": ["boolean", "null"]},
                    "has_abstract": {"type": ["boolean", "null"]},
                    "has_full_text": {"type": ["boolean", "null"]},
                    "language": {"type": ["string", "null"]},
                    "venue_or_source": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                    "field_or_domain": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                },
                "required": [
                    "year_from",
                    "year_to",
                    "publication_types",
                    "open_access_only",
                    "has_abstract",
                    "has_full_text",
                    "language",
                    "venue_or_source",
                    "field_or_domain",
                ],
                "additionalProperties": False,
            },
            "provider_specific_plan": {
                "type": "object",
                "properties": {
                    "provider": {"type": "string", "enum": provider_names},
                    "query": {"type": "string"},
                    "filters": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "name": {"type": "string"},
                                "value": {"type": "string"},
                                "reason": {"type": "string"},
                            },
                            "required": ["name", "value", "reason"],
                            "additionalProperties": False,
                        },
                    },
                    "sort": {"type": ["string", "null"]},
                    "max_results_recommendation": {"type": "integer"},
                },
                "required": [
                    "provider",
                    "query",
                    "filters",
                    "sort",
                    "max_results_recommendation",
                ],
                "additionalProperties": False,
            },
            "screening_notes": {"type": "string"},
            "risks_or_ambiguities": {
                "type": "array",
                "items": {"type": "string"},
            },
        },
        "required": [
            "topic_description",
            "recommended_provider",
            "provider_reason",
            "search_goal",
            "main_search_string",
            "alternate_search_strings",
            "search_queries",
            "filters",
            "provider_specific_plan",
            "screening_notes",
            "risks_or_ambiguities",
        ],
        "additionalProperties": False,
    }


def topic_contract_schema(provider_names: list[str]) -> dict[str, Any]:
    """Build the JSON schema for generated topic contract drafts."""
    category_schema = {
        "type": "object",
        "properties": {
            "category_id": {"type": "string"},
            "required": {"type": "boolean"},
            "values": {
                "type": "array",
                "minItems": 2,
                "items": {"type": "string"},
            },
        },
        "required": ["category_id", "required", "values"],
        "additionalProperties": False,
    }

    return {
        "type": "object",
        "properties": {
            "topic_id": {"type": "string"},
            "research_topic": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "description": {"type": "string"},
                },
                "required": ["title", "description"],
                "additionalProperties": False,
            },
            "scope": {
                "type": "object",
                "properties": {
                    "include_criteria": {
                        "type": "array",
                        "minItems": 3,
                        "items": {"type": "string"},
                    },
                    "exclude_criteria": {
                        "type": "array",
                        "minItems": 1,
                        "items": {"type": "string"},
                    },
                    "boundary_rules": {
                        "type": "array",
                        "minItems": 1,
                        "items": {"type": "string"},
                    },
                },
                "required": [
                    "include_criteria",
                    "exclude_criteria",
                    "boundary_rules",
                ],
                "additionalProperties": False,
            },
            "rule_based_screening": {
                "type": "object",
                "properties": {
                    "include_terms": {
                        "type": "array",
                        "minItems": 3,
                        "items": {"type": "string"},
                    },
                    "exclude_terms": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                    "exclude_wins": {"type": "boolean"},
                },
                "required": ["include_terms", "exclude_terms", "exclude_wins"],
                "additionalProperties": False,
            },
            "candidate_screening": {
                "type": "object",
                "properties": {
                    "missing_abstract_policy": {"type": "string"},
                    "borderline_policy": {"type": "string"},
                    "human_review_policy": {"type": "string"},
                    "review_policy": {"type": "string"},
                    "tangential_topic_policy": {"type": "string"},
                },
                "required": [
                    "missing_abstract_policy",
                    "borderline_policy",
                    "human_review_policy",
                    "review_policy",
                    "tangential_topic_policy",
                ],
                "additionalProperties": False,
            },
            "tagging": {
                "type": "object",
                "properties": {
                    "fallback_policy": {
                        "type": "object",
                        "properties": {
                            "prefer_unclear_when_allowed": {"type": "boolean"},
                            "prefer_mixed_or_unclear_when_unclear_missing": {
                                "type": "boolean"
                            },
                            "missing_information_value": {"type": "string"},
                            "knowledge_confidence": {"type": "string"},
                            "review_status": {"type": "string"},
                        },
                        "required": [
                            "prefer_unclear_when_allowed",
                            "prefer_mixed_or_unclear_when_unclear_missing",
                            "missing_information_value",
                            "knowledge_confidence",
                            "review_status",
                        ],
                        "additionalProperties": False,
                    },
                    "categories": {
                        "type": "array",
                        "minItems": 4,
                        "items": category_schema,
                    },
                },
                "required": ["fallback_policy", "categories"],
                "additionalProperties": False,
            },
            "collection": {
                "type": "object",
                "properties": {
                    "allowed_providers": {
                        "type": "array",
                        "minItems": 1,
                        "items": {"type": "string", "enum": provider_names},
                    },
                    "preferred_provider": {
                        "type": "string",
                        "enum": provider_names,
                    },
                    "max_results_default": {"type": "integer"},
                    "exclude_openalex_review_type": {"type": "boolean"},
                    "search_queries": {
                        "type": "array",
                        "minItems": 3,
                        "items": {
                            "type": "object",
                            "properties": {
                                "query": {"type": "string"},
                                "reason": {"type": "string"},
                            },
                            "required": ["query", "reason"],
                            "additionalProperties": False,
                        },
                    },
                },
                "required": [
                    "allowed_providers",
                    "preferred_provider",
                    "max_results_default",
                    "exclude_openalex_review_type",
                    "search_queries",
                ],
                "additionalProperties": False,
            },
        },
        "required": [
            "topic_id",
            "research_topic",
            "scope",
            "rule_based_screening",
            "candidate_screening",
            "tagging",
            "collection",
        ],
        "additionalProperties": False,
    }


SCREENING_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "decision": {
            "type": "string",
            "enum": ["include", "exclude"],
        },
        "reason": {"type": "string"},
        "confidence": {
            "type": "string",
            "enum": ["high", "medium", "low"],
        },
    },
    "required": ["decision", "reason", "confidence"],
    "additionalProperties": False,
}


RULE_RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "rules": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "category_id": {"type": "string"},
                    "selection": {"type": "string", "enum": ["single", "multi"]},
                    "required": {"type": "boolean"},
                    "fallback_value": {"type": "string"},
                    "reason": {"type": "string"},
                },
                "required": [
                    "category_id",
                    "selection",
                    "required",
                    "fallback_value",
                    "reason",
                ],
                "additionalProperties": False,
            },
        }
    },
    "required": ["rules"],
    "additionalProperties": False,
}


def paper_tags_schema(config: dict[str, Any]) -> dict[str, Any]:
    """Build the strict paper-tagging response schema for a normalized config."""
    properties: dict[str, Any] = {
        "paper_id": {"type": "string"},
        "main_knowledge_claim": {"type": "string"},
    }
    required = ["paper_id", "main_knowledge_claim"]

    categories = config.get("categories")
    if not isinstance(categories, list):
        raise ValueError("Normalized tagging config must contain categories list.")

    for category in categories:
        category_id = category["category_id"]
        allowed_values = [
            value["value"]
            for value in category.get("allowed_values", [])
            if isinstance(value, dict) and value.get("value")
        ]
        items: dict[str, Any] = {"type": "string"}
        if allowed_values:
            items["enum"] = allowed_values
        properties[category_id] = {
            "type": "array",
            "items": items,
        }
        required.append(category_id)

    return {
        "type": "object",
        "properties": properties,
        "required": required,
        "additionalProperties": False,
    }


def json_schema_format(name: str, schema: dict[str, Any]) -> dict[str, Any]:
    """Return the OpenAI Responses API strict JSON-schema format payload."""
    return {
        "type": "json_schema",
        "name": name,
        "strict": True,
        "schema": schema,
    }


def text_format(name: str, schema: dict[str, Any]) -> dict[str, Any]:
    """Return the Responses API text.format wrapper for a schema."""
    return {"format": json_schema_format(name, schema)}
