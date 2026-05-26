from __future__ import annotations

import json
from pathlib import Path

import pytest

from ad_lit_pipeline.core.errors import UnsupportedProviderError
from ad_lit_pipeline.providers.openalex import (
    OpenAlexProvider,
    build_openalex_url,
    candidate_from_work,
    inverted_index_to_text,
)
from ad_lit_pipeline.steps.collection.fetch_candidates import get_provider, run


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
