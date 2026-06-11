from __future__ import annotations

import argparse
import csv
import json
import os
import time
from pathlib import Path
from typing import Any

from ad_lit_pipeline.core.env import load_dotenv
from ad_lit_pipeline.core.step import StepResult, StepSpec
from ad_lit_pipeline.llm.client import JSONLLMClient, OpenAIResponsesClient
from ad_lit_pipeline.llm.schemas import title_relevance_schema
from ad_lit_pipeline.llm.trace import LLMTraceWriter
from ad_lit_pipeline.prompts.render import render_screen_title_relevance_prompt
from ad_lit_pipeline.steps.screening.llm_candidate_screening import (
    make_paper_id,
    read_jsonl,
)
from ad_lit_pipeline.topics.matching import (
    local_topic_match_tier,
    fields_for_match,
    term_pattern,
    topic_match_spec_from_contract,
    topic_field,
)
from ad_lit_pipeline.topics.contract import load_topic_contract


STEP = StepSpec(
    name="screen_title_relevance",
    inputs=["deduped_candidates_jsonl", "topic_contract_yaml"],
    outputs=["candidate_screening_csv"],
    uses_llm=True,
    description="Screen collected candidates by field-aware topic fit.",
)

SYSTEM_MESSAGE = "You screen paper titles against topic decomposition as strict JSON."

OUTPUT_COLUMNS = [
    "paper_id",
    "title",
    "year",
    "doi",
    "provider",
    "provider_id",
    "source_rank",
    "source_query",
    "source_query_reason",
    "screening_decision",
    "screening_confidence",
    "screening_reason",
    "title_anchor_present",
    "title_relevance_tier",
    "title_matched_main_topics",
    "title_matched_secondary_topics",
    "title_missing_main_topics",
]

EXCLUDED_TIER = 999


def topic_structure(contract: dict[str, Any]) -> dict[str, Any]:
    structure = contract["topic_structure"]
    if not isinstance(structure, dict):
        raise ValueError("topic_structure must be a mapping.")
    return structure


def main_topic_ids(contract: dict[str, Any]) -> list[str]:
    structure = topic_structure(contract)
    return [
        str(topic["topic_id"])
        for topic in structure["main_topics"]
        if isinstance(topic, dict)
    ]


def candidate_for_prompt(candidate: dict[str, Any]) -> dict[str, Any]:
    return {
        "title": candidate.get("title", ""),
        "abstract": candidate.get("abstract", ""),
        "year": candidate.get("year", ""),
        "doi": candidate.get("doi", ""),
        "provider": candidate.get("provider", ""),
        "query": candidate.get("query", ""),
        "query_reason": candidate.get("query_reason", ""),
    }


def valid_topic_ids(values: object, allowed: set[str]) -> list[str]:
    if not isinstance(values, list):
        return []
    deduped = []
    seen = set()
    for value in values:
        topic_id = str(value or "").strip()
        if topic_id in allowed and topic_id not in seen:
            deduped.append(topic_id)
            seen.add(topic_id)
    return deduped


def configured_secondary_groups(
    topic_contract: dict[str, Any],
) -> dict[tuple[str, str], dict[str, Any]]:
    spec = topic_match_spec_from_contract(topic_contract)
    groups = spec.get("secondary_topics") if isinstance(spec, dict) else []
    configured: dict[tuple[str, str], dict[str, Any]] = {}
    if not isinstance(groups, list):
        return configured
    for group in groups:
        if not isinstance(group, dict):
            continue
        main_topic_id = str(group.get("main_topic_id") or "").strip()
        secondary_topic_id = str(group.get("secondary_topic_id") or "").strip()
        if not main_topic_id or not secondary_topic_id:
            continue
        terms = group.get("terms")
        allowed_terms = {
            str(term).strip().casefold(): str(term).strip()
            for term in terms
            if str(term).strip()
        } if isinstance(terms, list) else {}
        configured[(main_topic_id, secondary_topic_id)] = {
            **group,
            "allowed_terms": allowed_terms,
        }
    return configured


def secondary_topic_ids(topic_contract: dict[str, Any]) -> list[str]:
    ids = []
    seen = set()
    for _, secondary_topic_id in configured_secondary_groups(topic_contract):
        if secondary_topic_id in seen:
            continue
        ids.append(secondary_topic_id)
        seen.add(secondary_topic_id)
    return ids


