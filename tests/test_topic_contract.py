from __future__ import annotations

import json
import subprocess
import sys
from copy import deepcopy
from pathlib import Path

import pytest

from ad_lit_pipeline.topics.contract import (
    generated_tagging_quality_issues,
    generated_tagging_quality_warnings,
    load_topic_contract,
    rule_based_screening_from_contract,
    tagging_config_from_contract,
    validate_generated_tagging_quality,
    validate_topic_contract,
)


ROOT = Path(__file__).resolve().parents[1]


def run_script(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, *args],
        cwd=ROOT,
        check=True,
        text=True,
        capture_output=True,
    )


def test_early_detection_topic_contract_loads() -> None:
    contract = load_topic_contract(ROOT / "configs/topics/early_detection_ad.yaml")

    assert contract["topic_id"] == "early_detection_ad"
    assert "main_topic_category" in contract["tagging"]["categories"]
    assert "research_target" in contract["tagging"]["categories"]
    assert contract["collection"]["allowed_providers"] == ["openalex"]
    assert contract["collection"]["exclude_openalex_review_type"] is True
    assert contract["rule_based_screening"]["exclude_wins"] is True
    assert contract["candidate_screening"]["borderline_policy"] == "include"
    assert contract["topic_structure"]["anchor_topic_id"] == "early_detection"
    assert "mild cognitive impairment" in contract["rule_based_screening"][
        "include_terms"
    ]


def test_non_ad_topic_contract_loads() -> None:
    contract = load_topic_contract(ROOT / "configs/topics/ai_in_education.yaml")

    assert contract["topic_id"] == "ai_in_education"
    assert "main_topic_category" in contract["tagging"]["categories"]
    assert "research_target" in contract["tagging"]["categories"]
    assert contract["collection"]["exclude_openalex_review_type"] is False
    assert contract["topic_structure"]["anchor_topic_id"] == "ai"


def test_topic_contract_template_loads() -> None:
    contract = load_topic_contract(ROOT / "configs/topics/topic_contract_template.yaml")

    assert contract["topic_id"] == "generated_topic_template"
    assert contract["topic_structure"]["anchor_topic_id"] == "primary_topic"
    assert contract["candidate_screening"]["borderline_policy"] == "include"
    assert contract["collection"]["exclude_openalex_review_type"] is False
    assert contract["collection"]["search_queries"] == []
    assert "knowledge_goal" in contract["tagging"]["categories"]
    assert "example_goal_b_subtype" in contract["tagging"]["categories"]
    assert "research_target" not in contract["tagging"]["categories"]


def test_topic_contract_converts_to_legacy_tagging_config() -> None:
    contract = load_topic_contract(ROOT / "configs/topics/early_detection_ad.yaml")
    config = tagging_config_from_contract(contract)

    assert config["research_topic"]["title"].startswith("Early detection")
    assert len(config["categories"]) == 12
    assert "main_topic_category" in config["categories"]
    assert "research_target" in config["categories"]
    assert config["categories"]["review_status"]["required"] is True
    assert config["categories"]["review_status"]["values"] == [
        "ai_tagged",
        "human_reviewed",
        "full_text_needed",
        "excluded_from_scope",
    ]


def test_rule_based_screening_uses_topic_terms_not_tag_values() -> None:
    contract = load_topic_contract(ROOT / "configs/topics/early_detection_ad.yaml")
    rule_based = rule_based_screening_from_contract(contract)

    assert "AD" in rule_based["include_terms"]
    assert "neuroimaging" in rule_based["include_terms"]
    assert "ad vs control" not in rule_based["include_terms"]
    assert "core topic" not in rule_based["include_terms"]
    assert "out of scope" not in rule_based["include_terms"]
    assert "mixed or unclear" not in rule_based["include_terms"]
    assert "ai tagged" not in rule_based["include_terms"]


def test_normalize_tagging_config_accepts_topic_contract(tmp_path: Path) -> None:
    output = tmp_path / "normalized.json"

    run_script(
        "scripts/normalize_tagging_config.py",
        "--topic-contract",
        "configs/topics/early_detection_ad.yaml",
        "--output",
        str(output),
    )

    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["source_config"] == "configs/topics/early_detection_ad.yaml"
    assert payload["source_type"] == "topic_contract"
    assert payload["category_count"] == 12
    review_status = [
        category
        for category in payload["categories"]
        if category["category_id"] == "review_status"
    ][0]
    assert review_status["required"] is True


def test_topic_contract_does_not_require_generic_mantis_categories() -> None:
    contract = deepcopy(load_topic_contract(ROOT / "configs/topics/early_detection_ad.yaml"))
    del contract["tagging"]["categories"]["main_topic_category"]
    del contract["tagging"]["categories"]["research_target"]

    validate_topic_contract(contract)


