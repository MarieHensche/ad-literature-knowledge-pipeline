from __future__ import annotations

import json
from pathlib import Path
from string import Template
from typing import Any


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
) -> str:
    max_results_text = (
        f"The user requested about {max_results} candidates."
        if max_results
        else "No explicit max result count was provided."
    )
    return render_template(
        "plan_search.md",
        {
            "topic_description": topic_description,
            "max_results_text": max_results_text,
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


def render_generate_tagging_rules_prompt(
    config: dict[str, object],
    topic_contract: dict[str, Any] | None = None,
    fallback_recommendations: dict[str, str] | None = None,
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


def render_tag_paper_prompt(
    paper: dict[str, str],
    config: dict[str, object],
    rules: dict[str, object],
    topic_contract: dict[str, Any] | None = None,
) -> str:
    scope = scope_text(topic_contract) if topic_contract is not None else ""
    return render_template(
        "tag_paper.md",
        {
            "research_topic_json": json_block(config["research_topic"]),
            "scope_text": scope,
            "paper_json": json_block(paper),
            "categories_json": json_block(config["categories"]),
            "rules_json": json_block(rules["rules"]),
        },
    )
