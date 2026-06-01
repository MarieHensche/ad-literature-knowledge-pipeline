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
from ad_lit_pipeline.steps.collection.targeted_collect import run as run_targeted_collect
from ad_lit_pipeline.steps.collection import fetch_candidates as fetch_candidates_step
from ad_lit_pipeline.steps.collection.generate_topic_contract import (
    run as run_generate_topic_contract,
)
from ad_lit_pipeline.steps.collection.refine_topic_contract import (
    run as run_refine_topic_contract,
)
from ad_lit_pipeline.steps.screening.llm_candidate_screening import run as run_screening
from ad_lit_pipeline.steps.tagging.generate_rules import run as run_generate_rules
from ad_lit_pipeline.steps.tagging.tag_papers import run as run_tag_papers
from ad_lit_pipeline.topics.contract import load_topic_contract


ROOT = Path(__file__).resolve().parents[1]
TOPIC_CONTRACT = ROOT / "configs/topics/early_detection_ad.yaml"


def write_csv(path: Path, rows: list[dict[str, str]], fieldnames: list[str]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


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
                        "knowledge_confidence": "very_low",
                        "review_status": "ai_tagged",
                    },
                    "categories": [
                        {
                            "category_id": "main_topic_category",
                            "required": False,
                            "values": [
                                "health_impact",
                                "adaptation",
                                "mixed_or_unclear",
                                "unclear",
                            ],
                        },
                        {
                            "category_id": "research_target",
                            "required": False,
                            "values": [
                                "mortality",
                                "morbidity",
                                "mental_health",
                                "mixed_or_unclear",
                                "unclear",
                            ],
                        },
                        {
                            "category_id": "study_type",
                            "required": False,
                            "values": ["empirical", "review", "unclear"],
                        },
                        {
                            "category_id": "knowledge_confidence",
                            "required": False,
                            "values": ["high", "medium", "low", "very_low"],
                        },
                        {
                            "category_id": "exposure_type",
                            "required": False,
                            "values": ["heat", "wildfire", "unclear"],
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
    assert "main_topic_category" in contract["tagging"]["categories"]
    assert contract["tagging"]["categories"]["main_topic_category"]["required"] is True
    assert contract["tagging"]["categories"]["main_topic_category"]["values"] == [
        "core_topic",
        "adjacent_but_relevant",
        "out_of_scope",
        "mixed_or_unclear",
        "unclear",
    ]
    assert contract["tagging"]["categories"]["review_status"]["required"] is True
    assert contract["tagging"]["categories"]["review_status"]["values"] == [
        "ai_tagged",
        "human_reviewed",
        "full_text_needed",
        "excluded_from_scope",
    ]
    assert contract["tagging"]["fallback_policy"]["review_status"] == "ai_tagged"
    assert contract["candidate_screening"]["borderline_policy"] == "include"
    assert result.row_counts["search_queries"] == 3
    assert result.trace_paths


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
    refined_payload["tagging"]["categories"] = [
        {
            "category_id": "main_topic_category",
            "required": False,
            "values": [
                "early_detection",
                "screening",
                "mixed_or_unclear",
                "unclear",
            ],
        },
        {
            "category_id": "research_target",
            "required": False,
            "values": ["ad", "mci", "dementia", "mixed_or_unclear", "unclear"],
        },
        {
            "category_id": "knowledge_signal_family",
            "required": False,
            "values": [
                "neuroimaging",
                "speech_language",
                "cognitive_assessment",
                "mixed_or_unclear",
                "unclear",
            ],
        },
        {
            "category_id": "knowledge_outcome_family",
            "required": False,
            "values": [
                "diagnostic_accuracy",
                "conversion_prediction",
                "screening_feasibility",
                "not_reported",
                "unclear",
            ],
        },
        {
            "category_id": "review_status",
            "required": True,
            "values": [
                "ai_tagged",
                "human_reviewed",
                "full_text_needed",
                "excluded_from_scope",
            ],
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
    assert categories["main_topic_category"]["values"] == [
        "core_topic",
        "adjacent_but_relevant",
        "out_of_scope",
        "mixed_or_unclear",
        "unclear",
    ]
    assert "knowledge_signal_family" in categories
    assert "knowledge_outcome_family" in categories
    assert result.row_counts["review_overviews"] == 1
    assert result.row_counts["tagging_categories"] == 5
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
        [
            {
                "decision": "include",
                "topic_fit": "core_topic",
                "reason": "Directly relevant.",
                "confidence": "high",
            }
        ]
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
    assert result.row_counts["core_topic"] == 1
    assert rows[0]["screening_decision"] == "include"
    assert rows[0]["screening_topic_fit"] == "core_topic"
    assert rows[0]["source_query"] == "MCI screening"
    assert "detecting MCI or cognitive impairment" in client.requests[0]["prompt"]
    assert "recall-oriented candidate-screening pass" in client.requests[0]["prompt"]
    assert "Adjacent screening query." in client.requests[0]["prompt"]


def test_targeted_collection_keeps_fetching_until_core_target(
    tmp_path: Path,
) -> None:
    class FakeProvider:
        name = "fake_provider"

        def validate_plan(self, plan: dict[str, object]) -> None:
            return None

        def iter_candidates(
            self,
            plan: dict[str, object],
            per_page: int,
            mailto: str | None,
            sleep_seconds: float,
        ):
            yield {
                "title": "Adjacent Study",
                "year": 2024,
                "doi": "10.123/adjacent",
                "provider": "fake_provider",
                "provider_id": "A1",
                "rank": 1,
                "abstract": "Adjacent topic.",
            }
            yield {
                "title": "Core Study",
                "year": 2024,
                "doi": "10.123/core",
                "provider": "fake_provider",
                "provider_id": "C1",
                "rank": 2,
                "abstract": "Core topic.",
            }
            yield {
                "title": "Duplicate Core Study",
                "year": 2024,
                "doi": "10.123/core",
                "provider": "fake_provider",
                "provider_id": "C2",
                "rank": 3,
                "abstract": "Duplicate core topic.",
            }

        def fetch_candidates(
            self,
            plan: dict[str, object],
            max_results: int,
            per_page: int,
            mailto: str | None,
            sleep_seconds: float,
        ) -> list[dict[str, object]]:
            return list(self.iter_candidates(plan, per_page, mailto, sleep_seconds))

    plan_path = tmp_path / "plan.json"
    candidates_path = tmp_path / "candidates.jsonl"
    deduped_path = tmp_path / "deduped.jsonl"
    screening_path = tmp_path / "screening.csv"
    output_path = tmp_path / "papers.csv"
    plan_path.write_text(
        json.dumps(
            {
                "recommended_provider": "fake_provider",
                "provider_specific_plan": {"provider": "fake_provider"},
            }
        ),
        encoding="utf-8",
    )
    client = StaticJSONClient(
        [
            {
                "decision": "include",
                "topic_fit": "adjacent_but_relevant",
                "reason": "Adjacent.",
                "confidence": "medium",
            },
            {
                "decision": "include",
                "topic_fit": "core_topic",
                "reason": "Core.",
                "confidence": "high",
            },
        ]
    )
    original_provider = fetch_candidates_step.PROVIDERS.get("fake_provider")
    fetch_candidates_step.PROVIDERS["fake_provider"] = FakeProvider()
    try:
        result = run_targeted_collect(
            plan_path,
            candidates_path,
            deduped_path,
            screening_path,
            output_path,
            "early detection",
            TOPIC_CONTRACT,
            "test-model",
            target_results=1,
            candidate_budget=10,
            client=client,
            trace_dir=tmp_path / "traces",
        )
    finally:
        if original_provider is None:
            fetch_candidates_step.PROVIDERS.pop("fake_provider", None)
        else:
            fetch_candidates_step.PROVIDERS["fake_provider"] = original_provider

    rows = list(csv.DictReader(output_path.open(newline="", encoding="utf-8")))
    assert result.row_counts["raw_candidates_seen"] == 2
    assert result.row_counts["core_topic_found"] == 1
    assert rows[0]["title"] == "Core Study"


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
    assert rows[0]["review_status"] == "ai_tagged"
    assert "full_text_evidence" in client.requests[0]["prompt"]
    assert "Participants completed cognitive tests and imaging" in client.requests[0][
        "prompt"
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