def secondary_matches(
    values: object,
    allowed: set[str],
    configured: dict[tuple[str, str], dict[str, Any]],
    candidate: dict[str, Any],
) -> dict[str, dict[str, list[str]]]:
    matches: dict[str, dict[str, list[str]]] = {}
    if not isinstance(values, list):
        return matches
    for item in values:
        if not isinstance(item, dict):
            continue
        topic_id = str(item.get("main_topic_id") or "").strip()
        if topic_id not in allowed:
            continue
        secondary_topic_id = str(item.get("secondary_topic_id") or "").strip()
        group = configured.get((topic_id, secondary_topic_id))
        if group is None:
            continue
        allowed_terms = group.get("allowed_terms")
        if not isinstance(allowed_terms, dict):
            continue
        terms = item.get("terms")
        if not isinstance(terms, list):
            continue
        cleaned_terms = []
        seen_terms = set()
        for term in terms:
            key = str(term or "").strip().casefold()
            if not key or key not in allowed_terms or key in seen_terms:
                continue
            configured_term = str(allowed_terms[key])
            fields = fields_for_match(candidate, topic_field(group))
            if not any(
                text and term_pattern(configured_term).search(text)
                for _, text in fields
            ):
                continue
            cleaned_terms.append(configured_term)
            seen_terms.add(key)
        if cleaned_terms:
            topic_matches = matches.setdefault(topic_id, {})
            topic_matches.setdefault(secondary_topic_id, []).extend(cleaned_terms)
    return matches


def format_secondary_matches(matches: dict[str, dict[str, list[str]]]) -> str:
    parts = []
    for topic_id in sorted(matches):
        groups = matches[topic_id]
        for secondary_topic_id in sorted(groups):
            terms = "|".join(groups[secondary_topic_id])
            parts.append(f"{topic_id}:{secondary_topic_id}:{terms}")
    return "; ".join(parts)


def terms_from_value_items(value_items: object) -> list[str]:
    if not isinstance(value_items, list):
        return []
    terms = []
    seen = set()
    for item in value_items:
        if not isinstance(item, dict):
            continue
        value = str(item.get("value") or "").strip()
        if not value:
            continue
        key = value.casefold()
        if key in seen:
            continue
        terms.append(value)
        seen.add(key)
    return terms


def format_secondary_topic_values(value_map: object) -> str:
    if not isinstance(value_map, dict):
        return ""
    parts = []
    for topic_id in sorted(value_map):
        terms = terms_from_value_items(value_map.get(topic_id))
        if terms:
            parts.append(f"{topic_id}:{'|'.join(terms)}")
    return "; ".join(parts)


def has_title_value(value_items: object) -> bool:
    if not isinstance(value_items, list):
        return False
    return any(
        isinstance(item, dict)
        and str(item.get("field") or "").strip() == "title"
        and str(item.get("value") or "").strip()
        for item in value_items
    )


def deterministic_tier0_screening(
    topic_contract: dict[str, Any],
    candidate: dict[str, Any],
    index: int,
) -> dict[str, str] | None:
    try:
        retrieval_tier = int(candidate.get("retrieval_tier"))
    except (TypeError, ValueError):
        return None
    if retrieval_tier != 0:
        return None

    topic_matches = candidate.get("topic_matches")
    if local_topic_match_tier(topic_matches) != 0 or not isinstance(
        topic_matches,
        dict,
    ):
        return None

    value_map = topic_matches.get("main_topic_values")
    if not isinstance(value_map, dict):
        return None

    ids = main_topic_ids(topic_contract)
    matched_main = [topic_id for topic_id in ids if has_title_value(value_map.get(topic_id))]
    if set(matched_main) != set(ids):
        return None

    paper_id = make_paper_id(candidate, index)
    return {
        "paper_id": paper_id,
        "title": str(candidate.get("title") or ""),
        "year": str(candidate.get("year") or ""),
        "doi": str(candidate.get("doi") or ""),
        "provider": str(candidate.get("provider") or ""),
        "provider_id": str(candidate.get("provider_id") or ""),
        "source_rank": str(candidate.get("rank") or ""),
        "source_query": str(candidate.get("query") or ""),
        "source_query_reason": str(candidate.get("query_reason") or ""),
        "screening_decision": "include",
        "screening_confidence": "high",
        "screening_reason": (
            "Deterministic title-strict tier-0 retrieval match: anchor and all "
            "main topics matched in the title."
        ),
        "title_anchor_present": "yes",
        "title_relevance_tier": "0",
        "title_matched_main_topics": "; ".join(matched_main),
        "title_matched_secondary_topics": format_secondary_topic_values(
            topic_matches.get("secondary_topic_values")
        ),
        "title_missing_main_topics": "",
    }


