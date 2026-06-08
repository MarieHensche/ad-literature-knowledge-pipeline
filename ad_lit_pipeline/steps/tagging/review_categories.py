from __future__ import annotations

import argparse
import csv
import os
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ad_lit_pipeline.core.env import load_dotenv
from ad_lit_pipeline.core.errors import PipelinePause
from ad_lit_pipeline.core.step import StepResult, StepSpec
from ad_lit_pipeline.io.jsonl_io import read_jsonl_objects
from ad_lit_pipeline.io.yaml_io import read_yaml_object, write_yaml_object
from ad_lit_pipeline.llm.client import JSONLLMClient, OpenAIResponsesClient
from ad_lit_pipeline.llm.schemas import tagging_category_value_completion_schema
from ad_lit_pipeline.llm.trace import LLMTraceWriter
from ad_lit_pipeline.prompts.render import render_complete_tagging_category_values_prompt
from ad_lit_pipeline.steps.full_text.evidence import read_text_evidence
from ad_lit_pipeline.topics.contract import (
    load_topic_contract,
    normalize_tagging_label,
    validate_generated_tagging_quality,
    validate_topic_contract,
)


STEP = StepSpec(
    name="review_tagging_categories",
    inputs=["topic_contract_yaml"],
    outputs=["tagging_categories_review_yaml", "topic_contract_yaml"],
    uses_llm=True,
    description="Pause for user review of tagging categories and values.",
)

SYSTEM_MESSAGE = "You complete user-requested tagging category values as strict JSON."
STATUS_NEEDS_REVIEW = "needs_review"
STATUS_APPROVED = "approved"
AUTO_VALUE_MARKERS = {"auto", "fill", "fill_values", "generate"}
MAX_REVIEW_EVIDENCE_RECORDS = 5
MAX_PAPER_EVIDENCE_RECORDS = 6
MAX_EVIDENCE_CHARS = 6_000
GENERIC_FALLBACK_POLICY_KEYS = {
    "prefer_unclear_when_allowed",
    "prefer_mixed_or_unclear_when_unclear_missing",
    "missing_information_value",
}


@dataclass(frozen=True)
class ReviewedCategory:
    category_id: str
    values: list[str]
    needs_values: bool = False


def category_review_payload(
    contract: dict[str, Any],
    topic_contract_path: Path,
) -> dict[str, Any]:
    """Return a small YAML-ready projection for human category review."""
    categories = contract["tagging"]["categories"]
    return {
        "status": STATUS_NEEDS_REVIEW,
        "source_topic_contract": str(topic_contract_path),
        "instructions": [
            "Edit only categories and values.",
            "Delete a category key to remove the category.",
            "Delete values from a category to remove only those values.",
            "Add values under an existing category to allow new values.",
            (
                "Add a new category with values: auto or values: [] to have "
                "the pipeline propose values from available full-text evidence."
            ),
            "Set status to approved when the categories are ready to merge.",
        ],
        "categories": {
            str(category_id): {"values": list(category.get("values", []))}
            for category_id, category in categories.items()
            if isinstance(category, dict)
        },
    }


def write_initial_review_file(
    review_path: Path,
    topic_contract_path: Path,
    contract: dict[str, Any],
) -> None:
    payload = category_review_payload(contract, topic_contract_path)
    write_yaml_object(review_path, payload)


def review_status(payload: dict[str, Any]) -> str:
    return str(payload.get("status") or "").strip().lower()


def values_need_completion(raw_values: object) -> bool:
    if raw_values is None:
        return True
    if isinstance(raw_values, str):
        return normalize_tagging_label(raw_values) in AUTO_VALUE_MARKERS
    if isinstance(raw_values, list):
        return len(raw_values) == 0
    return False


