from __future__ import annotations

import argparse
import csv
import html
import re
from datetime import date
from pathlib import Path
from typing import Any

from ad_lit_pipeline.core.step import StepResult, StepSpec
from ad_lit_pipeline.topics.contract import (
    collection_from_contract,
    load_topic_contract,
    rule_based_screening_from_contract,
)
from ad_lit_pipeline.topics.policy import (
    TopicStructurePolicy,
    default_topic_structure_policy,
)


STEP = StepSpec(
    name="screen_scope",
    inputs=["normalized_papers_csv", "topic_contract_yaml"],
    outputs=["scope_screened_csv"],
    uses_llm=False,
    description="Screen normalized papers with topic-contract include/exclude terms.",
)

SCOPE_COLUMNS = [
    "scope_decision",
    "scope_reason",
    "scope_matched_include_terms",
    "scope_matched_exclude_terms",
    "scope_publication_window_status",
]

PUBLICATION_WINDOW_REJECTION_STATUSES = {
    "before_publication_window",
    "after_publication_window",
    "invalid_publication_date",
    "publication_date_year_mismatch",
    "missing_publication_date",
    "missing_exact_boundary_date",
    "publication_window_constraint_mismatch",
}


def text_for_screening(row: dict[str, str]) -> str:
    return " ".join(
        [
            row.get("title", ""),
            row.get("abstract", ""),
        ]
    )


STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "by",
    "for",
    "from",
    "in",
    "into",
    "of",
    "on",
    "or",
    "the",
    "to",
    "with",
}


def normalize_text(value: str) -> str:
    """Normalize text for recall-oriented screening term matching."""
    text = html.unescape(value).lower()
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"[_/\\-]+", " ", text)
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def normalize_token(token: str) -> str:
    if len(token) > 4 and token.endswith("ies"):
        return f"{token[:-3]}y"
    if len(token) > 4 and token.endswith("es"):
        return token[:-2]
    if len(token) > 3 and token.endswith("s"):
        return token[:-1]
    return token


def meaningful_tokens(value: str) -> list[str]:
    return [
        normalize_token(token)
        for token in normalize_text(value).split()
        if token not in STOPWORDS
    ]


def acronym_for_tokens(tokens: list[str]) -> str:
    return "".join(token[0] for token in tokens if token and token not in STOPWORDS)


def term_variants(
    term: str,
    policy: TopicStructurePolicy | None = None,
) -> list[str]:
    normalized = normalize_text(term)
    if not normalized:
        return []

    variants = [normalized]
    active_policy = policy or default_topic_structure_policy()
    variants.extend(active_policy.screening_abbreviations.get(normalized, ()))
    for group in active_policy.surface_form_groups:
        if normalized in group.full_forms:
            variants.extend(sorted(group.abbreviations))

    tokens = meaningful_tokens(normalized)
    acronym = acronym_for_tokens(tokens)
    if len(tokens) > 1 and 2 <= len(acronym) <= 6:
        variants.append(acronym)

    deduped = []
    seen = set()
    for variant in variants:
        if variant and variant not in seen:
            deduped.append(variant)
            seen.add(variant)
    return deduped


def contains_phrase(text: str, phrase: str) -> bool:
    return bool(re.search(rf"(^| ){re.escape(phrase)}( |$)", text))


def token_sequence_matches(text_tokens: list[str], term: str) -> bool:
    """Match a stem-normalized phrase without claiming partial-token matches.

    Screening decisions are deliberately recall-oriented, but the recorded
    explanation must remain literal.  Treating two generic words from a
    three-word term as the full configured phrase produced misleading evidence
    such as reporting ``prodromal Alzheimer's disease`` when ``prodromal`` was
    absent.  Stop words may differ, while every meaningful term token must be
    present contiguously and in order.
    """
    term_tokens = meaningful_tokens(term)
    if not term_tokens:
        return False
    width = len(term_tokens)
    return any(
        text_tokens[index : index + width] == term_tokens
        for index in range(len(text_tokens) - width + 1)
    )


