from __future__ import annotations

import csv
import json
from copy import deepcopy
from pathlib import Path

from ad_lit_pipeline.llm.client import StaticJSONClient
from ad_lit_pipeline.llm.schemas import paper_tags_schema
from ad_lit_pipeline.io.jsonl_io import write_jsonl
from ad_lit_pipeline.io.yaml_io import write_yaml_object
from ad_lit_pipeline.steps.collection.plan_search import (
    enforce_topic_plan_constraints,
    ensure_search_queries,
    run as run_plan_search,
)
from ad_lit_pipeline.steps.collection.generate_topic_contract import (
    contract_from_model_payload,
    run as run_generate_topic_contract,
)
from ad_lit_pipeline.steps.collection.refine_topic_contract import (
    run as run_refine_topic_contract,
)
from ad_lit_pipeline.steps.screening.llm_candidate_screening import run as run_screening
from ad_lit_pipeline.steps.screening.title_relevance import run as run_title_relevance
from ad_lit_pipeline.steps.tagging.generate_rules import run as run_generate_rules
from ad_lit_pipeline.steps.tagging.tag_papers import (
    run as run_tag_papers,
    validate_tagged_row,
)
from ad_lit_pipeline.topics.contract import load_topic_contract


ROOT = Path(__file__).resolve().parents[1]
TOPIC_CONTRACT = ROOT / "configs/topics/early_detection_ad.yaml"


