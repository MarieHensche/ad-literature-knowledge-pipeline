from __future__ import annotations

import itertools
import re
from typing import Any

from ad_lit_pipeline.topics.matching import (
    DEFAULT_TOPIC_FIELD,
    RETRIEVAL_TERMS_LIMIT,
    dedupe_terms,
    secondary_group_id,
    secondary_topic_groups_from_structure,
    topic_field,
)


def retrieval_terms_from_topic(topic: dict[str, Any]) -> list[str]:
    retrieval_terms = topic.get("retrieval_terms")
    if isinstance(retrieval_terms, list) and retrieval_terms:
        return dedupe_terms(retrieval_terms)[:RETRIEVAL_TERMS_LIMIT]

    terms = topic.get("terms")
    if isinstance(terms, list):
        return dedupe_terms(terms)[:RETRIEVAL_TERMS_LIMIT]

    return []


def retrieval_terms_from_secondary_group(group: dict[str, Any]) -> list[str]:
    retrieval_terms = group.get("retrieval_terms")
    if isinstance(retrieval_terms, list) and retrieval_terms:
        return dedupe_terms(retrieval_terms)[:RETRIEVAL_TERMS_LIMIT]

    terms = group.get("terms")
    if isinstance(terms, list):
        return dedupe_terms(terms)[:RETRIEVAL_TERMS_LIMIT]

    return []


def safe_query_id_part(value: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9]+", "_", value.strip().lower()).strip("_")
    return cleaned or "secondary"


def fallback_block_text(terms: list[str]) -> str:
    if not terms:
        return ""
    values = []
    for term in terms:
        if any(character.isspace() for character in term):
            values.append(f'"{term}"')
        else:
            values.append(term)
    return " OR ".join(values)


def fallback_query_text(blocks: list[dict[str, Any]]) -> str:
    parts = []
    for block in blocks:
        terms = block.get("terms")
        if not isinstance(terms, list):
            continue
        text = fallback_block_text([str(term) for term in terms])
        if text:
            parts.append(f"({text})")
    return " AND ".join(parts)


def query_reason(tier: int, replaced_topic_ids: tuple[str, ...]) -> str:
    if tier == 0:
        return "Tier 0: anchor and all main topics."
    replaced = ", ".join(replaced_topic_ids)
    return f"Tier {tier}: secondary replacement for {replaced}."


def fallback_plain_query_text(terms: list[str]) -> str:
    return " ".join(term for term in terms if term.strip())


