from __future__ import annotations

import argparse
import json
import os
from copy import deepcopy
from dataclasses import asdict
from pathlib import Path
from typing import Any

from ad_lit_pipeline.corpus.specification import (
    corpus_specification_from_contract,
    default_corpus_specification_mapping,
)
from ad_lit_pipeline.core.env import load_dotenv
from ad_lit_pipeline.core.step import StepResult, StepSpec
from ad_lit_pipeline.io.yaml_io import read_yaml_object, write_yaml_object
from ad_lit_pipeline.llm.client import JSONLLMClient, OpenAIResponsesClient
from ad_lit_pipeline.llm.schemas import topic_contract_schema, topic_structure_schema
from ad_lit_pipeline.llm.trace import LLMTraceWriter
from ad_lit_pipeline.prompts.render import (
    render_generate_topic_contract_prompt,
    render_repair_topic_structure_prompt,
)
from ad_lit_pipeline.topics.contract import (
    concept_excluded_term_matches,
    concept_family_variant_matches,
    generated_topic_structure_crucial_issue_records,
    generic_secondary_topic_bucket_matches,
    generic_secondary_topic_term_matches,
    is_retired_tagging_category_id,
    is_crucial_topic_structure_issue,
    is_method_topic,
    is_title_or_abstract_exception_topic,
    method_internal_subtype_matches,
    normalize_tagging_label,
    validate_generated_topic_structure_quality,
    validate_topic_contract,
)
from ad_lit_pipeline.topics.matching import RETRIEVAL_TERMS_LIMIT
from ad_lit_pipeline.topics.policy import (
    TopicConceptProfile,
    TopicStructurePolicy,
    attach_topic_policy_reference,
    default_topic_structure_policy,
    render_topic_policy_guidance,
    selected_profile_ids,
    topic_profile,
)


STEP = StepSpec(
    name="generate_topic_contract",
    inputs=["topic_description", "base_topic_contract_yaml"],
    outputs=["topic_contract_yaml"],
    uses_llm=True,
    description="Generate a topic contract draft from a research question.",
)

SYSTEM_MESSAGE = "You draft configurable literature-pipeline topic contracts as strict JSON."
MAX_CONTRACT_VALIDATION_ATTEMPTS = 3

DEFAULT_BASE_CONTRACT = (
    Path(__file__).resolve().parents[3]
    / "configs"
    / "topics"
    / "topic_contract_template.yaml"
)

SUPPORTED_PROVIDERS = ["openalex"]


def prompt_with_validation_feedback(
    prompt: str,
    error: ValueError,
    best_contract: dict[str, Any] | None = None,
    policy_guidance: str = "",
) -> str:
    """Append validation feedback for one LLM correction attempt."""
    feedback = (
        prompt
        + "\n\nYour previous JSON response failed validation:\n"
        + str(error)
        + "\n\nReturn a corrected complete JSON response. Before returning, "
        "check every validation path above and make sure the rejected category "
        "ids and values are gone or corrected.\n"
        "- Replace weak, meta, or generic boilerplate categories with concrete "
        "topic-specific knowledge categories that can be answered from "
        "individual papers.\n"
        "- Do not keep generic category ids such as `target_population`, "
        "`study_design`, `study_type`, or `data_source_type`. If the distinction "
        "is truly central, replace it with a review-derived category id whose "
        "words name the topic concept, setting, signal, intervention, exposure, "
        "or outcome.\n"
        "- Use compact lowercase snake_case category ids and values. Convert "
        "hyphens, spaces, slashes, punctuation, and title case; for example, "
        "`self-help_resources` must become `self_help_resources` or a more "
        "specific topic-derived value.\n"
        "- Do not generate retired root categories. Use concrete, "
        "topic-specific categories directly instead of a single primary-focus "
        "selector.\n"
        "- If the failure names `topic_structure`, split merged main topics "
        "into one concept area per main topic.\n"
        "- For questions like `Could X be used to...` or `Use of X in/for...`, "
        "choose X as the anchor when X is the proposed source, tool, "
        "intervention, material, disease, exposure, or core phenomenon. Do "
        "not anchor on the application, outcome, or replacement/comparator "
        "goal if papers about that goal without X would be off-topic.\n"
        "- Keep every main topic's terms inside that same concept area.\n"
        "- Include commonly used surface forms explicitly when they matter, "
        "such as abbreviations plus full forms, common punctuation variants, "
        "and common synonyms. Do not add rare, invented, or merely "
        "capitalization-only variants.\n"
        "- Set the anchor topic's `field` to `title`.\n"
        "- Replace generic topic terms with specific component vocabulary.\n"
        "- Do not use `abstract` for generated main topics; use "
        "`title` for relevance-defining components and `title_or_abstract` "
        "only for detail or explanatory dimensions such as mechanisms, "
        "validation, workflows, measurement details, implementation details, "
        "or explanatory processes.\n"
        "- Default generated main-topic fields to `title`. If a concept is "
        "required for relevance, use richer terms rather than weakening it to "
        "`title_or_abstract`.\n"
        "- Set setting, context, or population components to `title`.\n"
        "- Keep `retrieval_terms` component-pure; remove phrases that mix one "
        "main topic with another.\n"
        "- Remove secondary-topic groups that simply duplicate a parent "
        "main-topic term.\n"
        "- Every main topic, including the anchor, needs a useful adjacent "
        "sibling secondary-topic group when a clean one exists.\n"
        "- Secondary topics must go in a different adjacent direction from the "
        "parent; they are not versions, aliases, variants, types, "
        "subcategories, synonyms, spelling variants, examples, or narrower "
        "subtypes. Move in-family variants and internal subtypes into the "
        "parent terms.\n"
        "- Each secondary topic must name exactly one adjacent concept, and "
        "its terms, retrieval_terms, and matching_terms must be aliases, "
        "variants, types, abbreviations, or surface forms of that one "
        "secondary concept. Do not create vague related/other buckets or put "
        "generic neighborhood descriptors in secondary term lists.\n"
        "- Parent and secondary term groups must be disjoint across terms, "
        "retrieval_terms, and matching_terms.\n"
        "- Main-topic terms should include common in-family subtopics, "
        "methods, concepts, components, and properties, while profile-specific "
        "exclusions remain outside the topic term lists.\n"
        + ("\n" + policy_guidance if policy_guidance else "")
        +
        "- If the user asks about replacing or substituting a named thing or "
        "applying something in a named use case, do not use a broad criterion "
        "or motivation as a required main topic. Use the explicit "
        "replacement/comparator/application concept instead.\n"
        "- If the user asks about replacing, substituting, or using an "
        "alternative to a concrete target, make that target or replacement "
        "relation a main topic id/label. Do not leave the target only as a "
        "term under a broader application topic.\n"
        "- Keep replacement/comparator topics component-pure: use target and "
        "substitution terms only. Remove application/domain terms, broad "
        "criterion words, and unrelated material-family terms.\n"
        "- If the replacement question also names an application or domain, "
        "keep that application/domain as a separate main topic. Do not let "
        "the replacement/comparator topic absorb it into mixed terms.\n"
        "- If the user explicitly names a valid component phrase, preserve "
        "that wording in the main topic id/label and put inferred nearby "
        "wording in secondary topics.\n"
        "- Keep application/domain topics concrete. Replace generic wording "
        "with concrete domain synonyms or product/application names.\n"
        "- For application/domain topic terms, replace process, property, or "
        "evaluation wording with terms that name the use area, product family, "
        "setting, or domain itself.\n"
        "- For application/domain secondary groups, replace criterion groups "
        "based on broad criteria with clean adjacent application groups.\n"
        "- If you add secondary groups for an application/domain topic, use "
        "clean adjacent application/domain fallbacks rather than criterion "
        "wording.\n"
        "- If a broad source/application component has too few terms, add "
        "focused synonyms, variants, abbreviations, named subtypes, or "
        "concrete indicators for that same component. Do not pad with broad "
        "background words."
    )
    if best_contract is None:
        return feedback

    return (
        feedback
        + "\n\nBest response so far, after deterministic snake_case cleanup:\n"
        + json.dumps(best_contract, indent=2, ensure_ascii=False)
        + "\n\nRepair this best response minimally. Keep the valid topic-specific "
        "categories and replace only the categories or values named in the "
        "validation feedback above."
    )