def normalize_review_values(category_id: str, raw_values: object) -> list[str]:
    if not isinstance(raw_values, list):
        raise ValueError(
            f"Reviewed category {category_id} values must be a list or 'auto'."
        )

    values = []
    seen = set()
    for value in raw_values:
        if not isinstance(value, str):
            raise ValueError(f"Reviewed category {category_id} values must be strings.")
        normalized = normalize_tagging_label(value)
        if not normalized or normalized in seen:
            continue
        values.append(normalized)
        seen.add(normalized)
    return values


def category_values_from_review_payload(
    category_id: str,
    payload: object,
) -> tuple[list[str], bool]:
    raw_values = payload.get("values") if isinstance(payload, dict) else payload
    if values_need_completion(raw_values):
        return [], True
    return normalize_review_values(category_id, raw_values), False


def reviewed_categories_from_payload(
    payload: dict[str, Any],
) -> dict[str, ReviewedCategory]:
    categories = payload.get("categories")
    if not isinstance(categories, dict):
        raise ValueError("Review file must contain a categories mapping.")

    reviewed: dict[str, ReviewedCategory] = {}
    raw_to_normalized: dict[str, str] = {}
    for raw_category_id, category_payload in categories.items():
        category_id = normalize_tagging_label(str(raw_category_id))
        if not category_id:
            raise ValueError("Reviewed category ids must not be empty.")
        if category_id in reviewed:
            original = raw_to_normalized[category_id]
            raise ValueError(
                "Reviewed categories contain duplicate ids after normalization: "
                f"{original}, {raw_category_id}"
            )

        values, needs_values = category_values_from_review_payload(
            category_id,
            category_payload,
        )
        reviewed[category_id] = ReviewedCategory(
            category_id=category_id,
            values=values,
            needs_values=needs_values,
        )
        raw_to_normalized[category_id] = str(raw_category_id)

    if not reviewed:
        raise ValueError("Review file must keep at least one category.")
    return reviewed


def categories_needing_values(
    reviewed_categories: dict[str, ReviewedCategory],
) -> list[ReviewedCategory]:
    return [
        category
        for category in reviewed_categories.values()
        if category.needs_values
    ]


def read_csv_rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def review_evidence_records(path: Path | None) -> list[dict[str, Any]]:
    if path is None or not path.exists():
        return []

    records = []
    for index, record in enumerate(read_jsonl_objects(path), start=1):
        evidence = read_text_evidence(
            str(record.get("full_text_text_path") or ""),
            max_chars=MAX_EVIDENCE_CHARS,
        )
        if not evidence:
            continue
        records.append(
            {
                "source_type": "review",
                "evidence_id": str(
                    record.get("provider_id")
                    or record.get("doi")
                    or record.get("paper_id")
                    or f"review_{index}"
                ),
                "title": str(record.get("title") or ""),
                "full_text_evidence": evidence,
            }
        )
        if len(records) >= MAX_REVIEW_EVIDENCE_RECORDS:
            break
    return records


def paper_evidence_records(path: Path | None) -> list[dict[str, Any]]:
    if path is None or not path.exists():
        return []

    records = []
    for index, row in enumerate(read_csv_rows(path), start=1):
        if row.get("scope_decision") and row.get("scope_decision") != "include":
            continue
        evidence = read_text_evidence(
            row.get("full_text_text_path", ""),
            max_chars=MAX_EVIDENCE_CHARS,
        )
        if not evidence:
            continue
        records.append(
            {
                "source_type": "included_paper",
                "evidence_id": row.get("paper_id") or f"paper_{index}",
                "title": row.get("title", ""),
                "abstract": row.get("abstract", ""),
                "full_text_evidence": evidence,
            }
        )
        if len(records) >= MAX_PAPER_EVIDENCE_RECORDS:
            break
    return records


def available_value_completion_evidence(
    review_overviews_path: Path | None,
    papers_path: Path | None,
) -> list[dict[str, Any]]:
    """Prefer review evidence, then fill with included primary paper evidence."""
    review_records = review_evidence_records(review_overviews_path)
    paper_records = paper_evidence_records(papers_path)
    return review_records + paper_records


