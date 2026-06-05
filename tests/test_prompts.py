from __future__ import annotations

from pathlib import Path

from ad_lit_pipeline.prompts.render import (
    render_generate_tagging_rules_prompt,
    render_generate_topic_contract_prompt,
    render_repair_topic_contract_tagging_prompt,
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
    assert "knowledge_goal" in prompt
    assert "examples only" in prompt
    assert "`applies_when`" in prompt
    assert "common abbreviations or acronyms" in prompt
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
                "title": "Review of AI biomarkers for early AD detection",
                "abstract": "A review of modalities and validation practices.",
            }
        ],
    )

    assert "Review and overview seed papers" in prompt
    assert "Bootstrap categories omitted" in prompt
    assert '"categories": []' in prompt
    assert "main_topic_category" not in prompt
    assert "knowledge categories" in prompt
    assert "at least 6 knowledge tagging categories" in prompt
    assert "category_id `knowledge_goal`" in prompt
    assert "topic_structure.main_topics" in prompt
    assert "complete, mutually exclusive partition" in prompt
    assert "mental distribution check" in prompt
    assert "no single value should be so broad" in prompt
    assert "conditional sub-categories" in prompt
    assert "Do not add `unclear`, `mixed_or_unclear`, `not_reported`, or `other`" in prompt
    assert "generic boilerplate categories" in prompt
    assert "generic method or participant buckets" in prompt
    assert "topic-specific id and values" in prompt
    assert "multiple allowed values" in prompt
    assert "`applies_when`" in prompt
    assert "only about knowledge tagging" in prompt
    assert "know-how" not in prompt
    assert "imagined primary papers" in prompt
    assert "If the review and overview seed paper list is empty" in prompt


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
    assert "Do not return a full topic contract" in prompt
    assert "boilerplate_category_id" in prompt


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
