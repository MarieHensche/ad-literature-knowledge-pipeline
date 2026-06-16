from __future__ import annotations

import argparse
import json
import os
from copy import deepcopy
from dataclasses import asdict
from pathlib import Path
from typing import Any

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
    generated_topic_structure_crucial_issue_records,
    is_retired_tagging_category_id,
    is_crucial_topic_structure_issue,
    is_title_or_abstract_exception_topic,
    normalize_tagging_label,
    validate_generated_topic_structure_quality,
    validate_topic_contract,
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
        "- If the failure names `topic_structure`, split any merged main topic "
        "into one concept area per main topic. For example, use separate "
        "`ai`, `school`, and `student_performance` topics instead of "
        "`ai_in_school` or `ai_and_student_performance`.\n"
        "- For questions like `Could X be used to...` or `Use of X in/for...`, "
        "choose X as the anchor when X is the proposed source, tool, "
        "intervention, material, disease, exposure, or core phenomenon. Do "
        "not anchor on the application, outcome, or replacement/comparator "
        "goal if papers about that goal without X would be off-topic.\n"
        "- Keep each main topic's terms inside that same concept area. Do not "
        "put phrases such as `AI in schools` inside the `ai` term list when "
        "`school` is a separate main topic.\n"
        "- Set the anchor topic's `field` to `title`.\n"
        "- Replace generic topic terms such as `education`, `learning "
        "environment`, `educational settings`, `performance metrics`, "
        "`technology`, `educational technology`, `digital technology`, "
        "`tools`, `outcomes`, or `students` with specific component "
        "vocabulary.\n"
        "- Do not use `abstract` for generated main topics; use "
        "`title` for relevance-defining components and `title_or_abstract` "
        "only for detail or explanatory dimensions such as mechanisms, "
        "validation, workflows, measurement details, implementation details, "
        "or explanatory processes.\n"
        "- Default generated main-topic fields to `title`. If a concept is "
        "required for relevance, use richer terms rather than weakening it to "
        "`title_or_abstract`.\n"
        "- Set setting, context, or population components to `title`.\n"
        "- Keep `retrieval_terms` component-pure; remove phrases that mix this "
        "topic with another main topic, such as `educational AI`.\n"
        "- Remove secondary-topic groups that simply duplicate a parent "
        "main-topic term.\n"
        "- If a non-anchor main topic has common adjacent wording that can "
        "substitute for that one component, add a useful secondary-topic "
        "fallback group. Do not define secondary replacements for the anchor.\n"
        "- For broad method, tool, model, analysis, evidence-signal, "
        "intervention, or platform families, add distinct secondary-topic "
        "groups when there are genuinely different adjacent expansions.\n"
        "- If the user asks about replacing or substituting a concrete thing "
        "or applying something in a concrete use case, do not use broad "
        "criteria such as sustainability or environmental impact as required "
        "main topics. Use the concrete replacement/comparator/application "
        "concept instead.\n"
        "- If the user asks about replacing, substituting, or using an "
        "alternative to a concrete target, make that target or replacement "
        "relation a main topic id/label. Do not leave the target only as a "
        "term under a broader application topic.\n"
        "- Keep replacement/comparator topics component-pure: use target and "
        "substitution terms only, such as concrete replacement, concrete "
        "alternative, cement replacement, or cement substitute. Remove "
        "application/domain terms and broad criterion words such as "
        "sustainable, green, eco-friendly, or renewable, plus broad "
        "material-family terms such as bare biomaterials or biodegradable "
        "materials, from replacement topics and their secondary groups.\n"
        "- If the replacement question also names an application or domain, "
        "keep that application/domain as a separate main topic. Do not let "
        "the replacement/comparator topic absorb it into mixed terms.\n"
        "- If the user explicitly names a valid component phrase, preserve "
        "that wording in the main topic id/label and put inferred nearby "
        "wording in secondary topics. For example, use `building_materials` "
        "as the main topic when the user says building materials; use "
        "`construction_products` or `building_products` as secondary groups.\n"
        "- Keep application/domain topics concrete. Replace generic terms such "
        "as innovative materials, materials science, construction technology, "
        "advanced materials, or broad sustainability criteria with concrete "
        "domain synonyms or product/application names.\n"
        "- For application/domain topic terms, replace process, property, or "
        "evaluation wording such as structural integrity, construction "
        "innovations, building techniques, effective products, or responsible "
        "practices with terms that name the use area, product family, setting, "
        "or domain itself.\n"
        "- For application/domain secondary groups, replace criterion groups "
        "such as eco-friendly materials, green alternatives, renewable "
        "materials, or sustainability criteria with adjacent application "
        "groups such as construction products, building products, structural "
        "materials, or insulation materials when appropriate.\n"
        "- If you add secondary groups for an application/domain topic, use "
        "clean adjacent application/domain fallbacks. For building-material "
        "topics, use construction products, building products, structural "
        "materials, or insulation materials, not green, eco-friendly, "
        "renewable, or sustainability wording.\n"
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


