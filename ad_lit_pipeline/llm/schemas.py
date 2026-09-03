from __future__ import annotations

from typing import Any

from ad_lit_pipeline.corpus.specification import (
    ACCESS_POLICIES,
    AS_OF_RESOLUTIONS,
    AVAILABILITY_DATE_RULES,
    CORPUS_SPECIFICATION_SCHEMA_VERSION,
    IDENTITY_BASIS_ORDER,
)
from ad_lit_pipeline.records.models import (
    IdentityStatus,
    NegativeNullPolicy,
    SourceVersionKind,
    WorkKind,
)
from ad_lit_pipeline.topics.contract import VALID_TAGGING_EVIDENCE_POLICIES


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


def topic_structure_schema() -> dict[str, Any]:
    """Build the JSON schema for generated topic structures."""
    main_topic_schema = {
        "type": "object",
        "properties": {
            "topic_id": {"type": "string"},
            "label": {"type": "string"},
            "field": {
                "type": "string",
                "enum": ["title", "abstract", "title_or_abstract"],
            },
            "terms": {
                "type": "array",
                "minItems": 2,
                "items": {"type": "string"},
            },
            "retrieval_terms": {
                "type": "array",
                "minItems": 1,
                "maxItems": 12,
                "items": {"type": "string"},
            },
            "matching_terms": {
                "type": "array",
                "minItems": 2,
                "items": {"type": "string"},
            },
        },
        "required": [
            "topic_id",
            "label",
            "field",
            "terms",
            "retrieval_terms",
            "matching_terms",
        ],
        "additionalProperties": False,
    }
    secondary_topic_schema = {
        "type": "object",
        "properties": {
            "main_topic_id": {"type": "string"},
            "secondary_topic_id": {"type": "string"},
            "label": {"type": "string"},
            "field": {
                "type": "string",
                "enum": ["title", "abstract", "title_or_abstract"],
            },
            "terms": {
                "type": "array",
                "minItems": 2,
                "items": {"type": "string"},
            },
            "retrieval_terms": {
                "type": "array",
                "minItems": 1,
                "maxItems": 12,
                "items": {"type": "string"},
            },
            "matching_terms": {
                "type": "array",
                "minItems": 1,
                "items": {"type": "string"},
            },
        },
        "required": [
            "main_topic_id",
            "secondary_topic_id",
            "label",
            "field",
            "terms",
            "retrieval_terms",
            "matching_terms",
        ],
        "additionalProperties": False,
    }

    return {
        "type": "object",
        "properties": {
            "anchor_topic_id": {"type": "string"},
            "anchor_reason": {"type": "string"},
            "main_topics": {
                "type": "array",
                "minItems": 2,
                "items": main_topic_schema,
            },
            "secondary_topics": {
                "type": "array",
                "items": secondary_topic_schema,
            },
        },
        "required": [
            "anchor_topic_id",
            "anchor_reason",
            "main_topics",
            "secondary_topics",
        ],
        "additionalProperties": False,
    }


