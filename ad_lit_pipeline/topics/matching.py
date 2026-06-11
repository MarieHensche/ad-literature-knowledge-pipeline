from __future__ import annotations

import copy
import re
from typing import Any


VALID_TOPIC_FIELDS = {"title", "abstract", "title_or_abstract"}
DEFAULT_TOPIC_FIELD = "title"
RETRIEVAL_TERMS_LIMIT = 12
EXCLUDED_MATCH_TIER = 999


def dedupe_terms(values: list[Any]) -> list[str]:
    terms: list[str] = []
    seen = set()
    for value in values:
        term = str(value or "").strip()
        key = term.casefold()
        if not term or key in seen:
            continue
        terms.append(term)
        seen.add(key)
    return terms


def terms_from_topic(topic: dict[str, Any]) -> list[str]:
    values: list[Any] = []
    for key in ("matching_terms", "retrieval_terms", "terms"):
        raw_values = topic.get(key)
        if isinstance(raw_values, list):
            values.extend(raw_values)
    return dedupe_terms(values)


def topic_field(topic: dict[str, Any], default: str = DEFAULT_TOPIC_FIELD) -> str:
    field = str(topic.get("field") or default).strip()
    if field not in VALID_TOPIC_FIELDS:
        return default
    return field


def secondary_group_id(group: dict[str, Any], fallback: str) -> str:
    raw_id = (
        group.get("secondary_topic_id")
        or group.get("topic_id")
        or group.get("id")
        or fallback
    )
    group_id = str(raw_id or "").strip()
    return group_id or fallback


def normalized_secondary_group(
    main_topic_id: str,
    raw_group: object,
    index: int,
    default_field: str,
) -> dict[str, Any] | None:
    fallback_id = f"{main_topic_id}_secondary_{index}"
    if isinstance(raw_group, dict):
        group_id = secondary_group_id(raw_group, fallback_id)
        label = str(raw_group.get("label") or group_id).strip() or group_id
        terms = terms_from_topic(raw_group)
        if not terms:
            return None
        group = {
            "main_topic_id": main_topic_id,
            "secondary_topic_id": group_id,
            "label": label,
            "field": topic_field(raw_group, default_field),
            "terms": terms,
        }
        for key in ("retrieval_terms", "matching_terms"):
            raw_terms = raw_group.get(key)
            if isinstance(raw_terms, list):
                cleaned_terms = dedupe_terms(raw_terms)
                if cleaned_terms:
                    group[key] = cleaned_terms
        return group

    if isinstance(raw_group, list):
        terms = dedupe_terms(raw_group)
        if not terms:
            return None
        return {
            "main_topic_id": main_topic_id,
            "secondary_topic_id": fallback_id,
            "label": f"Secondary replacement for {main_topic_id}",
            "field": default_field,
            "terms": terms,
        }

    return None


