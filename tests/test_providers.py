from __future__ import annotations

import json
from email.message import Message
from io import BytesIO
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlparse

import pytest

from ad_lit_pipeline.core.errors import UnsupportedProviderError
from ad_lit_pipeline.providers import openalex
from ad_lit_pipeline.providers.openalex import (
    OpenAlexProvider,
    build_openalex_url,
    candidate_from_work,
    fetch_json,
    inverted_index_to_text,
    query_resume_state,
    redact_openalex_url,
)
from ad_lit_pipeline.steps.collection.fetch_candidates import get_provider, run
from ad_lit_pipeline.topics.retrieval import execution_queries_for_provider


@pytest.fixture(autouse=True)
def clear_openalex_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENALEX_API_KEY", raising=False)


def openalex_plan() -> dict[str, object]:
    return {
        "recommended_provider": "openalex",
        "main_search_string": "early detection",
        "alternate_search_strings": ["MCI screening"],
        "search_queries": [
            {
                "query": "early detection Alzheimer's",
                "reason": "Primary phrasing.",
            },
            {
                "query": "MCI screening",
                "reason": "Adjacent phrasing.",
            },
        ],
        "filters": {
            "year_from": 2020,
            "year_to": 2024,
            "language": "en",
            "has_abstract": True,
            "exclude_reviews": True,
        },
        "provider_specific_plan": {
            "provider": "openalex",
            "query": "early detection Alzheimer's",
            "filters": [],
            "sort": None,
            "max_results_recommendation": 10,
        },
    }


def test_openalex_url_uses_query_and_supported_filters() -> None:
    url = build_openalex_url(openalex_plan(), page=2, per_page=50, mailto="a@test")

    assert url.startswith("https://api.openalex.org/works?")
    assert "search=early+detection+Alzheimer%27s" in url
    assert "page=2" in url
    assert "per-page=50" in url
    assert "from_publication_date%3A2020-01-01" in url
    assert "to_publication_date%3A2024-12-31" in url
    assert "language%3Aen" in url
    assert "has_abstract%3Atrue" in url
    assert "type%3A%21review" in url
    assert "mailto=a%40test" in url


def test_openalex_url_prefers_exact_provider_publication_dates() -> None:
    plan = openalex_plan()
    plan["filters"]["year_to"] = 2026
    plan["provider_specific_plan"]["filters"] = [
        {
            "name": "from_publication_date",
            "value": "2020-01-01",
            "reason": "Exact start date.",
        },
        {
            "name": "to_publication_date",
            "value": "2026-08-24",
            "reason": "Exact end date.",
        },
    ]

    url = build_openalex_url(plan, page=1, per_page=50, mailto=None)

    assert "from_publication_date%3A2020-01-01" in url
    assert "to_publication_date%3A2026-08-24" in url
    assert "to_publication_date%3A2026-12-31" not in url


def test_openalex_url_rejects_malformed_provider_publication_date() -> None:
    plan = openalex_plan()
    plan["provider_specific_plan"]["filters"] = [
        {
            "name": "to_publication_date",
            "value": "2026-8-24",
            "reason": "Malformed exact end date.",
        }
    ]

    with pytest.raises(ValueError, match="must use YYYY-MM-DD"):
        build_openalex_url(plan, page=1, per_page=50, mailto=None)


def test_openalex_url_uses_api_key_from_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENALEX_API_KEY", "secret-key")

    url = build_openalex_url(openalex_plan(), page=1, per_page=25, mailto=None)

    assert "api_key=secret-key" in url
    assert "api_key=REDACTED" in redact_openalex_url(url)
    assert "secret-key" not in redact_openalex_url(url)


def test_openalex_fetch_json_retries_transient_url_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0

    class FakeResponse:
        def __enter__(self) -> "FakeResponse":
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def read(self) -> bytes:
            return b'{"results": []}'

    def fake_urlopen(request: object, timeout: int) -> FakeResponse:
        nonlocal calls
        calls += 1
        if calls < 3:
            raise URLError("temporary DNS failure")
        return FakeResponse()

    monkeypatch.setattr(openalex, "urlopen", fake_urlopen)
    monkeypatch.setattr(openalex.time, "sleep", lambda seconds: None)

    assert fetch_json("https://api.openalex.org/works", retry_sleep_seconds=0) == {
        "results": []
    }
    assert calls == 3