def generated_quality_contract() -> dict:
    contract = deepcopy(load_topic_contract(ROOT / "configs/topics/ai_in_education.yaml"))
    contract["tagging"]["categories"] = {
        "knowledge_goal": {
            "required": True,
            "selection": "single",
            "values": [
                "performance_improvement",
                "engagement_support",
                "learning_process_support",
                "equity_or_access",
            ],
        },
        "ai_tool_type": {
            "required": False,
            "selection": "multi",
            "values": [
                "chatbot",
                "adaptive_learning_system",
                "automated_feedback",
                "generative_ai_assistant",
            ],
        },
        "education_level": {
            "required": False,
            "selection": "multi",
            "values": [
                "primary_school",
                "secondary_school",
                "higher_education",
                "mixed_levels",
            ],
        },
        "outcome_domain": {
            "required": False,
            "selection": "multi",
            "values": [
                "academic_performance",
                "student_engagement",
                "learning_outcomes",
                "motivation",
            ],
        },
        "learning_domain": {
            "required": False,
            "selection": "multi",
            "values": [
                "language_learning",
                "mathematics",
                "programming",
                "cross_subject",
            ],
        },
        "ai_use_context": {
            "required": False,
            "selection": "multi",
            "values": [
                "classroom_instruction",
                "homework_support",
                "after_class_review",
                "assessment_feedback",
            ],
        },
        "assessment_signal": {
            "required": False,
            "selection": "multi",
            "values": [
                "grades",
                "test_scores",
                "self_report_survey",
                "learning_analytics",
            ],
        },
    }
    return contract


def test_generated_tagging_quality_accepts_concrete_categories() -> None:
    validate_generated_tagging_quality(generated_quality_contract())


def test_generated_tagging_quality_rejects_meta_categories() -> None:
    contract = generated_quality_contract()
    contract["tagging"]["categories"]["knowledge_dimension"] = {
        "required": True,
        "selection": "single",
        "values": ["method", "outcome", "population", "not_reported"],
    }

    issues = generated_tagging_quality_issues(contract)

    assert any("knowledge_dimension is a meta-category" in issue for issue in issues)
    assert any("broad category-type values" in issue for issue in issues)


def test_generated_tagging_quality_requires_enough_categories() -> None:
    contract = generated_quality_contract()
    categories = contract["tagging"]["categories"]
    contract["tagging"]["categories"] = dict(list(categories.items())[:5])

    with pytest.raises(ValueError, match="at least 6 concrete"):
        validate_generated_tagging_quality(contract)


def test_generated_tagging_quality_requires_root_partition() -> None:
    contract = generated_quality_contract()
    del contract["tagging"]["categories"]["knowledge_goal"]

    with pytest.raises(ValueError, match="knowledge_goal"):
        validate_generated_tagging_quality(contract)


def test_generated_tagging_quality_requires_valid_knowledge_goal() -> None:
    contract = generated_quality_contract()
    contract["tagging"]["categories"]["knowledge_goal"]["selection"] = "multi"

    with pytest.raises(ValueError, match="knowledge_goal"):
        validate_generated_tagging_quality(contract)


def test_generated_tagging_quality_rejects_catchall_values() -> None:
    contract = generated_quality_contract()
    contract["tagging"]["categories"]["ai_tool_type"]["values"].append("not_reported")

    issues = generated_tagging_quality_issues(contract)

    assert any("contains catch-all value" in issue for issue in issues)


def test_generated_tagging_quality_rejects_boilerplate_categories() -> None:
    contract = generated_quality_contract()
    contract["tagging"]["categories"]["study_design"] = {
        "required": False,
        "selection": "multi",
        "values": [
            "cross_sectional",
            "longitudinal",
            "experimental",
            "meta_analysis",
        ],
    }

    issues = generated_tagging_quality_issues(contract)

    assert any("study_design is a generic boilerplate" in issue for issue in issues)
    warnings = generated_tagging_quality_warnings(contract)
    assert any("study_design.values look like generic" in warning for warning in warnings)


def test_generated_tagging_quality_rejects_non_snake_case_labels() -> None:
    contract = generated_quality_contract()
    contract["tagging"]["categories"]["knowledge_goal"]["values"] = [
        "performance improvement",
        "engagement_support",
        "learning_process_support",
    ]

    issues = generated_tagging_quality_issues(contract)

    assert any("non-snake-case" in issue for issue in issues)


def test_generated_tagging_quality_rejects_vague_knowledge_goal_values() -> None:
    contract = generated_quality_contract()
    contract["tagging"]["categories"]["knowledge_goal"]["values"] = [
        "improving_maternal_mental_health",
        "enhancing_user_engagement",
        "supporting_social_support_networks",
    ]

    issues = generated_tagging_quality_issues(contract)

    assert any("vague benefit/action" in issue for issue in issues)


def test_topic_contract_requires_valid_anchor_topic() -> None:
    contract = deepcopy(load_topic_contract(ROOT / "configs/topics/ai_in_education.yaml"))
    contract["topic_structure"]["anchor_topic_id"] = "missing_topic"

    with pytest.raises(ValueError, match="anchor_topic_id"):
        validate_topic_contract(contract)


def test_topic_contract_rejects_unknown_secondary_topic_key() -> None:
    contract = deepcopy(load_topic_contract(ROOT / "configs/topics/ai_in_education.yaml"))
    contract["topic_structure"]["secondary_topics"]["unknown_topic"] = ["related term"]

    with pytest.raises(ValueError, match="unknown main topic id"):
        validate_topic_contract(contract)
