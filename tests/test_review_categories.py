from __future__ import annotations

import csv
from copy import deepcopy
from pathlib import Path

import pytest

from ad_lit_pipeline.core.errors import PipelinePause
from ad_lit_pipeline.io.yaml_io import read_yaml_object, write_yaml_object
from ad_lit_pipeline.llm.client import StaticJSONClient
from ad_lit_pipeline.steps.tagging.review_categories import run as run_review_categories
from ad_lit_pipeline.topics.contract import load_topic_contract


ROOT = Path(__file__).resolve().parents[1]


def strict_review_contract() -> dict:
    contract = deepcopy(load_topic_contract(ROOT / "configs/topics/ai_in_education.yaml"))
    contract["tagging"]["fallback_policy"] = {
        "prefer_unclear_when_allowed": False,
        "prefer_mixed_or_unclear_when_unclear_missing": False,
        "missing_information_value": "",
        "clinical_data_context": "memory_clinic_record",
    }
    contract["tagging"]["categories"] = {
        "ad_signal_source": {
            "description": "AD detection signal sources visible in evidence.",
            "required": False,
            "selection": "multi",
            "values": ["amyloid_pet", "tau_pet", "speech_marker"],
            "applies_when": None,
        },
        "disease_transition_target": {
            "description": "Disease transition targets for early detection.",
            "required": False,
            "selection": "multi",
            "values": [
                "mci_to_ad_conversion",
                "preclinical_to_symptomatic",
                "normal_to_mci",
            ],
            "applies_when": None,
        },
        "prediction_method_family": {
            "description": "Prediction method families used in included papers.",
            "required": False,
            "selection": "multi",
            "values": [
                "convolutional_network",
                "survival_model",
                "ensemble_classifier",
            ],
            "applies_when": None,
        },
        "validation_evidence_context": {
            "description": "Validation evidence contexts for reported findings.",
            "required": False,
            "selection": "multi",
            "values": [
                "external_cohort",
                "cross_site_validation",
                "clinical_follow_up",
            ],
            "applies_when": None,
        },
        "screening_workflow_role": {
            "description": "Workflow roles for early detection tools.",
            "required": False,
            "selection": "multi",
            "values": [
                "population_screening",
                "specialist_triage",
                "monitoring_follow_up",
            ],
            "applies_when": None,
        },
        "clinical_data_context": {
            "description": "Clinical data contexts used in detection evidence.",
            "required": False,
            "selection": "multi",
            "values": [
                "memory_clinic_record",
                "community_cohort",
                "biomarker_registry",
            ],
            "applies_when": None,
        },
    }
    return contract


def write_csv(path: Path, rows: list[dict[str, str]], fieldnames: list[str]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def write_contract(path: Path) -> None:
    write_yaml_object(path, strict_review_contract())


def test_review_categories_writes_review_file_and_pauses(tmp_path: Path) -> None:
    contract_path = tmp_path / "topic_contract.yaml"
    review_path = tmp_path / "tagging_categories_review.yaml"
    write_contract(contract_path)

    with pytest.raises(PipelinePause):
        run_review_categories(contract_path, review_path, model="fake-model")

    payload = read_yaml_object(review_path)
    assert payload["status"] == "needs_review"
    assert set(payload["categories"]) == set(
        strict_review_contract()["tagging"]["categories"]
    )
    assert payload["categories"]["ad_signal_source"]["values"] == [
        "amyloid_pet",
        "tau_pet",
        "speech_marker",
    ]


def test_review_categories_merges_user_category_and_value_edits(
    tmp_path: Path,
) -> None:
    contract_path = tmp_path / "topic_contract.yaml"
    review_path = tmp_path / "tagging_categories_review.yaml"
    write_contract(contract_path)

    review_payload = {
        "status": "approved",
        "categories": {
            "ad_signal_source": {
                "values": ["amyloid_pet", "tau_pet", "plasma_marker"]
            },
            "disease_transition_target": {
                "values": [
                    "mci_to_ad_conversion",
                    "preclinical_to_symptomatic",
                    "normal_to_mci",
                ]
            },
            "prediction_method_family": {
                "values": [
                    "convolutional_network",
                    "survival_model",
                    "ensemble_classifier",
                ]
            },
            "validation_evidence_context": {
                "values": [
                    "external_cohort",
                    "cross_site_validation",
                    "clinical_follow_up",
                ]
            },
            "screening_workflow_role": {
                "values": [
                    "population_screening",
                    "specialist_triage",
                    "monitoring_follow_up",
                ]
            },
            "care_delivery_context": {
                "values": ["memory_clinic", "remote_assessment"]
            },
        },
    }
    write_yaml_object(review_path, review_payload)

    result = run_review_categories(contract_path, review_path, model="fake-model")

    contract = load_topic_contract(contract_path)
    categories = contract["tagging"]["categories"]
    assert "clinical_data_context" not in categories
    assert "care_delivery_context" in categories
    assert categories["ad_signal_source"]["values"] == [
        "amyloid_pet",
        "tau_pet",
        "plasma_marker",
    ]
    assert "clinical_data_context" not in contract["tagging"]["fallback_policy"]
    assert result.row_counts["tagging_categories"] == 6
    assert any("Removed tagging categories" in warning for warning in result.warnings)


def test_review_categories_auto_completes_values_from_paper_evidence(
    tmp_path: Path,
) -> None:
    contract_path = tmp_path / "topic_contract.yaml"
    review_path = tmp_path / "tagging_categories_review.yaml"
    papers_path = tmp_path / "papers.csv"
    evidence_path = tmp_path / "paper_text.txt"
    write_contract(contract_path)
    evidence_path.write_text(
        (
            "The reviewed primary evidence reports brief screening tests, "
            "computerized cognitive assessment, and longitudinal batteries."
        )
        * 10,
        encoding="utf-8",
    )
    write_csv(
        papers_path,
        [
            {
                "paper_id": "p1",
                "scope_decision": "include",
                "title": "Cognitive assessment in early AD",
                "abstract": "Brief screening and computerized testing.",
                "full_text_text_path": str(evidence_path),
            }
        ],
        [
            "paper_id",
            "scope_decision",
            "title",
            "abstract",
            "full_text_text_path",
        ],
    )
    review_payload = {
        "status": "approved",
        "categories": {
            **{
                category_id: {"values": category["values"]}
                for category_id, category in strict_review_contract()[
                    "tagging"
                ]["categories"].items()
            },
            "cognitive_test_context": {"values": "auto"},
        },
    }
    write_yaml_object(review_path, review_payload)
    client = StaticJSONClient(
        [
            {
                "categories": [
                    {
                        "category_id": "cognitive_test_context",
                        "values": [
                            "brief_screening_test",
                            "computerized_assessment",
                            "longitudinal_battery",
                        ],
                        "reason": "Evidence names these cognitive test contexts.",
                    }
                ]
            }
        ]
    )

    result = run_review_categories(
        contract_path,
        review_path,
        model="fake-model",
        papers_path=papers_path,
        client=client,
    )

    contract = load_topic_contract(contract_path)
    assert contract["tagging"]["categories"]["cognitive_test_context"]["values"] == [
        "brief_screening_test",
        "computerized_assessment",
        "longitudinal_battery",
    ]
    assert result.row_counts["auto_completed_categories"] == 1
    assert client.requests[0]["schema_name"] == "tagging_category_values"
    assert "cognitive_test_context" in client.requests[0]["prompt"]
