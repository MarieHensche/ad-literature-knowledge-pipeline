from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from string import Template
from typing import Any

from ad_lit_pipeline.topics.matching import topic_match_spec_from_contract


TEMPLATE_DIR = Path(__file__).resolve().parent / "templates"


def json_block(payload: Any) -> str:
    """Render payload as stable, readable JSON for prompts."""
    return json.dumps(payload, indent=2, ensure_ascii=False)


def render_template(template_name: str, variables: dict[str, object]) -> str:
    """Render a prompt template by name using string.Template placeholders."""
    template_path = TEMPLATE_DIR / template_name
    template = Template(template_path.read_text(encoding="utf-8"))
    rendered = template.safe_substitute(
        {key: str(value) for key, value in variables.items()}
    )
    return rendered.strip()


def scope_text(topic_contract: dict[str, Any]) -> str:
    """Render topic-contract scope lists as readable prompt text."""
    scope = topic_contract.get("scope", {})
    include = scope.get("include_criteria", [])
    exclude = scope.get("exclude_criteria", [])
    boundary = scope.get("boundary_rules", [])

    sections = ["Include:"]
    sections.extend(f"- {item}" for item in include)
    sections.append("")
    sections.append("Exclude or route elsewhere:")
    sections.extend(f"- {item}" for item in exclude)
    if boundary:
        sections.append("")
        sections.append("Boundary rules:")
        sections.extend(f"- {item}" for item in boundary)
    return "\n".join(sections)


def render_plan_search_prompt(
    topic_description: str,
    providers: list[dict[str, object]],
    max_results: int | None,
    topic_contract: dict[str, Any] | None = None,
) -> str:
    max_results_text = (
        f"The user requested about {max_results} candidates."
        if max_results
        else "No explicit max result count was provided."
    )
    topic_contract_guidance: dict[str, Any] = {}
    if topic_contract is not None:
        topic_contract_guidance = {
            "research_topic": topic_contract.get("research_topic", {}),
            "topic_structure": topic_contract.get("topic_structure", {}),
            "scope": topic_contract.get("scope", {}),
            "collection": topic_contract.get("collection", {}),
        }

    return render_template(
        "plan_search.md",
        {
            "topic_description": topic_description,
            "max_results_text": max_results_text,
            "topic_contract_guidance_json": json_block(topic_contract_guidance),
            "providers_json": json_block(providers),
        },
    )


def render_screen_candidate_prompt(
    topic_contract: dict[str, Any],
    candidate: dict[str, Any],
    topic_description: str | None = None,
) -> str:
    return render_template(
        "screen_candidate.md",
        {
            "research_topic_json": json_block(topic_contract["research_topic"]),
            "topic_description": topic_description or "",
            "scope_text": scope_text(topic_contract),
            "candidate_screening_json": json_block(
                topic_contract.get("candidate_screening", {})
            ),
            "candidate_json": json_block(candidate),
        },
    )


def render_screen_title_relevance_prompt(
    topic_contract: dict[str, Any],
    candidate: dict[str, Any],
) -> str:
    topic_match_spec = topic_match_spec_from_contract(topic_contract)
    return render_template(
        "screen_title_relevance.md",
        {
            "research_topic_json": json_block(topic_contract["research_topic"]),
            "topic_structure_json": json_block(topic_contract["topic_structure"]),
            "secondary_topic_groups_json": json_block(
                topic_match_spec.get("secondary_topics", [])
                if isinstance(topic_match_spec, dict)
                else []
            ),
            "candidate_json": json_block(candidate),
        },
    )


def render_generate_topic_contract_prompt(
    topic_description: str,
    base_contract: dict[str, Any],
) -> str:
    return render_template(
        "generate_topic_contract.md",
        {
            "topic_description": topic_description,
            "base_contract_json": json_block(base_contract),
        },
    )


def refinement_context_contract(current_contract: dict[str, Any]) -> dict[str, Any]:
    """Omit provisional bootstrap categories from refinement prompt context."""
    context = deepcopy(current_contract)
    tagging = context.get("tagging")
    if isinstance(tagging, dict):
        context["tagging"] = {
            "fallback_policy": deepcopy(tagging.get("fallback_policy", {})),
            "categories": [],
            "categories_note": (
                "Bootstrap categories omitted. Build final tagging categories "
                "only from extracted review full-text evidence."
            ),
        }
    return context


def render_refine_topic_contract_prompt(
    topic_description: str,
    current_contract: dict[str, Any],
    review_overviews: list[dict[str, Any]],
) -> str:
    return render_template(
        "refine_topic_contract_from_reviews.md",
        {
            "topic_description": topic_description,
            "current_contract_json": json_block(
                refinement_context_contract(current_contract)
            ),
            "review_overviews_json": json_block(review_overviews),
        },
    )


