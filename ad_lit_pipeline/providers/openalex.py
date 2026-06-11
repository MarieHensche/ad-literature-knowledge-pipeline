from __future__ import annotations

import json
import math
import os
import time
from datetime import date
from typing import Any
from urllib.parse import parse_qsl
from urllib.parse import urlencode
from urllib.parse import urlsplit
from urllib.parse import urlunsplit
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from ad_lit_pipeline.steps.collection.candidate_identity import dedupe_key
from ad_lit_pipeline.topics.matching import (
    annotate_candidate_topic_matches,
    local_topic_match_tier,
    merge_topic_matches,
)
from ad_lit_pipeline.topics.retrieval import execution_queries_for_provider


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


def active_filter_list_from_plan(plan: dict[str, object]) -> list[str]:
    filters = plan.get("filters")
    if not isinstance(filters, dict):
        return []

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

    if filters.get("open_access_only") is True:
        openalex_filters.append("open_access.is_oa:true")

    if filters.get("has_full_text") is True:
        openalex_filters.append("has_fulltext:true")

    if filters.get("has_pdf_url") is True:
        openalex_filters.append("has_pdf_url:true")

    if filters.get("has_content_pdf") is True:
        openalex_filters.append("has_content.pdf:true")

    publication_types = filters.get("publication_types")
    if (
        isinstance(publication_types, list)
        and "review" in publication_types
        and filters.get("exclude_reviews") is not True
    ):
        openalex_filters.append("type:review")

    if filters.get("exclude_reviews") is True:
        openalex_filters.append("type:!review")

    return openalex_filters


def active_filters_from_plan(plan: dict[str, object]) -> dict[str, str]:
    openalex_filters = active_filter_list_from_plan(plan)
    if not openalex_filters:
        return {}
    return {"filter": ",".join(openalex_filters)}


def clean_filter_value(value: object) -> str:
    return str(value or "").replace(",", " ").replace("|", " ").strip()


def openalex_search_filter_name(field: str) -> str:
    if field == "title":
        return "title.search"
    if field == "abstract":
        return "abstract.search"
    return "title_and_abstract.search"


def openalex_filters_from_query_entry(query_entry: dict[str, Any]) -> list[str]:
    blocks = query_entry.get("blocks")
    if not isinstance(blocks, list):
        return []

    filters = []
    for block in blocks:
        if not isinstance(block, dict):
            continue
        terms = block.get("terms")
        if not isinstance(terms, list):
            continue
        values = [clean_filter_value(term) for term in terms]
        values = [value for value in values if value]
        if not values:
            continue
        field = str(block.get("field") or "title")
        filters.append(f"{openalex_search_filter_name(field)}:{'|'.join(values)}")
    return filters


def build_openalex_url(
    plan: dict[str, object],
    page: int,
    per_page: int,
    mailto: str | None,
    query: str | None = None,
    query_entry: dict[str, Any] | None = None,
) -> str:
    provider_plan = plan.get("provider_specific_plan")
    if not isinstance(provider_plan, dict):
        raise ValueError("Plan must contain provider_specific_plan.")

    query_text = query or provider_plan.get("query") or plan.get("main_search_string")
    fielded_filters = (
        openalex_filters_from_query_entry(query_entry)
        if isinstance(query_entry, dict)
        else []
    )
    if not query_text and not fielded_filters:
        raise ValueError("Plan must contain a query or main_search_string.")

    params = {
        "page": str(page),
        "per-page": str(per_page),
    }

    if query_text and not fielded_filters:
        params["search"] = str(query_text)

    filters = [*active_filter_list_from_plan(plan), *fielded_filters]
    if filters:
        params["filter"] = ",".join(filters)

    if mailto:
        params["mailto"] = mailto

    api_key = str(os.environ.get("OPENALEX_API_KEY") or "").strip()
    if api_key:
        params["api_key"] = api_key

    return f"{OPENALEX_WORKS_URL}?{urlencode(params)}"


def redact_openalex_url(url: str) -> str:
    parts = urlsplit(url)
    query = []
    for key, value in parse_qsl(parts.query, keep_blank_values=True):
        if key == "api_key":
            value = "REDACTED"
        query.append((key, value))
    return urlunsplit(
        (
            parts.scheme,
            parts.netloc,
            parts.path,
            urlencode(query),
            parts.fragment,
        )
    )