def term_matches(text: str, text_tokens: list[str], term: str, similar: bool) -> bool:
    for variant in term_variants(term):
        if contains_phrase(text, variant):
            return True

    return similar and token_sequence_matches(text_tokens, term)


def matched_terms(text: str, terms: list[str], similar: bool = True) -> list[str]:
    normalized_text = normalize_text(text)
    text_tokens = meaningful_tokens(normalized_text)
    return [
        term
        for term in terms
        if term_matches(normalized_text, text_tokens, term, similar=similar)
    ]


def publication_window_status(
    row: dict[str, str],
    publication_window: dict[str, str] | None,
) -> str:
    row_start = row.get("corpus_publication_window_start", "").strip()
    row_end = row.get("corpus_publication_window_end", "").strip()
    row_inclusive = row.get("corpus_publication_window_inclusive", "").strip()
    if bool(row_start) != bool(row_end):
        return "publication_window_constraint_mismatch"
    if row_start and row_inclusive.casefold() not in {"", "1", "true", "yes"}:
        return "publication_window_constraint_mismatch"

    row_window = (
        {"start": row_start, "end": row_end}
        if row_start and row_end
        else None
    )
    if publication_window is not None and row_window is not None:
        if row_window != publication_window:
            return "publication_window_constraint_mismatch"
    effective_window = publication_window or row_window
    if effective_window is None:
        return "not_configured"

    try:
        start = date.fromisoformat(effective_window["start"])
        end = date.fromisoformat(effective_window["end"])
    except (KeyError, ValueError):
        return "publication_window_constraint_mismatch"
    if start > end:
        return "publication_window_constraint_mismatch"
    raw_date = row.get("publication_date", "").strip()
    if raw_date:
        try:
            published = date.fromisoformat(raw_date)
        except ValueError:
            return "invalid_publication_date"
        raw_year = row.get("year", "").strip()
        if raw_year and (
            re.fullmatch(r"\d{4}", raw_year) is None
            or int(raw_year) != published.year
        ):
            return "publication_date_year_mismatch"
        if published < start:
            return "before_publication_window"
        if published > end:
            return "after_publication_window"
        return "eligible_exact_date"

    year_match = re.fullmatch(r"\d{4}", row.get("year", "").strip())
    if year_match is None:
        return "missing_publication_date"
    year = int(year_match.group(0))
    year_start = date(year, 1, 1)
    year_end = date(year, 12, 31)
    if year_end < start:
        return "before_publication_window"
    if year_start > end:
        return "after_publication_window"
    if year_start >= start and year_end <= end:
        return "eligible_whole_year"
    return "missing_exact_boundary_date"


def decide_scope(
    row: dict[str, str],
    include_terms: list[str],
    exclude_terms: list[str],
    exclude_wins: bool = True,
    publication_window: dict[str, str] | None = None,
) -> dict[str, str]:
    text = text_for_screening(row)
    matched_exclude = matched_terms(text, exclude_terms, similar=False)
    matched_include = matched_terms(text, include_terms, similar=True)
    date_status = publication_window_status(row, publication_window)

    if date_status in PUBLICATION_WINDOW_REJECTION_STATUSES:
        decision = "exclude_or_route_elsewhere"
        reason = (
            "Publication-window constraint not satisfied: "
            f"{date_status}"
        )
    elif matched_exclude and (exclude_wins or not matched_include):
        decision = "exclude_or_route_elsewhere"
        reason = (
            f"Matched exclude term(s): {', '.join(matched_exclude)}; "
            f"matched include term(s): {', '.join(matched_include) if matched_include else 'none'}"
        )
    elif matched_include:
        decision = "include"
        reason = f"Matched include term(s): {', '.join(matched_include)}"
    else:
        decision = "include"
        reason = "No exclude term matched; included for downstream tagging."

    return {
        "scope_decision": decision,
        "scope_reason": reason,
        "scope_matched_include_terms": "; ".join(matched_include),
        "scope_matched_exclude_terms": "; ".join(matched_exclude),
        "scope_publication_window_status": date_status,
    }


