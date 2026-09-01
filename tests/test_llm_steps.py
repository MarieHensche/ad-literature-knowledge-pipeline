from __future__ import annotations

import csv
import json
from copy import deepcopy
from pathlib import Path

import pytest

from ad_lit_pipeline.llm.client import StaticJSONClient
from ad_lit_pipeline.llm.schemas import paper_tags_schema
from ad_lit_pipeline.io.jsonl_io import read_jsonl_objects, write_jsonl
from ad_lit_pipeline.io.yaml_io import write_yaml_object
from ad_lit_pipeline.steps.collection.plan_search import (
    enforce_topic_plan_constraints,
    ensure_search_queries,
    run as run_plan_search,
)
from ad_lit_pipeline.steps.collection import fetch_candidates as fetch_candidates_step
from ad_lit_pipeline.steps.collection import verify_full_text_availability
from ad_lit_pipeline.steps.collection.generate_topic_contract import (
    contract_from_model_payload,
    run as run_generate_topic_contract,
)
from ad_lit_pipeline.steps.collection.refine_topic_contract import (
    run as run_refine_topic_contract,
    select_review_overviews_with_full_text,
)
from ad_lit_pipeline.steps.collection.backfill_candidates import (
    run as run_backfill_candidates,
)
from ad_lit_pipeline.steps.screening.llm_candidate_screening import run as run_screening
from ad_lit_pipeline.steps.screening.title_relevance import (
    OUTPUT_COLUMNS as TITLE_RELEVANCE_COLUMNS,
    run as run_title_relevance,
)
from ad_lit_pipeline.steps.tagging.calibrate_topic_contract import (
    run as run_calibrate_topic_contract,
)
from ad_lit_pipeline.steps.tagging.generate_rules import run as run_generate_rules
from ad_lit_pipeline.steps.tagging.tag_papers import (
    paper_text,
    run as run_tag_papers,
    validate_tagged_row,
)
from ad_lit_pipeline.steps.review.config import normalize_review_config
from ad_lit_pipeline.topics.contract import load_topic_contract


ROOT = Path(__file__).resolve().parents[1]
TOPIC_CONTRACT = ROOT / "configs/topics/early_detection_ad.yaml"


def write_csv(path: Path, rows: list[dict[str, str]], fieldnames: list[str]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


class RaisingJSONClient:
    def __init__(self, error: ValueError) -> None:
        self.error = error
        self.requests: list[dict[str, object]] = []

    def create_json(self, **request: object) -> object:
        self.requests.append(request)
        raise self.error


def review_seed_with_full_text(
    tmp_path: Path,
    stem: str = "review",
    body: str | None = None,
    title: str = "Systematic review of early Alzheimer's detection biomarkers",
    abstract: str = "Metadata abstract that must not define tags.",
    query: str = "",
) -> dict[str, object]:
    text_path = tmp_path / f"{stem}_full_text.txt"
    text_path.write_text(
        (
            body
            or (
                "Introduction\nThis review maps early detection evidence.\n\n"
                "Results\nFull text evidence separates speech markers, imaging "
                "biomarkers, fluid assays, and external validation cohorts.\n\n"
                "Conclusion\nReview authors recommend clinically validated "
                "screening and conversion prediction categories.\n\n"
            )
        )
        * 8,
        encoding="utf-8",
    )
    return {
        "provider_id": stem,
        "title": title,
        "abstract": abstract,
        "query": query,
        "full_text_status": "local_text_extracted",
        "full_text_text_path": str(text_path),
        "full_text_chars": str(text_path.stat().st_size),
    }


def generated_topic_contract_payload() -> dict:
    payload = deepcopy(
        load_topic_contract(ROOT / "configs/topics/ai_in_education.yaml")
    )
    payload["topic_id"] = "ai_school_performance"
    payload["research_topic"] = {
        "title": "AI tools and student performance",
        "description": (
            "Research on artificial intelligence tools, learning contexts, and "
            "student performance or engagement outcomes."
        ),
    }
    payload["tagging"]["categories"] = {
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
    return payload


def refined_early_detection_contract_payload() -> dict:
    payload = deepcopy(load_topic_contract(TOPIC_CONTRACT))
    payload["tagging"]["categories"] = {
        "early_detection": {
            "description": (
                "Review evidence distinguishes early-detection tasks studied "
                "in AD and related impairment papers."
            ),
            "required": False,
            "selection": "multi",
            "values": [
                "screening",
                "early_diagnosis",
                "classification",
                "conversion_prediction",
            ],
            "applies_when": None,
        },
        "disease_state": {
            "description": (
                "Disease or impairment states targeted by early-detection "
                "evidence in the reviews."
            ),
            "required": False,
            "selection": "multi",
            "values": [
                "alzheimers_disease",
                "mci",
                "dementia",
                "preclinical_ad",
            ],
            "applies_when": None,
        },
        "evidence_signal": {
            "description": (
                "Evidence signal families used for early AD detection in the "
                "review full text."
            ),
            "required": False,
            "selection": "multi",
            "values": [
                "neuroimaging",
                "speech_language",
                "cognitive_assessment",
                "fluid_biomarker",
            ],
            "applies_when": None,
        },
        "modeling_approach": {
            "description": (
                "Analytic modeling approaches used for early detection."
            ),
            "required": False,
            "selection": "multi",
            "values": [
                "machine_learning",
                "deep_learning",
                "statistical_modeling",
                "clinical_rule",
            ],
            "applies_when": None,
        },
        "validation_context": {
            "description": (
                "Validation settings reported for detection evidence."
            ),
            "required": False,
            "selection": "multi",
            "values": [
                "internal_validation",
                "external_validation",
                "cross_validation",
                "clinical_validation",
            ],
            "applies_when": None,
        },
        "clinical_detection_context": {
            "description": (
                "Review evidence distinguishes screening, diagnosis, and "
                "risk-stratification contexts."
            ),
            "required": False,
            "selection": "multi",
            "values": [
                "population_screening",
                "clinical_diagnosis",
                "risk_stratification",
                "disease_monitoring",
            ],
            "applies_when": None,
        },
    }
    return payload


def test_generated_contract_payload_normalizes_tag_labels() -> None:
    payload = generated_topic_contract_payload()
    payload["tagging"]["categories"] = [
        {
            "category_id": "Green Space Type",
            "description": "Green-space forms studied in the paper.",
            "required": False,
            "selection": "multi",
            "values": ["community gardens", "natural reserves", "green-roofs"],
            "applies_when": None,
        },
        {
            "category_id": "Green Space Detail",
            "description": "Details for natural reserve papers.",
            "required": False,
            "selection": "multi",
            "values": ["trail access", "tree canopy"],
            "applies_when": {
                "category_id": "Green Space Type",
                "values": ["natural reserves"],
            },
        },
    ]

    contract = contract_from_model_payload(payload)
    categories = contract["tagging"]["categories"]

    assert list(categories) == [
        "green_space_type",
        "green_space_detail",
    ]
    assert categories["green_space_type"]["values"] == [
        "community_gardens",
        "natural_reserves",
        "green_roofs",
    ]
    assert categories["green_space_detail"]["applies_when"] == {
        "category_id": "green_space_type",
        "values": ["natural_reserves"],
    }


def test_plan_search_uses_enabled_providers_and_trace(tmp_path: Path) -> None:
    output = tmp_path / "plan.json"
    topic_contract = load_topic_contract(TOPIC_CONTRACT)
    topic_contract["candidate_screening"]["missing_abstract_policy"] = "include"
    topic_contract_path = tmp_path / "topic_contract.yaml"
    write_yaml_object(topic_contract_path, topic_contract)
    client = StaticJSONClient(
        [
            {
                "topic_description": "early detection",
                "recommended_provider": "openalex",
                "provider_reason": "Supported provider.",
                "search_goal": "Find papers.",
                "main_search_string": "early detection Alzheimer's",
                "alternate_search_strings": ["MCI screening"],
                "search_queries": [
                    {
                        "query": "early detection Alzheimer's",
                        "reason": "Primary topic phrasing.",
                    }
                ],
                "filters": {
                    "year_from": None,
                    "year_to": None,
                    "publication_types": [],
                    "open_access_only": None,
                    "has_abstract": None,
                    "has_full_text": None,
                    "language": None,
                    "venue_or_source": [],
                    "field_or_domain": [],
                },
                "provider_specific_plan": {
                    "provider": "openalex",
                    "query": "early detection Alzheimer's",
                    "filters": [],
                    "sort": None,
                    "max_results_recommendation": 5,
                },
                "screening_notes": "Screen later.",
                "risks_or_ambiguities": [],
            }
        ]
    )

    result = run_plan_search(
        "early detection",
        output,
        5,
        "test-model",
        topic_contract_path,
        client,
        tmp_path / "traces",
    )

    payload = json.loads(output.read_text(encoding="utf-8"))
    assert result.metadata["recommended_provider"] == "openalex"
    assert payload["recommended_provider"] == "openalex"
    assert payload["filters"]["has_abstract"] is None
    assert payload["filters"]["exclude_reviews"] is True
    assert payload["topic_match_spec"]["anchor_topic_id"] == "early_detection"
    assert payload["topic_match_spec"]["main_topics"][0]["field"] == "title"
    assert payload["retrieval_strategy"]["mode"] == "tiered_topic_blocks"
    assert payload["query_groups"][0]["tier"] == 0
    assert payload["query_groups"][0]["queries"][0]["requires_title_screening"] is False
    assert payload["search_queries"] == [
        {
            "query": "early detection Alzheimer's",
            "reason": "Primary topic phrasing.",
        },
        {"query": "MCI screening", "reason": "Alternate planned search string."},
    ]
    assert payload["provider_specific_plan"]["filters"] == [
        {
            "name": "type",
            "value": "!review",
            "reason": (
                "The topic contract excludes review/background papers, "
                "so OpenAlex review works are filtered before screening."
            ),
        },
    ]
    assert result.warnings == [
        "Added alternate_search_strings to search_queries.",
        "Set filters.exclude_reviews=true because topic contract excludes OpenAlex review works.",
        "Added provider_specific_plan type:!review filter for review exclusion policy.",
        "Added tiered topic-block query groups from topic contract.",
    ]
    assert client.requests[0]["schema"]["properties"]["recommended_provider"]["enum"] == [
        "openalex"
    ]
    assert "semantic_scholar" not in client.requests[0]["prompt"]
    assert result.trace_paths


def test_plan_search_adds_contract_seed_queries() -> None:
    contract = load_topic_contract(TOPIC_CONTRACT)
    contract["collection"]["search_queries"] = [
        {
            "query": "MCI conversion prediction",
            "reason": "Contract seed query.",
        }
    ]
    plan = {
        "recommended_provider": "openalex",
        "main_search_string": "early detection",
        "alternate_search_strings": [],
        "provider_specific_plan": {
            "provider": "openalex",
            "query": "early detection Alzheimer's",
            "filters": [],
            "sort": None,
            "max_results_recommendation": 5,
        },
    }

    warnings = ensure_search_queries(plan, contract)

    assert plan["search_queries"] == [
        {
            "query": "early detection Alzheimer's",
            "reason": "Provider-specific primary query.",
        },
        {
            "query": "early detection",
            "reason": "Main planned search string.",
        },
        {
            "query": "MCI conversion prediction",
            "reason": "Contract seed query.",
        },
    ]
    assert warnings == [
        "Added provider_specific_plan.query to search_queries.",
        "Added main_search_string to search_queries.",
        "Added topic-contract search query to search_queries.",
    ]


def test_generate_topic_contract_uses_fake_client_and_validates(
    tmp_path: Path,
) -> None:
    output = tmp_path / "contract.yaml"
    client = StaticJSONClient(
        [
            {
                "topic_id": "climate_health",
                "research_topic": {
                    "title": "Climate change and human health",
                    "description": (
                        "Research on relationships between climate change, "
                        "exposure, adaptation, and human health outcomes."
                    ),
                },
                "topic_structure": {
                    "anchor_topic_id": "climate_change",
                    "anchor_reason": (
                        "Climate change is the non-replaceable exposure focus."
                    ),
                    "main_topics": [
                        {
                            "topic_id": "climate_change",
                            "label": "Climate change",
                            "terms": [
                                "climate change",
                                "global warming",
                                "climate-related exposure",
                            ],
                        },
                        {
                            "topic_id": "human_health",
                            "label": "Human health",
                            "terms": [
                                "human health",
                                "health outcomes",
                                "mortality",
                                "morbidity",
                            ],
                        },
                        {
                            "topic_id": "adaptation_strategy",
                            "label": "Adaptation strategy",
                            "terms": [
                                "adaptation",
                                "public health adaptation",
                                "heat action plan",
                                "preparedness",
                            ],
                        },
                    ],
                        "secondary_topics": {
                            "climate_change": [
                                "weather",
                                "environmental change",
                            ],
                            "human_health": [
                                "well-being",
                                "public health adaptation",
                            ],
                            "adaptation_strategy": [
                                "resilience planning",
                                "preparedness policy",
                            ],
                        },
                    },
                "scope": {
                    "include_criteria": [
                        "Studies directly examining climate-related health outcomes",
                        "Studies on climate adaptation and health impacts",
                        "Reviews that map climate-health evidence",
                    ],
                    "exclude_criteria": [
                        "Papers with no climate or health connection",
                    ],
                    "boundary_rules": [
                        "Include adjacent exposure or adaptation papers for review.",
                    ],
                },
                "rule_based_screening": {
                    "include_terms": [
                        "climate change",
                        "human health",
                        "heat exposure",
                    ],
                    "exclude_terms": ["unrelated engineering"],
                    "exclude_wins": False,
                },
                "candidate_screening": {
                    "missing_abstract_policy": (
                        "include if title or metadata is plausibly relevant"
                    ),
                    "borderline_policy": "include",
                    "human_review_policy": "include",
                    "review_policy": "include reviews unless primary-only",
                    "tangential_topic_policy": (
                        "include candidates addressing one meaningful aspect"
                    ),
                },
                "tagging": {
                    "fallback_policy": {
                        "prefer_unclear_when_allowed": True,
                        "prefer_mixed_or_unclear_when_unclear_missing": True,
                        "missing_information_value": "not_reported",
                    },
                    "categories": [
                        {
                            "category_id": "climate_change",
                            "description": "Climate-related exposures examined in the paper.",
                            "required": False,
                            "selection": "multi",
                            "values": [
                                "heat",
                                "wildfire_smoke",
                                "flooding",
                                "extreme_weather",
                            ],
                            "applies_when": None,
                        },
                        {
                            "category_id": "human_health",
                            "description": "Health outcomes studied in climate-health papers.",
                            "required": False,
                            "selection": "multi",
                            "values": [
                                "mortality",
                                "morbidity",
                                "mental_health",
                                "healthcare_use",
                            ],
                            "applies_when": None,
                        },
                        {
                            "category_id": "adaptation_strategy",
                            "description": "Adaptation or response strategies discussed.",
                            "required": False,
                            "selection": "multi",
                            "values": [
                                "heat_action_plan",
                                "wildfire_preparedness",
                                "health_system_adaptation",
                                "community_resilience_program",
                            ],
                            "applies_when": None,
                        },
                        {
                            "category_id": "climate_health_evidence_type",
                            "description": (
                                "Review evidence distinguishes empirical, modeling, "
                                "and synthesis evidence for climate-health claims."
                            ),
                            "required": False,
                            "selection": "multi",
                            "values": [
                                "observed_association",
                                "projection_model",
                                "evidence_review",
                                "policy_evaluation",
                            ],
                            "applies_when": None,
                        },
                        {
                            "category_id": "exposure_measurement",
                            "description": (
                                "Review evidence separates direct climate exposure "
                                "measures from modeled or proxy exposure measures."
                            ),
                            "required": False,
                            "selection": "multi",
                            "values": [
                                "weather_station_measure",
                                "remote_sensing_measure",
                                "modeled_exposure",
                                "administrative_proxy",
                            ],
                            "applies_when": None,
                        },
                        {
                            "category_id": "heat_adaptation_detail",
                            "description": "Details used only when heat adaptation is tagged.",
                            "required": False,
                            "selection": "multi",
                            "values": [
                                "cooling_center",
                                "early_warning",
                                "urban_greening",
                            ],
                            "applies_when": {
                                "category_id": "adaptation_strategy",
                                "values": ["heat_action_plan"],
                            },
                        },
                    ],
                },
                "collection": {
                    "allowed_providers": ["openalex"],
                    "preferred_provider": "openalex",
                    "max_results_default": 50,
                    "exclude_openalex_review_type": False,
                    "search_queries": [
                        {
                            "query": "climate change human health",
                            "reason": "Core phrasing.",
                        },
                        {
                            "query": "heat exposure mortality morbidity",
                            "reason": "Exposure and outcome phrasing.",
                        },
                        {
                            "query": "climate adaptation health outcomes",
                            "reason": "Adaptation phrasing.",
                        },
                    ],
                },
            }
        ]
    )

    result = run_generate_topic_contract(
        "How does climate change affect human health?",
        output,
        "test-model",
        client=client,
        trace_dir=tmp_path / "traces",
    )

    contract = load_topic_contract(output)
    assert contract["topic_id"] == "climate_health"
    assert "main_topic_category" not in contract["tagging"]["categories"]
    assert "review_status" not in contract["tagging"]["categories"]
    assert contract["tagging"]["categories"]["human_health"]["selection"] == "multi"
    assert contract["tagging"]["categories"]["heat_adaptation_detail"][
        "applies_when"
    ] == {"category_id": "adaptation_strategy", "values": ["heat_action_plan"]}
    assert contract["candidate_screening"]["borderline_policy"] == "include"
    assert "climate_change" in contract["topic_structure"]["secondary_topics"]
    assert contract["topic_policy"]["policy_id"] == "topic_structure"
    assert contract["topic_policy"]["policy_version"] == "1.0.0"
    assert len(contract["topic_policy"]["policy_sha256"]) == 64
    assert contract["topic_policy"]["profile_ids"] == []
    assert result.metadata["topic_policy"] == contract["topic_policy"]
    assert result.row_counts["search_queries"] == 3
    assert result.trace_paths


def test_generate_topic_contract_accepts_weak_provisional_tagging(
    tmp_path: Path,
) -> None:
    weak_payload = generated_topic_contract_payload()
    weak_payload["tagging"]["categories"]["intervention_type"] = {
        "required": False,
        "selection": "multi",
        "values": ["self-help_resources", "therapist_guided"],
    }
    weak_payload["tagging"]["categories"]["target_population"] = {
        "required": False,
        "selection": "multi",
        "values": ["postpartum_mothers", "pregnant_people"],
    }
    weak_payload["tagging"]["categories"]["study_design"] = {
        "required": False,
        "selection": "multi",
        "values": ["cross_sectional", "longitudinal", "experimental"],
    }
    client = StaticJSONClient([weak_payload])
    output = tmp_path / "contract.yaml"

    result = run_generate_topic_contract(
        "How do AI tools affect student performance?",
        output,
        "test-model",
        client=client,
        trace_dir=tmp_path / "traces",
    )

    contract = load_topic_contract(output)
    categories = contract["tagging"]["categories"]
    assert len(client.requests) == 1
    assert client.requests[0]["call_id"] == "contract"
    assert client.requests[0]["schema"]["properties"]["tagging"]["properties"][
        "categories"
    ]["minItems"] == 1
    main_topic_schema = client.requests[0]["schema"]["properties"][
        "topic_structure"
    ]["properties"]["main_topics"]["items"]
    assert "field" in main_topic_schema["required"]
    assert "retrieval_terms" in main_topic_schema["required"]
    assert "matching_terms" in main_topic_schema["required"]
    assert main_topic_schema["properties"]["retrieval_terms"]["maxItems"] == 12
    secondary_topic_schema = client.requests[0]["schema"]["properties"][
        "topic_structure"
    ]["properties"]["secondary_topics"]["items"]
    assert "secondary_topic_id" in secondary_topic_schema["required"]
    assert "retrieval_terms" in secondary_topic_schema["required"]
    assert "matching_terms" in secondary_topic_schema["required"]
    assert secondary_topic_schema["properties"]["retrieval_terms"]["maxItems"] == 12
    assert "target_population" in categories
    assert "study_design" in categories
    assert result.row_counts["tagging_categories"] == 9


def test_generate_topic_contract_still_retries_on_structural_errors(
    tmp_path: Path,
) -> None:
    invalid_payload = generated_topic_contract_payload()
    invalid_payload["topic_structure"]["anchor_topic_id"] = "missing_topic"
    client = StaticJSONClient([invalid_payload, generated_topic_contract_payload()])
    output = tmp_path / "contract.yaml"

    result = run_generate_topic_contract(
        "How do AI tools affect student performance?",
        output,
        "test-model",
        client=client,
        trace_dir=tmp_path / "traces",
    )

    assert result.row_counts["tagging_categories"] == 6
    assert len(client.requests) == 2
    assert client.requests[0]["call_id"] == "contract"
    assert client.requests[1]["call_id"] == "contract_retry_2"
    assert "previous JSON response failed validation" in client.requests[1]["prompt"]
    assert "topic_structure.anchor_topic_id" in client.requests[1]["prompt"]


def test_generate_topic_contract_retries_on_merged_topic_structure(
    tmp_path: Path,
) -> None:
    invalid_payload = generated_topic_contract_payload()
    invalid_payload["topic_structure"]["main_topics"][0]["topic_id"] = "ai_in_school"
    invalid_payload["topic_structure"]["anchor_topic_id"] = "ai_in_school"
    client = StaticJSONClient([invalid_payload, generated_topic_contract_payload()])
    output = tmp_path / "contract.yaml"

    result = run_generate_topic_contract(
        "Use of AI in school lessons and student performance",
        output,
        "test-model",
        client=client,
        trace_dir=tmp_path / "traces",
    )

    contract = load_topic_contract(output)
    assert contract["topic_structure"]["anchor_topic_id"] == "ai"
    assert result.row_counts["tagging_categories"] == 6
    assert len(client.requests) == 2
    assert client.requests[1]["call_id"] == "contract_retry_2"
    assert "one concept area per main topic" in client.requests[1]["prompt"]
    assert "ai_in_school" in client.requests[1]["prompt"]


def test_contract_payload_removes_duplicate_secondary_parent_terms() -> None:
    payload = generated_topic_contract_payload()
    payload["topic_structure"]["secondary_topics"]["learning_impact"].append(
        {
            "secondary_topic_id": "student_outcomes",
            "label": "Student outcomes",
            "field": "title_or_abstract",
            "terms": ["learning outcomes", "dropout", "retention"],
            "retrieval_terms": ["learning outcomes", "dropout"],
            "matching_terms": ["learning outcomes", "dropout", "retention"],
        }
    )

    contract = contract_from_model_payload(payload)
    groups = contract["topic_structure"]["secondary_topics"]["learning_impact"]
    student_outcomes = [
        group
        for group in groups
        if group["secondary_topic_id"] == "student_outcomes"
    ][0]

    assert student_outcomes["terms"] == ["dropout", "retention"]
    assert student_outcomes["retrieval_terms"] == ["dropout"]
    assert student_outcomes["matching_terms"] == ["dropout", "retention"]


def test_contract_payload_cleans_method_terms_and_subtype_secondaries() -> None:
    payload = generated_topic_contract_payload()
    payload["topic_structure"]["main_topics"][1] = {
        "topic_id": "computational_methods",
        "label": "Computational methods",
        "field": "title",
        "terms": ["computational biology", "data analysis", "machine learning"],
        "retrieval_terms": ["computational biology", "data analysis"],
        "matching_terms": ["computational biology", "machine learning"],
    }
    payload["topic_structure"]["secondary_topics"] = {
        "computational_methods": [
            {
                "secondary_topic_id": "ai_in_biology",
                "label": "AI in biology",
                "field": "title",
                "terms": ["artificial intelligence", "deep learning"],
                "retrieval_terms": ["artificial intelligence"],
                "matching_terms": ["artificial intelligence", "deep learning"],
            }
        ],
        "learning_impact": payload["topic_structure"]["secondary_topics"][
            "learning_impact"
        ],
    }

    contract = contract_from_model_payload(payload)
    methods = {
        topic["topic_id"]: topic
        for topic in contract["topic_structure"]["main_topics"]
    }["computational_methods"]

    assert "data analysis" not in methods["terms"]
    assert "data analysis" not in methods["retrieval_terms"]
    assert "ML" in methods["terms"]
    assert "artificial intelligence" in methods["terms"]
    assert "deep learning" in methods["terms"]
    assert "supervised learning" in methods["terms"]
    assert "unsupervised learning" in methods["terms"]
    computational_secondaries = contract["topic_structure"]["secondary_topics"][
        "computational_methods"
    ]
    assert computational_secondaries[0]["secondary_topic_id"] == "experimental_methods"
    assert "experimental methods" in computational_secondaries[0]["terms"]


def test_contract_payload_moves_disease_variants_to_parent_terms() -> None:
    payload = generated_topic_contract_payload()
    payload["topic_structure"]["anchor_topic_id"] = "alzheimers_disease"
    payload["topic_structure"]["main_topics"] = [
        {
            "topic_id": "alzheimers_disease",
            "label": "Alzheimer's disease",
            "field": "title",
            "terms": ["Alzheimer's disease", "AD"],
            "retrieval_terms": ["Alzheimer's disease", "AD"],
            "matching_terms": ["Alzheimer's disease", "AD"],
        },
        payload["topic_structure"]["main_topics"][1],
    ]
    payload["topic_structure"]["secondary_topics"] = {
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
                "secondary_topic_id": "other_diseases",
                "label": "Other diseases",
                "field": "title",
                "terms": ["Parkinson's disease", "cancer", "dementia"],
                "retrieval_terms": ["Parkinson's disease", "cancer", "dementia"],
                "matching_terms": ["Parkinson's disease", "cancer", "dementia"],
            },
        ],
        "formal_education": payload["topic_structure"]["secondary_topics"][
            "formal_education"
        ],
    }

    contract = contract_from_model_payload(payload)
    topics = {
        topic["topic_id"]: topic
        for topic in contract["topic_structure"]["main_topics"]
    }
    alzheimers = topics["alzheimers_disease"]
    alzheimer_terms = {
        term.casefold()
        for term in (
            alzheimers["terms"]
            + alzheimers["retrieval_terms"]
            + alzheimers["matching_terms"]
        )
    }

    assert "MCI".casefold() in alzheimer_terms
    assert "mild cognitive impairment" in alzheimer_terms
    assert "dementia" in alzheimer_terms
    disease_secondaries = contract["topic_structure"]["secondary_topics"][
        "alzheimers_disease"
    ]
    assert [group["secondary_topic_id"] for group in disease_secondaries] == [
        "parkinsons_disease",
        "cancer",
    ]
    assert disease_secondaries[0]["terms"] == [
        "Parkinson's disease",
        "Parkinson disease",
        "PD",
    ]
    assert disease_secondaries[0]["retrieval_terms"] == [
        "Parkinson's disease",
        "Parkinson disease",
    ]
    assert disease_secondaries[1]["terms"] == ["cancer", "neoplasm", "tumor"]