def fallback_execution_queries(
    query_id: str,
    blocks: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    term_blocks = []
    for block in blocks:
        terms = block.get("terms")
        if not isinstance(terms, list):
            continue
        cleaned_terms = dedupe_terms(terms)
        if cleaned_terms:
            term_blocks.append(cleaned_terms)

    if not term_blocks:
        return []

    query_count = max(len(terms) for terms in term_blocks)
    queries = []
    seen = set()
    for index in range(query_count):
        terms = [terms[index % len(terms)] for terms in term_blocks]
        query = fallback_plain_query_text(terms)
        key = query.casefold()
        if not query or key in seen:
            continue
        seen.add(key)
        queries.append(
            {
                "query_id": f"{query_id}_fallback_{index + 1}",
                "logical_query_id": query_id,
                "query": query,
                "reason": (
                    "Provider fallback search decomposed from structured topic "
                    f"query {query_id}."
                ),
            }
        )
    return queries


def execution_queries_for_provider(
    query_entry: dict[str, Any],
    supports_boolean_query_blocks: bool,
) -> list[dict[str, Any]]:
    query_id = str(
        query_entry.get("query_id")
        or query_entry.get("query")
        or "topic_query"
    )
    if supports_boolean_query_blocks:
        return [
            {
                **query_entry,
                "query_id": query_id,
                "logical_query_id": query_id,
                "use_query_blocks": True,
            }
        ]

    fallback_queries = query_entry.get("fallback_queries")
    if not isinstance(fallback_queries, list) or not fallback_queries:
        blocks = query_entry.get("blocks")
        fallback_queries = (
            fallback_execution_queries(query_id, blocks)
            if isinstance(blocks, list)
            else []
        )

    entries = []
    for fallback in fallback_queries:
        if not isinstance(fallback, dict):
            continue
        fallback_id = str(fallback.get("query_id") or "").strip()
        fallback_query = str(fallback.get("query") or "").strip()
        if not fallback_id or not fallback_query:
            continue
        entries.append(
            {
                **query_entry,
                "query_id": fallback_id,
                "logical_query_id": query_id,
                "query": fallback_query,
                "reason": str(fallback.get("reason") or query_entry.get("reason") or ""),
                "use_query_blocks": False,
            }
        )
    return entries


def build_query_groups_from_contract(
    contract: dict[str, Any],
    max_results: int | None = None,
    iterations_per_group: int = 2,
) -> dict[str, Any]:
    structure = contract.get("topic_structure")
    if not isinstance(structure, dict):
        return {}

    main_topics = structure.get("main_topics")
    if not isinstance(main_topics, list):
        return {}

    anchor_topic_id = str(structure.get("anchor_topic_id") or "").strip()
    topic_by_id: dict[str, dict[str, Any]] = {}
    main_topic_order: list[str] = []
    main_topic_fields: dict[str, str] = {}
    for topic in main_topics:
        if not isinstance(topic, dict):
            continue
        topic_id = str(topic.get("topic_id") or "").strip()
        if not topic_id:
            continue
        topic_by_id[topic_id] = topic
        main_topic_order.append(topic_id)

        main_topic_fields[topic_id] = topic_field(topic, DEFAULT_TOPIC_FIELD)

    secondary_by_topic_id: dict[str, list[dict[str, Any]]] = {
        topic_id: [] for topic_id in main_topic_order
    }
    for group in secondary_topic_groups_from_structure(structure, main_topic_fields):
        main_topic_id = str(group.get("main_topic_id") or "").strip()
        if main_topic_id not in secondary_by_topic_id:
            continue
        terms = retrieval_terms_from_secondary_group(group)
        if not terms:
            continue
        secondary_by_topic_id[main_topic_id].append({**group, "terms": terms})

    replaceable_topic_ids = [
        topic_id
        for topic_id in main_topic_order
        if topic_id != anchor_topic_id and secondary_by_topic_id.get(topic_id)
    ]
    has_relaxed_main_topic_fields = any(
        field != "title" for field in main_topic_fields.values()
    )

    query_groups = []
    if has_relaxed_main_topic_fields:
        strict_title_query = query_from_replacement(
            0,
            (),
            {},
            main_topic_order,
            topic_by_id,
            field_overrides={topic_id: "title" for topic_id in main_topic_order},
            query_id_override="tier_0_all_main_title",
            reason_override=(
                "Tier 0 title-strict: anchor and all main topics must match "
                "in the title."
            ),
            requires_title_screening=False,
            retrieval_phase="strict_title",
        )
        if strict_title_query is not None:
            query_groups.append(
                {
                    "group_id": "tier_0_title",
                    "tier": 0,
                    "priority": 0,
                    "goal": (
                        "Fill target results first with papers where every main "
                        "topic is visible in the title."
                    ),
                    "queries": [strict_title_query],
                }
            )

    for tier in range(len(replaceable_topic_ids) + 1):
        queries = []
        replacements = (
            [()]
            if tier == 0
            else list(itertools.combinations(replaceable_topic_ids, tier))
        )
        for replacement_tuple in replacements:
            secondary_group_options = [
                secondary_by_topic_id.get(topic_id, [])
                for topic_id in replacement_tuple
            ]
            group_combinations = (
                [()]
                if not secondary_group_options
                else list(itertools.product(*secondary_group_options))
            )
            for group_combination in group_combinations:
                group_by_topic_id = {
                    str(group.get("main_topic_id") or ""): group
                    for group in group_combination
                    if isinstance(group, dict)
                }
                query = query_from_replacement(
                    tier,
                    replacement_tuple,
                    group_by_topic_id,
                    main_topic_order,
                    topic_by_id,
                    requires_title_screening=(
                        has_relaxed_main_topic_fields if tier == 0 else True
                    ),
                    retrieval_phase="field_relaxed" if tier == 0 else "secondary",
                )
                if query is not None:
                    queries.append(query)

        if queries:
            query_groups.append(
                {
                    "group_id": f"tier_{tier}",
                    "tier": tier,
                    "priority": tier + 1 if has_relaxed_main_topic_fields else tier,
                    "goal": (
                        "Fill remaining target results with this tier before "
                        "lower-priority tiers."
                    ),
                    "queries": queries,
                }
            )

    if not query_groups:
        return {}

    return {
        "mode": "tiered_topic_blocks",
        "target_max_results": max_results,
        "iterations_per_group": iterations_per_group,
        "retrieval_terms_per_topic_limit": RETRIEVAL_TERMS_LIMIT,
        "query_groups": query_groups,
    }


def query_from_replacement(
    tier: int,
    replacement_tuple: tuple[str, ...],
    group_by_topic_id: dict[str, dict[str, Any]],
    main_topic_order: list[str],
    topic_by_id: dict[str, dict[str, Any]],
    field_overrides: dict[str, str] | None = None,
    query_id_override: str | None = None,
    reason_override: str | None = None,
    requires_title_screening: bool | None = None,
    retrieval_phase: str | None = None,
) -> dict[str, Any] | None:
    replaced = set(replacement_tuple)
    field_overrides = field_overrides or {}
    blocks = []
    skip_query = False
    for topic_id in main_topic_order:
        topic = topic_by_id[topic_id]
        field = topic_field(topic, DEFAULT_TOPIC_FIELD)
        if topic_id in replaced:
            group = group_by_topic_id.get(topic_id)
            if not isinstance(group, dict):
                skip_query = True
                break
            terms = retrieval_terms_from_secondary_group(group)
            field = topic_field(group, field)
            kind = "secondary"
            group_id = secondary_group_id(
                group,
                f"{topic_id}_secondary",
            )
        else:
            terms = retrieval_terms_from_topic(topic)
            kind = "main"
            group_id = ""
        field = field_overrides.get(topic_id, field)
        if not terms:
            skip_query = True
            break
        block = {
            "topic_id": topic_id,
            "kind": kind,
            "field": field,
            "terms": terms,
        }
        if group_id:
            block["secondary_topic_id"] = group_id
            block["secondary_topic_label"] = str(group.get("label") or group_id)
        blocks.append(block)
    if skip_query:
        return None

    query_id = f"tier_{tier}_all_main"
    replacement_groups = []
    if tier > 0:
        replacement_parts = []
        for topic_id in replacement_tuple:
            group = group_by_topic_id.get(topic_id, {})
            group_id = secondary_group_id(
                group,
                f"{topic_id}_secondary",
            )
            replacement_parts.append(
                f"{safe_query_id_part(topic_id)}_with_"
                f"{safe_query_id_part(group_id)}"
            )
            replacement_groups.append(
                {
                    "main_topic_id": topic_id,
                    "secondary_topic_id": group_id,
                    "label": str(group.get("label") or group_id),
                }
            )
        query_id = f"tier_{tier}_replace_{'__'.join(replacement_parts)}"

    if query_id_override:
        query_id = query_id_override
    if requires_title_screening is None:
        requires_title_screening = tier > 0

    return {
        "query_id": query_id,
        "tier": tier,
        "query": fallback_query_text(blocks),
        "reason": reason_override or query_reason(tier, replacement_tuple),
        "requires_title_screening": requires_title_screening,
        "retrieval_phase": retrieval_phase or ("secondary" if tier > 0 else "main"),
        "blocks": blocks,
        "replaced_main_topics": list(replacement_tuple),
        "replacement_secondary_groups": replacement_groups,
        "fallback_queries": fallback_execution_queries(query_id, blocks),
    }