def render_repair_topic_contract_tagging_prompt(
    topic_description: str,
    failed_contract: dict[str, Any],
    review_overviews: list[dict[str, Any]],
    validation_issues: list[dict[str, Any]],
    existing_category_ids: list[str],
    forbidden_generic_ids: list[str],
    forbidden_catchall_values: list[str],
) -> str:
    return render_template(
        "repair_topic_contract_tagging.md",
        {
            "topic_description": topic_description,
            "failed_contract_json": json_block(failed_contract),
            "review_overviews_json": json_block(review_overviews),
            "validation_issues_json": json_block(validation_issues),
            "existing_category_ids_json": json_block(existing_category_ids),
            "forbidden_generic_ids_json": json_block(forbidden_generic_ids),
            "forbidden_catchall_values_json": json_block(forbidden_catchall_values),
        },
    )


def render_repair_topic_structure_prompt(
    topic_description: str,
    topic_structure: dict[str, Any],
    validation_issues: list[dict[str, Any]],
) -> str:
    return render_template(
        "repair_topic_structure.md",
        {
            "topic_description": topic_description,
            "topic_structure_json": json_block(topic_structure),
            "validation_issues_json": json_block(validation_issues),
        },
    )


def render_calibrate_topic_contract_prompt(
    topic_description: str,
    current_contract: dict[str, Any],
    primary_papers: list[dict[str, Any]],
) -> str:
    return render_template(
        "calibrate_topic_contract_from_papers.md",
        {
            "topic_description": topic_description,
            "current_contract_json": json_block(current_contract),
            "primary_papers_json": json_block(primary_papers),
        },
    )


def render_complete_tagging_category_values_prompt(
    topic_contract: dict[str, Any],
    existing_categories: dict[str, Any],
    requested_categories: list[dict[str, Any]],
    evidence: list[dict[str, Any]],
) -> str:
    return render_template(
        "complete_tagging_category_values.md",
        {
            "research_topic_json": json_block(topic_contract["research_topic"]),
            "topic_structure_json": json_block(topic_contract.get("topic_structure", {})),
            "existing_categories_json": json_block(existing_categories),
            "requested_categories_json": json_block(requested_categories),
            "evidence_json": json_block(evidence),
        },
    )


def render_generate_tagging_rules_prompt(
    config: dict[str, object],
    topic_contract: dict[str, Any] | None = None,
    fallback_recommendations: dict[str, str | None] | None = None,
) -> str:
    fallback_policy = {}
    if topic_contract is not None:
        tagging = topic_contract.get("tagging", {})
        if isinstance(tagging, dict):
            fallback_policy = tagging.get("fallback_policy", {})
    return render_template(
        "generate_tagging_rules.md",
        {
            "research_topic_json": json_block(config["research_topic"]),
            "categories_json": json_block(config["categories"]),
            "fallback_policy_json": json_block(fallback_policy),
            "fallback_recommendations_json": json_block(
                fallback_recommendations or {}
            ),
        },
    )


def render_extract_review_labels_prompt(
    paper: dict[str, Any],
    review_config: dict[str, Any],
) -> str:
    return render_template(
        "extract_review_labels.md",
        {
            "research_topic_json": json_block(review_config["research_topic"]),
            "topic_structure_json": json_block(
                review_config.get("topic_structure", {})
            ),
            "review_config_json": json_block(review_config["review"]),
            "paper_json": json_block(paper),
        },
    )


def render_tag_paper_with_review_prompt(
    paper: dict[str, str],
    config: dict[str, object],
    rules: dict[str, object],
    review_paper: dict[str, Any],
    review_config: dict[str, Any],
    topic_contract: dict[str, Any] | None = None,
) -> str:
    return render_template(
        "tag_paper_with_review.md",
        {
            "tagging_prompt": render_tag_paper_prompt(
                paper,
                config,
                rules,
                topic_contract,
            ),
            "review_config_json": json_block(review_config["review"]),
            "review_topic_structure_json": json_block(
                review_config.get("topic_structure", {})
            ),
            "review_paper_json": json_block(review_paper),
        },
    )


def render_synthesize_review_section_prompt(
    evidence_map: dict[str, Any],
    section: dict[str, Any],
) -> str:
    return render_template(
        "synthesize_review_section.md",
        {
            "research_topic_json": json_block(evidence_map.get("research_topic", {})),
            "overview_json": json_block(evidence_map.get("overview", {})),
            "quality_json": json_block(evidence_map.get("quality", {})),
            "section_json": json_block(section),
        },
    )


def render_tag_paper_prompt(
    paper: dict[str, str],
    config: dict[str, object],
    rules: dict[str, object],
    topic_contract: dict[str, Any] | None = None,
) -> str:
    scope = scope_text(topic_contract) if topic_contract is not None else ""
    categories = config.get("categories")
    category_ids = set()
    if isinstance(categories, list):
        category_ids = {
            str(category.get("category_id"))
            for category in categories
            if isinstance(category, dict)
        }
    if "review_status" in category_ids:
        review_status_instruction = (
            '- Set review_status to ["ai_tagged"] unless another configured '
            "review_status value such as full_text_needed clearly applies."
        )
    else:
        review_status_instruction = (
            "- Do not return review_status because it is not listed as an "
            "allowed category."
        )
    return render_template(
        "tag_paper.md",
        {
            "research_topic_json": json_block(config["research_topic"]),
            "scope_text": scope,
            "paper_json": json_block(paper),
            "categories_json": json_block(config["categories"]),
            "rules_json": json_block(rules["rules"]),
            "review_status_instruction": review_status_instruction,
        },
    )
