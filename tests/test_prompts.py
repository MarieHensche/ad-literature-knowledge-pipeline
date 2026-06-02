from __future__ import annotations

from pathlib import Path

from ad_lit_pipeline.prompts.render import (
    render_generate_tagging_rules_prompt,
    render_generate_topic_contract_prompt,
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
    assert "multiple topic-specific knowledge tagging categories" in prompt
    assert "at least 4 knowledge tagging categories" in prompt
    assert "multiple allowed values" in prompt
    assert "examples only" in prompt
    assert "`applies_when`" in prompt
    assert "common abbreviations or acronyms" in prompt
    assert "climate change affect human health" in prompt


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
    assert "knowledge categories" in prompt
    assert "at least 4 knowledge tagging categories" in prompt
    assert "multiple allowed values" in prompt
    assert "`applies_when`" in prompt
    assert "only about knowledge tagging" in prompt
    assert "know-how" not in prompt
    assert "imagined primary papers" in prompt


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