def corpus_specification_schema() -> dict[str, Any]:
    """Build the strict v1 corpus-semantics schema for generated contracts."""
    return {
        "type": "object",
        "properties": {
            "schema_version": {
                "type": "string",
                "enum": [CORPUS_SPECIFICATION_SCHEMA_VERSION],
            },
            "as_of": {
                "type": ["string", "null"],
                "pattern": r"^\d{4}-\d{2}-\d{2}$",
            },
            "as_of_resolution": {
                "type": "string",
                "enum": sorted(AS_OF_RESOLUTIONS),
            },
            "availability_date_rule": {
                "type": "string",
                "enum": sorted(AVAILABILITY_DATE_RULES),
            },
            "allowed_source_types": {
                "type": "array",
                "minItems": 1,
                "uniqueItems": True,
                "items": {
                    "type": "string",
                    "enum": [item.value for item in WorkKind],
                },
            },
            "allowed_languages": {
                "type": "array",
                "uniqueItems": True,
                "items": {"type": "string"},
            },
            "include_unknown_language": {"type": "boolean"},
            "access_policy": {
                "type": "string",
                "enum": sorted(ACCESS_POLICIES),
            },
            "version_policy": {
                "type": "object",
                "properties": {
                    "mode": {
                        "type": "string",
                        "enum": ["retain_all_identified"],
                    },
                    "retained_version_kinds": {
                        "type": "array",
                        "minItems": 1,
                        "uniqueItems": True,
                        "items": {
                            "type": "string",
                            "enum": [item.value for item in SourceVersionKind],
                        },
                    },
                    "preferred_version_kind": {
                        "type": "string",
                        "enum": [item.value for item in SourceVersionKind],
                    },
                    "link_versions_only_with_evidence": {
                        "type": "boolean",
                        "enum": [True],
                    },
                },
                "required": [
                    "mode",
                    "retained_version_kinds",
                    "preferred_version_kind",
                    "link_versions_only_with_evidence",
                ],
                "additionalProperties": False,
            },
            "identity_policy": {
                "type": "object",
                "properties": {
                    "ordered_bases": {
                        "type": "array",
                        "items": {
                            "type": "string",
                            "enum": list(IDENTITY_BASIS_ORDER),
                        },
                        "uniqueItems": True,
                        "minItems": len(IDENTITY_BASIS_ORDER),
                        "maxItems": len(IDENTITY_BASIS_ORDER),
                    },
                    "metadata_fingerprint_status": {
                        "type": "string",
                        "enum": [IdentityStatus.NEEDS_REVIEW.value],
                    },
                    "ambiguous_identity_policy": {
                        "type": "string",
                        "enum": ["review"],
                    },
                },
                "required": [
                    "ordered_bases",
                    "metadata_fingerprint_status",
                    "ambiguous_identity_policy",
                ],
                "additionalProperties": False,
            },
            "unknown_date_policy": {
                "type": "string",
                "enum": ["review_and_exclude"],
            },
            "negative_null_result_policy": {
                "type": "string",
                "enum": [item.value for item in NegativeNullPolicy],
            },
        },
        "required": [
            "schema_version",
            "as_of",
            "as_of_resolution",
            "availability_date_rule",
            "allowed_source_types",
            "allowed_languages",
            "include_unknown_language",
            "access_policy",
            "version_policy",
            "identity_policy",
            "unknown_date_policy",
            "negative_null_result_policy",
        ],
        "additionalProperties": False,
    }


def topic_contract_schema(
    provider_names: list[str],
    min_tagging_categories: int = 6,
) -> dict[str, Any]:
    """Build the JSON schema for generated topic contract drafts."""
    category_dependency_schema = {
        "type": "object",
        "properties": {
            "category_id": {"type": "string"},
            "values": {
                "type": "array",
                "minItems": 1,
                "items": {"type": "string"},
            },
        },
        "required": ["category_id", "values"],
        "additionalProperties": False,
    }
    category_schema = {
        "type": "object",
        "properties": {
            "category_id": {"type": "string"},
            "description": {"type": "string"},
            "required": {"type": "boolean"},
            "selection": {"type": "string", "enum": ["single", "multi"]},
            "values": {
                "type": "array",
                "minItems": 2,
                "items": {"type": "string"},
            },
            "applies_when": {
                "type": ["object", "null"],
                "properties": category_dependency_schema["properties"],
                "required": category_dependency_schema["required"],
                "additionalProperties": False,
            },
        },
        "required": [
            "category_id",
            "description",
            "required",
            "selection",
            "values",
            "applies_when",
        ],
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
            "topic_structure": topic_structure_schema(),
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
                    "evidence_policy": {
                        "type": "string",
                        "enum": sorted(VALID_TAGGING_EVIDENCE_POLICIES),
                    },
                    "fallback_policy": {
                        "type": "object",
                        "properties": {
                            "prefer_unclear_when_allowed": {"type": "boolean"},
                            "prefer_mixed_or_unclear_when_unclear_missing": {
                                "type": "boolean"
                            },
                            "missing_information_value": {"type": "string"},
                        },
                        "required": [
                            "prefer_unclear_when_allowed",
                            "prefer_mixed_or_unclear_when_unclear_missing",
                            "missing_information_value",
                        ],
                        "additionalProperties": False,
                    },
                    "categories": {
                        "type": "array",
                        "minItems": min_tagging_categories,
                        "items": category_schema,
                    },
                },
                "required": ["evidence_policy", "fallback_policy", "categories"],
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
                    "publication_window": {
                        "type": ["object", "null"],
                        "properties": {
                            "start": {
                                "type": "string",
                                "pattern": r"^\d{4}-\d{2}-\d{2}$",
                            },
                            "end": {
                                "type": "string",
                                "pattern": r"^\d{4}-\d{2}-\d{2}$",
                            },
                        },
                        "required": ["start", "end"],
                        "additionalProperties": False,
                    },
                    "corpus_specification": corpus_specification_schema(),
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
                    "publication_window",
                    "corpus_specification",
                    "search_queries",
                ],
                "additionalProperties": False,
            },
        },
        "required": [
            "topic_id",
            "research_topic",
            "topic_structure",
            "scope",
            "rule_based_screening",
            "candidate_screening",
            "tagging",
            "collection",
        ],
        "additionalProperties": False,
    }