def secondary_topic_groups_from_structure(
    structure: dict[str, Any],
    main_topic_fields: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    secondary_topics = structure.get("secondary_topics")
    if not isinstance(main_topic_fields, dict):
        main_topic_fields = {}

    groups: list[dict[str, Any]] = []

    def append_group(main_topic_id: str, raw_group: object, index: int) -> None:
        main_topic_id = str(main_topic_id or "").strip()
        if not main_topic_id:
            return
        default_field = main_topic_fields.get(main_topic_id, DEFAULT_TOPIC_FIELD)
        group = normalized_secondary_group(
            main_topic_id,
            raw_group,
            index,
            default_field,
        )
        if group is not None:
            groups.append(group)

    if isinstance(secondary_topics, dict):
        for raw_main_topic_id, raw_groups in secondary_topics.items():
            main_topic_id = str(raw_main_topic_id or "").strip()
            if isinstance(raw_groups, list) and all(
                not isinstance(item, dict) for item in raw_groups
            ):
                append_group(main_topic_id, raw_groups, 1)
                continue

            if isinstance(raw_groups, list):
                for index, raw_group in enumerate(raw_groups, start=1):
                    append_group(main_topic_id, raw_group, index)
                continue

            append_group(main_topic_id, raw_groups, 1)

    elif isinstance(secondary_topics, list):
        counters: dict[str, int] = {}
        for raw_group in secondary_topics:
            if not isinstance(raw_group, dict):
                continue
            main_topic_id = str(raw_group.get("main_topic_id") or "").strip()
            counters[main_topic_id] = counters.get(main_topic_id, 0) + 1
            append_group(main_topic_id, raw_group, counters[main_topic_id])

    return groups


def topic_match_spec_from_contract(contract: dict[str, Any]) -> dict[str, Any]:
    structure = contract.get("topic_structure")
    if not isinstance(structure, dict):
        return {}

    main_topics = structure.get("main_topics")
    if not isinstance(main_topics, list):
        return {}

    spec_main_topics = []
    main_topic_fields: dict[str, str] = {}
    for topic in main_topics:
        if not isinstance(topic, dict):
            continue
        topic_id = str(topic.get("topic_id") or "").strip()
        if not topic_id:
            continue
        field = topic_field(topic)
        main_topic_fields[topic_id] = field
        spec_main_topics.append(
            {
                "topic_id": topic_id,
                "label": str(topic.get("label") or topic_id),
                "field": field,
                "terms": terms_from_topic(topic),
            }
        )

    spec_secondary_topics = secondary_topic_groups_from_structure(
        structure,
        main_topic_fields,
    )

    return {
        "version": 1,
        "source": "topic_contract.topic_structure",
        "anchor_topic_id": str(structure.get("anchor_topic_id") or "").strip(),
        "main_topics": spec_main_topics,
        "secondary_topics": spec_secondary_topics,
    }


def fields_for_match(candidate: dict[str, Any], field: str) -> list[tuple[str, str]]:
    title = str(candidate.get("title") or "")
    abstract = str(candidate.get("abstract") or "")
    if field == "title":
        return [("title", title)]
    if field == "abstract":
        return [("abstract", abstract)]
    return [("title", title), ("abstract", abstract)]


def term_pattern(term: str) -> re.Pattern[str]:
    parts = [re.escape(part) for part in re.split(r"\s+", term.strip()) if part]
    pattern = r"\s+".join(parts)
    if term[:1].isalnum():
        pattern = rf"(?<![A-Za-z0-9]){pattern}"
    if term[-1:].isalnum():
        pattern = rf"{pattern}(?![A-Za-z0-9])"
    return re.compile(pattern, flags=re.IGNORECASE)


def matched_values(
    candidate: dict[str, Any],
    terms: list[str],
    field: str,
) -> list[dict[str, str]]:
    values = []
    seen = set()
    candidate_fields = fields_for_match(candidate, field)
    for term in terms:
        pattern = term_pattern(term)
        for field_name, text in candidate_fields:
            if not text or not pattern.search(text):
                continue
            key = (term.casefold(), field_name)
            if key in seen:
                continue
            values.append({"value": term, "field": field_name})
            seen.add(key)
    return values


def candidate_topic_matches(
    candidate: dict[str, Any],
    topic_match_spec: object,
) -> dict[str, Any]:
    if not isinstance(topic_match_spec, dict):
        return {}

    main_topics = topic_match_spec.get("main_topics")
    if not isinstance(main_topics, list):
        return {}

    main_values: dict[str, list[dict[str, str]]] = {}
    main_topic_ids: list[str] = []
    for topic in main_topics:
        if not isinstance(topic, dict):
            continue
        topic_id = str(topic.get("topic_id") or "").strip()
        if not topic_id:
            continue
        main_topic_ids.append(topic_id)
        raw_terms = topic.get("terms")
        terms = dedupe_terms(raw_terms if isinstance(raw_terms, list) else [])
        values = matched_values(candidate, terms, topic_field(topic))
        main_values[topic_id] = values

    secondary_values: dict[str, list[dict[str, str]]] = {
        topic_id: [] for topic_id in main_topic_ids
    }
    secondary_group_values: dict[str, dict[str, list[dict[str, str]]]] = {
        topic_id: {} for topic_id in main_topic_ids
    }
    secondary_topics = topic_match_spec.get("secondary_topics")
    if isinstance(secondary_topics, list):
        for topic in secondary_topics:
            if not isinstance(topic, dict):
                continue
            main_topic_id = str(topic.get("main_topic_id") or "").strip()
            if not main_topic_id:
                continue
            raw_terms = topic.get("terms")
            terms = dedupe_terms(raw_terms if isinstance(raw_terms, list) else [])
            values = matched_values(candidate, terms, topic_field(topic))
            if values:
                group_id = secondary_group_id(
                    topic,
                    f"{main_topic_id}_secondary",
                )
                secondary_values.setdefault(main_topic_id, []).extend(values)
                secondary_group_values.setdefault(main_topic_id, {})[
                    group_id
                ] = values

    matched_main = [
        topic_id for topic_id in main_topic_ids if main_values.get(topic_id)
    ]
    matched_secondary = [
        topic_id for topic_id in main_topic_ids if secondary_values.get(topic_id)
    ]
    missing_main = [
        topic_id for topic_id in main_topic_ids if topic_id not in set(matched_main)
    ]
    anchor_topic_id = str(topic_match_spec.get("anchor_topic_id") or "").strip()

    return {
        "anchor_topic_id": anchor_topic_id,
        "anchor_present": bool(anchor_topic_id and main_values.get(anchor_topic_id)),
        "matched_main_topics": matched_main,
        "matched_secondary_topics": matched_secondary,
        "missing_main_topics": missing_main,
        "main_topic_values": main_values,
        "secondary_topic_values": secondary_values,
        "secondary_topic_group_values": secondary_group_values,
    }


def annotate_candidate_topic_matches(
    candidate: dict[str, Any],
    topic_match_spec: object,
) -> dict[str, Any]:
    matches = candidate_topic_matches(candidate, topic_match_spec)
    if not matches:
        return candidate
    annotated = dict(candidate)
    annotated["topic_matches"] = matches
    return annotated


def local_topic_match_tier(topic_matches: object) -> int:
    if not isinstance(topic_matches, dict):
        return EXCLUDED_MATCH_TIER

    anchor_present = topic_matches.get("anchor_present") is True
    missing_main = topic_matches.get("missing_main_topics")
    secondary_values = topic_matches.get("secondary_topic_values")
    if not isinstance(missing_main, list):
        missing_main = []
    if not isinstance(secondary_values, dict):
        secondary_values = {}

    anchor_topic_id = str(topic_matches.get("anchor_topic_id") or "").strip()
    missing_ids = [str(topic_id) for topic_id in missing_main]
    missing_non_anchor = [
        topic_id for topic_id in missing_ids if topic_id != anchor_topic_id
    ]
    missing_without_secondary = [
        topic_id
        for topic_id in missing_non_anchor
        if not secondary_values.get(topic_id)
    ]

    if not anchor_present or anchor_topic_id in missing_ids or missing_without_secondary:
        return EXCLUDED_MATCH_TIER
    return len(missing_ids)


def merge_value_lists(
    existing: list[dict[str, str]],
    incoming: list[dict[str, str]],
) -> list[dict[str, str]]:
    merged = list(existing)
    seen = {
        (str(item.get("value") or "").casefold(), str(item.get("field") or ""))
        for item in merged
    }
    for item in incoming:
        value = str(item.get("value") or "").strip()
        field = str(item.get("field") or "").strip()
        key = (value.casefold(), field)
        if not value or not field or key in seen:
            continue
        merged.append({"value": value, "field": field})
        seen.add(key)
    return merged


def merge_topic_matches(matches: list[object]) -> dict[str, Any]:
    valid_matches = [match for match in matches if isinstance(match, dict)]
    if not valid_matches:
        return {}

    merged = copy.deepcopy(valid_matches[0])
    for key in ("main_topic_values", "secondary_topic_values"):
        value_map = merged.setdefault(key, {})
        if not isinstance(value_map, dict):
            value_map = {}
            merged[key] = value_map
        for match in valid_matches[1:]:
            incoming_map = match.get(key)
            if not isinstance(incoming_map, dict):
                continue
            for topic_id, incoming_values in incoming_map.items():
                if not isinstance(incoming_values, list):
                    continue
                existing_values = value_map.get(topic_id)
                if not isinstance(existing_values, list):
                    existing_values = []
                value_map[topic_id] = merge_value_lists(
                    existing_values,
                    incoming_values,
                )

    group_value_map = merged.setdefault("secondary_topic_group_values", {})
    if not isinstance(group_value_map, dict):
        group_value_map = {}
        merged["secondary_topic_group_values"] = group_value_map
    for match in valid_matches[1:]:
        incoming_map = match.get("secondary_topic_group_values")
        if not isinstance(incoming_map, dict):
            continue
        for topic_id, incoming_groups in incoming_map.items():
            if not isinstance(incoming_groups, dict):
                continue
            topic_groups = group_value_map.setdefault(topic_id, {})
            if not isinstance(topic_groups, dict):
                topic_groups = {}
                group_value_map[topic_id] = topic_groups
            for group_id, incoming_values in incoming_groups.items():
                if not isinstance(incoming_values, list):
                    continue
                existing_values = topic_groups.get(group_id)
                if not isinstance(existing_values, list):
                    existing_values = []
                topic_groups[group_id] = merge_value_lists(
                    existing_values,
                    incoming_values,
                )

    main_values = merged.get("main_topic_values")
    secondary_values = merged.get("secondary_topic_values")
    if not isinstance(main_values, dict):
        main_values = {}
    if not isinstance(secondary_values, dict):
        secondary_values = {}
    main_topic_ids = list(main_values)
    matched_main = [
        topic_id for topic_id in main_topic_ids if main_values.get(topic_id)
    ]
    matched_secondary = [
        topic_id for topic_id in main_topic_ids if secondary_values.get(topic_id)
    ]
    merged["matched_main_topics"] = matched_main
    merged["matched_secondary_topics"] = matched_secondary
    merged["missing_main_topics"] = [
        topic_id for topic_id in main_topic_ids if topic_id not in set(matched_main)
    ]
    anchor_topic_id = str(merged.get("anchor_topic_id") or "").strip()
    merged["anchor_present"] = bool(
        anchor_topic_id and main_values.get(anchor_topic_id)
    )
    return merged


def format_topic_value_map(value_map: object) -> str:
    if not isinstance(value_map, dict):
        return ""
    parts = []
    for topic_id in sorted(value_map):
        values = value_map.get(topic_id)
        if not isinstance(values, list) or not values:
            continue
        formatted_values = []
        seen = set()
        for item in values:
            if not isinstance(item, dict):
                continue
            value = str(item.get("value") or "").strip()
            field = str(item.get("field") or "").strip()
            if not value or not field:
                continue
            formatted = f"{value}@{field}"
            key = formatted.casefold()
            if key in seen:
                continue
            formatted_values.append(formatted)
            seen.add(key)
        if formatted_values:
            parts.append(f"{topic_id}={'|'.join(formatted_values)}")
    return ", ".join(parts)


def format_secondary_group_value_map(value_map: object) -> str:
    if not isinstance(value_map, dict):
        return ""
    parts = []
    for topic_id in sorted(value_map):
        groups = value_map.get(topic_id)
        if not isinstance(groups, dict):
            continue
        group_parts = []
        for group_id in sorted(groups):
            values = groups.get(group_id)
            if not isinstance(values, list) or not values:
                continue
            formatted_values = []
            seen = set()
            for item in values:
                if not isinstance(item, dict):
                    continue
                value = str(item.get("value") or "").strip()
                field = str(item.get("field") or "").strip()
                if not value or not field:
                    continue
                formatted = f"{value}@{field}"
                key = formatted.casefold()
                if key in seen:
                    continue
                formatted_values.append(formatted)
                seen.add(key)
            if formatted_values:
                group_parts.append(f"{group_id}={'|'.join(formatted_values)}")
        if group_parts:
            parts.append(f"{topic_id}[{'; '.join(group_parts)}]")
    return ", ".join(parts)
