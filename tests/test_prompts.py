from __future__ import annotations

from pathlib import Path

from ad_lit_pipeline.prompts.render import (
    render_generate_tagging_rules_prompt,
    render_generate_topic_contract_prompt,
    render_screen_candidate_prompt,
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
    assert '"missing_abstract_policy": "exclude"' in prompt
    assert "Speech Classification for Mild Cognitive Impairment" in prompt


def test_generate_rules_prompt_uses_topic_fallback_policy() -> None:
    contract = load_topic_contract(ROOT / "configs/topics/early_detection_ad.yaml")
    config = normalize_config(tagging_config_from_contract(contract))
    prompt = render_generate_tagging_rules_prompt(config, contract)

    assert '"review_status": "needs_decision"' in prompt
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
    assert "climate change affect human health" in prompt
