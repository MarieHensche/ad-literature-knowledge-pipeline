from __future__ import annotations

import argparse
import os
from copy import deepcopy
from dataclasses import asdict
from pathlib import Path
from typing import Any

from ad_lit_pipeline.core.env import load_dotenv
from ad_lit_pipeline.core.step import StepResult, StepSpec
from ad_lit_pipeline.io.jsonl_io import read_jsonl_objects
from ad_lit_pipeline.io.yaml_io import write_yaml_object
from ad_lit_pipeline.llm.client import JSONLLMClient, OpenAIResponsesClient
from ad_lit_pipeline.llm.schemas import (
    topic_contract_schema,
    topic_contract_tagging_repair_schema,
)
from ad_lit_pipeline.llm.trace import LLMTraceWriter
from ad_lit_pipeline.prompts.render import (
    render_refine_topic_contract_prompt,
    render_repair_topic_contract_tagging_prompt,
)
from ad_lit_pipeline.steps.collection.generate_topic_contract import (
    MAX_CONTRACT_VALIDATION_ATTEMPTS,
    SUPPORTED_PROVIDERS,
    contract_from_model_payload,
    prompt_with_validation_feedback,
)
from ad_lit_pipeline.steps.collection.fetch_review_overviews import (
    DEFAULT_MAX_REVIEWS,
    meaningful_tokens,
    normalize_text,
    review_identity,
    select_best_review_overviews,
)
from ad_lit_pipeline.steps.full_text.evidence import read_text_evidence
from ad_lit_pipeline.topics.contract import (
    BOILERPLATE_CATEGORY_IDS,
    GENERATED_CATCHALL_TAG_VALUES,
    KNOWLEDGE_GOAL_CATEGORY_ID,
    TaggingQualityIssue,
    generated_tagging_quality_issue_records,
    load_topic_contract,
    normalize_tagging_label,
    validate_generated_tagging_quality,
    validate_topic_contract,
)


STEP = StepSpec(
    name="refine_topic_contract",
    inputs=["topic_description", "topic_contract_yaml", "review_overviews_jsonl"],
    outputs=["topic_contract_yaml"],
    uses_llm=True,
    description="Refine topic-contract tags from review and overview papers.",
)

SYSTEM_MESSAGE = "You refine literature-pipeline topic contracts as strict JSON."
REPAIRABLE_TAGGING_ISSUE_CODES = {
    "boilerplate_category_id",
    "meta_category_id",
    "meta_values",
    "catchall_values",
    "too_few_values",
    "too_few_categories",
    "invalid_knowledge_goal_shape",
    "too_few_knowledge_goal_values",
    "knowledge_goal_missing_facet_categories",
    "vague_knowledge_goal_values",
    "meta_dependency",
    "broad_dependency_values",
}
REPLACE_CATEGORY_ISSUE_CODES = {
    "boilerplate_category_id",
    "meta_category_id",
    "meta_values",
    "catchall_values",
    "too_few_values",
    "invalid_knowledge_goal_shape",
    "too_few_knowledge_goal_values",
    "knowledge_goal_missing_facet_categories",
    "vague_knowledge_goal_values",
    "meta_dependency",
    "broad_dependency_values",
}
MISSING_REVIEW_FULL_TEXT_ERROR = (
    "Topic-contract refinement requires extracted full text from at least one "
    "topic-relevant review/overview seed paper. Run prepare_review_full_text "
    "and ensure at least one seed has a readable full_text_text_path and "
    "enough topic-specific evidence before refining tagging categories."
)
IGNORED_NO_FULL_TEXT_REVIEWS_WARNING = (
    "Ignored review/overview seed papers without extracted full text; final "
    "tagging categories were refined only from review full-text evidence."
)
IGNORED_OFF_TOPIC_REVIEWS_WARNING = (
    "Ignored review/overview seed papers whose title and extracted full text "
    "did not contain enough topic-specific evidence for ontology refinement."
)
MAX_REVIEW_FULL_TEXT_EVIDENCE_CHARS = 16_000
MIN_REVIEW_TITLE_TOPIC_TOKENS = 2
MAX_REVIEW_TITLE_PHRASE_NGRAM = 4