def test_openalex_fetch_json_retries_transient_http_503(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0

    class FakeResponse:
        def __enter__(self) -> "FakeResponse":
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def read(self) -> bytes:
            return b'{"results": []}'

    def fake_urlopen(request: object, timeout: int) -> FakeResponse:
        nonlocal calls
        calls += 1
        if calls < 4:
            raise HTTPError(
                "https://api.openalex.org/works",
                503,
                "Service Unavailable",
                Message(),
                BytesIO(),
            )
        return FakeResponse()

    monkeypatch.setattr(openalex, "urlopen", fake_urlopen)
    monkeypatch.setattr(openalex.time, "sleep", lambda seconds: None)

    assert fetch_json("https://api.openalex.org/works", retry_sleep_seconds=0) == {
        "results": []
    }
    assert calls == 4


def test_openalex_url_can_select_open_review_overviews() -> None:
    plan = openalex_plan()
    plan["filters"] = {
        "publication_types": ["review"],
        "open_access_only": True,
        "has_full_text": True,
        "has_pdf_url": True,
        "has_content_pdf": True,
    }

    url = build_openalex_url(plan, page=1, per_page=5, mailto=None)

    assert "type%3Areview" in url
    assert "open_access.is_oa%3Atrue" in url
    assert "has_fulltext%3Atrue" in url
    assert "has_pdf_url%3Atrue" in url
    assert "has_content.pdf%3Atrue" in url


def test_openalex_url_uses_fielded_topic_block_filters() -> None:
    query_entry = {
        "query": "(AI OR deep learning) AND (student achievement)",
        "blocks": [
            {"field": "title", "terms": ["AI", "deep learning"]},
            {"field": "abstract", "terms": ["student achievement"]},
            {"field": "title_or_abstract", "terms": ["K-12"]},
        ],
    }

    url = build_openalex_url(
        openalex_plan(),
        page=1,
        per_page=25,
        mailto=None,
        query=query_entry["query"],
        query_entry=query_entry,
    )

    assert "search=" not in url
    assert "title.search%3AAI%7Cdeep+learning" in url
    assert "abstract.search%3Astudent+achievement" in url
    assert "title_and_abstract.search%3AK-12" in url


def test_query_execution_decomposes_when_boolean_is_not_supported() -> None:
    query_entry = {
        "query_id": "tier_0_all_main",
        "query": "(AI OR machine learning) AND (school OR classroom)",
        "blocks": [
            {"field": "title", "terms": ["AI", "machine learning"]},
            {"field": "title", "terms": ["school", "classroom"]},
        ],
    }

    boolean_entries = execution_queries_for_provider(query_entry, True)
    fallback_entries = execution_queries_for_provider(query_entry, False)

    assert len(boolean_entries) == 1
    assert boolean_entries[0]["query_id"] == "tier_0_all_main"
    assert boolean_entries[0]["use_query_blocks"] is True
    assert [entry["query"] for entry in fallback_entries] == [
        "AI school",
        "machine learning classroom",
    ]
    assert all(entry["use_query_blocks"] is False for entry in fallback_entries)
    assert all(
        entry["logical_query_id"] == "tier_0_all_main"
        for entry in fallback_entries
    )


def test_openalex_candidate_conversion_rebuilds_abstract() -> None:
    work = {
        "id": "https://openalex.org/W1",
        "doi": "https://doi.org/10.123/example",
        "display_name": "Example Study",
        "publication_year": 2024,
        "abstract_inverted_index": {"hello": [0], "world": [1]},
        "authorships": [{"author": {"display_name": "A. Author"}}],
        "primary_location": {
            "source": {"display_name": "Journal"},
            "landing_page_url": "https://example.test",
        },
    }

    candidate = candidate_from_work(work, openalex_plan(), 1, "https://query.test")

    assert inverted_index_to_text(work["abstract_inverted_index"]) == "hello world"
    assert candidate["doi"] == "10.123/example"
    assert candidate["abstract"] == "hello world"
    assert candidate["authors"] == "A. Author"
    assert candidate["venue"] == "Journal"


def test_openalex_fetches_multiple_search_queries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    urls: list[str] = []

    def fake_fetch_json(url: str) -> dict[str, object]:
        urls.append(url)
        if "MCI+screening" in url:
            work_id = "https://openalex.org/W2"
            title = "MCI Screening"
        else:
            work_id = "https://openalex.org/W1"
            title = "Early Detection"
        return {
            "results": [
                {
                    "id": work_id,
                    "display_name": title,
                    "publication_year": 2024,
                    "abstract_inverted_index": {"abstract": [0]},
                }
            ]
        }

    monkeypatch.setattr(
        "ad_lit_pipeline.providers.openalex.fetch_json",
        fake_fetch_json,
    )

    provider = OpenAlexProvider()
    candidates = provider.fetch_candidates(
        openalex_plan(),
        max_results=2,
        per_page=25,
        mailto=None,
        sleep_seconds=0,
    )

    assert len(candidates) == 2
    assert candidates[0]["query"] == "early detection Alzheimer's"
    assert candidates[0]["query_index"] == 1
    assert candidates[0]["query_rank"] == 1
    assert candidates[1]["query"] == "MCI screening"
    assert candidates[1]["query_index"] == 2
    assert len(urls) == 2
    assert "search=early+detection+Alzheimer%27s" in urls[0]
    assert "search=MCI+screening" in urls[1]


def test_openalex_tiered_fetch_dedupes_and_continues_pages(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    urls: list[str] = []

    def fake_fetch_json(url: str) -> dict[str, object]:
        urls.append(url)
        if "page=1" in url:
            return {
                "results": [
                    {
                        "id": "https://openalex.org/W1",
                        "doi": "https://doi.org/10.1/example",
                        "display_name": "Deep learning in K-12 classrooms",
                        "publication_year": 2024,
                        "abstract_inverted_index": {
                            "student": [0],
                            "achievement": [1],
                        },
                    },
                    {
                        "id": "https://openalex.org/W1-duplicate",
                        "doi": "https://doi.org/10.1/example",
                        "display_name": "Deep learning in K-12 classrooms",
                        "publication_year": 2024,
                        "abstract_inverted_index": {
                            "student": [0],
                            "achievement": [1],
                        },
                    },
                ]
            }
        return {
            "results": [
                {
                    "id": "https://openalex.org/W2",
                    "doi": "https://doi.org/10.1/second",
                    "display_name": "AI in school learning outcomes",
                    "publication_year": 2024,
                    "abstract_inverted_index": {
                        "student": [0],
                        "achievement": [1],
                    },
                }
            ]
        }

    monkeypatch.setattr(
        "ad_lit_pipeline.providers.openalex.fetch_json",
        fake_fetch_json,
    )

    plan = openalex_plan()
    plan["topic_match_spec"] = {
        "anchor_topic_id": "ai",
        "main_topics": [
            {
                "topic_id": "ai",
                "field": "title_or_abstract",
                "terms": ["AI", "deep learning"],
            },
            {
                "topic_id": "education",
                "field": "title",
                "terms": ["K-12", "school"],
            },
            {
                "topic_id": "impact",
                "field": "abstract",
                "terms": ["student achievement"],
            },
        ],
        "secondary_topics": [],
    }
    plan["retrieval_strategy"] = {"iterations_per_group": 2}
    plan["query_groups"] = [
        {
            "group_id": "tier_0",
            "tier": 0,
            "queries": [
                {
                    "query_id": "tier_0_all_main",
                    "tier": 0,
                    "query": "(AI OR deep learning) AND (K-12 OR school)",
                    "reason": "Tier 0.",
                    "requires_title_screening": False,
                    "blocks": [
                        {
                            "topic_id": "ai",
                            "kind": "main",
                            "field": "title_or_abstract",
                            "terms": ["AI", "deep learning"],
                        },
                        {
                            "topic_id": "education",
                            "kind": "main",
                            "field": "title",
                            "terms": ["K-12", "school"],
                        },
                        {
                            "topic_id": "impact",
                            "kind": "main",
                            "field": "abstract",
                            "terms": ["student achievement"],
                        },
                    ],
                }
            ],
        }
    ]

    provider = OpenAlexProvider()
    candidates = provider.fetch_candidates(
        plan,
        max_results=2,
        per_page=25,
        mailto=None,
        sleep_seconds=0,
    )

    assert len(candidates) == 2
    assert candidates[0]["dedupe_key"] == "doi:10.1/example"
    assert candidates[0]["retrieval_tier"] == 0
    assert candidates[0]["local_relevance_tier"] == 0
    assert candidates[0]["in_fetch_duplicate_count"] == 2
    assert candidates[0]["in_fetch_duplicate_provenance"]
    assert candidates[0]["in_fetch_duplicate_provenance"][0]["query_rank"] == 2
    assert provider.last_fetch_diagnostics["raw_provider_candidates_seen"] == 3
    assert provider.last_fetch_diagnostics["in_fetch_duplicates_removed"] == 1
    assert "page=1" in urls[0]
    assert "page=2" in urls[1]


def test_tiered_fetch_uses_fallback_execution_queries_without_boolean(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    urls: list[str] = []

    def fake_fetch_json(url: str) -> dict[str, object]:
        urls.append(url)
        if "machine+learning+classroom" in url:
            work_id = "https://openalex.org/W2"
            title = "Machine learning classroom study"
        else:
            work_id = "https://openalex.org/W1"
            title = "AI school study"
        return {
            "results": [
                {
                    "id": work_id,
                    "display_name": title,
                    "publication_year": 2024,
                    "abstract_inverted_index": {"student": [0]},
                }
            ]
        }

    monkeypatch.setattr(
        "ad_lit_pipeline.providers.openalex.fetch_json",
        fake_fetch_json,
    )
    plan = openalex_plan()
    plan["retrieval_strategy"] = {"iterations_per_group": 2}
    plan["query_groups"] = [
        {
            "group_id": "tier_0",
            "tier": 0,
            "queries": [
                {
                    "query_id": "tier_0_all_main",
                    "tier": 0,
                    "query": "(AI OR machine learning) AND (school OR classroom)",
                    "reason": "Tier 0.",
                    "requires_title_screening": False,
                    "blocks": [
                        {
                            "topic_id": "ai",
                            "kind": "main",
                            "field": "title",
                            "terms": ["AI", "machine learning"],
                        },
                        {
                            "topic_id": "education",
                            "kind": "main",
                            "field": "title",
                            "terms": ["school", "classroom"],
                        },
                    ],
                }
            ],
        }
    ]

    provider = OpenAlexProvider()
    provider.supports_boolean_query_blocks = False
    candidates = provider.fetch_candidates(
        plan,
        max_results=2,
        per_page=25,
        mailto=None,
        sleep_seconds=0,
    )

    assert len(candidates) == 2
    assert candidates[0]["retrieval_query_id"] == "tier_0_all_main_fallback_1"
    assert candidates[0]["retrieval_logical_query_id"] == "tier_0_all_main"
    assert candidates[1]["retrieval_query_id"] == "tier_0_all_main_fallback_2"
    assert "search=AI+school" in urls[0]
    assert "search=machine+learning+classroom" in urls[1]
    assert "title.search" not in "".join(urls)
    assert provider.last_fetch_diagnostics["provider_boolean_query_blocks"] is False
    assert provider.last_fetch_diagnostics["logical_query_count"] == 1
    assert provider.last_fetch_diagnostics["execution_query_count"] == 2


def test_openalex_backfill_resumes_after_consumed_page(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    urls: list[str] = []

    def fake_fetch_json(url: str) -> dict[str, object]:
        urls.append(url)
        page = parse_qs(urlparse(url).query).get("page", ["1"])[0]
        if page == "1":
            work_id = "https://openalex.org/W1"
            title = "AI school achievement one"
        else:
            work_id = "https://openalex.org/W2"
            title = "AI school achievement two"
        return {
            "results": [
                {
                    "id": work_id,
                    "doi": f"https://doi.org/10.1/{work_id.rsplit('/', 1)[-1]}",
                    "display_name": title,
                    "publication_year": 2024,
                    "abstract_inverted_index": {"student": [0]},
                }
            ]
        }

    monkeypatch.setattr(
        "ad_lit_pipeline.providers.openalex.fetch_json",
        fake_fetch_json,
    )
    plan = openalex_plan()
    plan["retrieval_strategy"] = {"iterations_per_group": 2}
    plan["query_groups"] = [
        {
            "group_id": "tier_0",
            "tier": 0,
            "queries": [
                {
                    "query_id": "tier_0_all_main",
                    "tier": 0,
                    "query": "(AI) AND (school)",
                    "reason": "Tier 0.",
                    "requires_title_screening": False,
                    "blocks": [
                        {
                            "topic_id": "ai",
                            "kind": "main",
                            "field": "title",
                            "terms": ["AI"],
                        },
                        {
                            "topic_id": "education",
                            "kind": "main",
                            "field": "title",
                            "terms": ["school"],
                        },
                    ],
                }
            ],
        }
    ]

    provider = OpenAlexProvider()
    first = provider.fetch_candidates(
        plan,
        max_results=1,
        per_page=1,
        mailto=None,
        sleep_seconds=0,
    )
    additional = provider.fetch_additional_candidates(
        plan,
        first,
        max_results=1,
        per_page=1,
        mailto=None,
        sleep_seconds=0,
    )

    assert len(first) == 1
    assert len(additional) == 1
    assert additional[0]["provider_id"] == "https://openalex.org/W2"
    assert additional[0]["retrieval_backfill_round"] == 1
    assert "page=1" in urls[0]
    assert "page=2" in urls[1]
    assert provider.last_fetch_diagnostics["existing_candidates"] == 1
    assert provider.last_fetch_diagnostics["unique_candidates"] == 1


def test_openalex_resume_state_continues_after_consumed_pages() -> None:
    existing_candidates = [
        {
            "provider": "openalex",
            "provider_id": f"W{i}",
            "retrieval_query_id": "tier_0_all_main",
            "query_rank": i,
        }
        for i in range(1, 51)
    ]

    page_by_query_id, rank_by_query_id, offset_by_query_id = query_resume_state(
        existing_candidates,
        per_page=25,
    )

    assert page_by_query_id["tier_0_all_main"] == 3
    assert rank_by_query_id["tier_0_all_main"] == 50
    assert offset_by_query_id["tier_0_all_main"] == 0


def test_openalex_resume_state_counts_consumed_duplicate_ranks() -> None:
    existing_candidates = [
        {
            "provider": "openalex",
            "provider_id": "W1",
            "retrieval_query_id": "tier_0_all_main",
            "query_rank": 1,
            "in_fetch_duplicate_provenance": [
                {
                    "provider": "openalex",
                    "provider_id": "W1_DUPLICATE",
                    "retrieval_query_id": "tier_0_all_main",
                    "query_rank": 50,
                }
            ],
        }
    ]

    page_by_query_id, rank_by_query_id, offset_by_query_id = query_resume_state(
        existing_candidates,
        per_page=25,
    )

    assert page_by_query_id["tier_0_all_main"] == 3
    assert rank_by_query_id["tier_0_all_main"] == 50
    assert offset_by_query_id["tier_0_all_main"] == 0


def test_openalex_tiered_fetch_reports_exhausted_query_details(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    urls: list[str] = []

    def fake_fetch_json(url: str) -> dict[str, object]:
        urls.append(url)
        return {"results": []}

    monkeypatch.setattr(
        "ad_lit_pipeline.providers.openalex.fetch_json",
        fake_fetch_json,
    )
    plan = openalex_plan()
    plan["retrieval_strategy"] = {"iterations_per_group": 1}
    plan["query_groups"] = [
        {
            "group_id": "tier_0",
            "tier": 0,
            "queries": [
                {
                    "query_id": "tier_0_all_main",
                    "tier": 0,
                    "query": "(AI) AND (school)",
                    "reason": "Tier 0.",
                    "requires_title_screening": False,
                    "blocks": [
                        {
                            "topic_id": "ai",
                            "kind": "main",
                            "field": "title",
                            "terms": ["AI"],
                        },
                        {
                            "topic_id": "education",
                            "kind": "main",
                            "field": "title",
                            "terms": ["school"],
                        },
                    ],
                }
            ],
        }
    ]

    provider = OpenAlexProvider()
    candidates = provider.fetch_candidates(
        plan,
        max_results=1,
        per_page=25,
        mailto="person@example.test",
        sleep_seconds=0,
    )

    diagnostics = provider.last_fetch_diagnostics
    assert candidates == []
    assert diagnostics["exhausted_query_count"] == 1
    assert diagnostics["exhausted_queries"] == [
        {
            "query_id": "tier_0_all_main",
            "logical_query_id": "tier_0_all_main",
            "tier": 0,
            "iteration": 1,
            "page": 1,
            "per_page": 25,
            "query_url": redact_openalex_url(urls[0]),
            "reason": "empty_results",
            "pagination": "page",
            "backfill_round": 0,
            "results_returned": 0,
        }
    ]
    assert diagnostics["query_page_states"]["tier_0_all_main"]["page"] == 1


def test_fetch_candidates_rejects_unsupported_provider(tmp_path: Path) -> None:
    plan_path = tmp_path / "plan.json"
    output_path = tmp_path / "out.jsonl"
    plan = {
        "recommended_provider": "semantic_scholar",
        "provider_specific_plan": {
            "provider": "semantic_scholar",
            "max_results_recommendation": 1,
        },
    }
    plan_path.write_text(json.dumps(plan), encoding="utf-8")

    with pytest.raises(UnsupportedProviderError):
        run(plan_path, output_path)


def test_provider_registry_exposes_openalex_only() -> None:
    assert get_provider("openalex").name == "openalex"
    with pytest.raises(UnsupportedProviderError):
        get_provider("semantic_scholar")