def test_contract_payload_cleans_disease_method_topic_structure() -> None:
    payload = generated_topic_contract_payload()
    payload["topic_structure"]["anchor_topic_id"] = "computational_methods"
    payload["topic_structure"]["main_topics"] = [
        {
            "topic_id": "computational_methods",
            "label": "Computational Methods",
            "field": "title",
            "terms": ["computational biology", "machine learning"],
            "retrieval_terms": ["computational biology", "machine learning"],
            "matching_terms": ["computational methods", "data analysis"],
        },
        {
            "topic_id": "alzheimers_disease",
            "label": "Alzheimer's Disease",
            "field": "title",
            "terms": [
                "Alzheimer's disease",
                "AD",
                "tau pathology",
                "amyloid plaques",
                "neurodegeneration",
            ],
            "retrieval_terms": ["Alzheimer's disease", "AD"],
            "matching_terms": ["Alzheimer's", "memory loss", "tau pathology"],
        },
    ]
    payload["topic_structure"]["secondary_topics"] = {
        "computational_methods": [
            {
                "secondary_topic_id": "experimental_methods",
                "label": "Experimental Methods",
                "field": "title",
                "terms": [
                    "laboratory techniques",
                    "experimental designs",
                    "clinical trials",
                    "data collection",
                ],
                "retrieval_terms": ["experimental methods", "clinical trials"],
                "matching_terms": ["laboratory methods", "experimental techniques"],
            }
        ],
        "alzheimers_disease": [
            {
                "secondary_topic_id": "parkinsons_disease",
                "label": "Parkinson's Disease",
                "field": "title",
                "terms": ["Parkinson's disease", "PD", "movement disorders"],
                "retrieval_terms": ["Parkinson's disease", "PD"],
                "matching_terms": ["Parkinson's", "movement disorders"],
            }
        ],
    }

    contract = contract_from_model_payload(payload)
    topic_structure = contract["topic_structure"]
    topics = {topic["topic_id"]: topic for topic in topic_structure["main_topics"]}

    assert topic_structure["anchor_topic_id"] == "alzheimers_disease"
    alzheimers = topics["alzheimers_disease"]
    alzheimer_terms = [
        *(alzheimers["terms"]),
        *(alzheimers["retrieval_terms"]),
        *(alzheimers["matching_terms"]),
    ]
    assert "tau pathology" not in alzheimer_terms
    assert "amyloid plaques" not in alzheimer_terms
    assert "neurodegeneration" not in alzheimer_terms
    assert "memory loss" not in alzheimer_terms
    assert "mild cognitive impairment" in alzheimers["terms"]
    assert "MCI" in alzheimers["terms"]

    experimental = topic_structure["secondary_topics"]["computational_methods"][0]
    assert experimental["secondary_topic_id"] == "experimental_methods"
    assert experimental["terms"] == [
        "experimental methods",
        "laboratory methods",
        "clinical methods",
    ]
    parkinsons = topic_structure["secondary_topics"]["alzheimers_disease"][0]
    assert parkinsons["terms"] == [
        "Parkinson's disease",
        "Parkinson disease",
        "PD",
    ]
    assert "movement disorders" not in parkinsons["matching_terms"]


def test_generate_topic_contract_repairs_duplicate_secondary_topic(
    tmp_path: Path,
) -> None:
    invalid_payload = generated_topic_contract_payload()
    invalid_payload["topic_structure"]["secondary_topics"]["formal_education"].append(
        {
            "secondary_topic_id": "school",
            "label": "School",
            "field": "title",
            "terms": ["school"],
            "retrieval_terms": ["school"],
            "matching_terms": ["school"],
        }
    )
    repair_topic_structure = deepcopy(invalid_payload["topic_structure"])
    repair_topic_structure["secondary_topics"]["formal_education"] = (
        repair_topic_structure["secondary_topics"]["formal_education"][:-1]
    )
    client = StaticJSONClient(
        [
            invalid_payload,
            deepcopy(invalid_payload),
            deepcopy(invalid_payload),
            repair_topic_structure,
        ]
    )
    output = tmp_path / "contract.yaml"

    result = run_generate_topic_contract(
        "Use of AI in school lessons and student performance",
        output,
        "test-model",
        client=client,
        trace_dir=tmp_path / "traces",
    )

    contract = load_topic_contract(output)
    assert result.row_counts["tagging_categories"] == 6
    assert [request["call_id"] for request in client.requests] == [
        "contract",
        "contract_retry_2",
        "contract_retry_3",
        "contract_retry_3_topic_structure_repair",
    ]
    assert all(
        group["secondary_topic_id"] != "school"
        for group in contract["topic_structure"]["secondary_topics"][
            "formal_education"
        ]
    )
    assert any(
        path.name.endswith("topic_structure_repair_parsed.json")
        for path in result.trace_paths
    )


def test_generate_topic_contract_warns_when_topic_structure_repair_still_weak(
    tmp_path: Path,
) -> None:
    invalid_payload = generated_topic_contract_payload()
    invalid_payload["topic_structure"]["main_topics"][0]["topic_id"] = "ai_in_school"
    invalid_payload["topic_structure"]["anchor_topic_id"] = "ai_in_school"
    repair_topic_structure = deepcopy(invalid_payload["topic_structure"])
    client = StaticJSONClient(
        [
            invalid_payload,
            deepcopy(invalid_payload),
            deepcopy(invalid_payload),
            repair_topic_structure,
        ]
    )
    output = tmp_path / "contract.yaml"

    result = run_generate_topic_contract(
        "Use of AI in school lessons and student performance",
        output,
        "test-model",
        client=client,
        trace_dir=tmp_path / "traces",
    )

    contract = load_topic_contract(output)
    assert output.exists()
    assert contract["topic_structure"]["anchor_topic_id"] == "ai_in_school"
    assert len(client.requests) == 4
    assert result.warnings
    assert "Contract review recommended" in result.warnings[0]
    assert "topic_structure" in result.warnings[0]
    assert "ai_in_school" in result.warnings[0]


def test_generate_topic_contract_repairs_explicit_pair_umbrella_topic(
    tmp_path: Path,
) -> None:
    invalid_payload = generated_topic_contract_payload()
    invalid_payload["topic_id"] = "traffic_noise_attention_memory"
    invalid_payload["research_topic"] = {
        "title": "Traffic noise effects on attention and memory",
        "description": "Research on chronic traffic noise, attention, and memory.",
    }
    invalid_payload["topic_structure"] = {
        "anchor_topic_id": "traffic_noise",
        "anchor_reason": "Traffic noise is the non-replaceable exposure.",
        "main_topics": [
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
        ],
        "secondary_topics": {
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
        },
    }
    repair_topic_structure = {
        "anchor_topic_id": "traffic_noise",
        "anchor_reason": "Traffic noise is the non-replaceable exposure.",
        "main_topics": [
            {
                "topic_id": "traffic_noise",
                "label": "Traffic noise",
                "field": "title",
                "terms": ["traffic noise", "road traffic noise"],
                "retrieval_terms": ["traffic noise", "road traffic noise"],
                "matching_terms": ["traffic noise", "road noise"],
            },
            {
                "topic_id": "attention",
                "label": "Attention",
                "field": "title_or_abstract",
                "terms": ["attention", "sustained attention"],
                "retrieval_terms": ["attention", "sustained attention"],
                "matching_terms": ["attention", "attention span"],
            },
            {
                "topic_id": "memory",
                "label": "Memory",
                "field": "title_or_abstract",
                "terms": ["memory", "working memory"],
                "retrieval_terms": ["memory", "working memory"],
                "matching_terms": ["memory", "memory recall", "working memory"],
            },
        ],
        "secondary_topics": [
            {
                "main_topic_id": "traffic_noise",
                "secondary_topic_id": "environmental_noise",
                "label": "Environmental noise",
                "field": "title",
                "terms": ["environmental noise", "aircraft noise"],
                "retrieval_terms": ["environmental noise", "aircraft noise"],
                "matching_terms": ["environmental noise", "aircraft noise"],
            },
            {
                "main_topic_id": "attention",
                "secondary_topic_id": "executive_function",
                "label": "Executive function",
                "field": "title_or_abstract",
                "terms": ["executive function", "cognitive control"],
                "retrieval_terms": ["executive function"],
                "matching_terms": ["executive function", "cognitive control"],
            },
            {
                "main_topic_id": "memory",
                "secondary_topic_id": "learning_recall",
                "label": "Learning and recall",
                "field": "title_or_abstract",
                "terms": ["recall", "learning", "recognition memory"],
                "retrieval_terms": ["recall", "recognition memory"],
                "matching_terms": ["recall", "learning", "recognition memory"],
            },
        ],
    }
    client = StaticJSONClient(
        [
            invalid_payload,
            deepcopy(invalid_payload),
            deepcopy(invalid_payload),
            repair_topic_structure,
        ]
    )
    output = tmp_path / "contract.yaml"

    run_generate_topic_contract(
        "Impact of chronic traffic noise on attention and memory",
        output,
        "test-model",
        client=client,
        trace_dir=tmp_path / "traces",
    )

    contract = load_topic_contract(output)
    topic_ids = [
        topic["topic_id"] for topic in contract["topic_structure"]["main_topics"]
    ]
    assert "attention" in topic_ids
    assert "memory" in topic_ids
    assert "cognitive_effects" not in topic_ids
    assert client.requests[-1]["call_id"] == "contract_retry_3_topic_structure_repair"


def test_generate_topic_contract_repairs_criterion_topic_to_comparator(
    tmp_path: Path,
) -> None:
    invalid_payload = generated_topic_contract_payload()
    invalid_payload["topic_id"] = "fungi_sustainable_materials"
    invalid_payload["research_topic"] = {
        "title": "Fungi as sustainable building materials",
        "description": (
            "Research on fungal materials that could replace concrete in "
            "building applications."
        ),
    }
    invalid_payload["topic_structure"] = {
        "anchor_topic_id": "fungi",
        "anchor_reason": "Fungi are the non-replaceable biological source.",
        "main_topics": [
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
        ],
        "secondary_topics": {
            "building_materials": [
                {
                    "secondary_topic_id": "construction_products",
                    "label": "Construction products",
                    "field": "title_or_abstract",
                    "terms": ["construction products", "building products"],
                    "retrieval_terms": ["construction products"],
                    "matching_terms": [
                        "construction products",
                        "building products",
                    ],
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
        },
    }
    repair_topic_structure = {
        "anchor_topic_id": "fungi",
        "anchor_reason": "Fungi are the non-replaceable biological source.",
        "main_topics": [
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
                "topic_id": "concrete_replacement",
                "label": "Concrete replacement",
                "field": "title_or_abstract",
                "terms": ["concrete replacement", "concrete alternative"],
                "retrieval_terms": ["concrete replacement", "concrete alternative"],
                "matching_terms": [
                    "concrete replacement",
                    "concrete alternative",
                    "cement substitute",
                ],
            },
        ],
        "secondary_topics": [
            {
                "main_topic_id": "fungi",
                "secondary_topic_id": "plant_based_materials",
                "label": "Plant-based materials",
                "field": "title_or_abstract",
                "terms": ["plant-based materials", "cellulose materials"],
                "retrieval_terms": ["plant-based materials", "cellulose materials"],
                "matching_terms": ["plant-based materials", "cellulose materials"],
            },
            {
                "main_topic_id": "building_materials",
                "secondary_topic_id": "construction_products",
                "label": "Construction products",
                "field": "title_or_abstract",
                "terms": ["construction products", "building products"],
                "retrieval_terms": ["construction products"],
                "matching_terms": ["construction products", "building products"],
            },
            {
                "main_topic_id": "concrete_replacement",
                "secondary_topic_id": "cement_substitution",
                "label": "Cement substitution",
                "field": "title_or_abstract",
                "terms": ["cement substitute", "cement replacement"],
                "retrieval_terms": ["cement substitute", "cement replacement"],
                "matching_terms": ["cement substitute", "cement replacement"],
            },
        ],
    }
    client = StaticJSONClient(
        [
            invalid_payload,
            deepcopy(invalid_payload),
            deepcopy(invalid_payload),
            repair_topic_structure,
        ]
    )
    output = tmp_path / "contract.yaml"

    run_generate_topic_contract(
        "Could fungi be used to create sustainable building materials that "
        "replace concrete in certain applications?",
        output,
        "test-model",
        client=client,
        trace_dir=tmp_path / "traces",
    )

    contract = load_topic_contract(output)
    topic_ids = [
        topic["topic_id"] for topic in contract["topic_structure"]["main_topics"]
    ]
    assert "concrete_replacement" in topic_ids
    assert "sustainability" not in topic_ids
    assert client.requests[-1]["call_id"] == "contract_retry_3_topic_structure_repair"


def test_generate_topic_contract_repairs_buried_replacement_target(
    tmp_path: Path,
) -> None:
    invalid_payload = generated_topic_contract_payload()
    invalid_payload["topic_id"] = "fungi_sustainable_building_materials"
    invalid_payload["research_topic"] = {
        "title": "Fungi as sustainable building materials",
        "description": (
            "Research on fungal materials that could replace concrete in "
            "building applications."
        ),
    }
    invalid_payload["topic_structure"] = {
        "anchor_topic_id": "fungi",
        "anchor_reason": "Fungi are the non-replaceable biological source.",
        "main_topics": [
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
                "matching_terms": ["building materials", "concrete"],
            },
        ],
        "secondary_topics": {
            "building_materials": [
                {
                    "secondary_topic_id": "construction_products",
                    "label": "Construction products",
                    "field": "title_or_abstract",
                    "terms": ["construction products", "building products"],
                    "retrieval_terms": ["construction products"],
                    "matching_terms": [
                        "construction products",
                        "building products",
                    ],
                }
            ],
        },
    }
    repair_topic_structure = deepcopy(invalid_payload["topic_structure"])
    repair_topic_structure["main_topics"].append(
        {
            "topic_id": "concrete_replacement",
            "label": "Concrete replacement",
            "field": "title_or_abstract",
            "terms": ["concrete replacement", "concrete alternative"],
            "retrieval_terms": ["concrete replacement", "concrete alternative"],
            "matching_terms": ["concrete replacement", "cement substitute"],
        }
    )
    repair_topic_structure["main_topics"][1]["terms"] = [
        "building materials",
        "construction materials",
        "structural materials",
        "insulation materials",
    ]
    repair_topic_structure["main_topics"][1]["retrieval_terms"] = [
        "building materials",
        "construction materials",
    ]
    repair_topic_structure["main_topics"][1]["matching_terms"] = [
        "structural materials",
        "insulation materials",
    ]
    repair_topic_structure["secondary_topics"] = [
        {
            "main_topic_id": "fungi",
            "secondary_topic_id": "plant_based_materials",
            "label": "Plant-based materials",
            "field": "title_or_abstract",
            "terms": ["plant-based materials", "cellulose materials"],
            "retrieval_terms": ["plant-based materials", "cellulose materials"],
            "matching_terms": ["plant-based materials", "cellulose materials"],
        },
        {
            "main_topic_id": "building_materials",
            "secondary_topic_id": "construction_products",
            "label": "Construction products",
            "field": "title_or_abstract",
            "terms": ["construction products", "building products"],
            "retrieval_terms": ["construction products"],
            "matching_terms": ["construction products", "building products"],
        },
        {
            "main_topic_id": "concrete_replacement",
            "secondary_topic_id": "cement_substitution",
            "label": "Cement substitution",
            "field": "title_or_abstract",
            "terms": ["cement substitute", "cement replacement"],
            "retrieval_terms": ["cement substitute", "cement replacement"],
            "matching_terms": ["cement substitute", "cement replacement"],
        },
    ]
    client = StaticJSONClient(
        [
            invalid_payload,
            deepcopy(invalid_payload),
            deepcopy(invalid_payload),
            repair_topic_structure,
        ]
    )
    output = tmp_path / "contract.yaml"

    run_generate_topic_contract(
        "Could fungi be used to create sustainable building materials that "
        "replace concrete in certain applications?",
        output,
        "test-model",
        client=client,
        trace_dir=tmp_path / "traces",
    )

    contract = load_topic_contract(output)
    topic_ids = [
        topic["topic_id"] for topic in contract["topic_structure"]["main_topics"]
    ]
    assert "concrete_replacement" in topic_ids
    assert client.requests[-1]["call_id"] == "contract_retry_3_topic_structure_repair"


