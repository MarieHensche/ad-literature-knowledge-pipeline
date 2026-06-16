from __future__ import annotations

from pathlib import Path

from ad_lit_pipeline.prompts.render import (
    render_generate_tagging_rules_prompt,
    render_generate_topic_contract_prompt,
    render_calibrate_topic_contract_prompt,
    render_repair_topic_contract_tagging_prompt,
    render_repair_topic_structure_prompt,
    render_refine_topic_contract_prompt,
    render_screen_candidate_prompt,
    render_tag_paper_prompt,
)
from ad_lit_pipeline.steps.tagging.normalize_config import normalize_config
from ad_lit_pipeline.topics.contract import (
    load_topic_contract,
    tagging_config_from_contract,
)


ROOT = Path(__file__).resolve().parents[1]


def test_screen_candidate_prompt_uses_topic_contract_scope() -> None:
    contract = load_topic_contract(ROOT / "configs/topics/early_detection_ad.yaml")
    prompt = render_screen_candidate_prompt(
        contract,
        {
            "title": "Speech Classification for Mild Cognitive Impairment",
            "abstract": "A screening study.",
        },
    )

    assert "detecting MCI or cognitive impairment" in prompt
    assert "drug discovery or treatment response" in prompt
    assert "recall-oriented candidate-screening pass" in prompt
    assert '"borderline_policy": "include"' in prompt
    assert "Speech Classification for Mild Cognitive Impairment" in prompt


def test_generate_rules_prompt_uses_topic_fallback_policy() -> None:
    contract = load_topic_contract(ROOT / "configs/topics/early_detection_ad.yaml")
    config = normalize_config(tagging_config_from_contract(contract))
    prompt = render_generate_tagging_rules_prompt(config, contract)

    assert '"review_status": "ai_tagged"' in prompt
    assert '"knowledge_confidence": "very_low"' in prompt
    assert "Follow category-specific fallback values" in prompt


def test_generate_topic_contract_prompt_discourages_narrow_screening() -> None:
    template = load_topic_contract(ROOT / "configs/topics/topic_contract_template.yaml")
    prompt = render_generate_topic_contract_prompt(
        "How does climate change affect human health?",
        template,
    )

    assert "borderline or tangentially relevant candidates are included" in prompt
    assert "collection.search_queries" in prompt
    assert "discovery-focused topic contract" in prompt
    assert "tagging categories in this first contract are provisional" in prompt.lower()
    assert "final extraction ontology" in prompt
    assert "Include at least one provisional tagging category" in prompt
    assert "do not create any root\n  focus selector" in prompt
    assert "examples only" in prompt
    assert "`applies_when`" in prompt
    assert "common abbreviations or acronyms" in prompt
    assert "Make main topics broad enough for title screening" in prompt
    assert "least 4 focused `terms`" in prompt
    assert "Do not pad term lists" in prompt
    assert "`retrieval_terms`" in prompt
    assert "`matching_terms`" in prompt
    assert "`secondary_topic_id`" in prompt
    assert "Keep secondary replacements as separate semantic groups" in prompt
    assert "`title`, `abstract`, or `title_or_abstract`" in prompt
    assert "mandatory core concept for title screening" in prompt
    assert "categories may use those ids directly" in prompt.lower()
    assert "Could X be used to" in prompt
    assert "Do not anchor on the application" in prompt
    assert "Each main topic must represent exactly one\n    conceptual area" in prompt
    assert "instead of `ai_in_school`" in prompt
    assert "Terms inside a main topic must name only that one component" in prompt
    assert "Set the anchor main topic's `field` to `title`" in prompt
    assert "Keep `retrieval_terms` component-pure" in prompt
    assert "Do not create a secondary topic that simply repeats" in prompt
    assert "genuinely adjacent sibling directions" in prompt
    assert "machine_learning` and `deep_learning`" in prompt
    assert "Do not use `abstract` for generated main topics" in prompt
    assert "Setting, context, or population components should use `title`" in prompt
    assert "domain-specific named variants" in prompt
    assert "attention and" in prompt
    assert "memory should use separate" in prompt
    assert "broad criterion or motivation" in prompt
    assert "concrete replacement, comparator" in prompt
    assert "alternative to a concrete target" in prompt
    assert "not only a broad `building_materials` topic" in prompt
    assert "separate `fungi`, `building_materials`, and" in prompt
    assert "Keep replacement/comparator topics component-pure" in prompt
    assert "`cement substitute`" in prompt
    assert "Keep application/domain topics concrete" in prompt
    assert "`construction technology`" in prompt
    assert "preserve that\n  wording in the main topic id/label" in prompt
    assert "`construction_products` or `building_products`" in prompt
    assert "`structural integrity`, `construction" in prompt
    assert "`building techniques`" in prompt
    assert "performance metrics" in prompt
    assert "climate change affect human health" in prompt
    assert "at least 6 knowledge tagging categories" not in prompt
    assert "mental distribution check" not in prompt
    assert "no single value should be so broad" not in prompt