def contract_from_model_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Convert the model-friendly categories list into contract YAML shape."""
    contract = deepcopy(payload)
    normalize_topic_structure(contract)
    tagging = contract.get("tagging")
    if not isinstance(tagging, dict):
        raise ValueError("Generated topic contract must contain tagging.")

    categories = tagging.get("categories")
    if isinstance(categories, dict):
        tagging["categories"] = active_generated_categories(categories)
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


def normalize_topic_structure(contract: dict[str, Any]) -> None:
    topic_structure = contract.get("topic_structure")
    if not isinstance(topic_structure, dict):
        return

    raw_anchor_topic_id = str(topic_structure.get("anchor_topic_id") or "").strip()
    id_map: dict[str, str] = {}
    field_by_topic_id: dict[str, str] = {}
    parent_terms_by_topic_id: dict[str, set[str]] = {}
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
                )
            ):
                field = "title"
                topic["field"] = field
            field_by_topic_id[normalized_topic_id] = str(
                field
            )
            parent_terms: set[str] = set()
            for key in ("terms", "retrieval_terms", "matching_terms"):
                values = topic.get(key)
                if isinstance(values, list):
                    parent_terms.update(
                        normalize_secondary_term(value) for value in values
                    )
            parent_terms_by_topic_id[normalized_topic_id] = parent_terms

    anchor_topic_id = id_map.get(
        raw_anchor_topic_id,
        normalize_tagging_label(raw_anchor_topic_id),
    )
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
            "field": str(item.get("field") or field_by_topic_id.get(main_topic_id) or "title"),
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

    if anchor_topic_id:
        normalized.pop(anchor_topic_id, None)
    cleaned_normalized: dict[str, Any] = {}
    for main_topic_id, groups in normalized.items():
        if not isinstance(groups, list):
            continue
        cleaned_groups = []
        for group in groups:
            if not isinstance(group, dict):
                continue
            cleaned_group = remove_parent_duplicate_terms(main_topic_id, group)
            if cleaned_group is not None:
                cleaned_groups.append(cleaned_group)
        if cleaned_groups:
            cleaned_normalized[main_topic_id] = cleaned_groups
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
    prompt = render_repair_topic_structure_prompt(
        topic_description=topic_description,
        topic_structure=failed_contract.get("topic_structure", {}),
        validation_issues=[asdict(issue) for issue in issues],
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
    normalize_topic_structure(repaired_contract)
    validate_topic_contract(repaired_contract)
    validate_generated_topic_structure_quality(
        repaired_contract,
        topic_description=topic_description,
    )
    return repaired_contract, trace_paths


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
            else prompt_with_validation_feedback(prompt, best_error, best_contract)
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
            contract = contract_from_model_payload(result.parsed)
            validate_topic_contract(contract)
            validate_generated_topic_structure_quality(
                contract,
                topic_description=topic_description,
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
                    )
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
                        return contract, trace_paths, [
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