def write_csv(path: Path, rows: list[dict[str, str]], fieldnames: list[str]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


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
        "knowledge_goal": {
            "required": True,
            "selection": "single",
            "values": [
                "performance_effect",
                "engagement_pattern",
                "learning_process",
                "access_equity",
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
    return payload


def test_generated_contract_payload_normalizes_tag_labels() -> None:
    payload = generated_topic_contract_payload()
    payload["tagging"]["categories"] = [
        {
            "category_id": "Knowledge Goal",
            "description": "Root category.",
            "required": True,
            "selection": "single",
            "values": [
                "Sleep Quality Analysis",
                "stress-outcome evaluation",
                "urban/design effects",
            ],
            "applies_when": None,
        },
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
        "knowledge_goal",
        "green_space_type",
        "green_space_detail",
    ]
    assert categories["knowledge_goal"]["values"] == [
        "sleep_quality_analysis",
        "stress_outcome_evaluation",
        "urban_design_effects",
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
                            "category_id": "knowledge_goal",
                            "description": (
                                "Top-level partition of climate-health papers by "
                                "their main knowledge contribution."
                            ),
                            "required": True,
                            "selection": "single",
                            "values": [
                                "exposure_risk_assessment",
                                "health_impact_estimation",
                                "adaptation_or_response",
                                "policy_or_system_planning",
                            ],
                            "applies_when": None,
                        },
                        {
                            "category_id": "climate_exposure",
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
                            "category_id": "health_outcome",
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
    assert contract["tagging"]["categories"]["health_outcome"]["selection"] == "multi"
    assert contract["tagging"]["categories"]["heat_adaptation_detail"][
        "applies_when"
    ] == {"category_id": "adaptation_strategy", "values": ["heat_action_plan"]}
    assert contract["candidate_screening"]["borderline_policy"] == "include"
    assert "climate_change" not in contract["topic_structure"]["secondary_topics"]
    assert result.row_counts["search_queries"] == 3
    assert result.trace_paths


def test_generate_topic_contract_retries_with_tagging_quality_feedback(
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
    client = StaticJSONClient([weak_payload, generated_topic_contract_payload()])
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
    assert len(client.requests) == 2
    retry_prompt = client.requests[1]["prompt"]
    assert client.requests[0]["call_id"] == "contract"
    assert client.requests[1]["call_id"] == "contract_retry_2"
    assert "self-help_resources" in retry_prompt
    assert "target_population" in retry_prompt
    assert "study_design" in retry_prompt
    assert "check every validation path above" in retry_prompt
    assert "self_help_resources" in retry_prompt
    assert "Do not keep generic category ids" in retry_prompt
    assert "target_population" not in categories
    assert "study_design" not in categories
    assert result.row_counts["tagging_categories"] == 7


def test_generate_topic_contract_retries_from_best_failed_contract(
    tmp_path: Path,
) -> None:
    first_payload = generated_topic_contract_payload()
    first_payload["tagging"]["categories"]["study_design"] = {
        "required": False,
        "selection": "multi",
        "values": ["cross_sectional", "longitudinal", "experimental"],
    }
    worse_payload = generated_topic_contract_payload()
    worse_payload["tagging"]["categories"]["study_design"] = {
        "required": False,
        "selection": "multi",
        "values": ["cross_sectional", "longitudinal", "experimental"],
    }
    worse_payload["tagging"]["categories"]["study_population"] = {
        "required": False,
        "selection": "multi",
        "values": ["adults", "children", "general_population"],
    }
    client = StaticJSONClient(
        [first_payload, worse_payload, generated_topic_contract_payload()]
    )
    output = tmp_path / "contract.yaml"

    result = run_generate_topic_contract(
        "How do AI tools affect student performance?",
        output,
        "test-model",
        client=client,
        trace_dir=tmp_path / "traces",
    )

    retry_3_prompt = client.requests[2]["prompt"]
    assert result.row_counts["tagging_categories"] == 7
    assert len(client.requests) == 3
    assert client.requests[2]["call_id"] == "contract_retry_3"
    assert "Best response so far" in retry_3_prompt
    assert "tagging.categories.study_design is a generic boilerplate" in retry_3_prompt
    worse_issue = "tagging.categories.study_population is a generic boilerplate"
    assert worse_issue not in retry_3_prompt
    assert '"ai_tool_type"' in retry_3_prompt


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
            {
                "provider_id": "W1",
                "title": "Review of AI biomarkers for early AD detection",
                "year": 2024,
                "venue": "Example Reviews",
                "abstract": (
                    "This overview maps neuroimaging, speech, cognitive tests, "
                    "and model validation practices for early AD detection."
                ),
                "query": "early detection Alzheimer's review",
                "raw_record": {
                    "type": "review",
                    "open_access": {"is_oa": True},
                    "best_oa_location": {"pdf_url": "https://example.test/paper.pdf"},
                },
            }
        ],
    )

    refined_payload = deepcopy(contract)
    refined_payload["research_topic"]["title"] = "Changed outside tagging"
    refined_payload["tagging"]["categories"] = [
        {
            "category_id": "knowledge_goal",
            "description": (
                "Review-derived top-level partition of early AD computational "
                "biology papers by their main knowledge goal."
            ),
            "required": True,
            "selection": "single",
            "values": [
                "risk_prediction",
                "diagnosis",
                "disease_observation",
                "intervention_planning",
            ],
            "applies_when": None,
        },
        {
            "category_id": "evidence_signal_family",
            "description": "Evidence signal families used for early AD detection.",
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
        {
            "category_id": "detection_outcome",
            "description": "Detection outcomes emphasized by review evidence.",
            "required": False,
            "selection": "multi",
            "values": [
                "diagnostic_accuracy",
                "conversion_prediction",
                "screening_feasibility",
                "treatment_response_prediction",
            ],
            "applies_when": None,
        },
        {
            "category_id": "modeling_approach",
            "description": "Analytic modeling approaches used for early detection.",
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
        {
            "category_id": "validation_context",
            "description": "Validation settings reported for detection evidence.",
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
        {
            "category_id": "clinical_detection_context",
            "description": (
                "Review evidence distinguishes screening, diagnosis, and "
                "monitoring contexts."
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
        {
            "category_id": "biomarker_data_source",
            "description": (
                "Review evidence reports different data sources used for early "
                "detection biomarkers."
            ),
            "required": False,
            "selection": "multi",
            "values": [
                "imaging_data",
                "speech_language_data",
                "cognitive_test_data",
                "blood_or_csf_data",
            ],
            "applies_when": None,
        },
    ]
    client = StaticJSONClient([refined_payload])

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
    assert "main_topic_category" not in categories
    assert refined["research_topic"] == contract["research_topic"]
    assert refined["topic_structure"] == contract["topic_structure"]
    assert "evidence_signal_family" in categories
    assert "detection_outcome" in categories
    assert result.row_counts["review_overviews"] == 1
    assert result.row_counts["tagging_categories"] == 7
    assert result.trace_paths
    assert "Review and overview seed papers" in client.requests[0]["prompt"]
    assert "AI biomarkers" in client.requests[0]["prompt"]


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
                    {"main_topic_id": "formal_education", "terms": ["university"]}
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
                    {"main_topic_id": "learning_impact", "terms": ["well-being"]}
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
    assert client.requests[0]["schema_name"] == "title_relevance_screening"


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
                "category_id": "knowledge_goal",
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
                        "category_id": "knowledge_goal",
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
            "Repaired biased fallback_value for knowledge_goal: "
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