def test_generate_topic_contract_repairs_missing_replacement_application(
    tmp_path: Path,
) -> None:
    invalid_payload = generated_topic_contract_payload()
    invalid_payload["topic_id"] = "fungi_sustainable_building_materials"
    invalid_payload["research_topic"] = {
        "title": "Fungi as sustainable building materials",
        "description": (
            "Research on fungal materials that could replace concrete in "
            "building applications."
        ),
    }
    invalid_payload["topic_structure"] = {
        "anchor_topic_id": "fungi",
        "anchor_reason": "Fungi are the non-replaceable biological source.",
        "main_topics": [
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
        ],
        "secondary_topics": {
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
        },
    }
    repair_topic_structure = deepcopy(invalid_payload["topic_structure"])
    repair_topic_structure["main_topics"].insert(
        1,
        {
            "topic_id": "building_materials",
            "label": "Building materials",
            "field": "title",
            "terms": ["building materials", "construction materials"],
            "retrieval_terms": ["building materials", "construction materials"],
            "matching_terms": ["building materials", "construction materials"],
        },
    )
    repair_topic_structure["main_topics"][2]["terms"] = [
        "concrete replacement",
        "concrete alternative",
    ]
    repair_topic_structure["main_topics"][2]["retrieval_terms"] = [
        "concrete replacement",
        "concrete alternative",
    ]
    repair_topic_structure["main_topics"][2]["matching_terms"] = [
        "concrete replacement",
        "cement substitute",
    ]
    repair_topic_structure["secondary_topics"] = [
        {
            "main_topic_id": "fungi",
            "secondary_topic_id": "plant_based_materials",
            "label": "Plant-based materials",
            "field": "title_or_abstract",
            "terms": ["plant-based materials", "cellulose materials"],
            "retrieval_terms": ["plant-based materials", "cellulose materials"],
            "matching_terms": ["plant-based materials", "cellulose materials"],
        },
        {
            "main_topic_id": "building_materials",
            "secondary_topic_id": "construction_products",
            "label": "Construction products",
            "field": "title_or_abstract",
            "terms": ["construction products", "building products"],
            "retrieval_terms": ["construction products"],
            "matching_terms": ["construction products", "building products"],
        },
        {
            "main_topic_id": "concrete_replacement",
            "secondary_topic_id": "cement_substitution",
            "label": "Cement substitution",
            "field": "title_or_abstract",
            "terms": ["cement substitute", "cement replacement"],
            "retrieval_terms": ["cement substitute", "cement replacement"],
            "matching_terms": ["cement substitute", "cement replacement"],
        },
    ]
    client = StaticJSONClient(
        [
            invalid_payload,
            deepcopy(invalid_payload),
            deepcopy(invalid_payload),
            repair_topic_structure,
        ]
    )
    output = tmp_path / "contract.yaml"

    run_generate_topic_contract(
        "Could fungi be used to create sustainable building materials that "
        "replace concrete in certain applications?",
        output,
        "test-model",
        client=client,
        trace_dir=tmp_path / "traces",
    )

    contract = load_topic_contract(output)
    topic_ids = [
        topic["topic_id"] for topic in contract["topic_structure"]["main_topics"]
    ]
    assert topic_ids == ["fungi", "building_materials", "concrete_replacement"]
    assert client.requests[-1]["call_id"] == "contract_retry_3_topic_structure_repair"


def test_generate_topic_contract_repairs_comparator_anchor(
    tmp_path: Path,
) -> None:
    invalid_payload = generated_topic_contract_payload()
    invalid_payload["topic_id"] = "fungi_concrete_replacement"
    invalid_payload["research_topic"] = {
        "title": "Fungi as sustainable building materials",
        "description": (
            "Research on fungal materials that could replace concrete in "
            "building applications."
        ),
    }
    invalid_payload["topic_structure"] = {
        "anchor_topic_id": "concrete_replacement",
        "anchor_reason": "Concrete replacement is required for title relevance.",
        "main_topics": [
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
        ],
        "secondary_topics": {
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
        },
    }
    repair_topic_structure = deepcopy(invalid_payload["topic_structure"])
    repair_topic_structure["anchor_topic_id"] = "fungi"
    repair_topic_structure["anchor_reason"] = (
        "Fungi are the non-replaceable biological source."
    )
    repair_topic_structure["main_topics"][0]["field"] = "title_or_abstract"
    repair_topic_structure["main_topics"][1]["field"] = "title"
    repair_topic_structure["secondary_topics"] = [
        {
            "main_topic_id": "fungi",
            "secondary_topic_id": "plant_based_materials",
            "label": "Plant-based materials",
            "field": "title_or_abstract",
            "terms": ["plant-based materials", "cellulose materials"],
            "retrieval_terms": ["plant-based materials", "cellulose materials"],
            "matching_terms": ["plant-based materials", "cellulose materials"],
        },
        {
            "main_topic_id": "building_materials",
            "secondary_topic_id": "construction_products",
            "label": "Construction products",
            "field": "title_or_abstract",
            "terms": ["construction products", "building products"],
            "retrieval_terms": ["construction products"],
            "matching_terms": ["construction products", "building products"],
        },
        {
            "main_topic_id": "concrete_replacement",
            "secondary_topic_id": "cement_substitution",
            "label": "Cement substitution",
            "field": "title_or_abstract",
            "terms": ["cement substitute", "cement replacement"],
            "retrieval_terms": ["cement substitute", "cement replacement"],
            "matching_terms": ["cement substitute", "cement replacement"],
        },
    ]
    client = StaticJSONClient(
        [
            invalid_payload,
            deepcopy(invalid_payload),
            deepcopy(invalid_payload),
            repair_topic_structure,
        ]
    )
    output = tmp_path / "contract.yaml"

    run_generate_topic_contract(
        "Could fungi be used to create sustainable building materials that "
        "replace concrete in certain applications?",
        output,
        "test-model",
        client=client,
        trace_dir=tmp_path / "traces",
    )

    contract = load_topic_contract(output)
    assert contract["topic_structure"]["anchor_topic_id"] == "fungi"
    topic_by_id = {
        topic["topic_id"]: topic for topic in contract["topic_structure"]["main_topics"]
    }
    assert topic_by_id["fungi"]["field"] == "title"
    assert "fungi" in contract["topic_structure"]["secondary_topics"]
    fungi_secondary_ids = {
        group["secondary_topic_id"]
        for group in contract["topic_structure"]["secondary_topics"]["fungi"]
    }
    assert "mycelium_materials" not in fungi_secondary_ids
    assert "plant_based_materials" in fungi_secondary_ids
    assert client.requests[-1]["call_id"] == "contract_retry_3_topic_structure_repair"


def test_generate_topic_contract_repairs_mixed_replacement_and_application_terms(
    tmp_path: Path,
) -> None:
    invalid_payload = generated_topic_contract_payload()
    invalid_payload["topic_id"] = "fungi_building_materials"
    invalid_payload["research_topic"] = {
        "title": "Fungi as sustainable building materials",
        "description": (
            "Research on fungal materials that could replace concrete in "
            "building applications."
        ),
    }
    invalid_payload["topic_structure"] = {
        "anchor_topic_id": "fungi",
        "anchor_reason": "Fungi are the proposed source material.",
        "main_topics": [
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
        ],
        "secondary_topics": {
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
        },
    }
    repair_topic_structure = {
        "anchor_topic_id": "fungi",
        "anchor_reason": "Fungi are the non-replaceable biological source.",
        "main_topics": [
            {
                "topic_id": "fungi",
                "label": "Fungi",
                "field": "title",
                "terms": ["fungi", "mycelium", "mushroom", "fungal material"],
                "retrieval_terms": ["fungi", "mycelium", "mushroom"],
                "matching_terms": ["fungi", "mycelium", "fungal material"],
            },
            {
                "topic_id": "concrete_replacement",
                "label": "Concrete replacement",
                "field": "title_or_abstract",
                "terms": ["concrete replacement", "concrete alternative"],
                "retrieval_terms": ["concrete replacement", "concrete alternative"],
                "matching_terms": [
                    "concrete substitute",
                    "concrete alternative",
                ],
            },
            {
                "topic_id": "building_materials",
                "label": "Building materials",
                "field": "title_or_abstract",
                "terms": ["building materials", "construction materials"],
                "retrieval_terms": ["building materials", "construction materials"],
                "matching_terms": ["building elements", "construction components"],
            },
        ],
        "secondary_topics": [
            {
                "main_topic_id": "fungi",
                "secondary_topic_id": "plant_based_materials",
                "label": "Plant-based materials",
                "field": "title_or_abstract",
                "terms": ["plant-based materials", "cellulose materials"],
                "retrieval_terms": ["plant-based materials", "cellulose materials"],
                "matching_terms": ["plant-based materials", "cellulose materials"],
            },
            {
                "main_topic_id": "concrete_replacement",
                "secondary_topic_id": "cement_substitution",
                "label": "Cement substitution",
                "field": "title_or_abstract",
                "terms": ["cement substitute", "cement replacement"],
                "retrieval_terms": ["cement substitute", "cement replacement"],
                "matching_terms": ["cement substitute", "cement replacement"],
            },
            {
                "main_topic_id": "building_materials",
                "secondary_topic_id": "construction_products",
                "label": "Construction products",
                "field": "title_or_abstract",
                "terms": ["construction products", "building products"],
                "retrieval_terms": ["construction products"],
                "matching_terms": ["construction products", "building products"],
            },
        ],
    }
    client = StaticJSONClient(
        [
            invalid_payload,
            deepcopy(invalid_payload),
            deepcopy(invalid_payload),
            repair_topic_structure,
        ]
    )
    output = tmp_path / "contract.yaml"

    run_generate_topic_contract(
        "Could fungi be used to create sustainable building materials that "
        "replace concrete in certain applications?",
        output,
        "test-model",
        client=client,
        trace_dir=tmp_path / "traces",
    )

    contract = load_topic_contract(output)
    topic_by_id = {
        topic["topic_id"]: topic for topic in contract["topic_structure"]["main_topics"]
    }
    assert topic_by_id["concrete_replacement"]["terms"] == [
        "concrete replacement",
        "concrete alternative",
    ]
    assert "building materials" not in topic_by_id["concrete_replacement"][
        "matching_terms"
    ]
    assert topic_by_id["building_materials"]["matching_terms"] == [
        "building elements",
        "construction components",
    ]
    assert "green_alternatives" not in {
        group["secondary_topic_id"]
        for group in contract["topic_structure"]["secondary_topics"][
            "concrete_replacement"
        ]
    }
    assert client.requests[-1]["call_id"] == "contract_retry_3_topic_structure_repair"


def test_generate_topic_contract_repairs_application_secondary_criterion_group(
    tmp_path: Path,
) -> None:
    invalid_payload = generated_topic_contract_payload()
    invalid_payload["topic_id"] = "fungi_building_materials"
    invalid_payload["research_topic"] = {
        "title": "Fungi as sustainable building materials",
        "description": (
            "Research on fungal materials that could replace concrete in "
            "building applications."
        ),
    }
    invalid_payload["topic_structure"] = {
        "anchor_topic_id": "fungi",
        "anchor_reason": "Fungi are the proposed source material.",
        "main_topics": [
            {
                "topic_id": "fungi",
                "label": "Fungi",
                "field": "title",
                "terms": ["fungi", "mycelium", "mushroom", "fungal material"],
                "retrieval_terms": ["fungi", "mycelium"],
                "matching_terms": ["fungi", "mycelium", "fungal material"],
            },
            {
                "topic_id": "concrete_replacement",
                "label": "Concrete replacement",
                "field": "title_or_abstract",
                "terms": ["concrete replacement", "concrete alternative"],
                "retrieval_terms": ["concrete replacement", "concrete alternative"],
                "matching_terms": ["concrete substitute", "concrete alternative"],
            },
            {
                "topic_id": "building_materials",
                "label": "Building materials",
                "field": "title_or_abstract",
                "terms": [
                    "building materials",
                    "construction materials",
                    "structural materials",
                    "insulation materials",
                ],
                "retrieval_terms": ["building materials", "construction materials"],
                "matching_terms": ["building elements", "sustainable materials"],
            },
        ],
        "secondary_topics": {
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
            "building_materials": [
                {
                    "secondary_topic_id": "eco_construction_materials",
                    "label": "Eco construction materials",
                    "field": "title_or_abstract",
                    "terms": [
                        "sustainable construction materials",
                        "green alternatives",
                        "eco-friendly materials",
                    ],
                    "retrieval_terms": ["eco-friendly materials"],
                    "matching_terms": [
                        "sustainable construction materials",
                        "green alternatives",
                    ],
                }
            ],
        },
    }
    repair_topic_structure = deepcopy(invalid_payload["topic_structure"])
    repair_topic_structure["main_topics"][2]["matching_terms"] = [
        "building elements",
        "construction components",
    ]
    repair_topic_structure["secondary_topics"] = [
        {
            "main_topic_id": "fungi",
            "secondary_topic_id": "plant_based_materials",
            "label": "Plant-based materials",
            "field": "title_or_abstract",
            "terms": ["plant-based materials", "cellulose materials"],
            "retrieval_terms": ["plant-based materials", "cellulose materials"],
            "matching_terms": ["plant-based materials", "cellulose materials"],
        },
        {
            "main_topic_id": "concrete_replacement",
            "secondary_topic_id": "cement_substitution",
            "label": "Cement substitution",
            "field": "title_or_abstract",
            "terms": ["cement substitute", "cement replacement"],
            "retrieval_terms": ["cement substitute", "cement replacement"],
            "matching_terms": ["cement substitute", "cement replacement"],
        },
        {
            "main_topic_id": "building_materials",
            "secondary_topic_id": "construction_products",
            "label": "Construction products",
            "field": "title_or_abstract",
            "terms": ["construction products", "building products"],
            "retrieval_terms": ["construction products"],
            "matching_terms": ["construction products", "building products"],
        },
    ]
    client = StaticJSONClient(
        [
            invalid_payload,
            deepcopy(invalid_payload),
            deepcopy(invalid_payload),
            repair_topic_structure,
        ]
    )
    output = tmp_path / "contract.yaml"

    run_generate_topic_contract(
        "Could fungi be used to create sustainable building materials that "
        "replace concrete in certain applications?",
        output,
        "test-model",
        client=client,
        trace_dir=tmp_path / "traces",
    )

    contract = load_topic_contract(output)
    assert contract["topic_structure"]["secondary_topics"]["building_materials"][
        0
    ]["secondary_topic_id"] == "construction_products"
    topic_by_id = {
        topic["topic_id"]: topic for topic in contract["topic_structure"]["main_topics"]
    }
    assert "sustainable materials" not in topic_by_id["building_materials"][
        "matching_terms"
    ]
    assert client.requests[-1]["call_id"] == "contract_retry_3_topic_structure_repair"


def test_generate_topic_contract_repairs_missing_application_secondary_group(
    tmp_path: Path,
) -> None:
    invalid_payload = generated_topic_contract_payload()
    invalid_payload["topic_id"] = "fungi_building_materials"
    invalid_payload["research_topic"] = {
        "title": "Fungi as sustainable building materials",
        "description": (
            "Research on fungal materials that could replace concrete in "
            "building applications."
        ),
    }
    invalid_payload["topic_structure"] = {
        "anchor_topic_id": "fungi",
        "anchor_reason": "Fungi are the proposed source material.",
        "main_topics": [
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
                "topic_id": "concrete_replacement",
                "label": "Concrete replacement",
                "field": "title_or_abstract",
                "terms": ["concrete replacement", "concrete alternative"],
                "retrieval_terms": ["concrete replacement", "concrete alternative"],
                "matching_terms": ["concrete substitute", "concrete alternative"],
            },
            {
                "topic_id": "building_materials",
                "label": "Building materials",
                "field": "title_or_abstract",
                "terms": [
                    "building materials",
                    "construction materials",
                    "structural materials",
                    "insulation materials",
                ],
                "retrieval_terms": ["building materials", "construction materials"],
                "matching_terms": ["building elements", "construction components"],
            },
        ],
        "secondary_topics": {
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
        },
    }
    repair_topic_structure = deepcopy(invalid_payload["topic_structure"])
    repair_topic_structure["secondary_topics"] = [
        {
            "main_topic_id": "fungi",
            "secondary_topic_id": "plant_based_materials",
            "label": "Plant-based materials",
            "field": "title_or_abstract",
            "terms": ["plant-based materials", "cellulose materials"],
            "retrieval_terms": ["plant-based materials", "cellulose materials"],
            "matching_terms": ["plant-based materials", "cellulose materials"],
        },
        {
            "main_topic_id": "concrete_replacement",
            "secondary_topic_id": "cement_substitution",
            "label": "Cement substitution",
            "field": "title_or_abstract",
            "terms": ["cement substitute", "cement replacement"],
            "retrieval_terms": ["cement substitute", "cement replacement"],
            "matching_terms": ["cement substitute", "cement replacement"],
        },
        {
            "main_topic_id": "building_materials",
            "secondary_topic_id": "construction_products",
            "label": "Construction products",
            "field": "title_or_abstract",
            "terms": ["construction products", "building products"],
            "retrieval_terms": ["construction products"],
            "matching_terms": ["construction products", "building products"],
        },
    ]
    client = StaticJSONClient(
        [
            invalid_payload,
            deepcopy(invalid_payload),
            deepcopy(invalid_payload),
            repair_topic_structure,
        ]
    )
    output = tmp_path / "contract.yaml"

    run_generate_topic_contract(
        "Could fungi be used to create sustainable building materials that "
        "replace concrete in certain applications?",
        output,
        "test-model",
        client=client,
        trace_dir=tmp_path / "traces",
    )

    contract = load_topic_contract(output)
    topic_by_id = {
        topic["topic_id"]: topic for topic in contract["topic_structure"]["main_topics"]
    }
    assert "mycelium-based materials" in topic_by_id["fungi"]["matching_terms"]
    assert contract["topic_structure"]["secondary_topics"]["building_materials"][
        0
    ]["secondary_topic_id"] == "construction_products"
    assert client.requests[-1]["call_id"] == "contract_retry_3_topic_structure_repair"