def fetch_json(url: str) -> dict[str, object]:
    request = Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urlopen(request, timeout=60) as response:
            data = json.loads(response.read().decode("utf-8"))
    except HTTPError as error:
        if error.code == 429:
            raise RuntimeError(
                "OpenAlex returned HTTP 429 Too Many Requests. If you have an "
                "OpenAlex API key, make sure OPENALEX_API_KEY is set in .env or "
                "the shell; the request URL shown in logs redacts this value."
            ) from error
        raise

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

    candidate = {
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
    return annotate_candidate_topic_matches(candidate, plan.get("topic_match_spec"))


def int_value(value: object, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def query_resume_state(
    existing_candidates: list[dict[str, Any]],
    per_page: int,
) -> tuple[dict[str, int], dict[str, int], dict[str, int]]:
    """Return page, rank, and page-offset state for already-consumed queries."""
    max_rank_by_query_id: dict[str, int] = {}
    for candidate in existing_candidates:
        query_id = str(candidate.get("retrieval_query_id") or "").strip()
        if not query_id:
            continue
        query_rank = int_value(candidate.get("query_rank"))
        if query_rank <= 0:
            continue
        max_rank_by_query_id[query_id] = max(
            max_rank_by_query_id.get(query_id, 0),
            query_rank,
        )

    page_by_query_id: dict[str, int] = {}
    rank_by_query_id: dict[str, int] = {}
    offset_by_query_id: dict[str, int] = {}
    safe_per_page = max(1, per_page)
    for query_id, max_rank in max_rank_by_query_id.items():
        page = (max_rank // safe_per_page) + 1
        offset = max_rank % safe_per_page
        page_by_query_id[query_id] = page
        rank_by_query_id[query_id] = (page - 1) * safe_per_page
        offset_by_query_id[query_id] = offset

    return page_by_query_id, rank_by_query_id, offset_by_query_id


class OpenAlexProvider:
    """Candidate provider for the OpenAlex Works API."""

    name = "openalex"
    supports_fielded_text_search = True
    supports_boolean_query_blocks = True

    def __init__(self) -> None:
        self.last_fetch_diagnostics: dict[str, Any] = {}

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
        if isinstance(plan.get("query_groups"), list):
            return self.fetch_tiered_candidates(
                plan,
                max_results,
                per_page,
                mailto,
                sleep_seconds,
            )
        return self.fetch_legacy_candidates(
            plan,
            max_results,
            per_page,
            mailto,
            sleep_seconds,
        )

    def fetch_additional_candidates(
        self,
        plan: dict[str, Any],
        existing_candidates: list[dict[str, Any]],
        max_results: int,
        per_page: int,
        mailto: str | None,
        sleep_seconds: float,
        backfill_round: int = 1,
    ) -> list[dict[str, Any]]:
        if max_results <= 0:
            self.last_fetch_diagnostics = {
                "mode": "backfill_noop",
                "target_candidates": 0,
                "unique_candidates": 0,
                "existing_candidates": len(existing_candidates),
            }
            return []

        if isinstance(plan.get("query_groups"), list):
            return self.fetch_tiered_candidates(
                plan,
                max_results,
                per_page,
                mailto,
                sleep_seconds,
                existing_candidates=existing_candidates,
                max_new_results=max_results,
                backfill_round=backfill_round,
            )

        existing_keys = {dedupe_key(candidate) for candidate in existing_candidates}
        expanded_candidates = self.fetch_legacy_candidates(
            plan,
            len(existing_candidates) + max_results,
            per_page,
            mailto,
            sleep_seconds,
        )
        additional = [
            candidate
            for candidate in expanded_candidates
            if dedupe_key(candidate) not in existing_keys
        ][:max_results]
        self.last_fetch_diagnostics = {
            **self.last_fetch_diagnostics,
            "mode": "legacy_backfill_refetch",
            "target_candidates": max_results,
            "existing_candidates": len(existing_candidates),
            "unique_candidates": len(additional),
        }
        return additional

    def fetch_legacy_candidates(
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
        raw_candidates_seen = 0

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
                display_url = redact_openalex_url(query_url)
                print(
                    f"Fetching OpenAlex query {query_index} page {page}: "
                    f"{display_url}"
                )

                response = fetch_json(query_url)
                results = response.get("results")

                if not isinstance(results, list) or not results:
                    break

                for work in results:
                    if not isinstance(work, dict):
                        continue

                    raw_candidates_seen += 1
                    query_rank += 1
                    rank = len(candidates) + 1
                    candidates.append(
                        candidate_from_work(
                            work,
                            plan,
                            rank,
                            display_url,
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

        self.last_fetch_diagnostics = {
            "mode": "legacy_equal_per_query",
            "target_candidates": max_results,
            "raw_provider_candidates_seen": raw_candidates_seen,
            "in_fetch_duplicates_removed": 0,
            "unique_candidates": len(candidates),
        }
        return candidates

    def fetch_tiered_candidates(
        self,
        plan: dict[str, Any],
        max_results: int,
        per_page: int,
        mailto: str | None,
        sleep_seconds: float,
        existing_candidates: list[dict[str, Any]] | None = None,
        max_new_results: int | None = None,
        backfill_round: int | None = None,
    ) -> list[dict[str, Any]]:
        strategy = plan.get("retrieval_strategy")
        if not isinstance(strategy, dict):
            strategy = {}
        iterations = int(strategy.get("iterations_per_group") or 2)
        query_groups = plan.get("query_groups")
        if not isinstance(query_groups, list):
            return []

        existing_candidates = existing_candidates or []
        target_new_results = max_new_results if max_new_results is not None else max_results
        candidates: list[dict[str, Any]] = []
        candidates_by_key: dict[str, dict[str, Any]] = {
            dedupe_key(candidate): candidate for candidate in existing_candidates
        }
        (
            page_by_query_id,
            rank_by_query_id,
            offset_by_query_id,
        ) = query_resume_state(existing_candidates, per_page)
        exhausted_query_ids: set[str] = set()
        diagnostics: dict[str, Any] = {
            "mode": "tiered_topic_blocks",
            "provider_boolean_query_blocks": self.supports_boolean_query_blocks,
            "target_candidates": target_new_results,
            "existing_candidates": len(existing_candidates),
            "backfill_round": backfill_round or 0,
            "raw_provider_candidates_seen": 0,
            "resume_candidates_skipped": 0,
            "in_fetch_duplicates_removed": 0,
            "unique_candidates": 0,
            "tier_counts": {},
            "query_counts": {},
            "logical_query_counts": {},
        }

        query_index = 0
        valid_groups = [group for group in query_groups if isinstance(group, dict)]
        def group_sort_key(item: dict[str, Any]) -> tuple[int, int]:
            priority = item.get("priority")
            if priority is None:
                priority = item.get("tier")
            return int(priority or 0), int(item.get("tier") or 0)

        for group in sorted(valid_groups, key=group_sort_key):
            if len(candidates) >= target_new_results:
                break
            if not isinstance(group, dict):
                continue
            tier = int(group.get("tier") or 0)
            queries = group.get("queries")
            if not isinstance(queries, list) or not queries:
                continue
            execution_queries = []
            for query in queries:
                if not isinstance(query, dict):
                    continue
                execution_queries.extend(
                    execution_queries_for_provider(
                        query,
                        self.supports_boolean_query_blocks,
                    )
                )
            tier_key = str(tier)
            diagnostics["logical_query_counts"][tier_key] = (
                diagnostics["logical_query_counts"].get(tier_key, 0) + len(queries)
            )
            execution_count_map = diagnostics.setdefault("execution_query_counts", {})
            execution_count_map[tier_key] = (
                execution_count_map.get(tier_key, 0) + len(execution_queries)
            )
            if not execution_queries:
                continue

            for iteration in range(1, max(1, iterations) + 1):
                remaining = target_new_results - len(candidates)
                if remaining <= 0:
                    break
                active_queries = [
                    query
                    for query in execution_queries
                    if isinstance(query, dict)
                    and str(query.get("query_id") or query.get("query") or "")
                    not in exhausted_query_ids
                ]
                if not active_queries:
                    break

                per_query_goal = max(1, math.ceil(remaining / len(active_queries)))
                for query_entry in active_queries:
                    if len(candidates) >= target_new_results:
                        break
                    query_index += 1
                    query_id = str(
                        query_entry.get("query_id")
                        or query_entry.get("query")
                        or f"query_{query_index}"
                    )
                    page = page_by_query_id.get(query_id, 1)
                    query_rank = rank_by_query_id.get(query_id, 0)
                    resume_offset = offset_by_query_id.pop(query_id, 0)
                    accepted_for_query = 0
                    query = str(query_entry.get("query") or "")
                    query_reason = str(query_entry.get("reason") or "")
                    logical_query_id = str(
                        query_entry.get("logical_query_id") or query_id
                    )
                    use_query_blocks = bool(query_entry.get("use_query_blocks"))

                    while (
                        accepted_for_query < per_query_goal
                        and len(candidates) < target_new_results
                    ):
                        query_url = build_openalex_url(
                            plan,
                            page,
                            per_page,
                            mailto,
                            query=query,
                            query_entry=query_entry if use_query_blocks else None,
                        )
                        display_url = redact_openalex_url(query_url)
                        print(
                            "Fetching OpenAlex "
                            f"group tier {tier} iteration {iteration} "
                            f"query {query_id} page {page}: {display_url}"
                        )

                        response = fetch_json(query_url)
                        results = response.get("results")
                        if not isinstance(results, list) or not results:
                            exhausted_query_ids.add(query_id)
                            break

                        for work in results:
                            if not isinstance(work, dict):
                                continue

                            query_rank += 1
                            if resume_offset > 0:
                                resume_offset -= 1
                                diagnostics["resume_candidates_skipped"] += 1
                                continue

                            diagnostics["raw_provider_candidates_seen"] += 1
                            candidate = candidate_from_work(
                                work,
                                plan,
                                len(existing_candidates) + len(candidates) + 1,
                                display_url,
                                query=query,
                                query_index=query_index,
                                query_rank=query_rank,
                                query_reason=query_reason,
                            )
                            candidate["retrieval_group_id"] = str(
                                group.get("group_id") or f"tier_{tier}"
                            )
                            candidate["retrieval_tier"] = tier
                            candidate["retrieval_query_id"] = query_id
                            candidate["retrieval_logical_query_id"] = logical_query_id
                            candidate["retrieval_iteration"] = iteration
                            candidate["retrieval_phase"] = str(
                                query_entry.get("retrieval_phase") or ""
                            )
                            if backfill_round:
                                candidate["retrieval_backfill_round"] = backfill_round
                            candidate["retrieval_query_blocks"] = query_entry.get(
                                "blocks",
                                [],
                            )
                            candidate["requires_title_screening"] = bool(
                                query_entry.get("requires_title_screening")
                            )
                            candidate["local_relevance_tier"] = local_topic_match_tier(
                                candidate.get("topic_matches")
                            )

                            key = dedupe_key(candidate)
                            existing = candidates_by_key.get(key)
                            if existing is not None:
                                diagnostics["in_fetch_duplicates_removed"] += 1
                                existing["in_fetch_duplicate_count"] = int(
                                    existing.get("in_fetch_duplicate_count") or 1
                                ) + 1
                                merged_matches = merge_topic_matches(
                                    [
                                        existing.get("topic_matches"),
                                        candidate.get("topic_matches"),
                                    ]
                                )
                                if merged_matches:
                                    existing["topic_matches"] = merged_matches
                                    existing["local_relevance_tier"] = (
                                        local_topic_match_tier(merged_matches)
                                    )
                                provenance = existing.setdefault(
                                    "in_fetch_duplicate_provenance",
                                    [],
                                )
                                if isinstance(provenance, list):
                                    provenance.append(
                                        {
                                            "provider": candidate.get("provider", ""),
                                            "provider_id": candidate.get(
                                                "provider_id",
                                                "",
                                            ),
                                            "doi": candidate.get("doi", ""),
                                            "title": candidate.get("title", ""),
                                            "year": candidate.get("year", ""),
                                            "rank": candidate.get("rank", ""),
                                            "query": candidate.get("query", ""),
                                            "retrieval_tier": tier,
                                            "retrieval_query_id": query_id,
                                        }
                                    )
                                continue

                            candidate["dedupe_key"] = key
                            candidate["in_fetch_duplicate_count"] = 1
                            candidates_by_key[key] = candidate
                            candidates.append(candidate)
                            accepted_for_query += 1
                            tier_key = str(tier)
                            diagnostics["tier_counts"][tier_key] = (
                                diagnostics["tier_counts"].get(tier_key, 0) + 1
                            )
                            diagnostics["query_counts"][query_id] = (
                                diagnostics["query_counts"].get(query_id, 0) + 1
                            )

                            if (
                                accepted_for_query >= per_query_goal
                                or len(candidates) >= target_new_results
                            ):
                                break

                        page += 1
                        page_by_query_id[query_id] = page
                        rank_by_query_id[query_id] = query_rank

                        if (
                            accepted_for_query < per_query_goal
                            and len(candidates) < target_new_results
                            and query_id not in exhausted_query_ids
                        ):
                            time.sleep(sleep_seconds)

        if existing_candidates:
            for rank, candidate in enumerate(
                candidates,
                start=len(existing_candidates) + 1,
            ):
                candidate["rank"] = rank
        else:
            for rank, candidate in enumerate(candidates, start=1):
                candidate["rank"] = rank

        diagnostics["unique_candidates"] = len(candidates)
        diagnostics["exhausted_query_count"] = len(exhausted_query_ids)
        logical_counts = diagnostics.get("logical_query_counts")
        if isinstance(logical_counts, dict):
            diagnostics["logical_query_count"] = sum(
                count for count in logical_counts.values() if isinstance(count, int)
            )
        execution_counts = diagnostics.get("execution_query_counts")
        if isinstance(execution_counts, dict):
            diagnostics["execution_query_count"] = sum(
                count for count in execution_counts.values() if isinstance(count, int)
            )
        self.last_fetch_diagnostics = diagnostics
        return candidates