def validation_error_score(error: ValueError) -> int:
    """Prefer retry feedback from the smallest semantic validation failure."""
    message = str(error)
    issue_count = message.count("\n- ")
    if issue_count:
        return issue_count
    return 1000


def read_topic(args: argparse.Namespace) -> str:
    if args.topic:
        return args.topic.strip()

    if args.topic_file:
        return Path(args.topic_file).read_text(encoding="utf-8").strip()

    raise ValueError("Provide either --topic or --topic-file.")


def contract_from_model_payload(
    payload: dict[str, Any],
    policy: TopicStructurePolicy | None = None,
    profile_ids: tuple[str, ...] | None = None,
) -> dict[str, Any]:
    """Convert the model-friendly categories list into contract YAML shape."""
    contract = deepcopy(payload)
    collection = contract.get("collection")
    if isinstance(collection, dict):
        collection.setdefault(
            "corpus_specification",
            default_corpus_specification_mapping(),
        )
    active_policy = policy or default_topic_structure_policy()
    normalize_topic_structure(
        contract,
        policy=active_policy,
        profile_ids=profile_ids,
    )
    tagging = contract.get("tagging")
    if not isinstance(tagging, dict):
        raise ValueError("Generated topic contract must contain tagging.")

    categories = tagging.get("categories")
    if isinstance(categories, dict):
        tagging["categories"] = active_generated_categories(categories)
        attach_topic_policy_reference(contract, active_policy, profile_ids)
        return contract

    if not isinstance(categories, list):
        raise ValueError("Generated tagging.categories must be a list.")

    category_map: dict[str, dict[str, Any]] = {}
    for category in categories:
        if not isinstance(category, dict):
            raise ValueError("Each generated tagging category must be an object.")

        category_id = normalize_tagging_label(str(category.get("category_id") or ""))
        if not category_id:
            raise ValueError("Each generated tagging category needs category_id.")
        if is_retired_tagging_category_id(category_id):
            continue
        if category_id in category_map:
            raise ValueError(f"Duplicate generated tagging category: {category_id}")

        values = category.get("values")
        if not isinstance(values, list):
            raise ValueError(f"Generated category {category_id} needs values.")
        normalized_values = [
            normalize_tagging_label(value) if isinstance(value, str) else value
            for value in values
        ]

        category_payload: dict[str, Any] = {
            "required": bool(category.get("required", False)),
            "values": normalized_values,
        }
        description = str(category.get("description") or "").strip()
        if description:
            category_payload["description"] = description
        selection = str(category.get("selection") or "").strip()
        if selection:
            category_payload["selection"] = selection
        applies_when = category.get("applies_when")
        if isinstance(applies_when, dict):
            normalized_applies_when = dict(applies_when)
            normalized_applies_when["category_id"] = normalize_tagging_label(
                str(applies_when.get("category_id") or "")
            )
            trigger_values = applies_when.get("values")
            if isinstance(trigger_values, list):
                normalized_applies_when["values"] = [
                    normalize_tagging_label(value) if isinstance(value, str) else value
                    for value in trigger_values
                ]
            category_payload["applies_when"] = normalized_applies_when
        category_map[category_id] = category_payload

    tagging["categories"] = active_generated_categories(category_map)
    attach_topic_policy_reference(contract, active_policy, profile_ids)
    return contract