def test_refine_topic_contract_adds_review_seeded_categories(
    tmp_path: Path,
) -> None:
    contract = load_topic_contract(TOPIC_CONTRACT)
    contract["collection"]["search_queries"] = [
        {"query": "early detection Alzheimer's review", "reason": "Review seed."},
        {"query": "MCI diagnosis overview", "reason": "Overview seed."},
        {"query": "dementia screening systematic review", "reason": "Review seed."},
    ]
    contract_path = tmp_path / "topic_contract.yaml"
    write_yaml_object(contract_path, contract)
    review_path = tmp_path / "review_overviews.jsonl"
    write_jsonl(
        review_path,
        [
            review_seed_with_full_text(
                tmp_path,
                "W1",
                title=(
                    "Systematic review of early Alzheimer's detection "
                    "biomarkers"
                ),
                abstract=(
                    "Review evidence about MCI screening, diagnosis, "
                    "biomarkers, and early detection models."
                ),
                query="early detection Alzheimer's review overview",
            ),
            review_seed_with_full_text(
                tmp_path,
                "W2",
                body=(
                    "Introduction\nThis review is about hospital staffing.\n\n"
                    "Results\nUNSELECTED_FULL_TEXT_MARKER nursing shifts, "
                    "workflow staffing, and hospital rostering dominate this "
                    "review.\n\n"
                ),
                title="Review of unrelated hospital staffing workflows",
                abstract="A review about nursing staffing workflows.",
                query="unrelated review overview",
            ),
            {
                "provider_id": "abstract_only_review",
                "title": "Abstract-only review must not shape tags",
                "abstract": "This metadata-only review should be ignored.",
            },
        ],
    )

    refined_payload = refined_early_detection_contract_payload()
    refined_payload["research_topic"]["title"] = "Changed outside tagging"
    refined_payload["topic_structure"]["main_topics"][2]["terms"].append(
        "fluid assay"
    )
    client = StaticJSONClient([refined_payload])

    result = run_refine_topic_contract(
        "How can Alzheimer's disease be detected early?",
        contract_path,
        review_path,
        "test-model",
        client=client,
        trace_dir=tmp_path / "traces",
        max_review_overviews=1,
    )

    refined = load_topic_contract(contract_path)
    categories = refined["tagging"]["categories"]
    assert "main_topic_category" not in categories
    assert refined["research_topic"] == contract["research_topic"]
    assert refined["scope"] == contract["scope"]
    assert refined["topic_structure"] != contract["topic_structure"]
    assert "fluid assay" in refined["topic_structure"]["main_topics"][2]["terms"]
    assert "knowledge_goal" not in categories
    assert "evidence_signal" in categories
    assert "early_detection" in categories
    assert result.row_counts["review_overviews"] == 3
    assert result.row_counts["review_full_texts"] == 2
    assert result.row_counts["review_full_texts_unique"] == 2
    assert result.row_counts["review_full_texts_topic_eligible"] == 1
    assert result.row_counts["review_full_texts_selected"] == 1
    assert result.row_counts["tagging_categories"] == 6
    assert refined["topic_policy"]["profile_ids"] == [
        "computational_methods",
        "alzheimer_disease",
    ]
    assert result.metadata["topic_policy"] == refined["topic_policy"]
    assert result.warnings == [
        (
            "Ignored review/overview seed papers without extracted full text; "
            "final ontology and tagging categories were refined only from "
            "review full-text evidence. ignored=1 usable=2 selected=1."
        ),
        (
            "Ignored review/overview seed papers whose title and extracted full "
            "text did not contain enough topic-specific evidence for ontology "
            "refinement. ignored=1 eligible=1 selected=1."
        )
    ]
    assert result.trace_paths
    assert "Extracted review full-text evidence" in client.requests[0]["prompt"]
    assert "full_text_evidence" in client.requests[0]["prompt"]
    assert "full_text_status" not in client.requests[0]["prompt"]
    assert "speech markers, imaging biomarkers" in client.requests[0]["prompt"]
    assert "UNSELECTED_FULL_TEXT_MARKER" not in client.requests[0]["prompt"]
    assert "Abstract-only review must not shape tags" not in client.requests[0]["prompt"]
    assert "Metadata abstract that must not define tags" not in client.requests[0]["prompt"]
    assert "Bootstrap categories omitted" in client.requests[0]["prompt"]
    assert '"categories": []' in client.requests[0]["prompt"]
    assert "main_topic_category" not in client.requests[0]["prompt"]


def test_review_full_text_selection_requires_topic_specific_title_and_text(
    tmp_path: Path,
) -> None:
    contract = load_topic_contract(ROOT / "configs/topics/ai_in_education.yaml")
    records = [
        review_seed_with_full_text(
            tmp_path,
            "education_review",
            body=(
                "Introduction\nThis systematic review examines artificial "
                "intelligence in education.\n\n"
                "Results\nEducation studies report classroom teaching, student "
                "engagement, learning outcomes, and feedback support.\n\n"
            ),
            title="Artificial Intelligence in Education: A Review",
        ),
        review_seed_with_full_text(
            tmp_path,
            "nutrition_review",
            body=(
                "Introduction\nThis systematic review examines artificial "
                "intelligence and machine learning in nutrition.\n\n"
                "Results\nDietary assessment, biomarkers, and clinical nutrition "
                "applications dominate the review.\n\n"
            ),
            title=(
                "Applications of Artificial Intelligence, Machine Learning, "
                "and Deep Learning in Nutrition: A Systematic Review"
            ),
        ),
        review_seed_with_full_text(
            tmp_path,
            "broad_education_review",
            body=(
                "Introduction\nThis review examines technology-supported "
                "education.\n\n"
                "Results\nEducation studies report classroom teaching, student "
                "engagement, learning outcomes, and instructional support.\n\n"
            ),
            title=(
                "Technology-supported management education: a systematic "
                "review of antecedents of learning effectiveness"
            ),
        ),
    ]

    selected = select_review_overviews_with_full_text(
        contract,
        records,
        max_results=5,
    )

    assert [record["provider_id"] for record in selected] == ["education_review"]


def test_refine_topic_contract_requires_extracted_review_full_text(
    tmp_path: Path,
) -> None:
    contract = load_topic_contract(TOPIC_CONTRACT)
    contract_path = tmp_path / "topic_contract.yaml"
    write_yaml_object(contract_path, contract)
    review_path = tmp_path / "review_overviews.jsonl"
    review_path.write_text("", encoding="utf-8")
    client = StaticJSONClient([generated_topic_contract_payload()])

    with pytest.raises(ValueError, match="requires extracted full text"):
        run_refine_topic_contract(
            "How can Alzheimer's disease be detected early?",
            contract_path,
            review_path,
            "test-model",
            client=client,
            trace_dir=tmp_path / "traces",
        )

    refined = load_topic_contract(contract_path)
    assert len(client.requests) == 0
    assert refined["research_topic"] == contract["research_topic"]


def test_refine_topic_contract_repairs_boilerplate_category(
    tmp_path: Path,
) -> None:
    contract = load_topic_contract(TOPIC_CONTRACT)
    contract_path = tmp_path / "topic_contract.yaml"
    write_yaml_object(contract_path, contract)
    review_path = tmp_path / "review_overviews.jsonl"
    write_jsonl(review_path, [review_seed_with_full_text(tmp_path, "W1")])
    weak_payload = refined_early_detection_contract_payload()
    weak_payload["tagging"]["categories"]["study_design"] = {
        "required": False,
        "selection": "multi",
        "values": ["cross_sectional", "longitudinal", "experimental"],
    }
    repair_patch = {
        "remove_category_ids": ["study_design"],
        "upsert_categories": [
            {
                "category_id": "detection_validation_setting",
                "description": (
                    "Validation settings used for early detection evidence."
                ),
                "required": False,
                "selection": "multi",
                "values": [
                    "internal_validation",
                    "external_validation",
                    "clinical_validation",
                ],
                "applies_when": None,
            }
        ],
        "repair_notes": [
            "Replaced generic study_design with a topic-specific validation category."
        ],
    }
    client = StaticJSONClient([weak_payload, repair_patch])

    result = run_refine_topic_contract(
        "How can Alzheimer's disease be detected early?",
        contract_path,
        review_path,
        "test-model",
        client=client,
        trace_dir=tmp_path / "traces",
    )

    refined = load_topic_contract(contract_path)
    categories = refined["tagging"]["categories"]
    assert [request["call_id"] for request in client.requests] == [
        "contract_refinement",
        "contract_refinement_repair",
    ]
    assert "study_design" not in categories
    assert "detection_validation_setting" in categories
    assert refined["research_topic"] == contract["research_topic"]
    assert refined["topic_structure"]["anchor_topic_id"] == contract["topic_structure"][
        "anchor_topic_id"
    ]
    assert refined["topic_structure"]["main_topics"] == contract["topic_structure"][
        "main_topics"
    ]
    assert set(refined["topic_structure"]["secondary_topics"]) == set(
        contract["topic_structure"]["secondary_topics"]
    )
    for groups in refined["topic_structure"]["secondary_topics"].values():
        assert all("secondary_topic_id" in group for group in groups)
    assert refined["scope"] == contract["scope"]
    assert refined["collection"] == contract["collection"]
    assert any("repair" in path.name for path in result.trace_paths)


def test_refine_topic_contract_filters_retired_knowledge_goal(
    tmp_path: Path,
) -> None:
    contract = load_topic_contract(TOPIC_CONTRACT)
    contract_path = tmp_path / "topic_contract.yaml"
    write_yaml_object(contract_path, contract)
    review_path = tmp_path / "review_overviews.jsonl"
    write_jsonl(review_path, [review_seed_with_full_text(tmp_path, "W1")])
    weak_payload = refined_early_detection_contract_payload()
    weak_payload["tagging"]["categories"]["knowledge_goal"] = {
        "required": True,
        "selection": "single",
        "values": ["early_detection", "disease_state"],
    }
    client = StaticJSONClient([weak_payload])

    run_refine_topic_contract(
        "How can Alzheimer's disease be detected early?",
        contract_path,
        review_path,
        "test-model",
        client=client,
        trace_dir=tmp_path / "traces",
    )

    refined = load_topic_contract(contract_path)
    assert "knowledge_goal" not in refined["tagging"]["categories"]
    assert "early_detection" in refined["tagging"]["categories"]
    assert "disease_state" in refined["tagging"]["categories"]
    assert "evidence_signal" in refined["tagging"]["categories"]
    assert [request["call_id"] for request in client.requests] == [
        "contract_refinement",
    ]


def test_refine_topic_contract_falls_back_when_targeted_repair_fails(
    tmp_path: Path,
) -> None:
    contract = load_topic_contract(TOPIC_CONTRACT)
    contract_path = tmp_path / "topic_contract.yaml"
    write_yaml_object(contract_path, contract)
    review_path = tmp_path / "review_overviews.jsonl"
    write_jsonl(review_path, [review_seed_with_full_text(tmp_path, "W1")])
    weak_payload = refined_early_detection_contract_payload()
    weak_payload["tagging"]["categories"]["study_design"] = {
        "required": False,
        "selection": "multi",
        "values": ["cross_sectional", "longitudinal", "experimental"],
    }
    bad_repair_patch = {
        "remove_category_ids": ["study_design"],
        "upsert_categories": [
            {
                "category_id": "replacement_category",
                "description": "Invalid because it uses a catch-all value.",
                "required": False,
                "selection": "multi",
                "values": ["not_reported", "unclear"],
                "applies_when": None,
            }
        ],
        "repair_notes": ["This patch should fail semantic validation."],
    }
    client = StaticJSONClient(
        [
            weak_payload,
            bad_repair_patch,
            refined_early_detection_contract_payload(),
        ]
    )

    result = run_refine_topic_contract(
        "How can Alzheimer's disease be detected early?",
        contract_path,
        review_path,
        "test-model",
        client=client,
        trace_dir=tmp_path / "traces",
    )

    refined = load_topic_contract(contract_path)
    assert [request["call_id"] for request in client.requests] == [
        "contract_refinement",
        "contract_refinement_repair",
        "contract_refinement_retry_2",
    ]
    assert "study_design" not in refined["tagging"]["categories"]
    assert "early_detection" in refined["tagging"]["categories"]
    assert any(
        "contract_refinement_repair" in path.name for path in result.trace_paths
    )


def test_review_exclusion_does_not_force_abstracts_without_policy() -> None:
    contract = load_topic_contract(TOPIC_CONTRACT)
    contract["candidate_screening"]["missing_abstract_policy"] = "include"
    plan = {
        "recommended_provider": "openalex",
        "main_search_string": "early detection",
        "filters": {
            "year_from": None,
            "year_to": None,
            "publication_types": [],
            "open_access_only": None,
            "has_abstract": None,
            "has_full_text": None,
            "language": None,
            "venue_or_source": [],
            "field_or_domain": [],
        },
        "provider_specific_plan": {
            "provider": "openalex",
            "query": "early detection",
            "filters": [],
            "sort": None,
            "max_results_recommendation": 5,
        },
    }

    warnings = enforce_topic_plan_constraints(plan, contract)

    assert plan["filters"]["has_abstract"] is None
    assert plan["filters"]["exclude_reviews"] is True
    assert plan["provider_specific_plan"]["filters"] == [
        {
            "name": "type",
            "value": "!review",
            "reason": (
                "The topic contract excludes review/background papers, "
                "so OpenAlex review works are filtered before screening."
            ),
        }
    ]
    assert warnings == [
        "Set filters.exclude_reviews=true because topic contract excludes OpenAlex review works.",
        "Added provider_specific_plan type:!review filter for review exclusion policy.",
    ]


def test_full_text_requirement_does_not_prefilter_provider_search() -> None:
    contract = load_topic_contract(TOPIC_CONTRACT)
    contract["collection"]["require_full_text_availability"] = True
    contract["collection"]["full_text_availability_policy"] = "verified_url"
    contract["collection"]["exclude_openalex_review_type"] = False
    contract["candidate_screening"]["missing_abstract_policy"] = "exclude"
    plan = {
        "recommended_provider": "openalex",
        "main_search_string": "early detection",
        "filters": {
            "year_from": None,
            "year_to": None,
            "publication_types": [],
            "open_access_only": None,
            "has_abstract": None,
            "has_full_text": None,
            "language": None,
            "venue_or_source": [],
            "field_or_domain": [],
        },
        "provider_specific_plan": {
            "provider": "openalex",
            "query": "early detection",
            "filters": [],
            "sort": None,
            "max_results_recommendation": 5,
        },
    }

    warnings = enforce_topic_plan_constraints(
        plan,
        contract,
        require_full_text_availability=True,
    )

    assert plan["filters"]["has_abstract"] is True
    assert plan["filters"]["open_access_only"] is None
    assert plan["filters"]["has_full_text"] is None
    assert plan["provider_specific_plan"]["filters"] == [
        {
            "name": "has_abstract",
            "value": "true",
            "reason": (
                "The topic contract excludes candidates without abstracts, "
                "so the provider query should retrieve works with abstracts."
            ),
        }
    ]
    assert warnings == [
        "Set filters.has_abstract=true because topic contract excludes missing abstracts.",
        "Added provider_specific_plan has_abstract filter for screening policy.",
    ]


def test_publication_window_overrides_planner_dates_exactly() -> None:
    contract = load_topic_contract(TOPIC_CONTRACT)
    contract["collection"]["exclude_openalex_review_type"] = False
    contract["collection"]["publication_window"] = {
        "start": "2020-01-01",
        "end": "2026-06-19",
    }
    contract["candidate_screening"]["missing_abstract_policy"] = "include"
    plan = {
        "recommended_provider": "openalex",
        "filters": {
            "year_from": 2019,
            "year_to": 2027,
        },
        "provider_specific_plan": {
            "provider": "openalex",
            "filters": [
                {
                    "name": "from_publication_date",
                    "value": "2019-01-01",
                    "reason": "Planner guess.",
                },
                {
                    "name": "publication_year",
                    "value": "2024",
                    "reason": "Conflicting planner guess.",
                },
                {"name": "language", "value": "en", "reason": "Keep this."},
            ],
        },
        "corpus_constraints": {"future_constraint": {"enabled": True}},
    }

    warnings = enforce_topic_plan_constraints(plan, contract)

    assert plan["filters"]["year_from"] == 2020
    assert plan["filters"]["year_to"] == 2026
    assert plan["provider_specific_plan"]["filters"] == [
        {"name": "language", "value": "en", "reason": "Keep this."},
        {
            "name": "from_publication_date",
            "value": "2020-01-01",
            "reason": (
                "Exact inclusive lower publication-date boundary from the "
                "topic contract."
            ),
        },
        {
            "name": "to_publication_date",
            "value": "2026-06-19",
            "reason": (
                "Exact inclusive upper publication-date boundary from the "
                "topic contract."
            ),
        },
    ]
    assert plan["corpus_constraints"] == {
        "future_constraint": {"enabled": True},
        "publication_window": {
            "start": "2020-01-01",
            "end": "2026-06-19",
            "inclusive": True,
            "source": "topic_contract",
        },
    }
    assert warnings == [
        "Applied exact inclusive topic-contract publication window: "
        "2020-01-01 through 2026-06-19."
    ]


def test_full_text_requirement_clears_llm_full_text_prefilters() -> None:
    contract = load_topic_contract(TOPIC_CONTRACT)
    contract["collection"]["require_full_text_availability"] = True
    contract["collection"]["full_text_availability_policy"] = "verified_url"
    contract["collection"]["exclude_openalex_review_type"] = False
    contract["candidate_screening"]["missing_abstract_policy"] = "include"
    plan = {
        "recommended_provider": "openalex",
        "main_search_string": "early detection",
        "filters": {
            "year_from": None,
            "year_to": None,
            "publication_types": [],
            "open_access_only": True,
            "has_abstract": None,
            "has_full_text": True,
            "has_pdf_url": True,
            "has_content_pdf": True,
            "language": None,
            "venue_or_source": [],
            "field_or_domain": [],
        },
        "provider_specific_plan": {
            "provider": "openalex",
            "query": "early detection",
            "filters": [
                {"name": "open_access", "value": "true", "reason": "LLM prefilter."},
                {"name": "has_full_text", "value": "true", "reason": "LLM prefilter."},
                {"name": "language", "value": "en", "reason": "Keep this."},
            ],
            "sort": None,
            "max_results_recommendation": 5,
        },
    }

    warnings = enforce_topic_plan_constraints(
        plan,
        contract,
        require_full_text_availability=True,
    )

    assert plan["filters"]["open_access_only"] is None
    assert plan["filters"]["has_full_text"] is None
    assert plan["filters"]["has_pdf_url"] is None
    assert plan["filters"]["has_content_pdf"] is None
    assert plan["provider_specific_plan"]["filters"] == [
        {"name": "language", "value": "en", "reason": "Keep this."},
    ]
    assert warnings == [
        "Cleared filters.open_access_only because full-text availability is "
        "verified after relevance screening.",
        "Cleared filters.has_full_text because full-text availability is "
        "verified after relevance screening.",
        "Cleared filters.has_pdf_url because full-text availability is "
        "verified after relevance screening.",
        "Cleared filters.has_content_pdf because full-text availability is "
        "verified after relevance screening.",
        "Removed provider full-text availability prefilters "
        "(has_full_text, open_access) because URLs are verified after relevance "
        "screening.",
    ]