GENERIC_REVIEW_TOPIC_TOKENS = {
    "abstract",
    "academic",
    "adaptive",
    "affects",
    "algorithmic",
    "analyses",
    "analysis",
    "analyzing",
    "application",
    "applications",
    "approach",
    "approaches",
    "aspect",
    "aspects",
    "assess",
    "assessing",
    "artificial",
    "automated",
    "based",
    "borderline",
    "chatbot",
    "chatbots",
    "chatgpt",
    "clearly",
    "deep",
    "directly",
    "discuss",
    "effect",
    "effects",
    "effectiveness",
    "evidence",
    "empirical",
    "exclude",
    "explore",
    "exploring",
    "focused",
    "focus",
    "generative",
    "impact",
    "impacts",
    "include",
    "implementation",
    "indicate",
    "indicates",
    "investigate",
    "investigates",
    "intelligent",
    "intelligence",
    "language",
    "large",
    "learning",
    "literature",
    "llm",
    "machine",
    "method",
    "methodologies",
    "methods",
    "meta",
    "model",
    "models",
    "outcome",
    "outcomes",
    "paper",
    "papers",
    "performance",
    "platform",
    "platforms",
    "processes",
    "only",
    "related",
    "relevant",
    "research",
    "role",
    "review",
    "reviews",
    "smart",
    "study",
    "studies",
    "studying",
    "subtopics",
    "summarizing",
    "support",
    "supported",
    "supporting",
    "systematic",
    "system",
    "systems",
    "technology",
    "technologies",
    "they",
    "title",
    "tool",
    "tools",
    "unrelated",
}


class TaggingRepairError(ValueError):
    """Repair failure that preserves trace paths from the repair LLM call."""

    def __init__(self, message: str, trace_paths: list[Path]) -> None:
        super().__init__(message)
        self.trace_paths = trace_paths


def review_evidence_id(record: dict[str, Any], index: int) -> str:
    for key in ["provider_id", "doi", "paper_id"]:
        value = str(record.get(key) or "").strip()
        if value:
            return value
    return f"review_{index}"


def compact_review_overview(
    record: dict[str, Any],
    index: int,
) -> dict[str, Any] | None:
    """Keep only extracted review full-text evidence for tag ontology design."""
    full_text_evidence = read_text_evidence(
        str(record.get("full_text_text_path") or ""),
        max_chars=MAX_REVIEW_FULL_TEXT_EVIDENCE_CHARS,
    )
    if not full_text_evidence:
        return None

    return {
        "review_id": review_evidence_id(record, index),
        "full_text_evidence": full_text_evidence,
    }


