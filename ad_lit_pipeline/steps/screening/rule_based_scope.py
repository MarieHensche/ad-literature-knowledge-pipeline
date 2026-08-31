from __future__ import annotations

import argparse
import csv
import html
import re
from pathlib import Path
from typing import Any

from ad_lit_pipeline.core.step import StepResult, StepSpec
from ad_lit_pipeline.topics.contract import (
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
]


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


def token_overlap_matches(text_tokens: set[str], term: str) -> bool:
    tokens = meaningful_tokens(term)
    if len(tokens) < 2:
        return False

    matched = sum(1 for token in tokens if token in text_tokens)
    required = len(tokens) if len(tokens) == 2 else max(2, int(len(tokens) * 0.67))
    return matched >= required


def term_matches(text: str, text_tokens: set[str], term: str, similar: bool) -> bool:
    for variant in term_variants(term):
        if contains_phrase(text, variant):
            return True

    return similar and token_overlap_matches(text_tokens, term)


def matched_terms(text: str, terms: list[str], similar: bool = True) -> list[str]:
    normalized_text = normalize_text(text)
    text_tokens = {normalize_token(token) for token in normalized_text.split()}
    return [
        term
        for term in terms
        if term_matches(normalized_text, text_tokens, term, similar=similar)
    ]


def decide_scope(
    row: dict[str, str],
    include_terms: list[str],
    exclude_terms: list[str],
    exclude_wins: bool = True,
) -> dict[str, str]:
    text = text_for_screening(row)
    matched_exclude = matched_terms(text, exclude_terms, similar=False)
    matched_include = matched_terms(text, include_terms, similar=True)

    if matched_exclude and (exclude_wins or not matched_include):
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
    return rule_based_screening_from_contract(contract)


def screen_rows(
    rows: list[dict[str, str]],
    include_terms: list[str],
    exclude_terms: list[str],
    exclude_wins: bool,
) -> list[dict[str, str]]:
    screened_rows = []
    for row in rows:
        screened_rows.append(
            {
                **row,
                **decide_scope(row, include_terms, exclude_terms, exclude_wins),
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
    )
    write_rows(output_path, screened_rows, output_columns(fieldnames))

    return StepResult(
        step_name=STEP.name,
        inputs={
            "normalized_papers_csv": input_path,
            "topic_contract_yaml": topic_contract_path,
        },
        outputs={"scope_screened_csv": output_path},
        row_counts={"papers_screened": len(screened_rows)},
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
