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
    assert "climate_change" not in contract["topic_structure"]["secondary_topics"]
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
                        "secondary_topic_id": "formal_education_secondary_1",
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
                        "secondary_topic_id": "learning_impact_secondary_1",
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
    assert result.row_counts["final_included_rows"] == 2
    assert len(rows) == 3
    assert rows[-1]["screening_decision"] == "include"
    assert len(read_jsonl_objects(deduped_path)) == 3
    assert len(client.requests) == 1


def test_backfill_repeats_until_threshold_is_reached(
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
    assert result.row_counts["backfill_rounds"] == 2
    assert result.row_counts["backfill_candidates_fetched"] == 3
    assert result.row_counts["backfill_included_rows"] == 2
    assert result.row_counts["final_included_rows"] == 9
    assert fake_provider.calls == [(1, 10, 2), (2, 12, 1)]
    assert len(read_jsonl_objects(deduped_path)) == 13
    assert len(client.requests) == 3
    assert not result.warnings


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