def normalize_screening_result(
    topic_contract: dict[str, Any],
    parsed: dict[str, Any],
    candidate: dict[str, Any],
) -> dict[str, str]:
    ids = main_topic_ids(topic_contract)
    id_set = set(ids)
    structure = topic_structure(topic_contract)
    anchor_id = str(structure["anchor_topic_id"])

    matched_main = valid_topic_ids(parsed.get("matched_main_topics"), id_set)
    anchor_present = bool(parsed.get("anchor_present")) or anchor_id in matched_main
    if anchor_present and anchor_id not in matched_main:
        matched_main.insert(0, anchor_id)

    secondary = secondary_matches(
        parsed.get("matched_secondary_topics"),
        id_set,
        configured_secondary_groups(topic_contract),
        candidate,
    )
    missing = [topic_id for topic_id in ids if topic_id not in set(matched_main)]
    missing_non_anchor = [topic_id for topic_id in missing if topic_id != anchor_id]
    missing_without_replacement = [
        topic_id for topic_id in missing_non_anchor if topic_id not in secondary
    ]

    include = bool(anchor_present) and not missing_without_replacement
    if anchor_id in missing:
        include = False

    tier = len(missing) if include else EXCLUDED_TIER
    decision = "include" if include else "exclude"
    reason = str(parsed.get("reason") or "").strip()
    if not reason:
        reason = "Title fit was classified from topic decomposition."
    if decision == "exclude" and not anchor_present:
        reason = f"Anchor topic '{anchor_id}' is not present in the title."
    elif decision == "exclude" and missing_without_replacement:
        missing_text = ", ".join(missing_without_replacement)
        reason = f"Missing main topic(s) without secondary replacement: {missing_text}."

    confidence = str(parsed.get("confidence") or "low").strip()
    if confidence not in {"high", "medium", "low"}:
        confidence = "low"

    return {
        "screening_decision": decision,
        "screening_confidence": confidence,
        "screening_reason": reason,
        "title_anchor_present": "yes" if anchor_present else "no",
        "title_relevance_tier": str(tier),
        "title_matched_main_topics": "; ".join(matched_main),
        "title_matched_secondary_topics": format_secondary_matches(secondary),
        "title_missing_main_topics": "; ".join(missing),
    }


def call_llm(
    topic_contract: dict[str, Any],
    candidate: dict[str, Any],
    model: str,
    client: JSONLLMClient,
    trace_writer: LLMTraceWriter | None = None,
    call_id: str = "candidate",
) -> tuple[dict[str, str], list[Path]]:
    prompt = render_screen_title_relevance_prompt(
        topic_contract,
        candidate_for_prompt(candidate),
    )
    result = client.create_json(
        model=model,
        system_message=SYSTEM_MESSAGE,
        prompt=prompt,
        schema_name="title_relevance_screening",
        schema=title_relevance_schema(
            main_topic_ids(topic_contract),
            secondary_topic_ids(topic_contract),
        ),
        step_name=STEP.name,
        call_id=call_id,
        trace_writer=trace_writer,
    )
    output = normalize_screening_result(topic_contract, result.parsed, candidate)
    trace_paths = result.trace_paths.as_list() if result.trace_paths else []
    return output, trace_paths


def screen_candidate(
    topic_contract: dict[str, Any],
    candidate: dict[str, Any],
    index: int,
    model: str,
    client: JSONLLMClient,
    trace_writer: LLMTraceWriter | None = None,
) -> tuple[dict[str, str], list[Path]]:
    paper_id = make_paper_id(candidate, index)
    result, trace_paths = call_llm(
        topic_contract,
        candidate,
        model,
        client,
        trace_writer,
        paper_id,
    )
    return (
        {
            "paper_id": paper_id,
            "title": str(candidate.get("title") or ""),
            "year": str(candidate.get("year") or ""),
            "doi": str(candidate.get("doi") or ""),
            "provider": str(candidate.get("provider") or ""),
            "provider_id": str(candidate.get("provider_id") or ""),
            "source_rank": str(candidate.get("rank") or ""),
            "source_query": str(candidate.get("query") or ""),
            "source_query_reason": str(candidate.get("query_reason") or ""),
            **result,
        },
        trace_paths,
    )


def write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=OUTPUT_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)