def read_rows(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        return list(reader.fieldnames or []), list(reader)


def output_columns(input_columns: list[str]) -> list[str]:
    columns = list(input_columns)
    for column in SCOPE_COLUMNS:
        if column not in columns:
            columns.append(column)
    return columns


def write_rows(
    path: Path,
    rows: list[dict[str, str]],
    fieldnames: list[str],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)

    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({column: row.get(column, "") for column in fieldnames})


def settings_from_contract(topic_contract_path: Path) -> dict[str, Any]:
    contract = load_topic_contract(topic_contract_path)
    settings = rule_based_screening_from_contract(contract)
    collection = collection_from_contract(contract)
    publication_window = collection.get("publication_window")
    settings["publication_window"] = (
        dict(publication_window) if isinstance(publication_window, dict) else None
    )
    return settings


def screen_rows(
    rows: list[dict[str, str]],
    include_terms: list[str],
    exclude_terms: list[str],
    exclude_wins: bool,
    publication_window: dict[str, str] | None = None,
) -> list[dict[str, str]]:
    screened_rows = []
    for row in rows:
        screened_rows.append(
            {
                **row,
                **decide_scope(
                    row,
                    include_terms,
                    exclude_terms,
                    exclude_wins,
                    publication_window,
                ),
            }
        )
    return screened_rows


def run(
    input_path: Path,
    output_path: Path,
    topic_contract_path: Path,
) -> StepResult:
    fieldnames, rows = read_rows(input_path)
    settings = settings_from_contract(topic_contract_path)
    screened_rows = screen_rows(
        rows,
        list(settings["include_terms"]),
        list(settings["exclude_terms"]),
        bool(settings["exclude_wins"]),
        settings.get("publication_window"),
    )
    write_rows(output_path, screened_rows, output_columns(fieldnames))
    carried_windows = sorted(
        {
            (
                row.get("corpus_publication_window_start", "").strip(),
                row.get("corpus_publication_window_end", "").strip(),
            )
            for row in rows
            if row.get("corpus_publication_window_start", "").strip()
            or row.get("corpus_publication_window_end", "").strip()
        }
    )

    return StepResult(
        step_name=STEP.name,
        inputs={
            "normalized_papers_csv": input_path,
            "topic_contract_yaml": topic_contract_path,
        },
        outputs={"scope_screened_csv": output_path},
        row_counts={
            "papers_screened": len(screened_rows),
            "scope_included": sum(
                row.get("scope_decision") == "include"
                for row in screened_rows
            ),
            "scope_excluded_or_routed": sum(
                row.get("scope_decision") == "exclude_or_route_elsewhere"
                for row in screened_rows
            ),
            "publication_window_rejections": sum(
                row.get("scope_publication_window_status")
                in PUBLICATION_WINDOW_REJECTION_STATUSES
                for row in screened_rows
            ),
        },
        metadata={
            "topic_contract_publication_window": settings.get(
                "publication_window"
            ),
            "carried_corpus_publication_windows": [
                {"start": start, "end": end}
                for start, end in carried_windows
            ],
        },
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Screen papers against a topic contract scope."
    )
    parser.add_argument(
        "--input",
        default="data/processed/example_papers_normalized.csv",
        help="Normalized input CSV.",
    )
    parser.add_argument(
        "--output",
        default="data/processed/example_scope_screened.csv",
        help="Output screened CSV.",
    )
    parser.add_argument(
        "--topic-contract",
        required=True,
        help="Topic contract YAML with rule-based screening terms.",
    )
    args = parser.parse_args()

    result = run(Path(args.input), Path(args.output), Path(args.topic_contract))

    print(f"Screened {result.row_counts['papers_screened']} papers")
    print(f"Wrote {args.output}")