def active_generated_categories(categories: dict[str, Any]) -> dict[str, Any]:
    """Drop retired generated categories and conditionals that depend on them."""
    active_categories = {
        category_id: category
        for category_id, category in categories.items()
        if not is_retired_tagging_category_id(category_id)
    }
    removed_category_ids = set(categories) - set(active_categories)
    return {
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


def normalize_secondary_term(value: object) -> str:
    """Normalize secondary-topic terms for duplicate cleanup."""
    return " ".join(str(value or "").casefold().replace("_", " ").split())


def display_surface_form(term: str, policy: TopicStructurePolicy) -> str:
    return policy.surface_form_display.get(term, term)


def append_unique_term(values: list[Any], term: str) -> None:
    key = normalize_secondary_term(term)
    if not key:
        return
    existing = {normalize_secondary_term(value) for value in values}
    if key not in existing:
        values.append(term)


def clean_topic_terms(
    topic: dict[str, Any],
    topic_id: str,
    policy: TopicStructurePolicy,
    profile: TopicConceptProfile | None,
) -> None:
    """Apply deterministic term cleanup for generated topic structures."""
    method_topic = is_method_topic(topic_id, topic, policy)
    for key in ("terms", "retrieval_terms", "matching_terms"):
        values = topic.get(key)
        if not isinstance(values, list):
            continue
        cleaned_values = []
        seen = set()
        for value in values:
            term = str(value).strip()
            normalized = normalize_secondary_term(term)
            if not term or normalized in seen:
                continue
            if (
                method_topic
                and key in {"terms", "retrieval_terms"}
                and normalized
                in (
                    policy.quality_term_sets[
                        "broad_umbrella_topic_structure_terms"
                    ]
                    | policy.method_topic_bare_domain_terms
                )
            ):
                continue
            if (
                profile is not None
                and concept_excluded_term_matches(
                    topic_id,
                    topic,
                    term,
                    policy,
                )
            ):
                continue
            cleaned_values.append(term)
            seen.add(normalized)
        if cleaned_values:
            topic[key] = cleaned_values


def configured_profile_for_topic(
    topic: dict[str, Any],
    topic_id: str,
    policy: TopicStructurePolicy,
    profile_ids: tuple[str, ...],
) -> TopicConceptProfile | None:
    return topic_profile(
        policy,
        topic_id,
        topic,
        is_method=is_method_topic(topic_id, topic, policy),
        allowed_profile_ids=profile_ids,
    )


def complete_profile_terms(
    topic: dict[str, Any],
    profile: TopicConceptProfile | None,
) -> None:
    """Complete a topic with terms declared by its matched policy profile."""
    if profile is None:
        return
    for key in ("terms", "matching_terms"):
        values = topic.setdefault(key, [])
        if isinstance(values, list):
            for term in profile.completion_terms:
                append_unique_term(values, term)
    retrieval_terms = topic.setdefault("retrieval_terms", [])
    if isinstance(retrieval_terms, list):
        for term in profile.completion_terms:
            if len(retrieval_terms) >= RETRIEVAL_TERMS_LIMIT:
                break
            append_unique_term(retrieval_terms, term)


def complete_common_surface_forms(
    topic: dict[str, Any],
    policy: TopicStructurePolicy,
) -> None:
    """Add common abbreviation/full-form companions already implied by terms."""
    all_terms = []
    for key in ("terms", "retrieval_terms", "matching_terms"):
        values = topic.get(key)
        if isinstance(values, list):
            all_terms.extend(values)
    normalized_terms = {normalize_secondary_term(value) for value in all_terms}
    additions = []
    for group in policy.surface_form_groups:
        abbreviations = group.abbreviations
        full_forms = group.full_forms
        has_abbreviation = bool(normalized_terms.intersection(abbreviations))
        has_full_form = bool(normalized_terms.intersection(full_forms))
        if has_abbreviation == has_full_form:
            continue
        if has_abbreviation:
            additions.append(display_surface_form(sorted(full_forms)[0], policy))
        else:
            additions.append(
                display_surface_form(
                    min(abbreviations, key=lambda item: (len(item), item)),
                    policy,
                )
            )
    if not additions:
        return
    for key in ("terms", "matching_terms"):
        values = topic.setdefault(key, [])
        if isinstance(values, list):
            for addition in additions:
                append_unique_term(values, addition)
    retrieval_terms = topic.setdefault("retrieval_terms", [])
    if isinstance(retrieval_terms, list):
        for addition in additions:
            if len(retrieval_terms) >= RETRIEVAL_TERMS_LIMIT:
                break
            append_unique_term(retrieval_terms, addition)


def update_parent_terms_index(
    topic: dict[str, Any],
    topic_id: str,
    parent_terms_by_topic_id: dict[str, set[str]],
) -> None:
    parent_terms = set()
    for key in ("terms", "retrieval_terms", "matching_terms"):
        values = topic.get(key)
        if isinstance(values, list):
            parent_terms.update(normalize_secondary_term(value) for value in values)
    parent_terms_by_topic_id[topic_id] = parent_terms


def group_method_subtype_terms(
    group: dict[str, Any],
    policy: TopicStructurePolicy,
) -> list[str]:
    subtype_terms = []
    seen = set()
    for key in ("terms", "retrieval_terms", "matching_terms"):
        values = group.get(key)
        if not isinstance(values, list):
            continue
        for value in values:
            term = str(value).strip()
            normalized = normalize_secondary_term(term)
            if (
                term
                and method_internal_subtype_matches(term, policy)
                and normalized not in seen
            ):
                subtype_terms.append(term)
                seen.add(normalized)
    return subtype_terms


def group_has_method_subtype_signal(
    group: dict[str, Any],
    policy: TopicStructurePolicy,
) -> bool:
    for key in ("secondary_topic_id", "topic_id", "id", "label"):
        if method_internal_subtype_matches(group.get(key), policy):
            return True
    return bool(group_method_subtype_terms(group, policy))


def group_concept_family_terms(
    parent_topic_id: str,
    parent_topic: dict[str, Any],
    group: dict[str, Any],
    policy: TopicStructurePolicy,
) -> list[str]:
    family_terms = []
    seen = set()
    for key in ("secondary_topic_id", "topic_id", "id", "label"):
        for term in concept_family_variant_matches(
            parent_topic_id,
            parent_topic,
            group.get(key),
            policy,
        ):
            if term not in seen:
                family_terms.append(term)
                seen.add(term)
    for key in ("terms", "retrieval_terms", "matching_terms"):
        values = group.get(key)
        if not isinstance(values, list):
            continue
        for value in values:
            term = str(value).strip()
            normalized = normalize_secondary_term(term)
            matches = concept_family_variant_matches(
                parent_topic_id,
                parent_topic,
                term,
                policy,
            )
            if term and normalized in matches and normalized not in seen:
                family_terms.append(term)
                seen.add(normalized)
                continue
            for match in matches:
                if match not in seen:
                    family_terms.append(match)
                    seen.add(match)
    return family_terms


def group_has_concept_family_signal(
    parent_topic_id: str,
    parent_topic: dict[str, Any],
    group: dict[str, Any],
    policy: TopicStructurePolicy,
) -> bool:
    return bool(
        group_concept_family_terms(
            parent_topic_id,
            parent_topic,
            group,
            policy,
        )
    )


def group_has_concept_family_identity(
    parent_topic_id: str,
    parent_topic: dict[str, Any],
    group: dict[str, Any],
    policy: TopicStructurePolicy,
) -> bool:
    for key in ("secondary_topic_id", "topic_id", "id", "label"):
        if concept_family_variant_matches(
            parent_topic_id,
            parent_topic,
            group.get(key),
            policy,
        ):
            return True
    return False


def group_has_generic_secondary_identity(
    group: dict[str, Any],
    policy: TopicStructurePolicy,
) -> bool:
    for key in ("secondary_topic_id", "topic_id", "id", "label"):
        if generic_secondary_topic_bucket_matches(group.get(key), policy):
            return True
    return False


def remove_generic_secondary_terms(
    group: dict[str, Any],
    policy: TopicStructurePolicy,
) -> dict[str, Any] | None:
    cleaned_group = dict(group)
    for key in ("terms", "retrieval_terms", "matching_terms"):
        values = cleaned_group.get(key)
        if not isinstance(values, list):
            continue
        cleaned_values = [
            str(value).strip()
            for value in values
            if str(value).strip()
            and not generic_secondary_topic_term_matches(value, policy)
        ]
        if cleaned_values:
            cleaned_group[key] = cleaned_values
        else:
            cleaned_group.pop(key, None)
    terms = cleaned_group.get("terms")
    if not isinstance(terms, list) or not terms:
        return None
    if "retrieval_terms" not in cleaned_group:
        cleaned_group["retrieval_terms"] = list(terms[:12])
    if "matching_terms" not in cleaned_group:
        cleaned_group["matching_terms"] = list(terms)
    return cleaned_group


def canonical_secondary_group(
    group: dict[str, Any],
    policy: TopicStructurePolicy,
) -> dict[str, Any]:
    group_id = normalize_tagging_label(str(group.get("secondary_topic_id") or ""))
    configured_group = policy.secondary_groups.get(group_id)
    if configured_group is not None:
        return configured_group.as_topic_group()
    return group


def remove_concept_family_terms(
    parent_topic_id: str,
    parent_topic: dict[str, Any],
    group: dict[str, Any],
    policy: TopicStructurePolicy,
) -> dict[str, Any] | None:
    cleaned_group = dict(group)
    for key in ("terms", "retrieval_terms", "matching_terms"):
        values = cleaned_group.get(key)
        if not isinstance(values, list):
            continue
        cleaned_values = [
            str(value).strip()
            for value in values
            if str(value).strip()
            and not concept_family_variant_matches(
                parent_topic_id,
                parent_topic,
                value,
                policy,
            )
        ]
        if cleaned_values:
            cleaned_group[key] = cleaned_values
        else:
            cleaned_group.pop(key, None)
    terms = cleaned_group.get("terms")
    if not isinstance(terms, list) or not terms:
        return None
    if "retrieval_terms" not in cleaned_group:
        cleaned_group["retrieval_terms"] = list(terms[:12])
    if "matching_terms" not in cleaned_group:
        cleaned_group["matching_terms"] = list(terms)
    return cleaned_group


def move_terms_to_parent_topic(
    parent_topic: dict[str, Any],
    parent_topic_id: str,
    terms: list[str],
    parent_terms_by_topic_id: dict[str, set[str]],
    policy: TopicStructurePolicy,
    profile: TopicConceptProfile | None,
) -> None:
    for key in ("terms", "matching_terms"):
        values = parent_topic.setdefault(key, [])
        if isinstance(values, list):
            for term in terms:
                append_unique_term(values, term)
    retrieval_terms = parent_topic.setdefault("retrieval_terms", [])
    if isinstance(retrieval_terms, list):
        for term in terms:
            if len(retrieval_terms) >= RETRIEVAL_TERMS_LIMIT:
                break
            append_unique_term(retrieval_terms, term)
    clean_topic_terms(parent_topic, parent_topic_id, policy, profile)
    complete_common_surface_forms(parent_topic, policy)
    complete_profile_terms(parent_topic, profile)
    update_parent_terms_index(parent_topic, parent_topic_id, parent_terms_by_topic_id)


def normalize_topic_structure(
    contract: dict[str, Any],
    policy: TopicStructurePolicy | None = None,
    profile_ids: tuple[str, ...] | None = None,
) -> None:
    active_policy = policy or default_topic_structure_policy()
    active_profile_ids = (
        profile_ids
        if profile_ids is not None
        else selected_profile_ids(active_policy, contract)
    )
    topic_structure = contract.get("topic_structure")
    if not isinstance(topic_structure, dict):
        return

    raw_anchor_topic_id = str(topic_structure.get("anchor_topic_id") or "").strip()
    id_map: dict[str, str] = {}
    field_by_topic_id: dict[str, str] = {}
    parent_terms_by_topic_id: dict[str, set[str]] = {}
    topic_by_id: dict[str, dict[str, Any]] = {}
    profile_by_topic_id: dict[str, TopicConceptProfile | None] = {}
    main_topics = topic_structure.get("main_topics")
    if isinstance(main_topics, list):
        for topic in main_topics:
            if not isinstance(topic, dict):
                continue
            raw_topic_id = str(topic.get("topic_id") or "").strip()
            normalized_topic_id = normalize_tagging_label(raw_topic_id)
            if not normalized_topic_id:
                continue
            topic["topic_id"] = normalized_topic_id
            id_map[raw_topic_id] = normalized_topic_id
            id_map[normalized_topic_id] = normalized_topic_id
            field = str(topic.get("field") or "title")
            if (
                field == "title_or_abstract"
                and not is_title_or_abstract_exception_topic(
                    normalized_topic_id,
                    topic,
                    active_policy,
                )
            ):
                field = "title"
                topic["field"] = field
            field_by_topic_id[normalized_topic_id] = str(
                field
            )
            profile = configured_profile_for_topic(
                topic,
                normalized_topic_id,
                active_policy,
                active_profile_ids,
            )
            clean_topic_terms(
                topic,
                normalized_topic_id,
                active_policy,
                profile,
            )
            complete_common_surface_forms(topic, active_policy)
            complete_profile_terms(topic, profile)
            topic_by_id[normalized_topic_id] = topic
            profile_by_topic_id[normalized_topic_id] = profile
            update_parent_terms_index(
                topic,
                normalized_topic_id,
                parent_terms_by_topic_id,
            )

    anchor_topic_id = id_map.get(
        raw_anchor_topic_id,
        normalize_tagging_label(raw_anchor_topic_id),
    )
    anchor_topic = topic_by_id.get(anchor_topic_id)
    preferred_anchor_topic_ids = [
        topic_id
        for topic_id, profile in profile_by_topic_id.items()
        if profile is not None and "method" in profile.anchor_over_kinds
    ]
    if (
        preferred_anchor_topic_ids
        and anchor_topic is not None
        and is_method_topic(anchor_topic_id, anchor_topic, active_policy)
    ):
        anchor_topic_id = preferred_anchor_topic_ids[0]
    if anchor_topic_id:
        topic_structure["anchor_topic_id"] = anchor_topic_id

    def normalized_group(
        main_topic_id: str,
        item: dict[str, Any],
        index: int,
    ) -> dict[str, Any] | None:
        raw_group_id = str(
            item.get("secondary_topic_id")
            or item.get("topic_id")
            or item.get("id")
            or f"{main_topic_id}_secondary_{index}"
        ).strip()
        group_id = normalize_tagging_label(raw_group_id)
        if not group_id:
            group_id = f"{main_topic_id}_secondary_{index}"
        label = str(item.get("label") or raw_group_id or group_id).strip()
        terms = item.get("terms")
        if not isinstance(terms, list):
            return None
        cleaned_terms = [str(term).strip() for term in terms if str(term).strip()]
        if not cleaned_terms:
            return None
        group: dict[str, Any] = {
            "secondary_topic_id": group_id,
            "label": label,
            "field": str(
                item.get("field") or field_by_topic_id.get(main_topic_id) or "title"
            ),
            "terms": cleaned_terms,
        }
        for key in ("retrieval_terms", "matching_terms"):
            values = item.get(key)
            if isinstance(values, list):
                cleaned_values = [
                    str(value).strip() for value in values if str(value).strip()
                ]
                if cleaned_values:
                    group[key] = cleaned_values
        return group

    def remove_parent_duplicate_terms(
        main_topic_id: str,
        group: dict[str, Any],
    ) -> dict[str, Any] | None:
        parent_terms = parent_terms_by_topic_id.get(main_topic_id, set())
        if not parent_terms:
            return group
        cleaned_group = dict(group)
        for key in ("terms", "retrieval_terms", "matching_terms"):
            values = cleaned_group.get(key)
            if not isinstance(values, list):
                continue
            cleaned_values = [
                str(value).strip()
                for value in values
                if str(value).strip()
                and normalize_secondary_term(value) not in parent_terms
            ]
            if cleaned_values:
                cleaned_group[key] = cleaned_values
            else:
                cleaned_group.pop(key, None)
        terms = cleaned_group.get("terms")
        if not isinstance(terms, list) or not terms:
            return None
        if "retrieval_terms" not in cleaned_group:
            cleaned_group["retrieval_terms"] = list(terms[:12])
        if "matching_terms" not in cleaned_group:
            cleaned_group["matching_terms"] = list(terms)
        return cleaned_group

    secondary_topics = topic_structure.get("secondary_topics")
    normalized: dict[str, Any] = {}
    if isinstance(secondary_topics, dict):
        for main_topic_id, raw_groups in secondary_topics.items():
            raw_main_topic_id = str(main_topic_id or "").strip()
            normalized_main_topic_id = id_map.get(
                raw_main_topic_id,
                normalize_tagging_label(raw_main_topic_id),
            )
            if not normalized_main_topic_id or not isinstance(raw_groups, list):
                continue
            if all(not isinstance(item, dict) for item in raw_groups):
                cleaned_terms = [
                    str(term).strip() for term in raw_groups if str(term).strip()
                ]
                if cleaned_terms:
                    normalized[normalized_main_topic_id] = [
                        {
                            "secondary_topic_id": (
                                f"{normalized_main_topic_id}_secondary_1"
                            ),
                            "label": (
                                "Secondary replacement for "
                                f"{normalized_main_topic_id}"
                            ),
                            "field": field_by_topic_id.get(
                                normalized_main_topic_id,
                                "title",
                            ),
                            "terms": cleaned_terms,
                        }
                    ]
                continue
            groups = []
            for index, item in enumerate(raw_groups, start=1):
                if not isinstance(item, dict):
                    continue
                group = normalized_group(normalized_main_topic_id, item, index)
                if group is not None:
                    groups.append(group)
            if groups:
                normalized[normalized_main_topic_id] = groups
    elif isinstance(secondary_topics, list):
        counters: dict[str, int] = {}
        for item in secondary_topics:
            if not isinstance(item, dict):
                continue
            raw_main_topic_id = str(item.get("main_topic_id") or "").strip()
            main_topic_id = id_map.get(
                raw_main_topic_id,
                normalize_tagging_label(raw_main_topic_id),
            )
            if not main_topic_id:
                continue
            counters[main_topic_id] = counters.get(main_topic_id, 0) + 1
            group = normalized_group(main_topic_id, item, counters[main_topic_id])
            if group is not None:
                normalized.setdefault(main_topic_id, []).append(group)
    else:
        return

    cleaned_normalized: dict[str, Any] = {}
    for main_topic_id, groups in normalized.items():
        if not isinstance(groups, list):
            continue
        cleaned_groups = []
        for group in groups:
            if not isinstance(group, dict):
                continue
            group = canonical_secondary_group(group, active_policy)
            parent_topic = topic_by_id.get(main_topic_id)
            parent_profile = profile_by_topic_id.get(main_topic_id)
            if (
                parent_topic is not None
                and parent_profile is not None
                and parent_profile.family_terms
                and group_has_generic_secondary_identity(group, active_policy)
            ):
                continue
            if (
                parent_topic is not None
                and is_method_topic(main_topic_id, parent_topic, active_policy)
            ):
                subtype_terms = group_method_subtype_terms(group, active_policy)
                if subtype_terms or group_has_method_subtype_signal(
                    group,
                    active_policy,
                ):
                    move_terms_to_parent_topic(
                        parent_topic,
                        main_topic_id,
                        subtype_terms,
                        parent_terms_by_topic_id,
                        active_policy,
                        parent_profile,
                    )
                    continue
            if parent_topic is not None and group_has_concept_family_signal(
                main_topic_id,
                parent_topic,
                group,
                active_policy,
            ):
                family_terms = group_concept_family_terms(
                    main_topic_id,
                    parent_topic,
                    group,
                    active_policy,
                )
                move_terms_to_parent_topic(
                    parent_topic,
                    main_topic_id,
                    family_terms,
                    parent_terms_by_topic_id,
                    active_policy,
                    parent_profile,
                )
                if group_has_concept_family_identity(
                    main_topic_id,
                    parent_topic,
                    group,
                    active_policy,
                ):
                    continue
                group = remove_concept_family_terms(
                    main_topic_id,
                    parent_topic,
                    group,
                    active_policy,
                )
                if group is None:
                    continue
            group = remove_generic_secondary_terms(group, active_policy)
            if group is None:
                continue
            cleaned_group = remove_parent_duplicate_terms(main_topic_id, group)
            if cleaned_group is not None:
                cleaned_groups.append(cleaned_group)
        if cleaned_groups:
            cleaned_normalized[main_topic_id] = cleaned_groups
    for main_topic_id, profile in profile_by_topic_id.items():
        if main_topic_id in cleaned_normalized or profile is None:
            continue
        fallback_groups = []
        for group_id in profile.fallback_secondary_group_ids:
            fallback_group = remove_parent_duplicate_terms(
                main_topic_id,
                active_policy.secondary_groups[group_id].as_topic_group(),
            )
            if fallback_group is not None:
                fallback_groups.append(fallback_group)
        if fallback_groups:
            cleaned_normalized[main_topic_id] = fallback_groups
    normalized = cleaned_normalized
    topic_structure["secondary_topics"] = normalized


def call_topic_structure_repair(
    topic_description: str,
    failed_contract: dict[str, Any],
    issues: list[Any],
    model: str,
    client: JSONLLMClient,
    trace_writer: LLMTraceWriter | None,
    call_id: str,
) -> tuple[dict[str, Any], list[Path]]:
    """Ask the LLM to repair only topic_structure and validate the result."""
    policy = default_topic_structure_policy()
    profile_ids = selected_profile_ids(
        policy,
        failed_contract,
        topic_description,
    )
    prompt = render_repair_topic_structure_prompt(
        topic_description=topic_description,
        topic_structure=failed_contract.get("topic_structure", {}),
        validation_issues=[
            asdict(issue) if not isinstance(issue, dict) else issue
            for issue in issues
        ],
        topic_policy=policy.reference(profile_ids),
    )
    result = client.create_json(
        model=model,
        system_message=SYSTEM_MESSAGE,
        prompt=prompt,
        schema_name="topic_structure_repair",
        schema=topic_structure_schema(),
        step_name=STEP.name,
        call_id=call_id,
        trace_writer=trace_writer,
    )
    trace_paths = result.trace_paths.as_list() if result.trace_paths else []
    repaired_contract = deepcopy(failed_contract)
    repaired_contract["topic_structure"] = deepcopy(result.parsed)
    normalize_topic_structure(
        repaired_contract,
        policy=policy,
        profile_ids=profile_ids,
    )
    attach_topic_policy_reference(repaired_contract, policy, profile_ids)
    validate_topic_contract(repaired_contract, policy)
    validate_generated_topic_structure_quality(
        repaired_contract,
        topic_description=topic_description,
        policy=policy,
    )
    return repaired_contract, trace_paths


def raw_topic_structure_crucial_issues(
    contract: dict[str, Any],
    topic_description: str,
    policy: TopicStructurePolicy | None = None,
    profile_ids: tuple[str, ...] | None = None,
) -> list[Any]:
    try:
        return generated_topic_structure_crucial_issue_records(
            contract,
            topic_description=topic_description,
            policy=policy,
            profile_ids=profile_ids,
        )
    except ValueError as error:
        return [
            {
                "code": "invalid_topic_structure",
                "topic_id": None,
                "value": "",
                "message": str(error),
            }
        ]


def shape_valid_review_contract(contract: dict[str, Any]) -> dict[str, Any]:
    """Return a minimally shape-valid contract for human topic-structure review."""
    fallback = deepcopy(contract)
    topic_structure = fallback.get("topic_structure")
    if not isinstance(topic_structure, dict):
        return fallback

    main_topics = topic_structure.get("main_topics")
    if not isinstance(main_topics, list):
        return fallback

    main_topic_ids = {
        str(topic.get("topic_id") or "").strip()
        for topic in main_topics
        if isinstance(topic, dict) and str(topic.get("topic_id") or "").strip()
    }
    secondary_topics = topic_structure.get("secondary_topics")
    if isinstance(secondary_topics, dict):
        topic_structure["secondary_topics"] = {
            topic_id: groups
            for topic_id, groups in secondary_topics.items()
            if topic_id in main_topic_ids
        }

    validate_topic_contract(fallback)
    return fallback


def topic_structure_review_warning(issues: list[Any]) -> str:
    """Return a concise user-facing warning for non-fatal structure issues."""
    crucial_issues = [
        issue
        for issue in issues
        if getattr(issue, "code", None) is None
        or is_crucial_topic_structure_issue(issue)
    ]
    if not crucial_issues:
        return ""
    examples = []
    for issue in crucial_issues[:5]:
        message = str(getattr(issue, "message", "") or issue)
        if message:
            examples.append(message)
    issue_text = "; ".join(examples)
    remaining = len(crucial_issues) - len(examples)
    if remaining > 0:
        issue_text = f"{issue_text}; plus {remaining} more issue(s)"
    return (
        "Contract review recommended: generated topic_structure did not meet "
        "one or more crucial criteria after automatic repair. The topic contract was "
        "written, but review topic_structure before using it for retrieval."
        + (f" Issues: {issue_text}" if issue_text else "")
    )


def call_llm(
    topic_description: str,
    base_contract: dict[str, Any],
    model: str,
    client: JSONLLMClient,
    trace_writer: LLMTraceWriter | None = None,
) -> tuple[dict[str, Any], list[Path], list[str]]:
    policy = default_topic_structure_policy()
    profile_ids = selected_profile_ids(
        policy,
        base_contract,
        topic_description,
    )
    policy_guidance = render_topic_policy_guidance(policy, profile_ids)
    prompt = render_generate_topic_contract_prompt(topic_description, base_contract)
    trace_paths: list[Path] = []
    last_error: ValueError | None = None
    best_error: ValueError | None = None
    best_error_score = 1001
    best_contract: dict[str, Any] | None = None

    for attempt in range(1, MAX_CONTRACT_VALIDATION_ATTEMPTS + 1):
        attempt_prompt = (
            prompt
            if best_error is None
            else prompt_with_validation_feedback(
                prompt,
                best_error,
                best_contract,
                policy_guidance,
            )
        )
        call_id = "contract" if attempt == 1 else f"contract_retry_{attempt}"
        result = client.create_json(
            model=model,
            system_message=SYSTEM_MESSAGE,
            prompt=attempt_prompt,
            schema_name="topic_contract",
            schema=topic_contract_schema(
                SUPPORTED_PROVIDERS,
                min_tagging_categories=1,
            ),
            step_name=STEP.name,
            call_id=call_id,
            trace_writer=trace_writer,
        )
        if result.trace_paths:
            trace_paths.extend(result.trace_paths.as_list())

        try:
            contract: dict[str, Any] | None = None
            raw_issues = raw_topic_structure_crucial_issues(
                result.parsed,
                topic_description,
                policy,
                profile_ids,
            )
            contract = contract_from_model_payload(
                result.parsed,
                policy=policy,
                profile_ids=profile_ids,
            )
            validate_topic_contract(contract, policy)
            if raw_issues:
                issue_messages = "\n- ".join(
                    str(getattr(issue, "message", "") or issue)
                    for issue in raw_issues
                )
                raise ValueError(
                    "Generated topic contract has weak raw topic_structure:\n- "
                    + issue_messages
                )
            validate_generated_topic_structure_quality(
                contract,
                topic_description=topic_description,
                policy=policy,
            )
            return contract, trace_paths, []
        except ValueError as error:
            last_error = error
            score = validation_error_score(error)
            if score < best_error_score:
                best_error = error
                best_error_score = score
                if contract is not None:
                    best_contract = contract

            if attempt == MAX_CONTRACT_VALIDATION_ATTEMPTS:
                if contract is not None:
                    issues = generated_topic_structure_crucial_issue_records(
                        contract,
                        topic_description=topic_description,
                        policy=policy,
                    )
                    if not issues and "raw_issues" in locals():
                        issues = raw_issues
                    if issues:
                        try:
                            repaired_contract, repair_trace_paths = (
                                call_topic_structure_repair(
                                    topic_description=topic_description,
                                    failed_contract=contract,
                                    issues=issues,
                                    model=model,
                                    client=client,
                                    trace_writer=trace_writer,
                                    call_id=f"{call_id}_topic_structure_repair",
                                )
                            )
                            trace_paths.extend(repair_trace_paths)
                            return repaired_contract, trace_paths, []
                        except ValueError:
                            pass
                        warning_contract = shape_valid_review_contract(contract)
                        return warning_contract, trace_paths, [
                            topic_structure_review_warning(issues)
                        ]
                raise ValueError(
                    "Generated topic contract failed validation after "
                    f"{MAX_CONTRACT_VALIDATION_ATTEMPTS} attempts: "
                    f"{best_error or error}"
                ) from error

    raise ValueError("Generated topic contract failed validation.")


def run(
    topic_description: str,
    output_path: Path,
    model: str,
    base_contract_path: Path = DEFAULT_BASE_CONTRACT,
    client: JSONLLMClient | None = None,
    trace_dir: Path | None = None,
    overwrite: bool = False,
) -> StepResult:
    if output_path.exists() and not overwrite:
        raise ValueError(
            f"Topic contract already exists: {output_path}. "
            "Pass --overwrite-topic-contract to replace it."
        )

    base_contract = read_yaml_object(base_contract_path)
    trace_writer = LLMTraceWriter(trace_dir) if trace_dir is not None else None
    contract, trace_paths, warnings = call_llm(
        topic_description,
        base_contract,
        model,
        client or OpenAIResponsesClient(),
        trace_writer,
    )
    write_yaml_object(output_path, contract)

    categories = contract["tagging"]["categories"]
    collection = contract["collection"]
    corpus_specification = corpus_specification_from_contract(contract)
    search_queries = collection.get("search_queries", [])
    return StepResult(
        step_name=STEP.name,
        inputs={"base_topic_contract_yaml": base_contract_path},
        outputs={"topic_contract_yaml": output_path},
        row_counts={
            "tagging_categories": len(categories),
            "search_queries": (
                len(search_queries) if isinstance(search_queries, list) else 0
            ),
        },
        trace_paths=trace_paths,
        warnings=warnings,
        metadata={
            "topic_id": contract["topic_id"],
            "title": contract["research_topic"]["title"],
            "topic_policy": deepcopy(contract["topic_policy"]),
            "corpus_specification": corpus_specification.semantic_mapping(),
        },
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate a topic contract YAML draft from a research question."
    )
    parser.add_argument("--topic", help="Research question or topic description.")
    parser.add_argument("--topic-file", help="Path to a text file containing the topic.")
    parser.add_argument("--output", required=True, help="Output topic contract YAML.")
    parser.add_argument(
        "--base-contract",
        default=str(DEFAULT_BASE_CONTRACT),
        help="Base topic contract template YAML.",
    )
    parser.add_argument(
        "--model",
        default=None,
        help="OpenAI model. Defaults to OPENAI_MODEL or gpt-4o-mini.",
    )
    parser.add_argument(
        "--trace-dir",
        default=None,
        help="Optional directory where prompt/response traces are written.",
    )
    parser.add_argument(
        "--overwrite-topic-contract",
        action="store_true",
        help="Replace the output file if it already exists.",
    )
    args = parser.parse_args()

    load_dotenv()
    topic_description = read_topic(args)
    model = args.model or os.getenv("OPENAI_MODEL", "gpt-4o-mini")
    trace_dir = Path(args.trace_dir) if args.trace_dir else None
    result = run(
        topic_description,
        Path(args.output),
        model,
        Path(args.base_contract),
        trace_dir=trace_dir,
        overwrite=args.overwrite_topic_contract,
    )

    print(f"Topic id: {result.metadata['topic_id']}")
    print(f"Title: {result.metadata['title']}")
    print(f"Tagging categories: {result.row_counts['tagging_categories']}")
    print(f"Search queries: {result.row_counts['search_queries']}")
    for warning in result.warnings:
        print(f"WARNING: {warning}")
    print(f"Wrote {args.output}")


if __name__ == "__main__":
    main()