def requested_category_payloads(
    requested: list[ReviewedCategory],
    current_categories: dict[str, Any],
) -> list[dict[str, Any]]:
    payloads = []
    for category in requested:
        existing = current_categories.get(category.category_id)
        payload: dict[str, Any] = {
            "category_id": category.category_id,
            "existing_category": isinstance(existing, dict),
        }
        if isinstance(existing, dict):
            payload["current_values"] = list(existing.get("values", []))
        payloads.append(payload)
    return payloads


def validate_completed_values(
    requested: list[ReviewedCategory],
    result: dict[str, Any],
) -> dict[str, list[str]]:
    requested_ids = {category.category_id for category in requested}
    raw_categories = result.get("categories")
    if not isinstance(raw_categories, list):
        raise ValueError("Value-completion response must contain categories list.")

    completed: dict[str, list[str]] = {}
    for category in raw_categories:
        if not isinstance(category, dict):
            raise ValueError("Value-completion categories must contain objects.")
        category_id = normalize_tagging_label(str(category.get("category_id") or ""))
        if category_id not in requested_ids:
            raise ValueError(
                "Value-completion response returned unexpected category: "
                f"{category_id}"
            )
        values = normalize_review_values(category_id, category.get("values"))
        if len(values) < 2:
            raise ValueError(
                f"Value-completion response needs at least two values for {category_id}."
            )
        completed[category_id] = values

    missing = sorted(requested_ids - set(completed))
    if missing:
        raise ValueError(
            "Value-completion response omitted category value(s): "
            + ", ".join(missing)
        )
    return completed


def call_value_completion_llm(
    topic_contract: dict[str, Any],
    requested: list[ReviewedCategory],
    evidence: list[dict[str, Any]],
    model: str,
    client: JSONLLMClient,
    trace_writer: LLMTraceWriter | None = None,
) -> tuple[dict[str, list[str]], list[Path]]:
    current_categories = topic_contract["tagging"]["categories"]
    prompt = render_complete_tagging_category_values_prompt(
        topic_contract=topic_contract,
        existing_categories=current_categories,
        requested_categories=requested_category_payloads(
            requested,
            current_categories,
        ),
        evidence=evidence,
    )
    category_ids = [category.category_id for category in requested]
    result = client.create_json(
        model=model,
        system_message=SYSTEM_MESSAGE,
        prompt=prompt,
        schema_name="tagging_category_values",
        schema=tagging_category_value_completion_schema(category_ids),
        step_name=STEP.name,
        call_id="category_value_completion",
        trace_writer=trace_writer,
    )
    trace_paths = result.trace_paths.as_list() if result.trace_paths else []
    return validate_completed_values(requested, result.parsed), trace_paths


def default_new_category(category_id: str) -> dict[str, Any]:
    return {
        "description": f"User-added tagging category: {category_id}.",
        "required": False,
        "selection": "multi",
        "values": [],
        "applies_when": None,
    }


def cleanup_category_dependencies(
    categories: dict[str, Any],
) -> list[str]:
    warnings = []
    for category_id, category in categories.items():
        if not isinstance(category, dict):
            continue
        applies_when = category.get("applies_when")
        if applies_when in (None, {}):
            category["applies_when"] = None
            continue
        if not isinstance(applies_when, dict):
            category["applies_when"] = None
            warnings.append(f"Removed invalid applies_when for {category_id}.")
            continue

        parent_id = normalize_tagging_label(str(applies_when.get("category_id") or ""))
        parent = categories.get(parent_id)
        if not isinstance(parent, dict):
            category["applies_when"] = None
            warnings.append(
                f"Removed applies_when for {category_id}; parent category was removed."
            )
            continue

        parent_values = set(parent.get("values", []))
        values = [
            normalize_tagging_label(value)
            for value in applies_when.get("values", [])
            if normalize_tagging_label(value) in parent_values
        ]
        if not values:
            category["applies_when"] = None
            warnings.append(
                f"Removed applies_when for {category_id}; trigger values were removed."
            )
            continue

        category["applies_when"] = {"category_id": parent_id, "values": values}
    return warnings