def compact_review_overviews(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    compacted = []
    for index, record in enumerate(records, start=1):
        review = compact_review_overview(record, index)
        if review is not None:
            compacted.append(review)
    return compacted


def has_usable_review_full_text(record: dict[str, Any]) -> bool:
    text_path = str(record.get("full_text_text_path") or "").strip()
    if not text_path:
        return False
    return bool(
        read_text_evidence(
            text_path,
            max_chars=MAX_REVIEW_FULL_TEXT_EVIDENCE_CHARS,
        )
    )


def review_overviews_with_usable_full_text(
    records: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    return [record for record in records if has_usable_review_full_text(record)]


def review_deduplication_key(record: dict[str, Any], index: int) -> str:
    return review_identity(record, index).lower()


def deduplicate_review_overviews(
    records: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Keep the highest-scored record for each DOI/OpenAlex/paper identity."""
    deduped: dict[str, dict[str, Any]] = {}
    for index, record in enumerate(records):
        key = review_deduplication_key(record, index)
        current = deduped.get(key)
        current_score = (
            float(current.get("review_selection_score") or 0)
            if current
            else None
        )
        record_score = float(record.get("review_selection_score") or 0)
        if current is None or record_score > current_score:
            deduped[key] = record
    return list(deduped.values())


def topic_specific_terms(topic_contract: dict[str, Any]) -> set[str]:
    """Return contract terms specific enough to gate review relevance."""
    texts = []
    research_topic = topic_contract.get("research_topic", {})
    if isinstance(research_topic, dict):
        texts.extend(
            str(research_topic.get(field) or "")
            for field in ["title", "description"]
        )

    topic_structure = topic_contract.get("topic_structure", {})
    main_topics = (
        topic_structure.get("main_topics")
        if isinstance(topic_structure, dict)
        else []
    )
    if isinstance(main_topics, list):
        for topic in main_topics:
            if not isinstance(topic, dict):
                continue
            texts.append(str(topic.get("label") or ""))
            terms = topic.get("terms")
            if isinstance(terms, list):
                texts.extend(str(term) for term in terms)

    scope = topic_contract.get("scope", {})
    if isinstance(scope, dict):
        for key in ["include_criteria", "boundary_rules"]:
            values = scope.get(key)
            if isinstance(values, list):
                texts.extend(str(value) for value in values)

    collection = topic_contract.get("collection", {})
    search_queries = (
        collection.get("search_queries") if isinstance(collection, dict) else []
    )
    if isinstance(search_queries, list):
        for query in search_queries:
            if isinstance(query, dict):
                texts.append(str(query.get("query") or ""))
            elif isinstance(query, str):
                texts.append(query)

    tokens = set()
    for text in texts:
        tokens.update(meaningful_tokens(text))
    return {
        token
        for token in tokens
        if (len(token) >= 4 or token == "ai")
        and token not in GENERIC_REVIEW_TOPIC_TOKENS
    }


def topic_phrase_source_texts(topic_contract: dict[str, Any]) -> list[str]:
    """Return topic-contract text sources used for strong title phrase matches."""
    texts = []
    research_topic = topic_contract.get("research_topic", {})
    if isinstance(research_topic, dict):
        texts.extend(
            str(research_topic.get(field) or "")
            for field in ["title", "description"]
        )

    topic_structure = topic_contract.get("topic_structure", {})
    main_topics = (
        topic_structure.get("main_topics")
        if isinstance(topic_structure, dict)
        else []
    )
    if isinstance(main_topics, list):
        for topic in main_topics:
            if not isinstance(topic, dict):
                continue
            texts.append(str(topic.get("label") or ""))
            terms = topic.get("terms")
            if isinstance(terms, list):
                texts.extend(str(term) for term in terms)

    collection = topic_contract.get("collection", {})
    search_queries = (
        collection.get("search_queries") if isinstance(collection, dict) else []
    )
    if isinstance(search_queries, list):
        for query in search_queries:
            if isinstance(query, dict):
                texts.append(str(query.get("query") or ""))
            elif isinstance(query, str):
                texts.append(query)

    return [text for text in texts if text.strip()]


def topic_title_phrases(topic_contract: dict[str, Any]) -> set[str]:
    """Return normalized topic phrases strong enough for review-title gating."""
    phrases: set[str] = set()
    for text in topic_phrase_source_texts(topic_contract):
        tokens = normalize_text(text).split()
        for size in range(2, MAX_REVIEW_TITLE_PHRASE_NGRAM + 1):
            if len(tokens) < size:
                continue
            for start in range(0, len(tokens) - size + 1):
                phrase_tokens = tokens[start : start + size]
                content_tokens = meaningful_tokens(" ".join(phrase_tokens))
                if len(content_tokens) >= 2:
                    phrases.add(" ".join(phrase_tokens))
    return phrases


def matched_topic_title_phrases(
    text: object,
    phrases: set[str],
) -> set[str]:
    normalized = f" {normalize_text(text)} "
    return {
        phrase
        for phrase in phrases
        if f" {phrase} " in normalized
    }


def matched_topic_specific_terms(
    text: object,
    terms: set[str],
) -> set[str]:
    tokens = meaningful_tokens(text)
    return {token for token in tokens if token in terms}


def review_topic_eligibility(
    topic_contract: dict[str, Any],
    record: dict[str, Any],
) -> tuple[bool, list[str]]:
    """Require title and full-text evidence to contain topic-specific terms."""
    evidence = read_text_evidence(
        str(record.get("full_text_text_path") or ""),
        max_chars=MAX_REVIEW_FULL_TEXT_EVIDENCE_CHARS,
    )
    if not evidence:
        return False, ["missing readable extracted full text"]

    specific_terms = topic_specific_terms(topic_contract)
    if not specific_terms:
        return True, ["no topic-specific contract terms available for filtering"]

    title_phrases = topic_title_phrases(topic_contract)
    title_matches = matched_topic_specific_terms(
        record.get("title", ""),
        specific_terms,
    )
    title_phrase_matches = matched_topic_title_phrases(
        record.get("title", ""),
        title_phrases,
    )
    evidence_matches = matched_topic_specific_terms(evidence, specific_terms)
    has_strong_title_evidence = len(
        title_matches
    ) >= MIN_REVIEW_TITLE_TOPIC_TOKENS or (
        bool(title_matches) and bool(title_phrase_matches)
    )
    if not has_strong_title_evidence:
        return False, [
            "review title lacks enough topic-specific terms or phrase evidence",
            f"available_terms={', '.join(sorted(specific_terms)[:20])}",
            f"title_matches={', '.join(sorted(title_matches))}",
            f"title_phrase_matches={', '.join(sorted(title_phrase_matches)[:12])}",
        ]
    if len(evidence_matches) < 2 and not (title_matches & evidence_matches):
        return False, [
            "review full text lacks enough topic-specific evidence",
            f"title_matches={', '.join(sorted(title_matches))}",
            f"title_phrase_matches={', '.join(sorted(title_phrase_matches)[:12])}",
            f"evidence_matches={', '.join(sorted(evidence_matches)[:20])}",
        ]

    return True, [
        f"title_matches={', '.join(sorted(title_matches)[:12])}",
        f"title_phrase_matches={', '.join(sorted(title_phrase_matches)[:12])}",
        f"full_text_matches={', '.join(sorted(evidence_matches)[:20])}",
    ]


def eligible_review_overviews_for_refinement(
    topic_contract: dict[str, Any],
    records: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    usable_reviews = review_overviews_with_usable_full_text(records)
    deduped_reviews = deduplicate_review_overviews(usable_reviews)
    eligible = []
    for record in deduped_reviews:
        is_eligible, reasons = review_topic_eligibility(topic_contract, record)
        if not is_eligible:
            continue
        enriched = dict(record)
        enriched["review_relevance_reasons"] = reasons
        eligible.append(enriched)
    return eligible


def select_review_overviews_with_full_text(
    topic_contract: dict[str, Any],
    records: list[dict[str, Any]],
    max_results: int,
) -> list[dict[str, Any]]:
    if max_results < 1:
        raise ValueError("max_review_overviews must be at least 1.")
    eligible_reviews = eligible_review_overviews_for_refinement(topic_contract, records)
    return select_best_review_overviews(topic_contract, eligible_reviews, max_results)


def merge_refined_tagging(
    current_contract: dict[str, Any],
    proposed_contract: dict[str, Any],
) -> dict[str, Any]:
    """Apply only review-derived tagging updates to the current contract."""
    refined = deepcopy(current_contract)
    proposed_tagging = proposed_contract.get("tagging")
    if not isinstance(proposed_tagging, dict):
        raise ValueError("Refined topic contract must contain tagging.")

    refined["tagging"] = deepcopy(proposed_tagging)
    return refined


def normalize_repair_category(category: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    """Normalize a patch category into topic-contract category-map shape."""
    category_id = normalize_tagging_label(str(category.get("category_id") or ""))
    if not category_id:
        raise ValueError("Repair category needs category_id.")

    values = category.get("values")
    if not isinstance(values, list):
        raise ValueError(f"Repair category {category_id} needs values.")
    normalized_values = [
        normalize_tagging_label(value) if isinstance(value, str) else value
        for value in values
    ]

    category_payload: dict[str, Any] = {
        "description": str(category.get("description") or "").strip(),
        "required": bool(category.get("required", False)),
        "selection": str(category.get("selection") or "").strip(),
        "values": normalized_values,
        "applies_when": None,
    }
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

    return category_id, category_payload


def apply_tagging_repair_patch(
    contract: dict[str, Any],
    patch: dict[str, Any],
) -> dict[str, Any]:
    """Apply a patch-only tagging repair to a refined contract candidate."""
    repaired = deepcopy(contract)
    tagging = repaired.get("tagging")
    if not isinstance(tagging, dict):
        raise ValueError("Repair target must contain tagging.")
    categories = tagging.get("categories")
    if not isinstance(categories, dict):
        raise ValueError("Repair target tagging.categories must be a mapping.")

    remove_ids = patch.get("remove_category_ids")
    upsert_categories = patch.get("upsert_categories")
    if not isinstance(remove_ids, list):
        raise ValueError("Repair patch remove_category_ids must be a list.")
    if not isinstance(upsert_categories, list):
        raise ValueError("Repair patch upsert_categories must be a list.")

    normalized_remove_ids = [
        normalize_tagging_label(str(category_id))
        for category_id in remove_ids
        if str(category_id).strip()
    ]
    for category_id in normalized_remove_ids:
        if category_id != KNOWLEDGE_GOAL_CATEGORY_ID:
            categories.pop(category_id, None)

    original_order = list(categories)
    seen_upsert_ids: set[str] = set()
    for category in upsert_categories:
        if not isinstance(category, dict):
            raise ValueError("Repair patch upsert_categories must contain objects.")
        category_id, category_payload = normalize_repair_category(category)
        if category_id in seen_upsert_ids:
            raise ValueError(
                "Repair patch introduced duplicate category id after "
                f"normalization: {category_id}"
            )
        seen_upsert_ids.add(category_id)
        categories[category_id] = category_payload

    ordered_categories: dict[str, Any] = {}
    if KNOWLEDGE_GOAL_CATEGORY_ID in categories:
        ordered_categories[KNOWLEDGE_GOAL_CATEGORY_ID] = categories[
            KNOWLEDGE_GOAL_CATEGORY_ID
        ]
    for category_id in original_order:
        if category_id != KNOWLEDGE_GOAL_CATEGORY_ID and category_id in categories:
            ordered_categories[category_id] = categories[category_id]
    for category_id, category in categories.items():
        if category_id not in ordered_categories:
            ordered_categories[category_id] = category

    tagging["categories"] = ordered_categories
    validate_topic_contract(repaired)
    validate_generated_tagging_quality(
        repaired,
        label="Repaired refined topic contract",
    )
    return repaired


def should_attempt_tagging_repair(
    issues: list[TaggingQualityIssue],
    contract: dict[str, Any],
) -> bool:
    """Return whether semantic tagging issues are suitable for targeted repair."""
    if not issues:
        return False
    if any(issue.code not in REPAIRABLE_TAGGING_ISSUE_CODES for issue in issues):
        return False

    tagging = contract.get("tagging")
    categories = tagging.get("categories") if isinstance(tagging, dict) else {}
    category_count = len(categories) if isinstance(categories, dict) else 0
    affected_category_ids = {
        issue.category_id
        for issue in issues
        if issue.category_id is not None and issue.code in REPLACE_CATEGORY_ISSUE_CODES
    }
    if category_count and len(affected_category_ids) > category_count / 2:
        return False

    return True


def call_tagging_repair(
    topic_description: str,
    failed_contract: dict[str, Any],
    review_overviews: list[dict[str, Any]],
    issues: list[TaggingQualityIssue],
    model: str,
    client: JSONLLMClient,
    trace_writer: LLMTraceWriter | None,
    call_id: str,
) -> tuple[dict[str, Any], list[Path]]:
    """Ask the LLM for a patch-only repair and apply it safely."""
    categories = failed_contract.get("tagging", {}).get("categories", {})
    existing_category_ids = list(categories) if isinstance(categories, dict) else []
    prompt = render_repair_topic_contract_tagging_prompt(
        topic_description=topic_description,
        failed_contract=failed_contract,
        review_overviews=review_overviews,
        validation_issues=[asdict(issue) for issue in issues],
        existing_category_ids=existing_category_ids,
        forbidden_generic_ids=sorted(BOILERPLATE_CATEGORY_IDS),
        forbidden_catchall_values=sorted(GENERATED_CATCHALL_TAG_VALUES),
    )
    result = client.create_json(
        model=model,
        system_message=SYSTEM_MESSAGE,
        prompt=prompt,
        schema_name="topic_contract_tagging_repair",
        schema=topic_contract_tagging_repair_schema(),
        step_name=STEP.name,
        call_id=call_id,
        trace_writer=trace_writer,
    )
    trace_paths = result.trace_paths.as_list() if result.trace_paths else []
    try:
        repaired_contract = apply_tagging_repair_patch(failed_contract, result.parsed)
    except ValueError as error:
        raise TaggingRepairError(str(error), trace_paths) from error
    return repaired_contract, trace_paths


def call_llm(
    topic_description: str,
    current_contract: dict[str, Any],
    review_overviews: list[dict[str, Any]],
    model: str,
    client: JSONLLMClient,
    trace_writer: LLMTraceWriter | None = None,
    max_review_overviews: int = DEFAULT_MAX_REVIEWS,
) -> tuple[dict[str, Any], list[Path]]:
    selected_reviews = select_review_overviews_with_full_text(
        current_contract,
        review_overviews,
        max_review_overviews,
    )
    compact_reviews = compact_review_overviews(selected_reviews)
    if not compact_reviews:
        raise ValueError(MISSING_REVIEW_FULL_TEXT_ERROR)
    prompt = render_refine_topic_contract_prompt(
        topic_description,
        current_contract,
        compact_reviews,
    )
    trace_paths: list[Path] = []
    last_error: ValueError | None = None

    for attempt in range(1, MAX_CONTRACT_VALIDATION_ATTEMPTS + 1):
        attempt_prompt = (
            prompt
            if last_error is None
            else prompt_with_validation_feedback(prompt, last_error)
        )
        call_id = (
            "contract_refinement"
            if attempt == 1
            else f"contract_refinement_retry_{attempt}"
        )
        result = client.create_json(
            model=model,
            system_message=SYSTEM_MESSAGE,
            prompt=attempt_prompt,
            schema_name="topic_contract",
            schema=topic_contract_schema(SUPPORTED_PROVIDERS),
            step_name=STEP.name,
            call_id=call_id,
            trace_writer=trace_writer,
        )
        if result.trace_paths:
            trace_paths.extend(result.trace_paths.as_list())

        try:
            proposed_contract = contract_from_model_payload(result.parsed)
            validate_topic_contract(proposed_contract)
            contract = merge_refined_tagging(current_contract, proposed_contract)
            validate_topic_contract(contract)
        except ValueError as error:
            last_error = error
            if attempt == MAX_CONTRACT_VALIDATION_ATTEMPTS:
                raise ValueError(
                    "Refined topic contract failed validation after "
                    f"{MAX_CONTRACT_VALIDATION_ATTEMPTS} attempts: {error}"
                ) from error
            continue

        try:
            validate_generated_tagging_quality(
                contract,
                label="Refined topic contract",
            )
            return contract, trace_paths
        except ValueError as semantic_error:
            issues = generated_tagging_quality_issue_records(contract)
            if should_attempt_tagging_repair(issues, contract):
                repair_call_id = f"{call_id}_repair"
                try:
                    repaired_contract, repair_trace_paths = call_tagging_repair(
                        topic_description=topic_description,
                        failed_contract=contract,
                        review_overviews=compact_reviews,
                        issues=issues,
                        model=model,
                        client=client,
                        trace_writer=trace_writer,
                        call_id=repair_call_id,
                    )
                    trace_paths.extend(repair_trace_paths)
                    return repaired_contract, trace_paths
                except ValueError as repair_error:
                    if isinstance(repair_error, TaggingRepairError):
                        trace_paths.extend(repair_error.trace_paths)
                    last_error = ValueError(
                        f"{semantic_error}\nTargeted tagging repair failed: "
                        f"{repair_error}"
                    )
            else:
                last_error = semantic_error

            if attempt == MAX_CONTRACT_VALIDATION_ATTEMPTS:
                raise ValueError(
                    "Refined topic contract failed validation after "
                    f"{MAX_CONTRACT_VALIDATION_ATTEMPTS} attempts: {last_error}"
                ) from semantic_error

    raise ValueError("Refined topic contract failed validation.")


def run(
    topic_description: str,
    topic_contract_path: Path,
    review_overviews_path: Path,
    model: str,
    client: JSONLLMClient | None = None,
    trace_dir: Path | None = None,
    max_review_overviews: int = DEFAULT_MAX_REVIEWS,
) -> StepResult:
    current_contract = load_topic_contract(topic_contract_path)
    review_overviews = read_jsonl_objects(review_overviews_path)
    warnings = []
    usable_reviews = review_overviews_with_usable_full_text(review_overviews)
    unique_usable_reviews = deduplicate_review_overviews(usable_reviews)
    eligible_reviews = eligible_review_overviews_for_refinement(
        current_contract,
        review_overviews,
    )
    selected_reviews = select_review_overviews_with_full_text(
        current_contract,
        review_overviews,
        max_review_overviews,
    )
    if review_overviews and len(usable_reviews) < len(review_overviews):
        warnings.append(
            f"{IGNORED_NO_FULL_TEXT_REVIEWS_WARNING} "
            f"ignored={len(review_overviews) - len(usable_reviews)} "
            f"usable={len(usable_reviews)} "
            f"selected={len(selected_reviews)}."
        )
    if usable_reviews and len(eligible_reviews) < len(unique_usable_reviews):
        warnings.append(
            f"{IGNORED_OFF_TOPIC_REVIEWS_WARNING} "
            f"ignored={len(unique_usable_reviews) - len(eligible_reviews)} "
            f"eligible={len(eligible_reviews)} "
            f"selected={len(selected_reviews)}."
        )

    trace_writer = LLMTraceWriter(trace_dir) if trace_dir is not None else None
    refined_contract, trace_paths = call_llm(
        topic_description,
        current_contract,
        review_overviews,
        model,
        client or OpenAIResponsesClient(),
        trace_writer,
        max_review_overviews,
    )
    write_yaml_object(topic_contract_path, refined_contract)
    contract = refined_contract

    categories = contract["tagging"]["categories"]
    return StepResult(
        step_name=STEP.name,
        inputs={
            "topic_contract_yaml": topic_contract_path,
            "review_overviews_jsonl": review_overviews_path,
        },
        outputs={"topic_contract_yaml": topic_contract_path},
        row_counts={
            "review_overviews": len(review_overviews),
            "review_full_texts": len(usable_reviews),
            "review_full_texts_unique": len(unique_usable_reviews),
            "review_full_texts_topic_eligible": len(eligible_reviews),
            "review_full_texts_selected": len(selected_reviews),
            "tagging_categories": len(categories),
        },
        warnings=warnings,
        trace_paths=trace_paths,
        metadata={
            "topic_id": contract["topic_id"],
            "title": contract["research_topic"]["title"],
        },
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Refine topic-contract tags from review and overview papers."
    )
    parser.add_argument("--topic", required=True, help="Research question.")
    parser.add_argument("--topic-contract", required=True, help="Topic contract YAML.")
    parser.add_argument(
        "--review-overviews",
        required=True,
        help="Review/overview candidate JSONL, preferably enriched with full text.",
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
        "--max-review-overviews",
        type=int,
        default=DEFAULT_MAX_REVIEWS,
        help="Maximum extracted review full texts to send into refinement.",
    )
    args = parser.parse_args()

    load_dotenv()
    model = args.model or os.getenv("OPENAI_MODEL", "gpt-4o-mini")
    trace_dir = Path(args.trace_dir) if args.trace_dir else None
    result = run(
        args.topic,
        Path(args.topic_contract),
        Path(args.review_overviews),
        model,
        trace_dir=trace_dir,
        max_review_overviews=args.max_review_overviews,
    )

    print(f"Topic id: {result.metadata['topic_id']}")
    print(f"Title: {result.metadata['title']}")
    print(f"Review/overview candidates: {result.row_counts['review_overviews']}")
    print(
        "Selected review full texts: "
        f"{result.row_counts['review_full_texts_selected']}"
    )
    print(f"Tagging categories: {result.row_counts['tagging_categories']}")
    print(f"Wrote {args.topic_contract}")


if __name__ == "__main__":
    main()
