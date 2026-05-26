from __future__ import annotations

import json
import math
import time
from datetime import date
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen


OPENALEX_WORKS_URL = "https://api.openalex.org/works"
USER_AGENT = "ad-literature-knowledge-pipeline/0.1"


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

    has_abstract = filters.get("has_abstract")
    if isinstance(has_abstract, bool):
        openalex_filters.append(f"has_abstract:{str(has_abstract).lower()}")

    if filters.get("exclude_reviews") is True:
        openalex_filters.append("type:!review")

    if not openalex_filters:
        return {}

    return {"filter": ",".join(openalex_filters)}


def build_openalex_url(
    plan: dict[str, object],
    page: int,
    per_page: int,
    mailto: str | None,
    query: str | None = None,
) -> str:
    provider_plan = plan.get("provider_specific_plan")
    if not isinstance(provider_plan, dict):
        raise ValueError("Plan must contain provider_specific_plan.")

    query_text = query or provider_plan.get("query") or plan.get("main_search_string")
    if not query_text:
        raise ValueError("Plan must contain a query or main_search_string.")

    params = {
        "search": str(query_text),
        "page": str(page),
        "per-page": str(per_page),
    }

    params.update(active_filters_from_plan(plan))

    if mailto:
        params["mailto"] = mailto

    return f"{OPENALEX_WORKS_URL}?{urlencode(params)}"


def fetch_json(url: str) -> dict[str, object]:
    request = Request(url, headers={"User-Agent": USER_AGENT})
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
    query: str | None = None,
    query_index: int | None = None,
    query_rank: int | None = None,
    query_reason: str | None = None,
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
        "query": str(
            query or provider_plan.get("query") or plan.get("main_search_string") or ""
        ),
        "query_index": query_index,
        "query_rank": query_rank,
        "query_reason": query_reason or "",
        "rank": rank,
        "retrieval_date": date.today().isoformat(),
        "query_url": query_url,
        "raw_record": work,
    }


class OpenAlexProvider:
    """Candidate provider for the OpenAlex Works API."""

    name = "openalex"

    def validate_plan(self, plan: dict[str, Any]) -> None:
        provider = plan.get("recommended_provider")
        provider_plan = plan.get("provider_specific_plan")

        if provider != self.name:
            raise ValueError(
                f"OpenAlex provider cannot execute provider plan: {provider}"
            )

        if (
            not isinstance(provider_plan, dict)
            or provider_plan.get("provider") != self.name
        ):
            raise ValueError("provider_specific_plan.provider must be openalex.")

    def search_queries_from_plan(self, plan: dict[str, Any]) -> list[dict[str, str]]:
        search_queries = []
        seen = set()

        def append(query: object, reason: str) -> None:
            query_text = str(query or "").strip()
            query_key = query_text.lower()
            if not query_text or query_key in seen:
                return
            search_queries.append({"query": query_text, "reason": reason})
            seen.add(query_key)

        raw_search_queries = plan.get("search_queries")
        if isinstance(raw_search_queries, list):
            for item in raw_search_queries:
                if isinstance(item, dict):
                    append(item.get("query"), str(item.get("reason") or ""))
                else:
                    append(item, "Planned search query.")

        provider_plan = plan.get("provider_specific_plan")
        if isinstance(provider_plan, dict):
            append(provider_plan.get("query"), "Provider-specific primary query.")

        append(plan.get("main_search_string"), "Main planned search string.")

        alternate_search_strings = plan.get("alternate_search_strings")
        if isinstance(alternate_search_strings, list):
            for alternate in alternate_search_strings:
                append(alternate, "Alternate planned search string.")

        if not search_queries:
            raise ValueError("OpenAlex plan must contain at least one search query.")

        return search_queries

    def fetch_candidates(
        self,
        plan: dict[str, Any],
        max_results: int,
        per_page: int,
        mailto: str | None,
        sleep_seconds: float,
    ) -> list[dict[str, Any]]:
        candidates = []
        search_queries = self.search_queries_from_plan(plan)
        per_query_limit = max(1, math.ceil(max_results / len(search_queries)))

        for query_index, query_entry in enumerate(search_queries, start=1):
            page = 1
            query_rank = 0
            query = query_entry["query"]
            query_reason = query_entry["reason"]

            while query_rank < per_query_limit and len(candidates) < max_results:
                query_url = build_openalex_url(
                    plan,
                    page,
                    per_page,
                    mailto,
                    query=query,
                )
                print(f"Fetching OpenAlex query {query_index} page {page}: {query_url}")

                response = fetch_json(query_url)
                results = response.get("results")

                if not isinstance(results, list) or not results:
                    break

                for work in results:
                    if not isinstance(work, dict):
                        continue

                    query_rank += 1
                    rank = len(candidates) + 1
                    candidates.append(
                        candidate_from_work(
                            work,
                            plan,
                            rank,
                            query_url,
                            query=query,
                            query_index=query_index,
                            query_rank=query_rank,
                            query_reason=query_reason,
                        )
                    )

                    if query_rank >= per_query_limit or len(candidates) >= max_results:
                        break

                page += 1

                if query_rank < per_query_limit and len(candidates) < max_results:
                    time.sleep(sleep_seconds)

            if len(candidates) >= max_results:
                break

        return candidates
