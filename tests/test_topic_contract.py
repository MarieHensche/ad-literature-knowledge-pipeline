from __future__ import annotations

import json
import subprocess
import sys
from copy import deepcopy
from pathlib import Path

import pytest

from ad_lit_pipeline.topics.contract import (
    generated_tagging_quality_issue_records,
    generated_tagging_quality_issues,
    generated_tagging_quality_warnings,
    generated_topic_structure_crucial_issues,
    generated_topic_structure_quality_issues,
    load_topic_contract,
    rule_based_screening_from_contract,
    tagging_config_from_contract,
    validate_generated_tagging_quality,
    validate_generated_topic_structure_quality,
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
    assert "knowledge_goal" not in contract["tagging"]["categories"]
    assert "primary_topic_detail" in contract["tagging"]["categories"]
    assert "secondary_focus_detail" in contract["tagging"]["categories"]
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
        "ai": {
            "required": False,
            "selection": "multi",
            "values": [
                "chatbot",
                "adaptive_learning_system",
                "automated_feedback",
                "generative_ai_assistant",
            ],
        },
        "formal_education": {
            "required": False,
            "selection": "multi",
            "values": [
                "primary_school",
                "secondary_school",
                "higher_education",
                "mixed_levels",
            ],
        },
        "learning_impact": {
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


def test_generated_tagging_quality_rejects_retired_categories() -> None:
    contract = generated_quality_contract()
    contract["tagging"]["categories"]["knowledge_goal"] = {
        "required": True,
        "selection": "single",
        "values": ["ai", "formal_education"],
    }

    records = generated_tagging_quality_issue_records(contract)

    assert any(
        record.code == "retired_category_id"
        and record.category_id == "knowledge_goal"
        for record in records
    )


def test_generated_tagging_quality_rejects_catchall_values() -> None:
    contract = generated_quality_contract()
    contract["tagging"]["categories"]["ai"]["values"].append("not_reported")

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


def test_generated_tagging_quality_issue_records_include_codes() -> None:
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

    records = generated_tagging_quality_issue_records(contract)

    assert any(
        record.code == "boilerplate_category_id"
        and record.category_id == "study_design"
        for record in records
    )


def test_generated_tagging_quality_rejects_non_snake_case_labels() -> None:
    contract = generated_quality_contract()
    contract["tagging"]["categories"]["learning_impact"]["values"] = [
        "performance improvement",
        "engagement_support",
        "learning_process_support",
    ]

    issues = generated_tagging_quality_issues(contract)

    assert any("non-snake-case" in issue for issue in issues)


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


def test_topic_contract_accepts_grouped_secondary_topics() -> None:
    contract = deepcopy(load_topic_contract(ROOT / "configs/topics/ai_in_education.yaml"))
    contract["topic_structure"]["secondary_topics"] = {
        "formal_education": [
            {
                "secondary_topic_id": "higher_education",
                "label": "Higher education",
                "field": "title",
                "terms": ["higher education", "university"],
                "retrieval_terms": ["higher education"],
                "matching_terms": ["college"],
            },
            {
                "secondary_topic_id": "workplace_learning",
                "label": "Workplace learning",
                "field": "title_or_abstract",
                "terms": ["workplace", "internship"],
                "retrieval_terms": ["workplace"],
                "matching_terms": ["office"],
            },
        ]
    }

    validate_topic_contract(contract)


def test_topic_contract_rejects_too_many_retrieval_terms() -> None:
    contract = deepcopy(load_topic_contract(ROOT / "configs/topics/ai_in_education.yaml"))
    contract["topic_structure"]["main_topics"][0]["retrieval_terms"] = [
        f"term {index}" for index in range(13)
    ]

    with pytest.raises(ValueError, match="at most 12 terms"):
        validate_topic_contract(contract)


def test_topic_contract_rejects_invalid_topic_field() -> None:
    contract = deepcopy(load_topic_contract(ROOT / "configs/topics/ai_in_education.yaml"))
    contract["topic_structure"]["main_topics"][0]["field"] = "full_text"

    with pytest.raises(ValueError, match="field must be one of"):
        validate_topic_contract(contract)


def test_generated_topic_structure_rejects_merged_main_topic_id() -> None:
    contract = deepcopy(load_topic_contract(ROOT / "configs/topics/ai_in_education.yaml"))
    contract["topic_structure"]["main_topics"][0]["topic_id"] = "ai_in_school"
    contract["topic_structure"]["anchor_topic_id"] = "ai_in_school"

    with pytest.raises(ValueError, match="merges multiple concept areas"):
        validate_generated_topic_structure_quality(contract)


def test_generated_topic_structure_rejects_cross_topic_terms() -> None:
    contract = deepcopy(load_topic_contract(ROOT / "configs/topics/ai_in_education.yaml"))
    contract["topic_structure"]["main_topics"][0]["terms"].append("AI in schools")

    issues = generated_topic_structure_quality_issues(contract)

    assert any("AI in schools" in issue for issue in issues)


def test_generated_topic_structure_rejects_non_title_anchor_field() -> None:
    contract = deepcopy(load_topic_contract(ROOT / "configs/topics/ai_in_education.yaml"))
    contract["topic_structure"]["main_topics"][0]["field"] = "title_or_abstract"

    issues = generated_topic_structure_quality_issues(contract)

    assert any("anchor topic" in issue and "`title`" in issue for issue in issues)


def test_generated_topic_structure_rejects_generic_terms() -> None:
    contract = deepcopy(load_topic_contract(ROOT / "configs/topics/ai_in_education.yaml"))
    contract["topic_structure"]["main_topics"][1]["terms"].append("education")

    issues = generated_topic_structure_quality_issues(contract)

    assert any("generic term `education`" in issue for issue in issues)


def test_generated_topic_structure_flags_broad_umbrella_terms_as_soft_issue() -> None:
    contract = deepcopy(load_topic_contract(ROOT / "configs/topics/ai_in_education.yaml"))
    contract["topic_structure"]["main_topics"][0]["terms"].append("data analysis")

    issues = generated_topic_structure_quality_issues(contract)

    assert any("broad umbrella term `data analysis`" in issue for issue in issues)
    assert generated_topic_structure_crucial_issues(contract) == []
    validate_generated_topic_structure_quality(contract)


def test_generated_topic_structure_flags_missing_common_surface_form() -> None:
    contract = deepcopy(load_topic_contract(ROOT / "configs/topics/ai_in_education.yaml"))
    topic = contract["topic_structure"]["main_topics"][0]
    topic["terms"] = ["AI"]
    topic["retrieval_terms"] = ["AI"]
    topic["matching_terms"] = ["AI"]

    issues = generated_topic_structure_quality_issues(contract)

    assert any("missing the common full form" in issue for issue in issues)
    assert generated_topic_structure_crucial_issues(contract) == []
    validate_generated_topic_structure_quality(contract)


def test_generated_topic_structure_accepts_common_surface_form_pair() -> None:
    contract = deepcopy(load_topic_contract(ROOT / "configs/topics/ai_in_education.yaml"))

    issues = generated_topic_structure_quality_issues(contract)

    assert not any("missing the common" in issue for issue in issues)


def test_generated_topic_structure_rejects_broad_technology_terms() -> None:
    contract = deepcopy(load_topic_contract(ROOT / "configs/topics/ai_in_education.yaml"))
    contract["topic_structure"]["main_topics"][0]["terms"].append(
        "educational technology"
    )

    issues = generated_topic_structure_quality_issues(contract)

    assert any("educational technology" in issue for issue in issues)


def test_generated_topic_structure_rejects_abstract_only_main_topic_field() -> None:
    contract = deepcopy(load_topic_contract(ROOT / "configs/topics/ai_in_education.yaml"))
    contract["topic_structure"]["main_topics"][2]["field"] = "abstract"

    issues = generated_topic_structure_quality_issues(contract)

    assert any("abstract-only" in issue for issue in issues)


def test_generated_topic_structure_rejects_context_field_not_title() -> None:
    contract = deepcopy(load_topic_contract(ROOT / "configs/topics/ai_in_education.yaml"))
    contract["topic_structure"]["main_topics"][1]["field"] = "title_or_abstract"

    issues = generated_topic_structure_quality_issues(contract)

    assert any("setting, context, or population gate" in issue for issue in issues)


def test_generated_topic_structure_rejects_non_exception_title_or_abstract_field() -> None:
    contract = deepcopy(load_topic_contract(ROOT / "configs/topics/ai_in_education.yaml"))
    contract["topic_structure"]["main_topics"][2]["field"] = "title_or_abstract"

    issues = generated_topic_structure_crucial_issues(contract)

    assert any("should default to `title`" in issue for issue in issues)


def test_generated_topic_structure_allows_title_or_abstract_for_detail_topic() -> None:
    contract = deepcopy(load_topic_contract(ROOT / "configs/topics/ai_in_education.yaml"))
    topic = contract["topic_structure"]["main_topics"][2]
    topic["topic_id"] = "model_validation"
    topic["label"] = "Model validation"
    topic["field"] = "title_or_abstract"

    issues = generated_topic_structure_crucial_issues(contract)

    assert not any("should default to `title`" in issue for issue in issues)


def test_generated_topic_structure_rejects_cross_topic_retrieval_term() -> None:
    contract = deepcopy(load_topic_contract(ROOT / "configs/topics/ai_in_education.yaml"))
    contract["topic_structure"]["main_topics"][0]["retrieval_terms"].append(
        "educational AI"
    )

    issues = generated_topic_structure_quality_issues(contract)

    assert any("educational AI" in issue for issue in issues)


def test_generated_topic_structure_rejects_duplicate_secondary_topics() -> None:
    contract = deepcopy(load_topic_contract(ROOT / "configs/topics/ai_in_education.yaml"))
    contract["topic_structure"]["secondary_topics"]["learning_impact"].append(
        {
            "secondary_topic_id": "student_achievement",
            "label": "Student achievement",
            "field": "title_or_abstract",
            "terms": ["student achievement"],
            "retrieval_terms": ["student achievement"],
            "matching_terms": ["student achievement"],
        }
    )

    issues = generated_topic_structure_quality_issues(contract)

    assert any("overlaps parent term" in issue for issue in issues)


def test_generated_topic_structure_accepts_secondary_with_useful_extra_terms() -> None:
    contract = deepcopy(load_topic_contract(ROOT / "configs/topics/ai_in_education.yaml"))
    contract["topic_structure"]["secondary_topics"]["learning_impact"].append(
        {
            "secondary_topic_id": "student_outcomes",
            "label": "Student outcomes",
            "field": "title_or_abstract",
            "terms": ["dropout", "retention"],
            "retrieval_terms": ["dropout"],
            "matching_terms": ["dropout", "retention"],
        }
    )

    validate_generated_topic_structure_quality(contract)


def test_generated_topic_structure_requires_secondary_topics_for_each_main_topic() -> None:
    contract = deepcopy(load_topic_contract(ROOT / "configs/topics/ai_in_education.yaml"))
    del contract["topic_structure"]["secondary_topics"]["learning_impact"]

    issues = generated_topic_structure_quality_issues(contract)

    assert any(
        "main topic `learning_impact`" in issue for issue in issues
    )
    assert any(
        "main topic `learning_impact`" in issue
        for issue in generated_topic_structure_crucial_issues(contract)
    )
    with pytest.raises(ValueError, match="missing_secondary_topic"):
        validate_generated_topic_structure_quality(contract)


def test_generated_topic_structure_flags_internal_subtype_secondary() -> None:
    contract = deepcopy(load_topic_contract(ROOT / "configs/topics/ai_in_education.yaml"))
    contract["topic_structure"]["main_topics"][1] = {
        "topic_id": "computational_methods",
        "label": "Computational methods",
        "field": "title",
        "terms": ["computational biology", "bioinformatics"],
        "retrieval_terms": ["computational biology", "bioinformatics"],
        "matching_terms": ["computational biology", "bioinformatics", "algorithms"],
    }
    contract["topic_structure"]["secondary_topics"] = {
        "ai": contract["topic_structure"]["secondary_topics"]["ai"],
        "computational_methods": [
            {
                "secondary_topic_id": "machine_learning_techniques",
                "label": "Machine learning techniques",
                "field": "title_or_abstract",
                "terms": ["machine learning", "deep learning"],
                "retrieval_terms": ["machine learning"],
                "matching_terms": ["machine learning", "deep learning"],
            }
        ],
        "learning_impact": contract["topic_structure"]["secondary_topics"][
            "learning_impact"
        ],
    }

    issues = generated_topic_structure_quality_issues(contract)

    assert any("narrower internal parts of the parent" in issue for issue in issues)
    assert generated_topic_structure_crucial_issues(contract) == []
    validate_generated_topic_structure_quality(contract)


def test_generated_topic_structure_flags_disease_family_variant_secondary() -> None:
    contract = deepcopy(load_topic_contract(ROOT / "configs/topics/ai_in_education.yaml"))
    contract["topic_structure"]["anchor_topic_id"] = "alzheimers_disease"
    contract["topic_structure"]["main_topics"] = [
        {
            "topic_id": "alzheimers_disease",
            "label": "Alzheimer's disease",
            "field": "title",
            "terms": ["Alzheimer's disease", "AD"],
            "retrieval_terms": ["Alzheimer's disease", "AD"],
            "matching_terms": ["Alzheimer's disease", "AD"],
        },
        contract["topic_structure"]["main_topics"][1],
        contract["topic_structure"]["main_topics"][2],
    ]
    contract["topic_structure"]["secondary_topics"] = {
        "alzheimers_disease": [
            {
                "secondary_topic_id": "mild_cognitive_impairment",
                "label": "Mild cognitive impairment",
                "field": "title",
                "terms": ["MCI", "mild cognitive impairment"],
                "retrieval_terms": ["MCI"],
                "matching_terms": ["MCI", "mild cognitive impairment"],
            },
            {
                "secondary_topic_id": "parkinsons_disease",
                "label": "Parkinson's disease",
                "field": "title",
                "terms": ["Parkinson's disease"],
                "retrieval_terms": ["Parkinson's disease"],
                "matching_terms": ["Parkinson's disease", "parkinsonism"],
            },
        ],
        "formal_education": contract["topic_structure"]["secondary_topics"][
            "formal_education"
        ],
        "learning_impact": contract["topic_structure"]["secondary_topics"][
            "learning_impact"
        ],
    }

    issues = generated_topic_structure_quality_issues(contract)

    assert any("in-family disease variant" in issue for issue in issues)
    assert not any(
        "parkinsons_disease contains in-family disease variant" in issue
        for issue in issues
    )
    assert generated_topic_structure_crucial_issues(contract) == []
    validate_generated_topic_structure_quality(contract)


def test_generated_topic_structure_rejects_generic_secondary_disease_bucket() -> None:
    contract = deepcopy(load_topic_contract(ROOT / "configs/topics/ai_in_education.yaml"))
    contract["topic_structure"]["anchor_topic_id"] = "alzheimers_disease"
    contract["topic_structure"]["main_topics"] = [
        {
            "topic_id": "alzheimers_disease",
            "label": "Alzheimer's disease",
            "field": "title",
            "terms": ["Alzheimer's disease", "AD", "dementia"],
            "retrieval_terms": ["Alzheimer's disease", "AD"],
            "matching_terms": ["Alzheimer's disease", "AD", "dementia"],
        },
        contract["topic_structure"]["main_topics"][1],
        contract["topic_structure"]["main_topics"][2],
    ]
    contract["topic_structure"]["secondary_topics"] = {
        "alzheimers_disease": [
            {
                "secondary_topic_id": "related_diseases",
                "label": "Related Diseases",
                "field": "title",
                "terms": [
                    "vascular dementia",
                    "frontotemporal dementia",
                    "Lewy body dementia",
                ],
                "retrieval_terms": ["vascular dementia", "frontotemporal dementia"],
                "matching_terms": [
                    "dementia types",
                    "neurodegenerative diseases",
                    "cognitive impairments",
                ],
            }
        ],
        "formal_education": contract["topic_structure"]["secondary_topics"][
            "formal_education"
        ],
        "learning_impact": contract["topic_structure"]["secondary_topics"][
            "learning_impact"
        ],
    }

    issues = generated_topic_structure_quality_issues(contract)

    assert any("vague mixed secondary bucket" in issue for issue in issues)
    assert any("generic neighborhood descriptor" in issue for issue in issues)
    with pytest.raises(ValueError, match="generic_secondary_topic_bucket"):
        validate_generated_topic_structure_quality(contract)


def test_generated_topic_structure_flags_bare_domain_terms_in_method_topic() -> None:
    contract = deepcopy(load_topic_contract(ROOT / "configs/topics/ai_in_education.yaml"))
    contract["topic_structure"]["main_topics"][1] = {
        "topic_id": "computational_methods",
        "label": "Computational methods",
        "field": "title",
        "terms": ["computational biology", "bioinformatics", "genomics"],
        "retrieval_terms": ["computational biology", "genomics"],
        "matching_terms": ["computational biology", "bioinformatics", "genomics"],
    }
    contract["topic_structure"]["secondary_topics"]["computational_methods"] = [
        {
            "secondary_topic_id": "wet_lab_methods",
            "label": "Wet lab methods",
            "field": "title",
            "terms": ["wet lab methods", "experimental methods"],
            "retrieval_terms": ["wet lab methods", "experimental methods"],
            "matching_terms": ["wet lab methods", "experimental methods"],
        }
    ]
    del contract["topic_structure"]["secondary_topics"]["formal_education"]

    issues = generated_topic_structure_quality_issues(contract)

    assert any("bare domain/object term `genomics`" in issue for issue in issues)
    assert generated_topic_structure_crucial_issues(contract) == []
    validate_generated_topic_structure_quality(contract)


def test_generated_topic_structure_rejects_explicit_pair_hidden_under_umbrella() -> None:
    contract = deepcopy(load_topic_contract(ROOT / "configs/topics/ai_in_education.yaml"))
    contract["topic_structure"]["anchor_topic_id"] = "traffic_noise"
    contract["topic_structure"]["main_topics"] = [
        {
            "topic_id": "traffic_noise",
            "label": "Traffic noise",
            "field": "title",
            "terms": ["traffic noise", "road traffic noise"],
            "retrieval_terms": ["traffic noise", "road traffic noise"],
            "matching_terms": ["traffic noise", "road noise"],
        },
        {
            "topic_id": "cognitive_effects",
            "label": "Cognitive effects",
            "field": "title_or_abstract",
            "terms": ["attention", "memory", "cognitive performance"],
            "retrieval_terms": ["attention", "memory"],
            "matching_terms": ["attention", "memory", "working memory"],
        },
    ]
    contract["topic_structure"]["secondary_topics"] = {
        "cognitive_effects": [
            {
                "secondary_topic_id": "executive_function",
                "label": "Executive function",
                "field": "title_or_abstract",
                "terms": ["executive function", "cognitive control"],
                "retrieval_terms": ["executive function"],
                "matching_terms": ["executive function", "cognitive control"],
            }
        ]
    }

    issues = generated_topic_structure_quality_issues(
        contract,
        topic_description="Impact of chronic traffic noise on attention and memory",
    )

    assert any("attention` and `memory" in issue for issue in issues)


def test_generated_topic_structure_rejects_criterion_when_comparator_needed() -> None:
    contract = deepcopy(load_topic_contract(ROOT / "configs/topics/ai_in_education.yaml"))
    contract["topic_structure"]["anchor_topic_id"] = "fungi"
    contract["topic_structure"]["main_topics"] = [
        {
            "topic_id": "fungi",
            "label": "Fungi",
            "field": "title",
            "terms": ["fungi", "mycelium", "mushroom", "fungal material"],
            "retrieval_terms": ["fungi", "mycelium"],
            "matching_terms": ["fungi", "mycelium"],
        },
        {
            "topic_id": "building_materials",
            "label": "Building materials",
            "field": "title_or_abstract",
            "terms": ["building materials", "construction materials"],
            "retrieval_terms": ["building materials"],
            "matching_terms": ["building materials", "construction materials"],
        },
        {
            "topic_id": "sustainability",
            "label": "Sustainability",
            "field": "title_or_abstract",
            "terms": ["sustainability", "environmental impact"],
            "retrieval_terms": ["sustainability"],
            "matching_terms": ["sustainability", "green materials"],
        },
    ]
    contract["topic_structure"]["secondary_topics"] = {
        "building_materials": [
            {
                "secondary_topic_id": "construction_products",
                "label": "Construction products",
                "field": "title_or_abstract",
                "terms": ["construction products", "building products"],
                "retrieval_terms": ["construction products"],
                "matching_terms": ["construction products", "building products"],
            }
        ],
        "sustainability": [
            {
                "secondary_topic_id": "low_carbon_materials",
                "label": "Low-carbon materials",
                "field": "title_or_abstract",
                "terms": ["low-carbon materials", "green materials"],
                "retrieval_terms": ["low-carbon materials"],
                "matching_terms": ["low-carbon materials", "green materials"],
            }
        ],
    }

    issues = generated_topic_structure_quality_issues(
        contract,
        topic_description=(
            "Could fungi be used to create sustainable building materials "
            "that replace concrete in certain applications?"
        ),
    )

    assert any("broad criterion or motivation topic" in issue for issue in issues)


def test_generated_topic_structure_rejects_buried_replacement_target() -> None:
    contract = deepcopy(load_topic_contract(ROOT / "configs/topics/ai_in_education.yaml"))
    contract["topic_structure"]["anchor_topic_id"] = "fungi"
    contract["topic_structure"]["main_topics"] = [
        {
            "topic_id": "fungi",
            "label": "Fungi",
            "field": "title",
            "terms": ["fungi", "mycelium", "mushroom", "fungal material"],
            "retrieval_terms": ["fungi", "mycelium"],
            "matching_terms": ["fungi", "mycelium"],
        },
        {
            "topic_id": "building_materials",
            "label": "Building materials",
            "field": "title",
            "terms": ["building materials", "concrete", "biomaterials"],
            "retrieval_terms": ["building materials", "concrete"],
            "matching_terms": ["construction materials", "concrete"],
        },
    ]
    contract["topic_structure"]["secondary_topics"] = {
        "building_materials": [
            {
                "secondary_topic_id": "construction_products",
                "label": "Construction products",
                "field": "title_or_abstract",
                "terms": ["construction products", "building products"],
                "retrieval_terms": ["construction products"],
                "matching_terms": ["construction products", "building products"],
            }
        ]
    }

    issues = generated_topic_structure_quality_issues(
        contract,
        topic_description=(
            "Could fungi be used to create sustainable building materials "
            "that replace concrete in certain applications?"
        ),
    )

    assert any(
        "`concrete`" in issue and "main topic id or label" in issue
        for issue in issues
    )


def test_generated_topic_structure_accepts_replacement_target_main_topic() -> None:
    contract = deepcopy(load_topic_contract(ROOT / "configs/topics/ai_in_education.yaml"))
    contract["topic_structure"]["anchor_topic_id"] = "fungi"
    contract["topic_structure"]["main_topics"] = [
        {
            "topic_id": "fungi",
            "label": "Fungi",
            "field": "title",
            "terms": ["fungi", "mycelium", "mushroom", "fungal material"],
            "retrieval_terms": ["fungi", "mycelium"],
            "matching_terms": ["fungi", "mycelium"],
        },
        {
            "topic_id": "building_materials",
            "label": "Building materials",
            "field": "title",
            "terms": ["building materials", "construction materials"],
            "retrieval_terms": ["building materials"],
            "matching_terms": ["building materials", "construction materials"],
        },
        {
            "topic_id": "concrete_replacement",
            "label": "Concrete replacement",
            "field": "title",
            "terms": ["concrete replacement", "concrete alternative"],
            "retrieval_terms": ["concrete replacement", "concrete alternative"],
            "matching_terms": ["concrete replacement", "cement substitute"],
        },
    ]
    contract["topic_structure"]["secondary_topics"] = {
        "building_materials": [
            {
                "secondary_topic_id": "construction_products",
                "label": "Construction products",
                "field": "title_or_abstract",
                "terms": ["construction products", "building products"],
                "retrieval_terms": ["construction products"],
                "matching_terms": ["construction products", "building products"],
            }
        ],
        "concrete_replacement": [
            {
                "secondary_topic_id": "cement_substitution",
                "label": "Cement substitution",
                "field": "title_or_abstract",
                "terms": ["cement substitute", "cement replacement"],
                "retrieval_terms": ["cement substitute", "cement replacement"],
                "matching_terms": ["cement substitute", "cement replacement"],
            }
        ],
    }

    validate_generated_topic_structure_quality(
        contract,
        topic_description=(
            "Could fungi be used to create sustainable building materials "
            "that replace concrete in certain applications?"
        ),
    )


def test_generated_topic_structure_accepts_source_qualified_material_terms() -> None:
    contract = deepcopy(load_topic_contract(ROOT / "configs/topics/ai_in_education.yaml"))
    contract["topic_structure"]["anchor_topic_id"] = "fungi"
    contract["topic_structure"]["main_topics"] = [
        {
            "topic_id": "fungi",
            "label": "Fungi",
            "field": "title",
            "terms": ["fungi", "mycelium", "mushroom", "fungal material"],
            "retrieval_terms": ["fungi", "mycelium", "fungal materials"],
            "matching_terms": [
                "fungi",
                "mycelium",
                "mycelium-based materials",
                "fungal composites",
            ],
        },
        {
            "topic_id": "building_materials",
            "label": "Building materials",
            "field": "title",
            "terms": [
                "building materials",
                "construction materials",
                "structural materials",
                "insulation materials",
            ],
            "retrieval_terms": ["building materials", "construction materials"],
            "matching_terms": ["building elements", "construction components"],
        },
        {
            "topic_id": "concrete_replacement",
            "label": "Concrete replacement",
            "field": "title",
            "terms": ["concrete replacement", "concrete alternative"],
            "retrieval_terms": ["concrete replacement", "concrete alternative"],
            "matching_terms": ["concrete replacement", "cement substitute"],
        },
    ]
    contract["topic_structure"]["secondary_topics"] = {
        "building_materials": [
            {
                "secondary_topic_id": "construction_products",
                "label": "Construction products",
                "field": "title_or_abstract",
                "terms": ["construction products", "building products"],
                "retrieval_terms": ["construction products"],
                "matching_terms": ["construction products", "building products"],
            }
        ],
        "concrete_replacement": [
            {
                "secondary_topic_id": "cement_substitution",
                "label": "Cement substitution",
                "field": "title_or_abstract",
                "terms": ["cement substitute", "cement replacement"],
                "retrieval_terms": ["cement substitute", "cement replacement"],
                "matching_terms": ["cement substitute", "cement replacement"],
            }
        ],
    }

    validate_generated_topic_structure_quality(
        contract,
        topic_description=(
            "Could fungi be used to create sustainable building materials "
            "that replace concrete in certain applications?"
        ),
    )


def test_generated_topic_structure_rejects_missing_replacement_application_topic() -> None:
    contract = deepcopy(load_topic_contract(ROOT / "configs/topics/ai_in_education.yaml"))
    contract["topic_structure"]["anchor_topic_id"] = "fungi"
    contract["topic_structure"]["main_topics"] = [
        {
            "topic_id": "fungi",
            "label": "Fungi",
            "field": "title",
            "terms": ["fungi", "mycelium", "mushroom", "fungal material"],
            "retrieval_terms": ["fungi", "mycelium"],
            "matching_terms": ["fungi", "mycelium"],
        },
        {
            "topic_id": "concrete_replacement",
            "label": "Concrete replacement",
            "field": "title_or_abstract",
            "terms": [
                "concrete alternative",
                "sustainable building materials",
                "green construction",
            ],
            "retrieval_terms": ["concrete alternative"],
            "matching_terms": ["concrete replacement", "green construction"],
        },
    ]
    contract["topic_structure"]["secondary_topics"] = {
        "concrete_replacement": [
            {
                "secondary_topic_id": "cement_substitution",
                "label": "Cement substitution",
                "field": "title_or_abstract",
                "terms": ["cement substitute", "cement replacement"],
                "retrieval_terms": ["cement substitute", "cement replacement"],
                "matching_terms": ["cement substitute", "cement replacement"],
            }
        ],
    }

    issues = generated_topic_structure_quality_issues(
        contract,
        topic_description=(
            "Could fungi be used to create sustainable building materials "
            "that replace concrete in certain applications?"
        ),
    )

    assert any(
        "`building materials`" in issue
        and "application/domain component" in issue
        for issue in issues
    )


def test_generated_topic_structure_rejects_explicit_application_only_in_terms() -> None:
    contract = deepcopy(load_topic_contract(ROOT / "configs/topics/ai_in_education.yaml"))
    contract["topic_structure"]["anchor_topic_id"] = "fungi"
    contract["topic_structure"]["main_topics"] = [
        {
            "topic_id": "fungi",
            "label": "Fungi",
            "field": "title",
            "terms": ["fungi", "mycelium", "mushroom", "fungal material"],
            "retrieval_terms": ["fungi", "mycelium"],
            "matching_terms": ["fungi", "mycelium"],
        },
        {
            "topic_id": "concrete_replacement",
            "label": "Concrete replacement",
            "field": "title_or_abstract",
            "terms": ["concrete replacement", "concrete alternative"],
            "retrieval_terms": ["concrete replacement", "concrete alternative"],
            "matching_terms": ["cement substitute", "cement replacement"],
        },
        {
            "topic_id": "construction_products",
            "label": "Construction products",
            "field": "title_or_abstract",
            "terms": ["building materials", "construction products"],
            "retrieval_terms": ["building materials", "building products"],
            "matching_terms": ["construction products", "building products"],
        },
    ]
    contract["topic_structure"]["secondary_topics"] = {
        "concrete_replacement": [
            {
                "secondary_topic_id": "cement_substitution",
                "label": "Cement substitution",
                "field": "title_or_abstract",
                "terms": ["cement substitute", "cement replacement"],
                "retrieval_terms": ["cement substitute", "cement replacement"],
                "matching_terms": ["cement substitute", "cement replacement"],
            }
        ],
        "construction_products": [
            {
                "secondary_topic_id": "building_products",
                "label": "Building products",
                "field": "title_or_abstract",
                "terms": ["building products", "construction products"],
                "retrieval_terms": ["building products"],
                "matching_terms": ["building products", "construction products"],
            }
        ],
    }

    issues = generated_topic_structure_quality_issues(
        contract,
        topic_description=(
            "Could fungi be used to create sustainable building materials "
            "that replace concrete in certain applications?"
        ),
    )

    assert any(
        "`building materials`" in issue
        and "application/domain component" in issue
        for issue in issues
    )


def test_generated_topic_structure_rejects_comparator_anchor_for_source_use_question() -> None:
    contract = deepcopy(load_topic_contract(ROOT / "configs/topics/ai_in_education.yaml"))
    contract["topic_structure"]["anchor_topic_id"] = "concrete_replacement"
    contract["topic_structure"]["main_topics"] = [
        {
            "topic_id": "concrete_replacement",
            "label": "Concrete replacement",
            "field": "title",
            "terms": ["concrete replacement", "alternative to concrete"],
            "retrieval_terms": ["concrete replacement", "concrete alternative"],
            "matching_terms": ["concrete replacement", "cement substitute"],
        },
        {
            "topic_id": "fungi",
            "label": "Fungi",
            "field": "title_or_abstract",
            "terms": ["fungi", "mycelium", "mushroom", "fungal material"],
            "retrieval_terms": ["fungi", "mycelium"],
            "matching_terms": ["fungi", "mycelium"],
        },
        {
            "topic_id": "building_materials",
            "label": "Building materials",
            "field": "title",
            "terms": ["building materials", "construction materials"],
            "retrieval_terms": ["building materials", "construction materials"],
            "matching_terms": ["building materials", "construction materials"],
        },
    ]
    contract["topic_structure"]["secondary_topics"] = {
        "fungi": [
            {
                "secondary_topic_id": "mycelium_materials",
                "label": "Mycelium materials",
                "field": "title_or_abstract",
                "terms": ["mycelium materials", "fungal composites"],
                "retrieval_terms": ["mycelium materials"],
                "matching_terms": ["mycelium materials", "fungal composites"],
            }
        ],
        "building_materials": [
            {
                "secondary_topic_id": "construction_products",
                "label": "Construction products",
                "field": "title_or_abstract",
                "terms": ["construction products", "building products"],
                "retrieval_terms": ["construction products"],
                "matching_terms": ["construction products", "building products"],
            }
        ],
    }

    issues = generated_topic_structure_quality_issues(
        contract,
        topic_description=(
            "Could fungi be used to create sustainable building materials "
            "that replace concrete in certain applications?"
        ),
    )

    assert any(
        "Main topic `fungi`" in issue
        and "should be the `anchor_topic_id`" in issue
        for issue in issues
    )


def test_generated_topic_structure_rejects_mixed_replacement_and_application_terms() -> None:
    contract = deepcopy(load_topic_contract(ROOT / "configs/topics/ai_in_education.yaml"))
    contract["topic_structure"]["anchor_topic_id"] = "fungi"
    contract["topic_structure"]["main_topics"] = [
        {
            "topic_id": "fungi",
            "label": "Fungi",
            "field": "title",
            "terms": ["fungi", "mycelium", "mushroom", "fungal material"],
            "retrieval_terms": ["fungi", "mycelium"],
            "matching_terms": ["fungi", "mycelium"],
        },
        {
            "topic_id": "concrete_replacement",
            "label": "Concrete replacement",
            "field": "title_or_abstract",
            "terms": [
                "concrete substitute",
                "alternative building materials",
                "green building materials",
            ],
            "retrieval_terms": [
                "concrete replacement",
                "alternative materials",
                "sustainable materials",
            ],
            "matching_terms": ["building materials", "replacement materials"],
        },
        {
            "topic_id": "building_materials",
            "label": "Building materials",
            "field": "title_or_abstract",
            "terms": ["building materials", "sustainable construction"],
            "retrieval_terms": ["building materials"],
            "matching_terms": [
                "materials science",
                "construction technology",
                "innovative materials",
            ],
        },
    ]
    contract["topic_structure"]["secondary_topics"] = {
        "concrete_replacement": [
            {
                "secondary_topic_id": "green_alternatives",
                "label": "Green alternatives",
                "field": "title_or_abstract",
                "terms": ["renewable building materials", "eco-materials"],
                "retrieval_terms": ["green alternatives"],
                "matching_terms": ["environmentally friendly materials"],
            }
        ],
        "building_materials": [
            {
                "secondary_topic_id": "innovative_materials",
                "label": "Innovative materials",
                "field": "title_or_abstract",
                "terms": ["novel building materials", "biomaterials"],
                "retrieval_terms": ["biomaterials"],
                "matching_terms": ["hybrid materials", "advanced materials"],
            }
        ],
    }

    issues = generated_topic_structure_quality_issues(
        contract,
        topic_description=(
            "Could fungi be used to create sustainable building materials "
            "that replace concrete in certain applications?"
        ),
    )

    assert any("alternative building materials" in issue for issue in issues)
    assert any("green building materials" in issue for issue in issues)
    assert any("materials science" in issue for issue in issues)
    assert any("green_alternatives" in issue for issue in issues)
    assert any("innovative_materials" in issue for issue in issues)


def test_generated_topic_structure_rejects_application_process_property_terms() -> None:
    contract = deepcopy(load_topic_contract(ROOT / "configs/topics/ai_in_education.yaml"))
    contract["topic_structure"]["anchor_topic_id"] = "fungi"
    contract["topic_structure"]["main_topics"] = [
        {
            "topic_id": "fungi",
            "label": "Fungi",
            "field": "title",
            "terms": ["fungi", "mycelium", "mushroom", "fungal material"],
            "retrieval_terms": ["fungi", "mycelium"],
            "matching_terms": ["fungi", "mycelium"],
        },
        {
            "topic_id": "building_materials",
            "label": "Building materials",
            "field": "title_or_abstract",
            "terms": ["building materials", "construction products"],
            "retrieval_terms": ["building materials", "building products"],
            "matching_terms": [
                "structural integrity",
                "construction innovations",
                "building techniques",
            ],
        },
    ]
    contract["topic_structure"]["secondary_topics"] = {
        "building_materials": [
            {
                "secondary_topic_id": "construction_products",
                "label": "Construction products",
                "field": "title_or_abstract",
                "terms": ["construction products", "building products"],
                "retrieval_terms": ["construction products"],
                "matching_terms": ["construction products", "building products"],
            }
        ],
    }

    issues = generated_topic_structure_quality_issues(contract)

    assert any("structural integrity" in issue for issue in issues)
    assert any("construction innovations" in issue for issue in issues)
    assert any("building techniques" in issue for issue in issues)


def test_generated_topic_structure_allows_one_secondary_for_narrow_outcome() -> None:
    contract = deepcopy(load_topic_contract(ROOT / "configs/topics/ai_in_education.yaml"))

    validate_generated_topic_structure_quality(contract)


def test_generated_topic_structure_accepts_atomic_multiword_topics() -> None:
    contract = deepcopy(load_topic_contract(ROOT / "configs/topics/early_detection_ad.yaml"))

    validate_generated_topic_structure_quality(contract)