def test_candidate_screening_uses_fake_client(tmp_path: Path) -> None:
    input_path = tmp_path / "candidates.jsonl"
    output_path = tmp_path / "screening.csv"
    input_path.write_text(
        json.dumps(
            {
                "title": "MCI screening",
                "year": 2024,
                "doi": "10.123/example",
                "provider": "openalex",
                "provider_id": "W1",
                "rank": 1,
                "abstract": "Screening for mild cognitive impairment.",
                "query": "MCI screening",
                "query_reason": "Adjacent screening query.",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    client = StaticJSONClient(
        [{"decision": "include", "reason": "Directly relevant.", "confidence": "high"}]
    )

    result = run_screening(
        input_path,
        "early detection",
        output_path,
        "test-model",
        TOPIC_CONTRACT,
        client=client,
        trace_dir=tmp_path / "traces",
    )

    rows = list(csv.DictReader(output_path.open(newline="", encoding="utf-8")))
    assert result.row_counts["included"] == 1
    assert rows[0]["screening_decision"] == "include"
    assert rows[0]["source_query"] == "MCI screening"
    assert "detecting MCI or cognitive impairment" in client.requests[0]["prompt"]
    assert "recall-oriented candidate-screening pass" in client.requests[0]["prompt"]
    assert "Adjacent screening query." in client.requests[0]["prompt"]


def test_title_relevance_screening_applies_anchor_and_tiers(
    tmp_path: Path,
) -> None:
    input_path = tmp_path / "candidates.jsonl"
    output_path = tmp_path / "title_screening.csv"
    write_jsonl(
        input_path,
        [
            {
                "provider": "openalex",
                "provider_id": "W1",
                "doi": "10.1/core",
                "title": "ChatGPT in school education improves student grades",
                "year": 2024,
                "rank": 1,
                "query": "AI school performance",
            },
            {
                "provider": "openalex",
                "provider_id": "W2",
                "doi": "10.1/adjacent",
                "title": "ChatGPT in university improves student grades",
                "year": 2024,
                "rank": 2,
                "query": "AI university performance",
            },
            {
                "provider": "openalex",
                "provider_id": "W3",
                "doi": "10.1/no-anchor",
                "title": "Tablet use in schools improves student grades",
                "year": 2024,
                "rank": 3,
                "query": "school performance",
            },
            {
                "provider": "openalex",
                "provider_id": "W4",
                "doi": "10.1/no-replacement",
                "title": "ChatGPT and student well-being",
                "year": 2024,
                "rank": 4,
                "query": "AI wellbeing",
            },
        ],
    )
    client = StaticJSONClient(
        [
            {
                "anchor_present": True,
                "matched_main_topics": [
                    "ai",
                    "formal_education",
                    "learning_impact",
                ],
                "matched_secondary_topics": [],
                "missing_main_topics": [],
                "relevance_tier": 0,
                "decision": "include",
                "confidence": "high",
                "reason": "Title contains all main topic components.",
            },
            {
                "anchor_present": True,
                "matched_main_topics": ["ai", "learning_impact"],
                "matched_secondary_topics": [
                    {
                        "main_topic_id": "formal_education",
                        "secondary_topic_id": "higher_education",
                        "terms": ["university"],
                    }
                ],
                "missing_main_topics": ["formal_education"],
                "relevance_tier": 1,
                "decision": "include",
                "confidence": "high",
                "reason": "University replaces the formal education setting.",
            },
            {
                "anchor_present": False,
                "matched_main_topics": ["formal_education", "learning_impact"],
                "matched_secondary_topics": [],
                "missing_main_topics": ["ai"],
                "relevance_tier": 999,
                "decision": "exclude",
                "confidence": "high",
                "reason": "The AI anchor is absent.",
            },
            {
                "anchor_present": True,
                "matched_main_topics": ["ai"],
                "matched_secondary_topics": [
                    {
                        "main_topic_id": "learning_impact",
                        "secondary_topic_id": "student_wellbeing",
                        "terms": ["well-being"],
                    }
                ],
                "missing_main_topics": ["formal_education", "learning_impact"],
                "relevance_tier": 2,
                "decision": "include",
                "confidence": "medium",
                "reason": "The title misses a setting component.",
            },
        ]
    )

    result = run_title_relevance(
        input_path,
        output_path,
        "test-model",
        ROOT / "configs/topics/ai_in_education.yaml",
        client=client,
        trace_dir=tmp_path / "traces",
    )

    rows = list(csv.DictReader(output_path.open(newline="", encoding="utf-8")))
    assert result.row_counts["included"] == 2
    assert rows[0]["screening_decision"] == "include"
    assert rows[0]["title_relevance_tier"] == "0"
    assert rows[1]["screening_decision"] == "include"
    assert rows[1]["title_relevance_tier"] == "1"
    assert rows[2]["screening_decision"] == "exclude"
    assert rows[2]["title_anchor_present"] == "no"
    assert rows[3]["screening_decision"] == "exclude"
    assert "formal_education" in rows[3]["screening_reason"]
    assert "Topic structure" in client.requests[0]["prompt"]
    assert "Configured secondary replacement groups" in client.requests[0]["prompt"]
    assert client.requests[0]["schema_name"] == "title_relevance_screening"
    secondary_schema = client.requests[0]["schema"]["properties"][
        "matched_secondary_topics"
    ]["items"]
    assert "secondary_topic_id" in secondary_schema["required"]


def test_title_relevance_ignores_unconfigured_secondary_replacements(
    tmp_path: Path,
) -> None:
    input_path = tmp_path / "candidates.jsonl"
    output_path = tmp_path / "title_screening.csv"
    write_jsonl(
        input_path,
        [
            {
                "provider": "openalex",
                "provider_id": "W1",
                "doi": "10.1/flipped",
                "title": "ChatGPT in flipped classroom improves well-being",
                "year": 2024,
                "rank": 1,
                "query": "AI flipped classroom",
            },
            {
                "provider": "openalex",
                "provider_id": "W2",
                "doi": "10.1/invalid-term",
                "title": "ChatGPT in flipped classroom improves well-being",
                "year": 2024,
                "rank": 2,
                "query": "AI flipped classroom",
            },
            {
                "provider": "openalex",
                "provider_id": "W3",
                "doi": "10.1/missing-visible-secondary",
                "title": "ChatGPT in university courses",
                "year": 2024,
                "rank": 3,
                "query": "AI university",
            },
        ],
    )
    client = StaticJSONClient(
        [
            {
                "anchor_present": True,
                "matched_main_topics": ["ai", "learning_impact"],
                "matched_secondary_topics": [
                    {
                        "main_topic_id": "formal_education",
                        "secondary_topic_id": "flipped_classroom",
                        "terms": ["flipped classroom"],
                    }
                ],
                "missing_main_topics": ["formal_education"],
                "relevance_tier": 1,
                "decision": "include",
                "confidence": "medium",
                "reason": "The title uses a flipped classroom setting.",
            },
            {
                "anchor_present": True,
                "matched_main_topics": ["ai", "learning_impact"],
                "matched_secondary_topics": [
                    {
                        "main_topic_id": "formal_education",
                        "secondary_topic_id": "formal_education_secondary_1",
                        "terms": ["flipped classroom"],
                    }
                ],
                "missing_main_topics": ["formal_education"],
                "relevance_tier": 1,
                "decision": "include",
                "confidence": "medium",
                "reason": "The title uses an invalid term for the configured group.",
            },
            {
                "anchor_present": True,
                "matched_main_topics": ["ai", "formal_education"],
                "matched_secondary_topics": [
                    {
                        "main_topic_id": "learning_impact",
                        "secondary_topic_id": "learning_impact_secondary_1",
                        "terms": ["well-being"],
                    }
                ],
                "missing_main_topics": ["learning_impact"],
                "relevance_tier": 1,
                "decision": "include",
                "confidence": "medium",
                "reason": "The configured secondary term is not in the title.",
            },
        ]
    )

    result = run_title_relevance(
        input_path,
        output_path,
        "test-model",
        ROOT / "configs/topics/ai_in_education.yaml",
        client=client,
        trace_dir=tmp_path / "traces",
    )

    rows = list(csv.DictReader(output_path.open(newline="", encoding="utf-8")))
    assert result.row_counts["included"] == 0
    assert rows[0]["screening_decision"] == "exclude"
    assert rows[0]["title_matched_secondary_topics"] == ""
    assert "formal_education" in rows[0]["screening_reason"]
    assert rows[1]["screening_decision"] == "exclude"
    assert rows[1]["title_matched_secondary_topics"] == ""
    assert rows[2]["screening_decision"] == "exclude"
    assert rows[2]["title_matched_secondary_topics"] == ""


def test_title_relevance_auto_includes_deterministic_tier_zero(
    tmp_path: Path,
) -> None:
    input_path = tmp_path / "candidates.jsonl"
    output_path = tmp_path / "title_screening.csv"
    write_jsonl(
        input_path,
        [
            {
                "provider": "openalex",
                "provider_id": "W1",
                "doi": "10.1/tier0",
                "title": "Deep learning in K-12 classrooms improves grades",
                "year": 2024,
                "rank": 1,
                "query": "tier zero",
                "retrieval_tier": 0,
                "topic_matches": {
                    "anchor_topic_id": "ai",
                    "anchor_present": True,
                    "matched_main_topics": [
                        "ai",
                        "formal_education",
                        "learning_impact",
                    ],
                    "matched_secondary_topics": [],
                    "missing_main_topics": [],
                    "main_topic_values": {
                        "ai": [{"value": "deep learning", "field": "title"}],
                        "formal_education": [
                            {"value": "K-12", "field": "title"}
                        ],
                        "learning_impact": [
                            {"value": "grades", "field": "title"}
                        ],
                    },
                    "secondary_topic_values": {
                        "formal_education": [],
                        "learning_impact": [],
                    },
                },
            }
        ],
    )
    client = StaticJSONClient([])

    result = run_title_relevance(
        input_path,
        output_path,
        "test-model",
        ROOT / "configs/topics/ai_in_education.yaml",
        client=client,
        trace_dir=tmp_path / "traces",
    )

    rows = list(csv.DictReader(output_path.open(newline="", encoding="utf-8")))
    assert rows[0]["screening_decision"] == "include"
    assert rows[0]["title_relevance_tier"] == "0"
    assert result.row_counts["deterministic_tier0_included"] == 1
    assert result.row_counts["llm_screened"] == 0
    assert client.requests == []


def test_title_relevance_auto_excludes_strict_title_anchor_miss(
    tmp_path: Path,
) -> None:
    input_path = tmp_path / "candidates.jsonl"
    output_path = tmp_path / "title_screening.csv"
    write_jsonl(
        input_path,
        [
            {
                "provider": "openalex",
                "provider_id": "W1",
                "doi": "10.1/anchor-miss",
                "title": "Deeper learning in high school improves grades",
                "year": 2024,
                "rank": 1,
                "query": "strict title",
                "retrieval_tier": 0,
                "retrieval_phase": "strict_title",
                "requires_title_screening": False,
                "topic_matches": {
                    "anchor_topic_id": "ai",
                    "anchor_present": False,
                    "matched_main_topics": [
                        "formal_education",
                        "learning_impact",
                    ],
                    "matched_secondary_topics": [],
                    "missing_main_topics": ["ai"],
                    "main_topic_values": {
                        "ai": [],
                        "formal_education": [
                            {"value": "high school", "field": "title"}
                        ],
                        "learning_impact": [
                            {"value": "grades", "field": "title"}
                        ],
                    },
                    "secondary_topic_values": {
                        "formal_education": [],
                        "learning_impact": [],
                    },
                },
            }
        ],
    )
    client = StaticJSONClient([])

    result = run_title_relevance(
        input_path,
        output_path,
        "test-model",
        ROOT / "configs/topics/ai_in_education.yaml",
        client=client,
        trace_dir=tmp_path / "traces",
    )

    rows = list(csv.DictReader(output_path.open(newline="", encoding="utf-8")))
    assert rows[0]["screening_decision"] == "exclude"
    assert rows[0]["title_anchor_present"] == "no"
    assert rows[0]["title_missing_main_topics"] == "ai"
    assert "Deterministic local reject" in rows[0]["screening_reason"]
    assert result.row_counts["deterministic_local_excluded"] == 1
    assert result.row_counts["llm_screened"] == 0
    assert client.requests == []


def test_title_relevance_keeps_non_anchor_local_miss_for_llm(
    tmp_path: Path,
) -> None:
    input_path = tmp_path / "candidates.jsonl"
    output_path = tmp_path / "title_screening.csv"
    write_jsonl(
        input_path,
        [
            {
                "provider": "openalex",
                "provider_id": "W1",
                "doi": "10.1/non-anchor-miss",
                "title": "ChatGPT in high school higher-order thinking",
                "year": 2024,
                "rank": 1,
                "query": "strict title",
                "retrieval_tier": 0,
                "retrieval_phase": "strict_title",
                "requires_title_screening": False,
                "topic_matches": {
                    "anchor_topic_id": "ai",
                    "anchor_present": True,
                    "matched_main_topics": ["ai", "formal_education"],
                    "matched_secondary_topics": [],
                    "missing_main_topics": ["learning_impact"],
                    "main_topic_values": {
                        "ai": [{"value": "ChatGPT", "field": "title"}],
                        "formal_education": [
                            {"value": "high school", "field": "title"}
                        ],
                        "learning_impact": [],
                    },
                    "secondary_topic_values": {
                        "formal_education": [],
                        "learning_impact": [],
                    },
                },
            }
        ],
    )
    client = StaticJSONClient(
        [
            {
                "anchor_present": True,
                "matched_main_topics": [
                    "ai",
                    "formal_education",
                    "learning_impact",
                ],
                "matched_secondary_topics": [],
                "missing_main_topics": [],
                "relevance_tier": 0,
                "decision": "include",
                "confidence": "medium",
                "reason": "The title uses a learning impact synonym.",
            }
        ]
    )

    result = run_title_relevance(
        input_path,
        output_path,
        "test-model",
        ROOT / "configs/topics/ai_in_education.yaml",
        client=client,
        trace_dir=tmp_path / "traces",
    )

    rows = list(csv.DictReader(output_path.open(newline="", encoding="utf-8")))
    assert rows[0]["screening_decision"] == "include"
    assert result.row_counts["deterministic_local_excluded"] == 0
    assert result.row_counts["llm_screened"] == 1
    assert len(client.requests) == 1


def test_title_relevance_marks_ambiguous_llm_error_for_review(
    tmp_path: Path,
) -> None:
    input_path = tmp_path / "candidates.jsonl"
    output_path = tmp_path / "title_screening.csv"
    write_jsonl(
        input_path,
        [
            {
                "provider": "openalex",
                "provider_id": "W1",
                "doi": "10.1/llm-error-review",
                "title": "ChatGPT in high school higher-order thinking",
                "year": 2024,
                "rank": 1,
                "query": "AI high school",
                "topic_matches": {
                    "anchor_topic_id": "ai",
                    "anchor_present": True,
                    "matched_main_topics": ["ai", "formal_education"],
                    "matched_secondary_topics": [],
                    "missing_main_topics": ["learning_impact"],
                    "main_topic_values": {
                        "ai": [{"value": "ChatGPT", "field": "title"}],
                        "formal_education": [
                            {"value": "high school", "field": "title"}
                        ],
                        "learning_impact": [],
                    },
                    "secondary_topic_values": {
                        "formal_education": [],
                        "learning_impact": [],
                    },
                },
            }
        ],
    )
    client = RaisingJSONClient(
        ValueError(
            "OpenAI request failed for screen_title_relevance/test "
            "with model test-model: Error code: 403"
        )
    )

    result = run_title_relevance(
        input_path,
        output_path,
        "test-model",
        ROOT / "configs/topics/ai_in_education.yaml",
        client=client,
        trace_dir=tmp_path / "traces",
    )

    rows = list(csv.DictReader(output_path.open(newline="", encoding="utf-8")))
    assert rows[0]["screening_decision"] == "review"
    assert rows[0]["screening_status"] == "llm_error"
    assert rows[0]["needs_manual_review"] == "yes"
    assert rows[0]["llm_error_type"] == "openai_403"
    assert rows[0]["title_anchor_present"] == "yes"
    assert result.row_counts["excluded"] == 0
    assert result.row_counts["manual_review_rows"] == 1
    assert result.row_counts["llm_error_rows"] == 1
    assert "marked for manual review" in result.warnings[0]
    raw_trace_paths = [
        path for path in result.trace_paths if path.name.endswith("_raw_response.json")
    ]
    assert raw_trace_paths
    raw_payload = json.loads(raw_trace_paths[0].read_text(encoding="utf-8"))
    assert raw_payload["error_type"] == "openai_403"
    assert len(client.requests) == 1


def test_title_relevance_auto_excludes_llm_error_when_local_anchor_absent(
    tmp_path: Path,
) -> None:
    input_path = tmp_path / "candidates.jsonl"
    output_path = tmp_path / "title_screening.csv"
    write_jsonl(
        input_path,
        [
            {
                "provider": "openalex",
                "provider_id": "W1",
                "doi": "10.1/llm-error-anchor-miss",
                "title": "Deeper learning in high school improves grades",
                "year": 2024,
                "rank": 1,
                "query": "high school grades",
                "topic_matches": {
                    "anchor_topic_id": "ai",
                    "anchor_present": False,
                    "matched_main_topics": [
                        "formal_education",
                        "learning_impact",
                    ],
                    "matched_secondary_topics": [],
                    "missing_main_topics": ["ai"],
                    "main_topic_values": {
                        "ai": [],
                        "formal_education": [
                            {"value": "high school", "field": "title"}
                        ],
                        "learning_impact": [
                            {"value": "grades", "field": "title"}
                        ],
                    },
                    "secondary_topic_values": {
                        "formal_education": [],
                        "learning_impact": [],
                    },
                },
            }
        ],
    )
    client = RaisingJSONClient(ValueError("OpenAI request failed: Error code: 403"))

    result = run_title_relevance(
        input_path,
        output_path,
        "test-model",
        ROOT / "configs/topics/ai_in_education.yaml",
        client=client,
        trace_dir=tmp_path / "traces",
    )

    rows = list(csv.DictReader(output_path.open(newline="", encoding="utf-8")))
    assert rows[0]["screening_decision"] == "exclude"
    assert rows[0]["screening_status"] == "llm_error_auto_excluded_anchor_missing"
    assert rows[0]["needs_manual_review"] == "no"
    assert rows[0]["title_anchor_present"] == "no"
    assert rows[0]["title_missing_main_topics"] == "ai"
    assert result.row_counts["excluded"] == 1
    assert result.row_counts["manual_review_rows"] == 0
    assert result.row_counts["llm_error_auto_excluded"] == 1
    assert "auto-excluded after local anchor miss" in result.warnings[0]
    assert len(client.requests) == 1


def test_title_relevance_screens_tier_zero_when_main_topic_only_in_abstract(
    tmp_path: Path,
) -> None:
    input_path = tmp_path / "candidates.jsonl"
    output_path = tmp_path / "title_screening.csv"
    write_jsonl(
        input_path,
        [
            {
                "provider": "openalex",
                "provider_id": "W1",
                "doi": "10.1/abstract-only",
                "title": "Deep learning in K-12 classrooms",
                "abstract": "The study reports improved grades.",
                "year": 2024,
                "rank": 1,
                "query": "relaxed tier zero",
                "retrieval_tier": 0,
                "topic_matches": {
                    "anchor_topic_id": "ai",
                    "anchor_present": True,
                    "matched_main_topics": [
                        "ai",
                        "formal_education",
                        "learning_impact",
                    ],
                    "matched_secondary_topics": [],
                    "missing_main_topics": [],
                    "main_topic_values": {
                        "ai": [{"value": "deep learning", "field": "title"}],
                        "formal_education": [
                            {"value": "K-12", "field": "title"}
                        ],
                        "learning_impact": [
                            {"value": "grades", "field": "abstract"}
                        ],
                    },
                    "secondary_topic_values": {
                        "formal_education": [],
                        "learning_impact": [],
                    },
                },
            }
        ],
    )
    client = StaticJSONClient(
        [
            {
                "anchor_present": True,
                "matched_main_topics": [
                    "ai",
                    "formal_education",
                    "learning_impact",
                ],
                "matched_secondary_topics": [],
                "missing_main_topics": [],
                "relevance_tier": 0,
                "decision": "include",
                "confidence": "high",
                "reason": "Allowed fields contain all main topics.",
            }
        ]
    )

    result = run_title_relevance(
        input_path,
        output_path,
        "test-model",
        ROOT / "configs/topics/ai_in_education.yaml",
        client=client,
        trace_dir=tmp_path / "traces",
    )

    rows = list(csv.DictReader(output_path.open(newline="", encoding="utf-8")))
    assert rows[0]["screening_decision"] == "include"
    assert result.row_counts["deterministic_tier0_included"] == 0
    assert result.row_counts["llm_screened"] == 1
    assert len(client.requests) == 1
    assert '"abstract": "The study reports improved grades."' in client.requests[0][
        "prompt"
    ]


def test_title_relevance_can_defer_llm_until_full_text(
    tmp_path: Path,
) -> None:
    input_path = tmp_path / "candidates.jsonl"
    output_path = tmp_path / "title_screening.csv"
    write_jsonl(
        input_path,
        [
            {
                "provider": "openalex",
                "provider_id": "W1",
                "doi": "10.1/abstract-only",
                "title": "Deep learning in K-12 classrooms",
                "abstract": "The study reports improved grades.",
                "year": 2024,
                "rank": 1,
                "query": "relaxed tier zero",
                "retrieval_tier": 0,
                "topic_matches": {
                    "anchor_topic_id": "ai",
                    "anchor_present": True,
                    "matched_main_topics": [
                        "ai",
                        "formal_education",
                        "learning_impact",
                    ],
                    "matched_secondary_topics": [],
                    "missing_main_topics": [],
                    "main_topic_values": {
                        "ai": [{"value": "deep learning", "field": "title"}],
                        "formal_education": [
                            {"value": "K-12", "field": "title"}
                        ],
                        "learning_impact": [
                            {"value": "grades", "field": "abstract"}
                        ],
                    },
                    "secondary_topic_values": {
                        "formal_education": [],
                        "learning_impact": [],
                    },
                },
            }
        ],
    )
    client = StaticJSONClient(
        [
            {
                "anchor_present": True,
                "matched_main_topics": [
                    "ai",
                    "formal_education",
                    "learning_impact",
                ],
                "matched_secondary_topics": [],
                "missing_main_topics": [],
                "relevance_tier": 0,
                "decision": "include",
                "confidence": "high",
                "reason": "Allowed fields contain all main topics.",
            }
        ]
    )

    result = run_title_relevance(
        input_path,
        output_path,
        "test-model",
        ROOT / "configs/topics/ai_in_education.yaml",
        client=client,
        trace_dir=tmp_path / "traces",
        defer_llm_until_full_text=True,
    )

    rows = list(csv.DictReader(output_path.open(newline="", encoding="utf-8")))
    assert rows[0]["screening_decision"] == "review"
    assert rows[0]["screening_status"] == "pending_llm_full_text"
    assert result.row_counts["pending_llm_full_text_rows"] == 1
    assert result.row_counts["llm_screened"] == 0
    assert client.requests == []


def test_backfill_fetches_and_screens_when_title_screening_drops_too_many(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan_path = tmp_path / "plan.json"
    candidates_path = tmp_path / "candidates.jsonl"
    deduped_path = tmp_path / "deduped.jsonl"
    screening_path = tmp_path / "screening.csv"
    plan_path.write_text(
        json.dumps(
            {
                "recommended_provider": "openalex",
                "provider_specific_plan": {
                    "provider": "openalex",
                    "query": "AI school performance",
                    "filters": [],
                },
            }
        ),
        encoding="utf-8",
    )
    existing_candidates = [
        {
            "provider": "openalex",
            "provider_id": "W1",
            "doi": "10.1/included",
            "title": "ChatGPT in school improves grades",
            "year": 2024,
            "rank": 1,
            "query": "AI school performance",
        },
        {
            "provider": "openalex",
            "provider_id": "W2",
            "doi": "10.1/excluded",
            "title": "ChatGPT goes to law school",
            "year": 2024,
            "rank": 2,
            "query": "AI school performance",
        },
    ]
    write_jsonl(candidates_path, existing_candidates)
    write_jsonl(deduped_path, existing_candidates)
    write_csv(
        screening_path,
        [
            {
                "paper_id": "10_1_included",
                "title": "ChatGPT in school improves grades",
                "year": "2024",
                "doi": "10.1/included",
                "provider": "openalex",
                "provider_id": "W1",
                "source_rank": "1",
                "source_query": "AI school performance",
                "source_query_reason": "",
                "screening_decision": "include",
                "screening_confidence": "high",
                "screening_reason": "Relevant.",
                "title_anchor_present": "yes",
                "title_relevance_tier": "0",
                "title_matched_main_topics": "ai; formal_education; learning_impact",
                "title_matched_secondary_topics": "",
                "title_missing_main_topics": "",
            },
            {
                "paper_id": "10_1_excluded",
                "title": "ChatGPT goes to law school",
                "year": "2024",
                "doi": "10.1/excluded",
                "provider": "openalex",
                "provider_id": "W2",
                "source_rank": "2",
                "source_query": "AI school performance",
                "source_query_reason": "",
                "screening_decision": "exclude",
                "screening_confidence": "high",
                "screening_reason": "Missing impact.",
                "title_anchor_present": "yes",
                "title_relevance_tier": "999",
                "title_matched_main_topics": "ai",
                "title_matched_secondary_topics": "",
                "title_missing_main_topics": "formal_education; learning_impact",
            },
        ],
        TITLE_RELEVANCE_COLUMNS,
    )

    class FakeProvider:
        name = "openalex"
        last_fetch_diagnostics = {
            "mode": "fake_backfill",
            "target_candidates": 1,
            "unique_candidates": 1,
        }

        def validate_plan(self, plan: dict[str, object]) -> None:
            pass

        def fetch_additional_candidates(
            self,
            plan: dict[str, object],
            existing_candidates: list[dict[str, object]],
            max_results: int,
            per_page: int,
            mailto: str | None,
            sleep_seconds: float,
            backfill_round: int = 1,
        ) -> list[dict[str, object]]:
            assert len(existing_candidates) == 2
            assert max_results == 1
            return [
                {
                    "provider": "openalex",
                    "provider_id": "W1",
                    "doi": "10.1/included",
                    "title": "ChatGPT in school improves grades",
                    "year": 2024,
                    "rank": 1,
                    "query": "AI school performance",
                },
                {
                    "provider": "openalex",
                    "provider_id": "W3",
                    "doi": "10.1/backfill",
                    "title": "AI in classroom learning outcomes",
                    "year": 2024,
                    "rank": 3,
                    "query": "AI school performance",
                }
            ]

    monkeypatch.setitem(fetch_candidates_step.PROVIDERS, "openalex", FakeProvider())
    client = StaticJSONClient(
        [
            {
                "anchor_present": True,
                "matched_main_topics": [
                    "ai",
                    "formal_education",
                    "learning_impact",
                ],
                "matched_secondary_topics": [],
                "missing_main_topics": [],
                "relevance_tier": 0,
                "decision": "include",
                "confidence": "high",
                "reason": "The title contains all components.",
            }
        ]
    )

    result = run_backfill_candidates(
        plan_path,
        candidates_path,
        deduped_path,
        screening_path,
        ROOT / "configs/topics/ai_in_education.yaml",
        "test-model",
        max_results=2,
        client=client,
        trace_dir=tmp_path / "traces",
    )

    rows = list(csv.DictReader(screening_path.open(newline="", encoding="utf-8")))
    assert result.row_counts["backfill_triggered"] == 1
    assert result.row_counts["backfill_candidates_fetched"] == 1
    assert result.metadata["fetch_diagnostics"]["new_candidates_after_seen_filter"] == 1
    assert result.row_counts["final_included_rows"] == 2
    assert len(rows) == 3
    assert rows[-1]["screening_decision"] == "include"
    assert len(read_jsonl_objects(deduped_path)) == 3
    assert len(client.requests) == 1


def test_backfill_repeats_until_target_or_provider_exhaustion(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan_path = tmp_path / "plan.json"
    candidates_path = tmp_path / "candidates.jsonl"
    deduped_path = tmp_path / "deduped.jsonl"
    screening_path = tmp_path / "screening.csv"
    plan_path.write_text(
        json.dumps(
            {
                "recommended_provider": "openalex",
                "provider_specific_plan": {
                    "provider": "openalex",
                    "query": "AI school performance",
                    "filters": [],
                },
            }
        ),
        encoding="utf-8",
    )
    existing_candidates = [
        {
            "provider": "openalex",
            "provider_id": f"W{i}",
            "doi": f"10.1/existing-{i}",
            "title": f"Existing candidate {i}",
            "year": 2024,
            "rank": i,
            "query": "AI school performance",
        }
        for i in range(1, 11)
    ]
    write_jsonl(candidates_path, existing_candidates)
    write_jsonl(deduped_path, existing_candidates)
    screening_rows = []
    for i, candidate in enumerate(existing_candidates, start=1):
        include = i <= 7
        screening_rows.append(
            {
                "paper_id": f"existing_{i}",
                "title": str(candidate["title"]),
                "year": "2024",
                "doi": str(candidate["doi"]),
                "provider": "openalex",
                "provider_id": str(candidate["provider_id"]),
                "source_rank": str(i),
                "source_query": "AI school performance",
                "source_query_reason": "",
                "screening_decision": "include" if include else "exclude",
                "screening_confidence": "high",
                "screening_reason": "Initial screening.",
                "title_anchor_present": "yes",
                "title_relevance_tier": "0" if include else "999",
                "title_matched_main_topics": (
                    "ai; formal_education; learning_impact" if include else "ai"
                ),
                "title_matched_secondary_topics": "",
                "title_missing_main_topics": "" if include else "learning_impact",
            }
        )
    write_csv(screening_path, screening_rows, TITLE_RELEVANCE_COLUMNS)

    class FakeProvider:
        name = "openalex"

        def __init__(self) -> None:
            self.calls: list[tuple[int, int, int]] = []
            self.last_fetch_diagnostics: dict[str, object] = {}

        def validate_plan(self, plan: dict[str, object]) -> None:
            pass

        def fetch_additional_candidates(
            self,
            plan: dict[str, object],
            existing_candidates: list[dict[str, object]],
            max_results: int,
            per_page: int,
            mailto: str | None,
            sleep_seconds: float,
            backfill_round: int = 1,
        ) -> list[dict[str, object]]:
            self.calls.append((backfill_round, len(existing_candidates), max_results))
            self.last_fetch_diagnostics = {
                "mode": "fake_iterative_backfill",
                "backfill_round": backfill_round,
                "target_candidates": max_results,
            }
            if backfill_round == 1:
                return [
                    {
                        "provider": "openalex",
                        "provider_id": "W11",
                        "doi": "10.1/backfill-include",
                        "title": "AI in classroom learning outcomes",
                        "year": 2024,
                        "rank": 11,
                        "query": "AI school performance",
                    },
                    {
                        "provider": "openalex",
                        "provider_id": "W12",
                        "doi": "10.1/backfill-exclude",
                        "title": "ChatGPT unrelated title",
                        "year": 2024,
                        "rank": 12,
                        "query": "AI school performance",
                    },
                ]
            if backfill_round == 2:
                return [
                    {
                        "provider": "openalex",
                        "provider_id": "W13",
                        "doi": "10.1/backfill-second-include",
                        "title": "Machine learning school academic achievement",
                        "year": 2024,
                        "rank": 13,
                        "query": "AI school performance",
                    }
                ]
            return []

    fake_provider = FakeProvider()
    monkeypatch.setitem(fetch_candidates_step.PROVIDERS, "openalex", fake_provider)
    client = StaticJSONClient(
        [
            {
                "anchor_present": True,
                "matched_main_topics": [
                    "ai",
                    "formal_education",
                    "learning_impact",
                ],
                "matched_secondary_topics": [],
                "missing_main_topics": [],
                "relevance_tier": 0,
                "decision": "include",
                "confidence": "high",
                "reason": "The title contains all components.",
            },
            {
                "anchor_present": True,
                "matched_main_topics": ["ai"],
                "matched_secondary_topics": [],
                "missing_main_topics": ["formal_education", "learning_impact"],
                "relevance_tier": 999,
                "decision": "exclude",
                "confidence": "high",
                "reason": "The title misses required components.",
            },
            {
                "anchor_present": True,
                "matched_main_topics": [
                    "ai",
                    "formal_education",
                    "learning_impact",
                ],
                "matched_secondary_topics": [],
                "missing_main_topics": [],
                "relevance_tier": 0,
                "decision": "include",
                "confidence": "high",
                "reason": "The title contains all components.",
            },
        ]
    )

    result = run_backfill_candidates(
        plan_path,
        candidates_path,
        deduped_path,
        screening_path,
        ROOT / "configs/topics/ai_in_education.yaml",
        "test-model",
        max_results=10,
        client=client,
        trace_dir=tmp_path / "traces",
    )

    assert result.row_counts["backfill_triggered"] == 1
    assert result.row_counts["backfill_rounds"] == 3
    assert result.row_counts["target_included_rows"] == 10
    assert result.row_counts["missing_to_target_before_backfill"] == 3
    assert result.row_counts["backfill_candidates_fetched"] == 3
    assert result.row_counts["backfill_included_rows"] == 2
    assert result.row_counts["final_included_rows"] == 9
    assert result.metadata["backfill_target_policy"] == "requested_max_results"
    assert result.metadata["backfill_stop_reason"] == "exhausted_no_new_candidates"
    assert fake_provider.calls == [(1, 10, 3), (2, 12, 2), (3, 13, 1)]
    assert len(read_jsonl_objects(deduped_path)) == 13
    assert len(client.requests) == 3
    assert len(result.warnings) == 2
    assert "no new candidates were returned" in result.warnings[0]
    assert "fewer included papers than requested" in result.warnings[1]


def test_backfill_runs_when_initial_includes_reach_old_threshold(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan_path = tmp_path / "plan.json"
    candidates_path = tmp_path / "candidates.jsonl"
    deduped_path = tmp_path / "deduped.jsonl"
    screening_path = tmp_path / "screening.csv"
    plan_path.write_text(
        json.dumps(
            {
                "recommended_provider": "openalex",
                "provider_specific_plan": {
                    "provider": "openalex",
                    "query": "AI school performance",
                    "filters": [],
                },
            }
        ),
        encoding="utf-8",
    )
    existing_candidates = [
        {
            "provider": "openalex",
            "provider_id": f"W{i}",
            "doi": f"10.1/existing-threshold-{i}",
            "title": f"Existing candidate {i}",
            "year": 2024,
            "rank": i,
            "query": "AI school performance",
        }
        for i in range(1, 11)
    ]
    write_jsonl(candidates_path, existing_candidates)
    write_jsonl(deduped_path, existing_candidates)
    screening_rows = []
    for i, candidate in enumerate(existing_candidates, start=1):
        include = i <= 9
        screening_rows.append(
            {
                "paper_id": f"existing_threshold_{i}",
                "title": str(candidate["title"]),
                "year": "2024",
                "doi": str(candidate["doi"]),
                "provider": "openalex",
                "provider_id": str(candidate["provider_id"]),
                "source_rank": str(i),
                "source_query": "AI school performance",
                "source_query_reason": "",
                "screening_decision": "include" if include else "exclude",
                "screening_confidence": "high",
                "screening_reason": "Initial screening.",
                "title_anchor_present": "yes",
                "title_relevance_tier": "0" if include else "999",
                "title_matched_main_topics": (
                    "ai; formal_education; learning_impact" if include else "ai"
                ),
                "title_matched_secondary_topics": "",
                "title_missing_main_topics": "" if include else "learning_impact",
            }
        )
    write_csv(screening_path, screening_rows, TITLE_RELEVANCE_COLUMNS)

    class FakeProvider:
        name = "openalex"
        last_fetch_diagnostics = {
            "mode": "fake_target_backfill",
            "target_candidates": 1,
        }

        def validate_plan(self, plan: dict[str, object]) -> None:
            pass

        def fetch_additional_candidates(
            self,
            plan: dict[str, object],
            existing_candidates: list[dict[str, object]],
            max_results: int,
            per_page: int,
            mailto: str | None,
            sleep_seconds: float,
            backfill_round: int = 1,
        ) -> list[dict[str, object]]:
            assert max_results == 1
            return [
                {
                    "provider": "openalex",
                    "provider_id": "W11",
                    "doi": "10.1/backfill-target",
                    "title": "Machine learning school academic achievement",
                    "year": 2024,
                    "rank": 11,
                    "query": "AI school performance",
                }
            ]

    fake_provider = FakeProvider()
    monkeypatch.setitem(fetch_candidates_step.PROVIDERS, "openalex", fake_provider)
    client = StaticJSONClient(
        [
            {
                "anchor_present": True,
                "matched_main_topics": [
                    "ai",
                    "formal_education",
                    "learning_impact",
                ],
                "matched_secondary_topics": [],
                "missing_main_topics": [],
                "relevance_tier": 0,
                "decision": "include",
                "confidence": "high",
                "reason": "The title contains all components.",
            }
        ]
    )

    result = run_backfill_candidates(
        plan_path,
        candidates_path,
        deduped_path,
        screening_path,
        ROOT / "configs/topics/ai_in_education.yaml",
        "test-model",
        max_results=10,
        client=client,
        trace_dir=tmp_path / "traces",
    )

    assert result.row_counts["backfill_triggered"] == 1
    assert result.row_counts["backfill_rounds"] == 1
    assert result.row_counts["target_included_rows"] == 10
    assert result.row_counts["backfill_candidates_fetched"] == 1
    assert result.row_counts["backfill_included_rows"] == 1
    assert result.row_counts["final_included_rows"] == 10
    assert len(read_jsonl_objects(deduped_path)) == 11
    assert len(client.requests) == 1
    assert not result.warnings


def test_backfill_after_full_text_loss_uses_provider_continuation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan_path = tmp_path / "plan.json"
    candidates_path = tmp_path / "candidates.jsonl"
    deduped_path = tmp_path / "deduped.jsonl"
    screening_path = tmp_path / "screening.csv"
    availability_path = tmp_path / "availability.csv"
    contract_path = tmp_path / "contract.yaml"
    contract = load_topic_contract(ROOT / "configs/topics/ai_in_education.yaml")
    contract["collection"]["allowed_providers"] = ["digital_library"]
    contract["collection"]["preferred_provider"] = "digital_library"
    contract["collection"]["require_full_text_availability"] = True
    write_yaml_object(contract_path, contract)
    plan_path.write_text(
        json.dumps(
            {
                "recommended_provider": "digital_library",
                "provider_specific_plan": {
                    "provider": "digital_library",
                    "query": "AI school performance",
                    "filters": [],
                },
            }
        ),
        encoding="utf-8",
    )
    existing_candidates = [
        {
            "provider": "digital_library",
            "provider_id": "D1",
            "doi": "10.1/verified",
            "title": "AI classroom learning outcomes verified",
            "year": 2024,
            "rank": 1,
            "query": "AI school performance",
            "full_text_locations": [
                {"source": "digital_library_record", "url": "https://example.test/1.pdf"}
            ],
        },
        {
            "provider": "digital_library",
            "provider_id": "D2",
            "doi": "10.1/missing-full-text",
            "title": "ChatGPT school academic performance missing full text",
            "year": 2024,
            "rank": 2,
            "query": "AI school performance",
        },
    ]
    write_jsonl(candidates_path, existing_candidates)
    write_jsonl(deduped_path, existing_candidates)
    write_csv(
        screening_path,
        [
            {
                "paper_id": "verified",
                "title": "AI classroom learning outcomes verified",
                "year": "2024",
                "doi": "10.1/verified",
                "provider": "digital_library",
                "provider_id": "D1",
                "source_rank": "1",
                "source_query": "AI school performance",
                "source_query_reason": "",
                "screening_decision": "include",
                "screening_confidence": "high",
                "screening_reason": "Relevant.",
                "title_anchor_present": "yes",
                "title_relevance_tier": "0",
                "title_matched_main_topics": "ai; formal_education; learning_impact",
                "title_matched_secondary_topics": "",
                "title_missing_main_topics": "",
            },
            {
                "paper_id": "missing_full_text",
                "title": "ChatGPT school academic performance missing full text",
                "year": "2024",
                "doi": "10.1/missing-full-text",
                "provider": "digital_library",
                "provider_id": "D2",
                "source_rank": "2",
                "source_query": "AI school performance",
                "source_query_reason": "",
                "screening_decision": "include",
                "screening_confidence": "high",
                "screening_reason": "Relevant.",
                "title_anchor_present": "yes",
                "title_relevance_tier": "0",
                "title_matched_main_topics": "ai; formal_education; learning_impact",
                "title_matched_secondary_topics": "",
                "title_missing_main_topics": "",
            },
        ],
        TITLE_RELEVANCE_COLUMNS,
    )

    class FakeDigitalLibraryProvider:
        name = "digital_library"

        def __init__(self) -> None:
            self.calls: list[tuple[int, int, int]] = []
            self.last_fetch_diagnostics: dict[str, object] = {}

        def validate_plan(self, plan: dict[str, object]) -> None:
            assert plan["recommended_provider"] == "digital_library"

        def fetch_additional_candidates(
            self,
            plan: dict[str, object],
            existing_candidates: list[dict[str, object]],
            max_results: int,
            per_page: int,
            mailto: str | None,
            sleep_seconds: float,
            backfill_round: int = 1,
        ) -> list[dict[str, object]]:
            self.calls.append((backfill_round, len(existing_candidates), max_results))
            self.last_fetch_diagnostics = {
                "mode": "fake_provider_resume",
                "backfill_round": backfill_round,
                "target_candidates": max_results,
            }
            assert [candidate["provider_id"] for candidate in existing_candidates] == [
                "D1",
                "D2",
            ]
            return [
                {
                    "provider": "digital_library",
                    "provider_id": "D3",
                    "doi": "10.1/backfill-full-text",
                    "title": "AI classroom learning outcomes backfill",
                    "year": 2024,
                    "rank": 3,
                    "query": "AI school performance",
                    "full_text_locations": [
                        {
                            "source": "digital_library_record",
                            "url": "https://example.test/3.pdf",
                        }
                    ],
                }
            ]

    checked_urls: list[str] = []

    def fake_checker(
        location: verify_full_text_availability.FullTextLocation,
        timeout_seconds: float,
    ) -> verify_full_text_availability.AvailabilityResult:
        checked_urls.append(location.url)
        return verify_full_text_availability.AvailabilityResult(
            status=verify_full_text_availability.STATUS_VERIFIED,
            source=location.source,
            url=location.url,
            checked_at="2026-06-11T00:00:00+00:00",
        )

    fake_provider = FakeDigitalLibraryProvider()
    monkeypatch.setitem(
        fetch_candidates_step.PROVIDERS,
        "digital_library",
        fake_provider,
    )
    client = StaticJSONClient(
        [
            {
                "anchor_present": True,
                "matched_main_topics": [
                    "ai",
                    "formal_education",
                    "learning_impact",
                ],
                "matched_secondary_topics": [],
                "missing_main_topics": [],
                "relevance_tier": 0,
                "decision": "include",
                "confidence": "high",
                "reason": "The title contains all components.",
            }
        ]
    )

    result = run_backfill_candidates(
        plan_path,
        candidates_path,
        deduped_path,
        screening_path,
        contract_path,
        "test-model",
        max_results=2,
        client=client,
        trace_dir=tmp_path / "traces",
        availability_path=availability_path,
        require_full_text_availability=True,
        availability_checker=fake_checker,
    )

    availability_rows = list(
        csv.DictReader(availability_path.open(newline="", encoding="utf-8"))
    )
    assert result.row_counts["backfill_triggered"] == 1
    assert result.row_counts["initial_included_rows"] == 2
    assert result.row_counts["initial_verified_full_text_rows"] == 1
    assert result.row_counts["backfill_candidates_fetched"] == 1
    assert result.row_counts["final_included_rows"] == 3
    assert result.row_counts["final_verified_full_text_rows"] == 2
    assert fake_provider.calls == [(1, 2, 1)]
    assert checked_urls == [
        "https://example.test/1.pdf",
        "https://example.test/3.pdf",
    ]
    assert [row["full_text_availability_status"] for row in availability_rows] == [
        "verified",
        "not_available",
        "verified",
    ]
    assert len(client.requests) == 1


def test_generate_rules_uses_fake_client_and_validates(tmp_path: Path) -> None:
    config_path = tmp_path / "config.json"
    output_path = tmp_path / "rules.json"
    config = {
        "research_topic": {"title": "Topic", "description": "Description"},
        "categories": [
            {
                "category_id": "review_status",
                "required": True,
                "allowed_values": [
                    {"value": "ai_tagged"},
                    {"value": "human_reviewed"},
                ],
            }
        ],
    }
    config_path.write_text(json.dumps(config), encoding="utf-8")
    client = StaticJSONClient(
        [
            {
                "rules": [
                    {
                        "category_id": "review_status",
                        "selection": "single",
                        "required": True,
                        "fallback_value": "ai_tagged",
                        "reason": "Review status is required.",
                    }
                ]
            }
        ]
    )

    result = run_generate_rules(
        config_path,
        output_path,
        "test-model",
        TOPIC_CONTRACT,
        client,
        tmp_path / "traces",
    )

    assert result.row_counts["rules"] == 1
    assert json.loads(output_path.read_text(encoding="utf-8"))["rules_count"] == 1
    assert '"review_status": "ai_tagged"' in client.requests[0]["prompt"]


def test_calibrate_topic_contract_uses_primary_paper_full_text(
    tmp_path: Path,
) -> None:
    contract = load_topic_contract(ROOT / "configs/topics/ai_in_education.yaml")
    contract["tagging"]["categories"] = generated_topic_contract_payload()["tagging"][
        "categories"
    ]
    contract_path = tmp_path / "topic_contract.yaml"
    write_yaml_object(contract_path, contract)
    papers_path = tmp_path / "scope_screened_full_text.csv"
    full_texts = {
        "p1": (
            "Introduction\nThe paper studies classroom use of AI tutoring.\n\n"
            "Results\nPrimary paper full text reports student performance, "
            "lesson feedback, engagement, and teacher-supported adoption.\n\n"
        ),
        "p2": (
            "Introduction\nThis paper studies automated AI feedback and "
            "assessment in lessons.\n\n"
            "Results\nPrimary paper full text reports formative feedback, "
            "teacher review, and assessment support for student performance.\n\n"
        ),
        "p3": (
            "Introduction\nThis paper studies classroom motivation during AI "
            "supported learning activities.\n\n"
            "Results\nPrimary paper full text reports engagement, motivation, "
            "lesson participation, and learning outcomes.\n\n"
        ),
    }
    full_text_paths = {}
    for paper_id, text in full_texts.items():
        full_text_path = tmp_path / f"{paper_id}_full_text.txt"
        full_text_path.write_text(text * 20, encoding="utf-8")
        full_text_paths[paper_id] = full_text_path

    write_csv(
        papers_path,
        [
            {
                "paper_id": "p1",
                "title": "AI tutoring in school lessons",
                "abstract": "AI tutoring and student performance.",
                "doi": "10.123/calibration",
                "scope_decision": "include",
                "full_text_text_path": str(full_text_paths["p1"]),
            },
            {
                "paper_id": "p2",
                "title": "AI feedback assessment in school lessons",
                "abstract": "AI feedback and assessment support.",
                "doi": "10.123/calibration-feedback",
                "scope_decision": "include",
                "full_text_text_path": str(full_text_paths["p2"]),
            },
            {
                "paper_id": "p3",
                "title": "AI engagement in classroom lessons",
                "abstract": "AI learning support and student engagement.",
                "doi": "10.123/calibration-engagement",
                "scope_decision": "include",
                "full_text_text_path": str(full_text_paths["p3"]),
            },
        ],
        [
            "paper_id",
            "title",
            "abstract",
            "doi",
            "scope_decision",
            "full_text_text_path",
        ],
    )

    calibrated_payload = deepcopy(contract)
    calibrated_payload["tagging"]["categories"] = [
        {
            "category_id": "ai",
            "description": "Role played by AI in the lesson or learning activity.",
            "required": False,
            "selection": "multi",
            "values": ["tutor", "feedback_provider", "content_generator"],
            "applies_when": None,
        },
        {
            "category_id": "formal_education",
            "description": "Formal education context represented in the paper.",
            "required": False,
            "selection": "multi",
            "values": ["classroom_lesson", "assessment_activity", "teacher_guided_use"],
            "applies_when": None,
        },
        {
            "category_id": "learning_impact",
            "description": "Student impact signal used to judge AI education use.",
            "required": False,
            "selection": "multi",
            "values": ["test_score", "course_grade", "engagement"],
            "applies_when": None,
        },
        {
            "category_id": "lesson_activity_supported",
            "description": "Lesson activity supported by AI tools.",
            "required": False,
            "selection": "multi",
            "values": ["practice_exercise", "writing_task", "assessment_activity"],
            "applies_when": None,
        },
        {
            "category_id": "implementation_condition",
            "description": "Conditions shaping AI use in classroom practice.",
            "required": False,
            "selection": "multi",
            "values": ["teacher_guided_use", "student_independent_use"],
            "applies_when": None,
        },
    ]
    invalid_payload = deepcopy(calibrated_payload)
    invalid_payload["tagging"]["categories"][0]["values"] = [
        "unclear",
        "not_reported",
    ]
    client = StaticJSONClient(
        [
            invalid_payload,
            calibrated_payload,
        ]
    )

    result = run_calibrate_topic_contract(
        papers_path,
        contract_path,
        "test-model",
        client=client,
        trace_dir=tmp_path / "traces",
        max_primary_papers=3,
    )

    calibrated = load_topic_contract(contract_path)
    categories = calibrated["tagging"]["categories"]
    assert result.row_counts["primary_papers"] == 3
    assert result.row_counts["primary_full_texts_selected"] == 3
    assert result.row_counts["tagging_categories"] == 6
    assert result.trace_paths
    assert calibrated["research_topic"] == contract["research_topic"]
    assert calibrated["scope"] == contract["scope"]
    assert list(categories)[0] == "ai"
    assert categories["ai"]["values"] == [
        "tutor",
        "feedback_provider",
        "content_generator",
    ]
    assert len(client.requests) == 2
    assert client.requests[0]["call_id"] == "contract_calibration"
    assert client.requests[0]["schema_name"] == "topic_contract"
    assert client.requests[1]["call_id"] == "contract_calibration_retry_2"
    assert "weak knowledge tagging categories" in client.requests[1]["prompt"]
    assert "corrected complete topic contract" in client.requests[1]["prompt"]
    assert "Selected primary-paper full-text evidence" in client.requests[0]["prompt"]
    assert "Primary paper full text reports student performance" in client.requests[0][
        "prompt"
    ]
    assert "AI tutoring in school lessons" not in client.requests[0]["prompt"]


def test_calibrate_topic_contract_skips_non_primary_or_off_topic_text(
    tmp_path: Path,
) -> None:
    contract = load_topic_contract(ROOT / "configs/topics/early_detection_ad.yaml")
    contract_path = tmp_path / "topic_contract.yaml"
    write_yaml_object(contract_path, contract)
    papers_path = tmp_path / "scope_screened_full_text.csv"
    off_topic_path = tmp_path / "off_topic.txt"
    off_topic_path.write_text(
        "This full text discusses unrelated crop irrigation and soil chemistry. "
        * 20,
        encoding="utf-8",
    )

    write_csv(
        papers_path,
        [
            {
                "paper_id": "review",
                "title": "Systematic review of early detection biomarkers",
                "abstract": "Relevant review.",
                "doi": "10.123/review",
                "scope_decision": "include",
                "full_text_text_path": str(off_topic_path),
            },
            {
                "paper_id": "protocol",
                "title": "Trial protocol for early detection screening",
                "abstract": "Relevant protocol.",
                "doi": "10.123/protocol",
                "scope_decision": "include",
                "full_text_text_path": str(off_topic_path),
            },
            {
                "paper_id": "off_topic",
                "title": "Primary study with no useful topic evidence",
                "abstract": "No relevant evidence.",
                "doi": "10.123/off-topic",
                "scope_decision": "include",
                "full_text_text_path": str(off_topic_path),
            },
        ],
        [
            "paper_id",
            "title",
            "abstract",
            "doi",
            "scope_decision",
            "full_text_text_path",
        ],
    )
    client = StaticJSONClient([])

    result = run_calibrate_topic_contract(
        papers_path,
        contract_path,
        "test-model",
        client=client,
        trace_dir=tmp_path / "traces",
        max_primary_papers=3,
    )

    assert result.row_counts["primary_full_texts_selected"] == 0
    assert result.metadata["calibration_skipped"] is True
    assert "topic-specific evidence" in result.warnings[0]
    assert client.requests == []
    assert load_topic_contract(contract_path) == contract


def test_generate_rules_repairs_invalid_fallback_values(tmp_path: Path) -> None:
    config_path = tmp_path / "config.json"
    output_path = tmp_path / "rules.json"
    config = {
        "research_topic": {"title": "Topic", "description": "Description"},
        "categories": [
            {
                "category_id": "main_topic_category",
                "required": False,
                "allowed_values": [
                    {"value": "mci_detection"},
                    {"value": "mixed_or_unclear"},
                ],
            },
            {
                "category_id": "evidence_modality_family",
                "required": False,
                "allowed_values": [
                    {"value": "neuroimaging"},
                    {"value": "unclear"},
                ],
            },
        ],
    }
    config_path.write_text(json.dumps(config), encoding="utf-8")
    client = StaticJSONClient(
        [
            {
                "rules": [
                    {
                        "category_id": "main_topic_category",
                        "selection": "single",
                        "required": False,
                        "fallback_value": "unclear",
                        "reason": "Model picked a generic fallback.",
                    },
                    {
                        "category_id": "evidence_modality_family",
                        "selection": "multi",
                        "required": False,
                        "fallback_value": "not_reported",
                        "reason": "Model picked a missing-information fallback.",
                    },
                ]
            }
        ]
    )

    result = run_generate_rules(
        config_path,
        output_path,
        "test-model",
        TOPIC_CONTRACT,
        client,
        tmp_path / "traces",
    )

    payload = json.loads(output_path.read_text(encoding="utf-8"))
    rules = {rule["category_id"]: rule for rule in payload["rules"]}
    assert rules["main_topic_category"]["fallback_value"] == "mixed_or_unclear"
    assert rules["evidence_modality_family"]["fallback_value"] == "unclear"
    assert result.warnings == [
        "Repaired invalid fallback_value for main_topic_category: unclear -> mixed_or_unclear",
        "Repaired invalid fallback_value for evidence_modality_family: not_reported -> unclear",
    ]
    assert '"main_topic_category": "mixed_or_unclear"' in client.requests[0][
        "prompt"
    ]
    assert '"evidence_modality_family": "unclear"' in client.requests[0]["prompt"]


def test_generate_rules_allows_null_fallback_for_exhaustive_categories(
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "config.json"
    output_path = tmp_path / "rules.json"
    config = {
        "research_topic": {"title": "Topic", "description": "Description"},
        "categories": [
            {
                "category_id": "research_goal",
                "required": True,
                "selection": "single",
                "allowed_values": [
                    {"value": "diagnosis"},
                    {"value": "prognosis"},
                    {"value": "treatment"},
                ],
            }
        ],
    }
    config_path.write_text(json.dumps(config), encoding="utf-8")
    client = StaticJSONClient(
        [
            {
                "rules": [
                    {
                        "category_id": "research_goal",
                        "selection": "single",
                        "required": True,
                        "fallback_value": "unclear",
                        "reason": "The model should not invent fallback values.",
                    }
                ]
            }
        ]
    )

    result = run_generate_rules(
        config_path,
        output_path,
        "test-model",
        TOPIC_CONTRACT,
        client,
        tmp_path / "traces",
    )

    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert payload["rules"][0]["fallback_value"] is None
    assert result.warnings == [
        "Repaired invalid fallback_value for research_goal: unclear -> None",
    ]
    assert '"research_goal": null' in client.requests[0]["prompt"]


def test_generate_rules_removes_biased_concrete_fallback_for_exhaustive_category(
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "config.json"
    output_path = tmp_path / "rules.json"
    config = {
        "research_topic": {"title": "Topic", "description": "Description"},
        "categories": [
            {
                "category_id": "dominant_focus",
                "required": True,
                "selection": "single",
                "allowed_values": [
                    {"value": "screening_detection"},
                    {"value": "treatment_effectiveness"},
                    {"value": "engagement_acceptability"},
                ],
            }
        ],
    }
    config_path.write_text(json.dumps(config), encoding="utf-8")
    client = StaticJSONClient(
        [
            {
                "rules": [
                    {
                        "category_id": "dominant_focus",
                        "selection": "single",
                        "required": True,
                        "fallback_value": "treatment_effectiveness",
                        "reason": "The model picked the broadest value.",
                    }
                ]
            }
        ]
    )

    result = run_generate_rules(
        config_path,
        output_path,
        "test-model",
        TOPIC_CONTRACT,
        client,
        tmp_path / "traces",
    )

    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert payload["rules"][0]["fallback_value"] is None
    assert result.warnings == [
        (
            "Repaired biased fallback_value for dominant_focus: "
            "treatment_effectiveness -> None"
        ),
    ]


def test_tag_papers_uses_fake_client_and_writes_flat_csv(tmp_path: Path) -> None:
    papers_path = tmp_path / "scope.csv"
    config_path = tmp_path / "config.json"
    rules_path = tmp_path / "rules.json"
    output_path = tmp_path / "filled.csv"
    full_text_path = tmp_path / "p1_full_text.txt"
    full_text_path.write_text(
        (
            "Introduction\nThe study concerns MCI screening.\n\n"
            "Methods\nParticipants completed cognitive tests and imaging.\n\n"
            "Results\nThe model improved early detection.\n\n"
        )
        * 20,
        encoding="utf-8",
    )
    write_csv(
        papers_path,
        [
            {
                "paper_id": "p1",
                "title": "MCI screening",
                "year": "2024",
                "doi": "10.123/example",
                "abstract": "Screening for MCI.",
                "authors": "A. Author",
                "venue": "Journal",
                "source": "test",
                "full_text_path": "",
                "full_text_text_path": str(full_text_path),
                "full_text_status": "local_text_extracted",
                "scope_decision": "include",
            }
        ],
        [
            "paper_id",
            "title",
            "year",
            "doi",
            "abstract",
            "authors",
            "venue",
            "source",
            "full_text_path",
            "full_text_text_path",
            "full_text_status",
            "scope_decision",
        ],
    )
    config = {
        "research_topic": {"title": "Topic", "description": "Description"},
        "categories": [
            {
                "category_id": "review_status",
                "required": True,
                "allowed_values": [
                    {"value": "ai_tagged"},
                    {"value": "full_text_needed"},
                ],
            }
        ],
    }
    rules = {
        "rules": [
            {
                "category_id": "review_status",
                "selection": "single",
                "required": True,
                "fallback_value": "ai_tagged",
                "reason": "Required.",
            }
        ]
    }
    config_path.write_text(json.dumps(config), encoding="utf-8")
    rules_path.write_text(json.dumps(rules), encoding="utf-8")
    client = StaticJSONClient(
        [
            {
                "paper_id": "p1",
                "main_knowledge_claim": "The paper screens for MCI.",
                "review_status": ["ai_tagged"],
            }
        ]
    )

    result = run_tag_papers(
        papers_path,
        config_path,
        rules_path,
        output_path,
        "test-model",
        TOPIC_CONTRACT,
        client,
        tmp_path / "traces",
    )

    rows = list(csv.DictReader(output_path.open(newline="", encoding="utf-8")))
    assert result.row_counts["tagged_papers"] == 1
    assert rows[0]["main_knowledge_claim"] == "The paper screens for MCI."
    assert rows[0]["abstract"] == "Screening for MCI."
    assert rows[0]["review_status"] == "ai_tagged"
    assert "full_text_evidence" in client.requests[0]["prompt"]
    assert "model improved early detection" in client.requests[0][
        "prompt"
    ]


def test_tag_papers_requires_abstract_or_extracted_full_text(
    tmp_path: Path,
) -> None:
    papers_path = tmp_path / "scope.csv"
    config_path = tmp_path / "config.json"
    rules_path = tmp_path / "rules.json"
    output_path = tmp_path / "filled.csv"
    full_text_path = tmp_path / "p3_full_text.txt"
    full_text_path.write_text(
        (
            "Methods\nThe study used imaging and cognitive tests.\n\n"
            "Results\nThe model identified Alzheimer's disease.\n\n"
        )
        * 20,
        encoding="utf-8",
    )
    write_csv(
        papers_path,
        [
            {
                "paper_id": "p1",
                "title": "Title-only survey",
                "abstract": "",
                "full_text_status": "extraction_failed",
                "full_text_text_path": "",
                "scope_decision": "include",
            },
            {
                "paper_id": "p2",
                "title": "Abstract-only study",
                "abstract": "The abstract reports an AI diagnostic model.",
                "full_text_status": "extraction_failed",
                "full_text_text_path": "",
                "scope_decision": "include",
            },
            {
                "paper_id": "p3",
                "title": "Full-text study",
                "abstract": "",
                "full_text_status": "local_text_extracted",
                "full_text_text_path": str(full_text_path),
                "scope_decision": "include",
            },
        ],
        [
            "paper_id",
            "title",
            "abstract",
            "full_text_status",
            "full_text_text_path",
            "scope_decision",
        ],
    )
    config = {
        "research_topic": {"title": "Topic", "description": "Description"},
        "categories": [
            {
                "category_id": "review_status",
                "required": True,
                "allowed_values": [{"value": "ai_tagged"}],
            }
        ],
    }
    rules = {
        "rules": [
            {
                "category_id": "review_status",
                "selection": "single",
                "required": True,
                "fallback_value": "ai_tagged",
            }
        ]
    }
    config_path.write_text(json.dumps(config), encoding="utf-8")
    rules_path.write_text(json.dumps(rules), encoding="utf-8")
    client = StaticJSONClient(
        [
            {
                "paper_id": "p2",
                "main_knowledge_claim": "The abstract reports a diagnostic model.",
                "review_status": ["ai_tagged"],
            },
            {
                "paper_id": "p3",
                "main_knowledge_claim": "The full text reports a diagnostic model.",
                "review_status": ["ai_tagged"],
            },
        ]
    )

    result = run_tag_papers(
        papers_path,
        config_path,
        rules_path,
        output_path,
        "test-model",
        TOPIC_CONTRACT,
        client,
        tmp_path / "traces",
    )

    with output_path.open(newline="", encoding="utf-8") as handle:
        rows = {row["paper_id"]: row for row in csv.DictReader(handle)}

    assert result.row_counts == {
        "tagging_candidate_papers": 3,
        "tagged_papers": 2,
        "skipped_insufficient_evidence": 1,
        "failed_tagging_papers": 0,
        "tagging_output_rows": 3,
    }
    assert rows["p1"]["tagging_status"] == "skipped_insufficient_evidence"
    assert rows["p1"]["tagging_evidence_basis"] == "none"
    assert rows["p1"]["main_knowledge_claim"] == ""
    assert rows["p1"]["review_status"] == ""
    assert "full_text_status=extraction_failed" in rows["p1"]["tagging_error"]
    assert rows["p2"]["tagging_status"] == "tagged"
    assert rows["p2"]["tagging_evidence_basis"] == "abstract"
    assert rows["p3"]["tagging_status"] == "tagged"
    assert rows["p3"]["tagging_evidence_basis"] == "full_text"
    assert len(client.requests) == 2
    assert '"paper_id": "p2"' in client.requests[0]["prompt"]
    assert '"tagging_evidence_basis": "abstract"' in client.requests[0][
        "prompt"
    ]
    assert '"paper_id": "p3"' in client.requests[1]["prompt"]
    assert '"tagging_evidence_basis": "full_text"' in client.requests[1][
        "prompt"
    ]
    assert result.warnings == [
        "Skipped paper 'p1': no usable abstract or extracted full text is "
        "available (full_text_status=extraction_failed)."
    ]


def test_tagging_payload_distinguishes_locator_from_resolved_document() -> None:
    payload = paper_text(
        {
            "paper_id": "p1",
            "title": "Evidence-backed study",
            "abstract": "A substantive abstract reports diagnostic performance.",
            "full_text_url": "https://example.org/original-locator",
            "full_text_resolved_url": "https://example.org/resolved-document.pdf",
            "full_text_source": "provider_metadata",
            "full_text_resolved_source": "landing_pdf",
        }
    )

    assert payload["full_text_availability_url"] == (
        "https://example.org/original-locator"
    )
    assert payload["full_text_url"] == (
        "https://example.org/resolved-document.pdf"
    )
    assert payload["full_text_source"] == "landing_pdf"


def test_tag_papers_full_text_required_policy_preserves_abstract_only_row(
    tmp_path: Path,
) -> None:
    papers_path = tmp_path / "scope.csv"
    config_path = tmp_path / "config.json"
    rules_path = tmp_path / "rules.json"
    contract_path = tmp_path / "contract.yaml"
    output_path = tmp_path / "filled.csv"
    write_csv(
        papers_path,
        [
            {
                "paper_id": "p1",
                "title": "Abstract-only study",
                "abstract": "A substantive abstract reports a diagnostic model.",
                "full_text_status": "extraction_failed",
                "full_text_text_path": "",
                "scope_decision": "include",
            }
        ],
        [
            "paper_id",
            "title",
            "abstract",
            "full_text_status",
            "full_text_text_path",
            "scope_decision",
        ],
    )
    config = {
        "research_topic": {"title": "Topic", "description": "Description"},
        "categories": [
            {
                "category_id": "review_status",
                "required": True,
                "allowed_values": [{"value": "ai_tagged"}],
            }
        ],
    }
    rules = {
        "rules": [
            {
                "category_id": "review_status",
                "selection": "single",
                "required": True,
                "fallback_value": "ai_tagged",
            }
        ]
    }
    config_path.write_text(json.dumps(config), encoding="utf-8")
    rules_path.write_text(json.dumps(rules), encoding="utf-8")
    contract = load_topic_contract(TOPIC_CONTRACT)
    contract["tagging"]["evidence_policy"] = "full_text_required"
    write_yaml_object(contract_path, contract)
    client = StaticJSONClient([])

    result = run_tag_papers(
        papers_path,
        config_path,
        rules_path,
        output_path,
        "test-model",
        contract_path,
        client,
        tmp_path / "traces",
    )

    row = next(csv.DictReader(output_path.open(newline="", encoding="utf-8")))
    assert row["tagging_status"] == "skipped_insufficient_evidence"
    assert row["tagging_evidence_basis"] == "none"
    assert "identity-verified remote extracted full text" in row["tagging_error"]
    assert result.row_counts["tagged_papers"] == 0
    assert result.row_counts["skipped_insufficient_evidence"] == 1
    assert result.metadata["tagging_evidence_policy"] == "full_text_required"
    assert client.requests == []


def test_tag_papers_preserves_failed_llm_row_with_error_state(
    tmp_path: Path,
) -> None:
    papers_path = tmp_path / "scope.csv"
    config_path = tmp_path / "config.json"
    rules_path = tmp_path / "rules.json"
    output_path = tmp_path / "filled.csv"
    write_csv(
        papers_path,
        [
            {
                "paper_id": "p1",
                "title": "Evidence-backed study",
                "abstract": "A substantive abstract reports diagnostic performance.",
                "scope_decision": "include",
            }
        ],
        ["paper_id", "title", "abstract", "scope_decision"],
    )
    config = {
        "research_topic": {"title": "Topic", "description": "Description"},
        "categories": [
            {
                "category_id": "review_status",
                "required": True,
                "allowed_values": [{"value": "ai_tagged"}],
            }
        ],
    }
    rules = {
        "rules": [
            {
                "category_id": "review_status",
                "selection": "single",
                "required": True,
            }
        ]
    }
    config_path.write_text(json.dumps(config), encoding="utf-8")
    rules_path.write_text(json.dumps(rules), encoding="utf-8")
    client = RaisingJSONClient(ValueError("model response unavailable"))

    result = run_tag_papers(
        papers_path,
        config_path,
        rules_path,
        output_path,
        "test-model",
        TOPIC_CONTRACT,
        client,
        tmp_path / "traces",
    )

    row = next(csv.DictReader(output_path.open(newline="", encoding="utf-8")))
    assert row["paper_id"] == "p1"
    assert row["tagging_status"] == "failed"
    assert row["tagging_evidence_basis"] == "abstract"
    assert row["tagging_error"] == "model response unavailable"
    assert row["main_knowledge_claim"] == ""
    assert row["review_status"] == ""
    assert result.row_counts["failed_tagging_papers"] == 1
    assert result.row_counts["tagging_output_rows"] == 1


def test_tag_papers_rejects_category_collision_with_input_provenance(
    tmp_path: Path,
) -> None:
    papers_path = tmp_path / "scope.csv"
    config_path = tmp_path / "config.json"
    rules_path = tmp_path / "rules.json"
    output_path = tmp_path / "filled.csv"
    write_csv(
        papers_path,
        [
            {
                "paper_id": "p1",
                "title": "Evidence-backed study",
                "abstract": "A substantive abstract reports diagnostic performance.",
                "review_status": "provider_supplied_value",
            }
        ],
        ["paper_id", "title", "abstract", "review_status"],
    )
    config_path.write_text(
        json.dumps(
            {
                "categories": [
                    {
                        "category_id": "review_status",
                        "allowed_values": [{"value": "ai_tagged"}],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    rules_path.write_text(json.dumps({"rules": []}), encoding="utf-8")

    with pytest.raises(ValueError, match="collide with preserved input columns"):
        run_tag_papers(
            papers_path,
            config_path,
            rules_path,
            output_path,
            "test-model",
            TOPIC_CONTRACT,
            StaticJSONClient([]),
            tmp_path / "traces",
        )


def test_tag_papers_rejects_reserved_state_category_id(tmp_path: Path) -> None:
    papers_path = tmp_path / "scope.csv"
    config_path = tmp_path / "config.json"
    rules_path = tmp_path / "rules.json"
    output_path = tmp_path / "filled.csv"
    write_csv(
        papers_path,
        [
            {
                "paper_id": "p1",
                "title": "Evidence-backed study",
                "abstract": "A substantive abstract reports diagnostic performance.",
            }
        ],
        ["paper_id", "title", "abstract"],
    )
    config_path.write_text(
        json.dumps(
            {
                "categories": [
                    {
                        "category_id": "tagging_status",
                        "allowed_values": [{"value": "model_label"}],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    rules_path.write_text(json.dumps({"rules": []}), encoding="utf-8")

    with pytest.raises(ValueError, match="use reserved output columns"):
        run_tag_papers(
            papers_path,
            config_path,
            rules_path,
            output_path,
            "test-model",
            TOPIC_CONTRACT,
            StaticJSONClient([]),
            tmp_path / "traces",
        )


def test_tag_papers_can_write_review_labels_in_same_llm_call(
    tmp_path: Path,
) -> None:
    papers_path = tmp_path / "scope.csv"
    config_path = tmp_path / "config.json"
    rules_path = tmp_path / "rules.json"
    output_path = tmp_path / "filled.csv"
    review_config_path = tmp_path / "review_config.json"
    review_output_path = tmp_path / "review_labels.csv"
    full_text_path = tmp_path / "p1_full_text.txt"
    full_text_path.write_text(
        (
            "Methods\nThe authors used MRI classification.\n\n"
            "Results\nThe model improved early detection.\n\n"
        )
        * 20,
        encoding="utf-8",
    )
    write_csv(
        papers_path,
        [
            {
                "paper_id": "p1",
                "title": "MCI screening",
                "year": "2024",
                "doi": "10.123/example",
                "abstract": "Screening for MCI.",
                "authors": "A. Author",
                "venue": "Journal",
                "source": "test",
                "full_text_text_path": str(full_text_path),
                "scope_decision": "include",
            }
        ],
        [
            "paper_id",
            "title",
            "year",
            "doi",
            "abstract",
            "authors",
            "venue",
            "source",
            "full_text_text_path",
            "scope_decision",
        ],
    )
    config = {
        "research_topic": {"title": "Topic", "description": "Description"},
        "categories": [
            {
                "category_id": "review_status",
                "required": True,
                "allowed_values": [{"value": "ai_tagged"}],
            }
        ],
    }
    rules = {
        "rules": [
            {
                "category_id": "review_status",
                "selection": "single",
                "required": True,
                "fallback_value": "ai_tagged",
                "reason": "Required.",
            }
        ]
    }
    contract = deepcopy(load_topic_contract(TOPIC_CONTRACT))
    contract["review"] = {
        "labels": {
            "main_topic": {
                "description": "Best topic-structure main topic.",
                "value_mode": "controlled_fixed",
                "selection": "single",
                "values_from": "topic_structure.main_topics",
                "evidence_sections": ["title", "abstract"],
            },
            "methodology": {
                "description": "Methods used in the paper.",
                "value_mode": "controlled_auto",
                "selection": "multi",
                "values": "auto",
                "evidence_sections": ["methods"],
            },
        }
    }
    config_path.write_text(json.dumps(config), encoding="utf-8")
    rules_path.write_text(json.dumps(rules), encoding="utf-8")
    review_config_path.write_text(
        json.dumps(normalize_review_config(contract)),
        encoding="utf-8",
    )
    client = StaticJSONClient(
        [
            {
                "knowledge_tags": {
                    "paper_id": "p1",
                    "main_knowledge_claim": "The paper screens for MCI.",
                    "review_status": ["ai_tagged"],
                },
                "review_labels": {
                    "paper_id": "p1",
                    "labels": {
                        "main_topic": ["early_detection"],
                        "methodology": ["MRI Classification"],
                    },
                    "evidence_sections_used": ["methods"],
                    "extraction_notes": [],
                },
            }
        ]
    )

    result = run_tag_papers(
        papers_path,
        config_path,
        rules_path,
        output_path,
        "test-model",
        TOPIC_CONTRACT,
        client,
        tmp_path / "traces",
        review_config_path=review_config_path,
        review_output_path=review_output_path,
    )

    knowledge_rows = list(csv.DictReader(output_path.open(newline="", encoding="utf-8")))
    review_rows = list(
        csv.DictReader(review_output_path.open(newline="", encoding="utf-8"))
    )
    assert result.row_counts["tagged_papers"] == 1
    assert result.row_counts["review_labeled_papers"] == 1
    assert knowledge_rows[0]["main_knowledge_claim"] == "The paper screens for MCI."
    assert review_rows[0]["main_topic"] == "early_detection"
    assert review_rows[0]["methodology"] == "mri_classification"
    assert len(client.requests) == 1
    assert client.requests[0]["schema_name"] == "paper_tags_with_review"
    assert "Section-focused review evidence" in client.requests[0]["prompt"]


def test_tag_papers_review_max_limits_same_pass_review_labels(
    tmp_path: Path,
) -> None:
    papers_path = tmp_path / "scope.csv"
    review_papers_path = tmp_path / "review_eligible.csv"
    config_path = tmp_path / "config.json"
    rules_path = tmp_path / "rules.json"
    output_path = tmp_path / "filled.csv"
    review_config_path = tmp_path / "review_config.json"
    review_output_path = tmp_path / "review_labels.csv"
    full_text_path = tmp_path / "full_text.txt"
    full_text_path.write_text(
        "Methods\nThe authors used MRI classification.\n\n"
        "Results\nThe model improved early detection.\n",
        encoding="utf-8",
    )
    rows = [
        {
            "paper_id": "p1",
            "title": "First MCI screening paper",
            "year": "2024",
            "doi": "10.123/one",
            "abstract": "Screening for MCI.",
            "authors": "A. Author",
            "venue": "Journal",
            "source": "test",
            "full_text_text_path": str(full_text_path),
            "scope_decision": "include",
        },
        {
            "paper_id": "p2",
            "title": "Second MCI screening paper",
            "year": "2024",
            "doi": "10.123/two",
            "abstract": "Screening for MCI.",
            "authors": "B. Author",
            "venue": "Journal",
            "source": "test",
            "full_text_text_path": str(full_text_path),
            "scope_decision": "include",
        },
    ]
    fieldnames = [
        "paper_id",
        "title",
        "year",
        "doi",
        "abstract",
        "authors",
        "venue",
        "source",
        "full_text_text_path",
        "scope_decision",
    ]
    write_csv(papers_path, rows, fieldnames)
    write_csv(review_papers_path, rows, fieldnames)
    config = {
        "research_topic": {"title": "Topic", "description": "Description"},
        "categories": [
            {
                "category_id": "review_status",
                "required": True,
                "allowed_values": [{"value": "ai_tagged"}],
            }
        ],
    }
    rules = {
        "rules": [
            {
                "category_id": "review_status",
                "selection": "single",
                "required": True,
                "fallback_value": "ai_tagged",
                "reason": "Required.",
            }
        ]
    }
    contract = deepcopy(load_topic_contract(TOPIC_CONTRACT))
    contract["review"] = {
        "labels": {
            "main_topic": {
                "description": "Best topic-structure main topic.",
                "value_mode": "controlled_fixed",
                "selection": "single",
                "values_from": "topic_structure.main_topics",
                "evidence_sections": ["title", "abstract"],
            },
        }
    }
    config_path.write_text(json.dumps(config), encoding="utf-8")
    rules_path.write_text(json.dumps(rules), encoding="utf-8")
    review_config_path.write_text(
        json.dumps(normalize_review_config(contract)),
        encoding="utf-8",
    )
    client = StaticJSONClient(
        [
            {
                "knowledge_tags": {
                    "paper_id": "p1",
                    "main_knowledge_claim": "The first paper screens for MCI.",
                    "review_status": ["ai_tagged"],
                },
                "review_labels": {
                    "paper_id": "p1",
                    "labels": {"main_topic": ["early_detection"]},
                    "evidence_sections_used": ["abstract"],
                    "extraction_notes": [],
                },
            },
            {
                "paper_id": "p2",
                "main_knowledge_claim": "The second paper screens for MCI.",
                "review_status": ["ai_tagged"],
            },
        ]
    )

    result = run_tag_papers(
        papers_path,
        config_path,
        rules_path,
        output_path,
        "test-model",
        TOPIC_CONTRACT,
        client,
        tmp_path / "traces",
        review_config_path=review_config_path,
        review_output_path=review_output_path,
        review_papers_path=review_papers_path,
        review_max_papers=1,
    )

    review_rows = list(
        csv.DictReader(review_output_path.open(newline="", encoding="utf-8"))
    )
    assert result.row_counts["tagged_papers"] == 2
    assert result.row_counts["review_eligible_papers"] == 2
    assert result.row_counts["review_selected_papers"] == 1
    assert result.row_counts["review_max_papers"] == 1
    assert result.row_counts["review_labeled_papers"] == 1
    assert [request["schema_name"] for request in client.requests] == [
        "paper_tags_with_review",
        "paper_tags",
    ]
    assert [row["paper_id"] for row in review_rows] == ["p1"]


def test_validate_tagged_row_allows_optional_and_clears_inapplicable_values() -> None:
    config = {
        "categories": [
            {
                "category_id": "ai_method",
                "required": False,
                "selection": "multi",
                "allowed_values": [
                    {"value": "machine_learning"},
                    {"value": "deep_learning"},
                    {"value": "unclear"},
                ],
            },
            {
                "category_id": "deep_learning_architecture",
                "required": False,
                "selection": "multi",
                "allowed_values": [
                    {"value": "cnn"},
                    {"value": "transformer"},
                    {"value": "unclear"},
                ],
                "applies_when": {
                    "category_id": "ai_method",
                    "values": ["deep_learning"],
                },
            },
        ],
    }
    rules = {
        "rules": [
            {
                "category_id": "ai_method",
                "selection": "multi",
                "required": False,
                "fallback_value": "unclear",
                "reason": "Optional method tag.",
            },
            {
                "category_id": "deep_learning_architecture",
                "selection": "multi",
                "required": False,
                "fallback_value": "unclear",
                "reason": "Only applies to deep learning papers.",
                "applies_when": {
                    "category_id": "ai_method",
                    "values": ["deep_learning"],
                },
            },
        ]
    }
    tagged = {
        "ai_method": ["machine_learning"],
        "deep_learning_architecture": ["cnn"],
    }

    validate_tagged_row(tagged, config, rules)

    assert tagged["deep_learning_architecture"] == []


def test_validate_tagged_row_removes_fallback_when_concrete_values_exist() -> None:
    config = {
        "categories": [
            {
                "category_id": "health_outcome",
                "required": True,
                "selection": "multi",
                "allowed_values": [
                    {"value": "hypertension"},
                    {"value": "ischemic_heart_disease"},
                    {"value": "not_reported"},
                ],
            }
        ],
    }
    rules = {
        "rules": [
            {
                "category_id": "health_outcome",
                "selection": "multi",
                "required": True,
                "fallback_value": "not_reported",
                "reason": "Required outcome tag.",
            }
        ]
    }
    tagged = {
        "health_outcome": [
            "hypertension",
            "not_reported",
            "ischemic_heart_disease",
        ],
    }

    validate_tagged_row(tagged, config, rules)

    assert tagged["health_outcome"] == [
        "hypertension",
        "ischemic_heart_disease",
    ]


def test_paper_tags_schema_constrains_category_values() -> None:
    config = {
        "categories": [
            {
                "category_id": "impact_category",
                "allowed_values": [
                    {"value": "physical_health"},
                    {"value": "vulnerable_populations"},
                ],
            }
        ]
    }

    schema = paper_tags_schema(config)

    assert schema["properties"]["impact_category"]["items"]["enum"] == [
        "physical_health",
        "vulnerable_populations",
    ]
