from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest

from ad_lit_pipeline.io.yaml_io import write_yaml_object
from ad_lit_pipeline.steps.review.config import normalize_review_config, run
from ad_lit_pipeline.topics.contract import load_topic_contract


ROOT = Path(__file__).resolve().parents[1]


def test_default_review_config_uses_focused_review_labels() -> None:
    contract = load_topic_contract(ROOT / "configs/topics/early_detection_ad.yaml")

    normalized = normalize_review_config(contract)

    assert normalized["review"]["enabled"] is True
    assert normalized["review"]["output"]["formats"] == ["markdown"]
    label_ids = [label["label_id"] for label in normalized["review"]["labels"]]
    assert label_ids == [
        "methodology",
        "study_design",
        "dataset_or_sample",
        "key_finding",
        "paper_limitation",
        "direct_quote",
        "future_work_or_gap",
    ]
    assert "main_topic" not in label_ids
    assert "contribution" not in label_ids
    assert "paraphrased_evidence" not in label_ids
    main_topic_values = normalized["topic_structure"]["main_topics"]
    assert {
        "value": "early_detection",
        "label": "Early detection or screening",
    } in main_topic_values
    labels = {label["label_id"]: label for label in normalized["review"]["labels"]}
    assert labels["methodology"]["value_mode"] == "controlled_auto"
    assert labels["methodology"]["max_values_per_paper"] == 2
    assert labels["methodology"]["max_words_per_value"] == 5
    assert labels["study_design"]["value_mode"] == "controlled_fixed"
    assert labels["study_design"]["selection"] == "single"
    assert labels["study_design"]["max_values_per_paper"] == 1
    assert labels["study_design"]["max_words_per_value"] == 4
    assert labels["dataset_or_sample"]["max_items_per_paper"] == 2
    assert labels["dataset_or_sample"]["max_words_per_item"] == 18
    assert labels["dataset_or_sample"]["missing_value"] == "unclear"
    assert labels["key_finding"]["max_items_per_paper"] == 1
    assert labels["key_finding"]["max_words_per_item"] == 35
    assert labels["key_finding"]["missing_value"] == "unclear"
    assert labels["paper_limitation"]["max_items_per_paper"] == 2
    assert labels["paper_limitation"]["max_words_per_item"] == 25
    assert labels["paper_limitation"]["missing_value"] == "unclear"
    assert "Do not infer limitations" in labels["paper_limitation"][
        "extraction_rule"
    ]
    assert labels["future_work_or_gap"]["max_items_per_paper"] == 2
    assert labels["future_work_or_gap"]["max_words_per_item"] == 25
    assert labels["future_work_or_gap"]["missing_value"] == "unclear"
    assert "Do not infer or invent gaps" in labels["future_work_or_gap"][
        "extraction_rule"
    ]
    assert "future_work" in labels["future_work_or_gap"]["evidence_sections"]
    study_design_values = {
        value["value"] for value in labels["study_design"]["allowed_values"]
    }
    assert "systematic_review" not in study_design_values
    assert "literature_review" not in study_design_values
    assert "scoping_review" not in study_design_values
    assert "meta_analysis" not in study_design_values
    assert "model_development_study" in study_design_values
    assert "unclear" in study_design_values


def test_default_review_config_exposes_topic_terms_as_general_context() -> None:
    contract = deepcopy(load_topic_contract(ROOT / "configs/topics/early_detection_ad.yaml"))
    contract["topic_structure"]["anchor_topic_id"] = "disease_state"
    contract["topic_structure"]["main_topics"] = [
        {
            "topic_id": "disease_state",
            "label": "Disease state",
            "field": "title",
            "terms": ["Alzheimer's disease", "mild cognitive impairment"],
            "retrieval_terms": ["Alzheimer's disease"],
            "matching_terms": ["AD", "MCI"],
        },
        {
            "topic_id": "computational_methods",
            "label": "Computational methods",
            "field": "title",
            "terms": ["machine learning", "deep learning"],
            "retrieval_terms": ["bioinformatics"],
            "matching_terms": ["network analysis"],
        },
    ]
    contract["topic_structure"]["secondary_topics"] = {
        "disease_state": [],
        "computational_methods": [],
    }

    normalized = normalize_review_config(contract)
    methodology = [
        label
        for label in normalized["review"]["labels"]
        if label["label_id"] == "methodology"
    ][0]

    assert "title" in methodology["evidence_sections"]
    assert "abstract" in methodology["evidence_sections"]
    term_hint_topics = {
        topic["topic_id"]: topic for topic in normalized["topic_structure"]["term_hints"]
    }
    assert term_hint_topics["disease_state"]["is_anchor"] is True
    assert term_hint_topics["computational_methods"]["is_anchor"] is False
    computational_terms = {
        term["value"] for term in term_hint_topics["computational_methods"]["terms"]
    }
    disease_terms = {
        term["value"] for term in term_hint_topics["disease_state"]["terms"]
    }
    assert "machine_learning" in computational_terms
    assert "network_analysis" in computational_terms
    assert "alzheimer_s_disease" in disease_terms
    assert "term_hints" not in methodology
    assert "future_work" in normalized["review"]["known_section_keys"]


def test_review_config_accepts_custom_review_section(tmp_path: Path) -> None:
    contract = deepcopy(load_topic_contract(ROOT / "configs/topics/early_detection_ad.yaml"))
    contract["review"] = {
        "enabled": True,
        "output": {
            "formats": ["markdown"],
            "citation_style": "vancouver",
            "max_quote_words": 30,
        },
        "labels": {
            "research_method": {
                "description": "Method used by the study.",
                "value_mode": "controlled_auto",
                "selection": "multi",
                "values": "auto",
                "evidence_sections": ["Methods", "Analysis"],
            },
            "important_quote": {
                "description": "Direct quotation for the review.",
                "value_mode": "evidence_quote",
                "evidence_sections": ["Discussion", "Conclusion"],
            },
        },
    }
    contract_path = tmp_path / "topic_contract.yaml"
    output_path = tmp_path / "review_config.json"
    write_yaml_object(contract_path, contract)

    result = run(contract_path, output_path)
    payload = json.loads(output_path.read_text(encoding="utf-8"))

    assert result.row_counts["review_labels"] == 2
    assert payload["source_type"] == "topic_contract"
    assert payload["review"]["enabled"] is True
    assert payload["review"]["output"]["citation_style"] == "vancouver"
    assert payload["review"]["output"]["max_quote_words"] == 30
    assert [label["label_id"] for label in payload["review"]["labels"]] == [
        "research_method",
        "important_quote",
    ]
    assert payload["review"]["labels"][0]["evidence_sections"] == [
        "methods",
        "analysis",
    ]


def test_review_config_rejects_invalid_value_mode() -> None:
    contract = deepcopy(load_topic_contract(ROOT / "configs/topics/early_detection_ad.yaml"))
    contract["review"] = {
        "labels": {
            "methodology": {
                "description": "Bad mode.",
                "value_mode": "anything_goes",
                "values": ["a", "b"],
            },
        },
    }

    with pytest.raises(ValueError, match="value_mode"):
        normalize_review_config(contract)