def topic_contract_tagging_repair_schema() -> dict[str, Any]:
    """Build the JSON schema for patch-only topic tagging repairs."""
    category_dependency_schema = {
        "type": "object",
        "properties": {
            "category_id": {"type": "string"},
            "values": {
                "type": "array",
                "minItems": 1,
                "items": {"type": "string"},
            },
        },
        "required": ["category_id", "values"],
        "additionalProperties": False,
    }
    category_schema = {
        "type": "object",
        "properties": {
            "category_id": {"type": "string"},
            "description": {"type": "string"},
            "required": {"type": "boolean"},
            "selection": {"type": "string", "enum": ["single", "multi"]},
            "values": {
                "type": "array",
                "minItems": 2,
                "items": {"type": "string"},
            },
            "applies_when": {
                "type": ["object", "null"],
                "properties": category_dependency_schema["properties"],
                "required": category_dependency_schema["required"],
                "additionalProperties": False,
            },
        },
        "required": [
            "category_id",
            "description",
            "required",
            "selection",
            "values",
            "applies_when",
        ],
        "additionalProperties": False,
    }

    return {
        "type": "object",
        "properties": {
            "remove_category_ids": {
                "type": "array",
                "items": {"type": "string"},
            },
            "upsert_categories": {
                "type": "array",
                "items": category_schema,
            },
            "repair_notes": {
                "type": "array",
                "items": {"type": "string"},
            },
        },
        "required": [
            "remove_category_ids",
            "upsert_categories",
            "repair_notes",
        ],
        "additionalProperties": False,
    }


def tagging_category_value_completion_schema(category_ids: list[str]) -> dict[str, Any]:
    """Build the schema for filling values for user-requested categories."""
    category_id_schema: dict[str, Any] = {"type": "string"}
    if category_ids:
        category_id_schema["enum"] = category_ids

    return {
        "type": "object",
        "properties": {
            "categories": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "category_id": category_id_schema,
                        "values": {
                            "type": "array",
                            "minItems": 2,
                            "items": {"type": "string"},
                        },
                        "reason": {"type": "string"},
                    },
                    "required": ["category_id", "values", "reason"],
                    "additionalProperties": False,
                },
            }
        },
        "required": ["categories"],
        "additionalProperties": False,
    }


