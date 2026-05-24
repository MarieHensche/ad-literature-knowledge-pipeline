#!/usr/bin/env python3
"""Fetch paper candidates from OpenAlex using a generated search plan."""

from __future__ import annotations

import argparse
import json
import re
import time
from datetime import date
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen


OPENALEX_WORKS_URL = "https://api.openalex.org/works"


def load_json(path: Path) -> dict[str, object]:
    with path.open(encoding="utf-8") as handle:
        data = json.load(handle)

    if not isinstance(data, dict):
        raise ValueError(f"Expected JSON object: {path}")

    return data


def normalize_doi(value: object) -> str:
    doi = str(value or "").strip()
    doi = doi.replace("https://doi.org/", "")
    doi = doi.replace("http://doi.org/", "")
    doi = doi.replace("doi:", "")
    return doi.strip()


def inverted_index_to_text(index: object) -> str:
    if not isinstance(index, dict):
        return ""

    positions: list[tuple[int, str]] = []
    for word, word_positions in index.items():
        if not isinstance(word_positions, list):
            continue
        for position in word_positions:
            if isinstance(position, int):
                positions.append((position, str(word)))

    return " ".join(word for _, word in sorted(positions))


def extract_authors(work: dict[str, object]) -> str:
    authorships = work.get("authorships")
    if not isinstance(authorships, list):
        return ""

    names = []
    for authorship in authorships:
        if not isinstance(authorship, dict):
            continue
        author = authorship.get("author")
        if not isinstance(author, dict):
            continue
        name = author.get("display_name")
        if name:
            names.append(str(name))

    return "; ".join(names)


def extract_venue(work: dict[str, object]) -> str:
    primary_location = work.get("primary_location")
    if not isinstance(primary_location, dict):
        return ""

    source = primary_location.get("source")
    if isinstance(source, dict) and source.get("display_name"):
        return str(source["display_name"])

    return ""


def extract_url(work: dict[str, object]) -> str:
    doi = work.get("doi")
    if doi:
        return str(doi)

    primary_location = work.get("primary_location")
    if isinstance(primary_location, dict) and primary_location.get("landing_page_url"):
        return str(primary_location["landing_page_url"])

    return str(work.get("id") or "")


def active_filters_from_plan(plan: dict[str, object]) -> dict[str, str]:
    filters = plan.get("filters")
    if not isinstance(filters, dict):
        return {}

    openalex_filters = []

    year_from = filters.get("year_from")
    year_to = filters.get("year_to")

    if isinstance(year_from, int):
        openalex_filters.append(f"from_publication_date:{year_from}-01-01")

    if isinstance(year_to, int):
        openalex_filters.append(f"to_publication_date:{year_to}-12-31")

    language = filters.get("language")
    if isinstance(language, str) and language:
        openalex_filters.append(f"language:{language}")

    if not openalex_filters:
        return {}

    return {"filter": ",".join(openalex_filters)}


def build_openalex_url(
    plan: dict[str, object],
    page: int,
    per_page: int,
    mailto: str | None,
) -> str:
    provider_plan = plan.get("provider_specific_plan")
    if not isinstance(provider_plan, dict):
        raise ValueError("Plan must contain provider_specific_plan.")

    query = provider_plan.get("query") or plan.get("main_search_string")
    if not query:
        raise ValueError("Plan must contain a query or main_search_string.")

    params = {
        "search": str(query),
        "page": str(page),
        "per-page": str(per_page),
    }

    params.update(active_filters_from_plan(plan))

    if mailto:
        params["mailto"] = mailto

    return f"{OPENALEX_WORKS_URL}?{urlencode(params)}"


def fetch_json(url: str) -> dict[str, object]:
    request = Request(url, headers={"User-Agent": "ad-literature-knowledge-pipeline/0.1"})
    with urlopen(request, timeout=60) as response:
        data = json.loads(response.read().decode("utf-8"))

    if not isinstance(data, dict):
        raise ValueError("OpenAlex response was not a JSON object.")

    return data


def candidate_from_work(
    work: dict[str, object],
    plan: dict[str, object],
    rank: int,
    query_url: str,
) -> dict[str, object]:
    provider_plan = plan.get("provider_specific_plan")
    if not isinstance(provider_plan, dict):
        provider_plan = {}

    abstract = inverted_index_to_text(work.get("abstract_inverted_index"))

    return {
        "provider": "openalex",
        "provider_id": str(work.get("id") or ""),
        "doi": normalize_doi(work.get("doi")),
        "title": str(work.get("display_name") or ""),
        "year": work.get("publication_year"),
        "abstract": abstract,
        "authors": extract_authors(work),
        "venue": extract_venue(work),
        "url": extract_url(work),
        "query": str(provider_plan.get("query") or plan.get("main_search_string") or ""),
        "rank": rank,
        "retrieval_date": date.today().isoformat(),
        "query_url": query_url,
        "raw_record": work,
    }


def write_jsonl(output_path: Path, rows: list[dict[str, object]]) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with output_path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def fetch_candidates(
    plan: dict[str, object],
    max_results: int,
    per_page: int,
    mailto: str | None,
    sleep_seconds: float,
) -> list[dict[str, object]]:
    candidates = []
    page = 1

    while len(candidates) < max_results:
        query_url = build_openalex_url(plan, page, per_page, mailto)
        print(f"Fetching OpenAlex page {page}: {query_url}")

        response = fetch_json(query_url)
        results = response.get("results")

        if not isinstance(results, list) or not results:
            break

        for work in results:
            if not isinstance(work, dict):
                continue

            rank = len(candidates) + 1
            candidates.append(candidate_from_work(work, plan, rank, query_url))

            if len(candidates) >= max_results:
                break

        page += 1

        if len(candidates) < max_results:
            time.sleep(sleep_seconds)

    return candidates


def validate_openalex_plan(plan: dict[str, object]) -> None:
    provider = plan.get("recommended_provider")
    provider_plan = plan.get("provider_specific_plan")

    if provider != "openalex":
        raise ValueError(
            f"This script only supports OpenAlex plans. Recommended provider was: {provider}"
        )

    if not isinstance(provider_plan, dict) or provider_plan.get("provider") != "openalex":
        raise ValueError("provider_specific_plan.provider must be openalex.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch OpenAlex candidate papers.")
    parser.add_argument("--plan", required=True, help="Input search plan JSON.")
    parser.add_argument("--output", required=True, help="Output candidates JSONL.")
    parser.add_argument("--max-results", type=int, default=None, help="Override max result count.")
    parser.add_argument("--per-page", type=int, default=25, help="OpenAlex page size.")
    parser.add_argument("--mailto", default=None, help="Optional email for OpenAlex polite pool.")
    parser.add_argument("--sleep", type=float, default=0.2, help="Delay between API pages.")
    args = parser.parse_args()

    plan_path = Path(args.plan)
    output_path = Path(args.output)
    plan = load_json(plan_path)
    validate_openalex_plan(plan)

    provider_plan = plan.get("provider_specific_plan")
    if not isinstance(provider_plan, dict):
        raise ValueError("Plan must contain provider_specific_plan.")

    max_results = args.max_results or int(provider_plan.get("max_results_recommendation") or 100)

    candidates = fetch_candidates(
        plan=plan,
        max_results=max_results,
        per_page=args.per_page,
        mailto=args.mailto,
        sleep_seconds=args.sleep,
    )

    write_jsonl(output_path, candidates)

    print(f"Fetched candidates: {len(candidates)}")
    print(f"Wrote {output_path}")


if __name__ == "__main__":
    main()