def run(
    input_path: Path,
    output_path: Path,
    model: str,
    topic_contract_path: Path,
    limit: int | None = None,
    client: JSONLLMClient | None = None,
    trace_dir: Path | None = None,
) -> StepResult:
    topic_contract = load_topic_contract(topic_contract_path)
    candidates = read_jsonl(input_path)
    if limit is not None:
        candidates = candidates[:limit]

    llm_client = client or OpenAIResponsesClient()
    trace_writer = LLMTraceWriter(trace_dir) if trace_dir is not None else None
    rows = []
    all_trace_paths: list[Path] = []
    warnings = []
    deterministic_tier0_included = 0
    llm_screened = 0

    for index, candidate in enumerate(candidates, start=1):
        deterministic_row = deterministic_tier0_screening(
            topic_contract,
            candidate,
            index,
        )
        if deterministic_row is not None:
            rows.append(deterministic_row)
            deterministic_tier0_included += 1
            print(
                "Auto-included deterministic tier-0 title "
                f"{index}/{len(candidates)}: {candidate.get('title')}",
                flush=True,
            )
            continue

        llm_screened += 1
        started_at = time.monotonic()
        print(
            f"Screening title {index}/{len(candidates)}: {candidate.get('title')}",
            flush=True,
        )
        try:
            row, trace_paths = screen_candidate(
                topic_contract,
                candidate,
                index,
                model,
                llm_client,
                trace_writer,
            )
            rows.append(row)
            all_trace_paths.extend(trace_paths)
            elapsed = time.monotonic() - started_at
            print(
                f"  Completed title {index}/{len(candidates)} in {elapsed:.1f}s",
                flush=True,
            )
        except ValueError as error:
            elapsed = time.monotonic() - started_at
            paper_id = make_paper_id(candidate, index)
            warning = (
                f"Failed to screen title '{paper_id}' after retry "
                f"after {elapsed:.1f}s (auto-excluded): {error}"
            )
            warnings.append(warning)
            print(f"  Warning: {warning}", flush=True)
            rows.append(
                {
                    "paper_id": paper_id,
                    "title": str(candidate.get("title") or ""),
                    "year": str(candidate.get("year") or ""),
                    "doi": str(candidate.get("doi") or ""),
                    "provider": str(candidate.get("provider") or ""),
                    "provider_id": str(candidate.get("provider_id") or ""),
                    "source_rank": str(candidate.get("rank") or ""),
                    "source_query": str(candidate.get("query") or ""),
                    "source_query_reason": str(candidate.get("query_reason") or ""),
                    "screening_decision": "exclude",
                    "screening_confidence": "n/a",
                    "screening_reason": f"Auto-excluded due to LLM error: {error}",
                    "title_anchor_present": "no",
                    "title_relevance_tier": str(EXCLUDED_TIER),
                    "title_matched_main_topics": "",
                    "title_matched_secondary_topics": "",
                    "title_missing_main_topics": "",
                }
            )

    write_csv(output_path, rows)
    included = sum(1 for row in rows if row["screening_decision"] == "include")
    excluded = sum(1 for row in rows if row["screening_decision"] == "exclude")
    tier_counts: dict[str, int] = {}
    for row in rows:
        tier = row.get("title_relevance_tier", "")
        tier_counts[tier] = tier_counts.get(tier, 0) + 1

    return StepResult(
        step_name=STEP.name,
        inputs={
            "deduped_candidates_jsonl": input_path,
            "topic_contract_yaml": topic_contract_path,
        },
        outputs={"candidate_screening_csv": output_path},
        row_counts={
            "screened_candidates": len(rows),
            "included": included,
            "excluded": excluded,
            "deterministic_tier0_included": deterministic_tier0_included,
            "llm_screened": llm_screened,
        },
        trace_paths=all_trace_paths,
        warnings=warnings,
        metadata={"tier_counts": tier_counts},
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Screen paper candidate titles against topic decomposition."
    )
    parser.add_argument("--input", required=True, help="Input deduplicated JSONL.")
    parser.add_argument("--output", required=True, help="Output screening CSV.")
    parser.add_argument("--topic-contract", required=True, help="Topic contract YAML.")
    parser.add_argument("--limit", type=int, default=None, help="Optional row limit.")
    parser.add_argument(
        "--model",
        default=None,
        help="OpenAI model. Defaults to OPENAI_MODEL or gpt-4o-mini.",
    )
    parser.add_argument("--trace-dir", default=None, help="Optional trace directory.")
    args = parser.parse_args()

    load_dotenv()
    model = args.model or os.getenv("OPENAI_MODEL", "gpt-4o-mini")
    trace_dir = Path(args.trace_dir) if args.trace_dir else None
    result = run(
        Path(args.input),
        Path(args.output),
        model,
        Path(args.topic_contract),
        args.limit,
        trace_dir=trace_dir,
    )

    print(f"Screened candidates: {result.row_counts['screened_candidates']}")
    print(f"Included: {result.row_counts['included']}")
    print(f"Excluded: {result.row_counts['excluded']}")
    print(f"Wrote {args.output}")


if __name__ == "__main__":
    main()