def test_refine_topic_contract_prompt_requests_multiple_knowledge_categories() -> None:
    contract = load_topic_contract(ROOT / "configs/topics/early_detection_ad.yaml")
    prompt = render_refine_topic_contract_prompt(
        "How can Alzheimer's disease be detected early?",
        contract,
        [
            {
                "review_id": "W1",
                "full_text_evidence": "[Results]\nSpeech and imaging markers matter.",
            }
        ],
    )

    assert "Extracted review full-text evidence" in prompt
    assert "Bootstrap categories omitted" in prompt
    assert (
        "Build final tagging categories only from extracted review full-text evidence"
        in prompt
    )
    assert '"categories": []' in prompt
    assert "main_topic_category" not in prompt
    assert "knowledge categories" in prompt
    assert "full_text_evidence" in prompt
    assert "Define tagging categories and allowed values only from `full_text_evidence`" in prompt
    assert "Do not use titles, abstracts, query metadata" in prompt
    assert "at least 6 knowledge tagging categories" in prompt
    assert "Do not create a root focus selector" in prompt
    assert "Tag papers directly with topic-specific categories" in prompt
    assert "topic_structure.main_topics" in prompt
    assert "mandatory core concept for title screening" in prompt
    assert "improve recall without weakening topical fit" in prompt
    assert "Could X be used to" in prompt
    assert "Do not anchor on the application" in prompt
    assert "Each main topic must represent exactly one conceptual area" in prompt
    assert "Bad examples: `ai_in_school`" in prompt
    assert "Terms inside a main topic must name only that one component" in prompt
    assert "Set the anchor main topic's `field` to `title`" in prompt
    assert "Keep `retrieval_terms` component-pure" in prompt
    assert "Do not create a secondary topic that simply repeats" in prompt
    assert "genuinely adjacent sibling directions" in prompt
    assert "machine_learning` and `deep_learning`" in prompt
    assert "Do not use `abstract` for generated main topics" in prompt
    assert "Setting, context, or population components should use `title`" in prompt
    assert "multiple outcomes, targets, signals" in prompt
    assert "broad criterion or motivation" in prompt
    assert "alternative to a concrete target" in prompt
    assert "not only a broad `building_materials` topic" in prompt
    assert "separate `fungi`, `building_materials`, and" in prompt
    assert "Keep replacement/comparator topics component-pure" in prompt
    assert "`cement substitute`" in prompt
    assert "Keep application/domain topics concrete" in prompt
    assert "`construction technology`" in prompt
    assert "preserve that\n    wording in the main topic id/label" in prompt
    assert "`construction_products` or\n    `building_products`" in prompt
    assert "`structural integrity`, `construction" in prompt
    assert "`building techniques`" in prompt
    assert "whole-question" in prompt
    assert "effect_of_x" in prompt
    assert "mental distribution check" in prompt
    assert "conditional sub-categories" in prompt
    assert "Do not add `unclear`, `mixed_or_unclear`, `not_reported`, or `other`" in prompt
    assert "generic boilerplate categories" in prompt
    assert "generic method or participant buckets" in prompt
    assert "topic-specific id and values" in prompt
    assert "multiple allowed values" in prompt
    assert "`applies_when`" in prompt
    assert "may refine only `topic_structure` and `tagging.categories`" in prompt
    assert "know-how" not in prompt
    assert "imagined primary papers" in prompt
    assert "If no extracted review full-text evidence is available" in prompt


def test_calibrate_topic_contract_prompt_uses_primary_full_text_evidence() -> None:
    contract = load_topic_contract(ROOT / "configs/topics/ai_in_education.yaml")
    prompt = render_calibrate_topic_contract_prompt(
        "Use of AI in school lessons and student performance",
        contract,
        [
            {
                "paper_id": "p1",
                "full_text_evidence": (
                    "[Results]\nAI tutoring changed classroom engagement."
                ),
            }
        ],
    )

    assert "Selected primary-paper full-text evidence" in prompt
    assert "full_text_evidence" in prompt
    assert "review-derived ontology as the starting point" in prompt
    assert "light polish step" in prompt
    assert "Do not create any root focus selector" in prompt
    assert "root focus selector" in prompt
    assert "Preserve `research_topic`, `topic_structure`, `scope`" in prompt
    assert "AI tutoring changed classroom engagement" in prompt
    assert "completely new ontology" in prompt


