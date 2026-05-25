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
            "filters",
            "provider_specific_plan",
            "screening_notes",
            "risks_or_ambiguities",
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
        properties[category_id] = {
            "type": "array",
            "items": {"type": "string"},
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