def cleanup_fallback_policy(
    tagging: dict[str, Any],
) -> list[str]:
    warnings = []
    policy = tagging.get("fallback_policy")
    categories = tagging.get("categories")
    if not isinstance(policy, dict) or not isinstance(categories, dict):
        return warnings

    for key in list(policy):
        if key in GENERIC_FALLBACK_POLICY_KEYS:
            continue
        category = categories.get(key)
        if not isinstance(category, dict):
            del policy[key]
            warnings.append(
                f"Removed fallback policy for removed category {key}."
            )
            continue

        value = policy.get(key)
        if isinstance(value, str) and value not in set(category.get("values", [])):
            del policy[key]
            warnings.append(
                f"Removed fallback policy for {key}; value {value} is no "
                "longer allowed."
            )
    return warnings


def merge_reviewed_categories(
    contract: dict[str, Any],
    reviewed_categories: dict[str, ReviewedCategory],
    completed_values: dict[str, list[str]] | None = None,
) -> tuple[dict[str, Any], list[str]]:
    completed_values = completed_values or {}
    merged = deepcopy(contract)
    current_categories = contract["tagging"]["categories"]
    merged_categories: dict[str, Any] = {}
    warnings = []

    removed_category_ids = sorted(set(current_categories) - set(reviewed_categories))
    if removed_category_ids:
        warnings.append(
            "Removed tagging categories: " + ", ".join(removed_category_ids)
        )

    for category_id, reviewed in reviewed_categories.items():
        existing_category = current_categories.get(category_id)
        if isinstance(existing_category, dict):
            category = deepcopy(existing_category)
        else:
            category = default_new_category(category_id)
            warnings.append(f"Added user-requested tagging category: {category_id}")

        values = completed_values.get(category_id) if reviewed.needs_values else None
        if values is None:
            values = reviewed.values
        category["values"] = values
        category.setdefault("required", False)
        category.setdefault("selection", "multi")
        category.setdefault("applies_when", None)
        merged_categories[category_id] = category

    merged["tagging"]["categories"] = merged_categories
    warnings.extend(cleanup_category_dependencies(merged_categories))
    warnings.extend(cleanup_fallback_policy(merged["tagging"]))
    validate_topic_contract(merged)
    validate_generated_tagging_quality(merged, label="Reviewed topic contract")
    return merged, warnings


def pause_result(
    topic_contract_path: Path,
    review_path: Path,
    contract: dict[str, Any],
    status: str,
) -> StepResult:
    categories = contract["tagging"]["categories"]
    return StepResult(
        step_name=STEP.name,
        inputs={"topic_contract_yaml": topic_contract_path},
        outputs={
            "tagging_categories_review_yaml": review_path,
            "topic_contract_yaml": topic_contract_path,
        },
        row_counts={"tagging_categories": len(categories)},
        metadata={
            "review_status": status,
            "review_file": str(review_path),
        },
    )


def pause_for_review(
    topic_contract_path: Path,
    review_path: Path,
    contract: dict[str, Any],
    status: str,
) -> None:
    message = (
        "Review tagging categories before continuing. Edit "
        f"{review_path}, set status to approved, then resume from "
        f"{STEP.name}."
    )
    raise PipelinePause(
        message,
        pause_result(topic_contract_path, review_path, contract, status),
    )