def test_repair_topic_contract_tagging_prompt_is_patch_only() -> None:
    prompt = render_repair_topic_contract_tagging_prompt(
        topic_description="How does green space affect sleep?",
        failed_contract={
            "topic_id": "green_space_sleep",
            "tagging": {
                "categories": {
                    "study_design": {
                        "required": False,
                        "selection": "multi",
                        "values": ["cross_sectional", "longitudinal"],
                    }
                }
            },
        },
        review_overviews=[],
        validation_issues=[
            {
                "code": "boilerplate_category_id",
                "category_id": "study_design",
                "values": [],
                "message": "study_design is generic.",
            }
        ],
        existing_category_ids=["study_design"],
        forbidden_generic_ids=["study_design"],
        forbidden_catchall_values=["not_reported", "other"],
    )

    assert "Return only a JSON patch" in prompt
    assert "Do not modify `research_topic`, `topic_structure`, `scope`" in prompt
    assert "Patch only `tagging.categories`" in prompt
    assert "full_text_evidence" in prompt
    assert "Do not use abstracts, titles, query" in prompt
    assert "Do not return a full topic contract" in prompt
    assert "boilerplate_category_id" in prompt
    assert "Remove retired categories if they appear" in prompt


def test_repair_topic_structure_prompt_is_structure_only() -> None:
    prompt = render_repair_topic_structure_prompt(
        topic_description="Use of AI in school lessons and student performance",
        topic_structure={
            "anchor_topic_id": "ai",
            "main_topics": [
                {"topic_id": "ai"},
                {"topic_id": "school"},
                {"topic_id": "student_performance"},
            ],
            "secondary_topics": [],
        },
        validation_issues=[
            {
                "code": "missing_secondary_topic",
                "topic_id": "school",
                "message": "Missing secondary topic.",
            }
        ],
    )

    assert "Return only a complete repaired `topic_structure` JSON object" in prompt
    assert "Do not return a full topic contract" in prompt
    assert "source/tool/intervention/material should be\n  the anchor" in prompt
    assert "not the application, outcome, or replacement goal" in prompt
    assert "adjacent sibling directions" in prompt
    assert "not narrower internal\n  subtypes" in prompt
    assert "Do not use `abstract` for generated main topics" in prompt
    assert "Setting, context, or population components should use `title`" in prompt
    assert "explicit paired concepts are buried" in prompt
    assert "broad criterion or motivation topic" in prompt
    assert "replacement target is not a main topic" in prompt
    assert "do not leave\n  `concrete` only inside terms" in prompt
    assert "replacement/comparator topic has criterion" in prompt
    assert "concrete replacement, concrete\n  alternative, cement substitute" in prompt
    assert "replacement application/domain is not a main" in prompt
    assert "application/domain topic has generic terms" in prompt
    assert "application/domain topic or secondary group has" in prompt
    assert "`structural integrity`, `construction innovations`" in prompt
    assert "application/domain secondary group has criterion" in prompt
    assert "`construction_products`, `building_products`" in prompt
    assert "missing secondary topic is an application/domain topic" in prompt
    assert "without a fallback after removing invalid green" in prompt
    assert "school" in prompt
    assert "missing_secondary_topic" in prompt


def test_tag_paper_prompt_only_mentions_review_status_when_configured() -> None:
    config = {
        "research_topic": {"title": "Topic", "description": "Description"},
        "categories": [
            {
                "category_id": "impact_category",
                "allowed_values": [{"value": "physical_health"}],
            }
        ],
    }
    rules = {
        "rules": [
            {
                "category_id": "impact_category",
                "selection": "single",
                "fallback_value": "physical_health",
            }
        ]
    }
    prompt = render_tag_paper_prompt(
        {"paper_id": "p1", "title": "Climate health"},
        config,
        rules,
    )

    assert "Do not return review_status" in prompt
    assert 'Set review_status to ["ai_tagged"]' not in prompt
    assert "Do not combine fallback values" in prompt
    assert "required categories with no fallback_value" in prompt
    assert "Do not select the broadest or first-listed value" in prompt
    assert "single main-topic value" in prompt