def title_relevance_schema(
    main_topic_ids: list[str],
    secondary_topic_ids: list[str] | None = None,
) -> dict[str, Any]:
    """Build the candidate title relevance response schema."""
    topic_id_schema: dict[str, Any] = {"type": "string"}
    if main_topic_ids:
        topic_id_schema["enum"] = main_topic_ids
    secondary_topic_id_schema: dict[str, Any] = {"type": "string"}
    if secondary_topic_ids:
        secondary_topic_id_schema["enum"] = secondary_topic_ids

    return {
        "type": "object",
        "properties": {
            "anchor_present": {"type": "boolean"},
            "matched_main_topics": {
                "type": "array",
                "items": topic_id_schema,
            },
            "matched_secondary_topics": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "main_topic_id": topic_id_schema,
                        "secondary_topic_id": secondary_topic_id_schema,
                        "terms": {
                            "type": "array",
                            "items": {"type": "string"},
                        },
                    },
                    "required": ["main_topic_id", "secondary_topic_id", "terms"],
                    "additionalProperties": False,
                },
            },
            "missing_main_topics": {
                "type": "array",
                "items": topic_id_schema,
            },
            "relevance_tier": {"type": "integer"},
            "decision": {"type": "string", "enum": ["include", "exclude"]},
            "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
            "reason": {"type": "string"},
        },
        "required": [
            "anchor_present",
            "matched_main_topics",
            "matched_secondary_topics",
            "missing_main_topics",
            "relevance_tier",
            "decision",
            "confidence",
            "reason",
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
                    "fallback_value": {"type": ["string", "null"]},
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


def review_labels_schema(config: dict[str, Any]) -> dict[str, Any]:
    """Build the strict paper-level review-label extraction schema."""
    labels = config.get("review", {}).get("labels")
    if not isinstance(labels, list):
        raise ValueError("Normalized review config must contain review.labels list.")

    label_properties: dict[str, Any] = {}
    required_labels = []
    for label in labels:
        if not isinstance(label, dict):
            raise ValueError("Normalized review labels must contain objects.")
        label_id = str(label.get("label_id") or "")
        if not label_id:
            raise ValueError("Normalized review labels must contain label_id.")

        value_mode = str(label.get("value_mode") or "")
        if value_mode in {"controlled_fixed", "controlled_auto"}:
            items: dict[str, Any] = {"type": "string"}
            allowed_values = [
                str(value.get("value"))
                for value in label.get("allowed_values", [])
                if isinstance(value, dict) and value.get("value")
            ]
            if allowed_values:
                items["enum"] = allowed_values
            property_schema: dict[str, Any] = {"type": "array", "items": items}
            max_values = label.get("max_values_per_paper")
            if isinstance(max_values, int) and max_values > 0:
                property_schema["maxItems"] = max_values
            label_properties[label_id] = property_schema
        elif value_mode == "evidence_quote":
            label_properties[label_id] = {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "quote": {"type": "string"},
                        "section": {"type": "string"},
                        "reason": {"type": "string"},
                    },
                    "required": ["quote", "section", "reason"],
                    "additionalProperties": False,
                },
            }
        else:
            label_properties[label_id] = {"type": "string"}
        required_labels.append(label_id)

    return {
        "type": "object",
        "properties": {
            "paper_id": {"type": "string"},
            "labels": {
                "type": "object",
                "properties": label_properties,
                "required": required_labels,
                "additionalProperties": False,
            },
            "evidence_sections_used": {
                "type": "array",
                "items": {"type": "string"},
            },
            "extraction_notes": {
                "type": "array",
                "items": {"type": "string"},
            },
        },
        "required": [
            "paper_id",
            "labels",
            "evidence_sections_used",
            "extraction_notes",
        ],
        "additionalProperties": False,
    }


def paper_tags_with_review_schema(
    config: dict[str, Any],
    review_config: dict[str, Any],
) -> dict[str, Any]:
    """Build one response schema for knowledge tags plus review labels."""
    return {
        "type": "object",
        "properties": {
            "knowledge_tags": paper_tags_schema(config),
            "review_labels": review_labels_schema(review_config),
        },
        "required": ["knowledge_tags", "review_labels"],
        "additionalProperties": False,
    }


def review_section_schema() -> dict[str, Any]:
    """Build the strict schema for one drafted literature-review section."""
    citation_schema = {
        "type": "object",
        "properties": {
            "paper_id": {"type": "string"},
            "claim": {"type": "string"},
        },
        "required": ["paper_id", "claim"],
        "additionalProperties": False,
    }
    quote_schema = {
        "type": "object",
        "properties": {
            "paper_id": {"type": "string"},
            "quote": {"type": "string"},
            "reason": {"type": "string"},
        },
        "required": ["paper_id", "quote", "reason"],
        "additionalProperties": False,
    }
    return {
        "type": "object",
        "properties": {
            "section_id": {"type": "string"},
            "title": {"type": "string"},
            "summary": {"type": "string"},
            "body_markdown": {"type": "string"},
            "key_points": {
                "type": "array",
                "items": {"type": "string"},
            },
            "methodological_patterns": {
                "type": "array",
                "items": {"type": "string"},
            },
            "limitations_or_gaps": {
                "type": "array",
                "items": {"type": "string"},
            },
            "citation_support": {
                "type": "array",
                "items": citation_schema,
            },
            "cited_paper_ids": {
                "type": "array",
                "items": {"type": "string"},
            },
            "quote_uses": {
                "type": "array",
                "items": quote_schema,
            },
        },
        "required": [
            "section_id",
            "title",
            "summary",
            "body_markdown",
            "key_points",
            "methodological_patterns",
            "limitations_or_gaps",
            "citation_support",
            "cited_paper_ids",
            "quote_uses",
        ],
        "additionalProperties": False,
    }


def review_sections_schema() -> dict[str, Any]:
    """Build the strict schema for edited literature-review sections."""
    return {
        "type": "object",
        "properties": {
            "sections": {
                "type": "array",
                "items": review_section_schema(),
            },
        },
        "required": ["sections"],
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