def run(
    topic_contract_path: Path,
    review_path: Path,
    model: str,
    review_overviews_path: Path | None = None,
    papers_path: Path | None = None,
    client: JSONLLMClient | None = None,
    trace_dir: Path | None = None,
) -> StepResult:
    contract = load_topic_contract(topic_contract_path)
    if not review_path.exists():
        write_initial_review_file(review_path, topic_contract_path, contract)
        pause_for_review(
            topic_contract_path,
            review_path,
            contract,
            STATUS_NEEDS_REVIEW,
        )

    review_payload = read_yaml_object(review_path)
    status = review_status(review_payload)
    if status != STATUS_APPROVED:
        pause_for_review(topic_contract_path, review_path, contract, status)

    reviewed_categories = reviewed_categories_from_payload(review_payload)
    requested_value_completion = categories_needing_values(reviewed_categories)
    trace_writer = LLMTraceWriter(trace_dir) if trace_dir is not None else None
    trace_paths: list[Path] = []
    completed_values: dict[str, list[str]] = {}

    if requested_value_completion:
        evidence = available_value_completion_evidence(
            review_overviews_path,
            papers_path,
        )
        if not evidence:
            requested_ids = ", ".join(
                category.category_id for category in requested_value_completion
            )
            raise ValueError(
                "Cannot auto-fill values for reviewed category/categories without "
                f"review or included-paper full-text evidence: {requested_ids}. "
                "Add values manually, or run review/full-text preparation first."
            )
        completed_values, trace_paths = call_value_completion_llm(
            contract,
            requested_value_completion,
            evidence,
            model,
            client or OpenAIResponsesClient(),
            trace_writer,
        )

    reviewed_contract, warnings = merge_reviewed_categories(
        contract,
        reviewed_categories,
        completed_values,
    )
    write_yaml_object(topic_contract_path, reviewed_contract)
    categories = reviewed_contract["tagging"]["categories"]
    values_count = sum(
        len(category.get("values", []))
        for category in categories.values()
        if isinstance(category, dict)
    )

    return StepResult(
        step_name=STEP.name,
        inputs={
            "topic_contract_yaml": topic_contract_path,
            "tagging_categories_review_yaml": review_path,
        },
        outputs={
            "tagging_categories_review_yaml": review_path,
            "topic_contract_yaml": topic_contract_path,
        },
        row_counts={
            "tagging_categories": len(categories),
            "tagging_values": values_count,
            "auto_completed_categories": len(requested_value_completion),
        },
        warnings=warnings,
        trace_paths=trace_paths,
        metadata={
            "review_status": status,
            "review_file": str(review_path),
        },
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Review and merge topic-contract tagging categories."
    )
    parser.add_argument("--topic-contract", required=True, help="Topic contract YAML.")
    parser.add_argument(
        "--review-file",
        required=True,
        help="Editable tagging categories review YAML.",
    )
    parser.add_argument(
        "--review-overviews",
        default=None,
        help="Optional review/overview JSONL with full-text paths for value completion.",
    )
    parser.add_argument(
        "--papers",
        default=None,
        help="Optional scope-screened full-text CSV for value completion.",
    )
    parser.add_argument(
        "--model",
        default=None,
        help="OpenAI model. Defaults to OPENAI_MODEL or gpt-4o-mini.",
    )
    parser.add_argument(
        "--trace-dir",
        default=None,
        help="Optional directory where value-completion traces are written.",
    )
    args = parser.parse_args()

    load_dotenv()
    model = args.model or os.getenv("OPENAI_MODEL", "gpt-4o-mini")
    trace_dir = Path(args.trace_dir) if args.trace_dir else None
    try:
        result = run(
            Path(args.topic_contract),
            Path(args.review_file),
            model,
            review_overviews_path=(
                Path(args.review_overviews) if args.review_overviews else None
            ),
            papers_path=Path(args.papers) if args.papers else None,
            trace_dir=trace_dir,
        )
    except PipelinePause as pause:
        print(str(pause))
        return

    print(f"Review status: {result.metadata['review_status']}")
    print(f"Tagging categories: {result.row_counts['tagging_categories']}")
    print(f"Tagging values: {result.row_counts['tagging_values']}")
    print(f"Wrote {args.topic_contract}")


if __name__ == "__main__":
    main()
