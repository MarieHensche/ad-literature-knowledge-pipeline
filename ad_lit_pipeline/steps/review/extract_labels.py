from __future__ import annotations

import argparse
import csv
import json
import os
import re
from pathlib import Path
from typing import Any

from ad_lit_pipeline.core.env import load_dotenv
from ad_lit_pipeline.core.step import StepResult, StepSpec
from ad_lit_pipeline.io.json_io import read_json_object
from ad_lit_pipeline.llm.client import JSONLLMClient, OpenAIResponsesClient
from ad_lit_pipeline.llm.schemas import review_labels_schema
from ad_lit_pipeline.llm.trace import LLMTraceWriter
from ad_lit_pipeline.prompts.render import render_extract_review_labels_prompt
from ad_lit_pipeline.steps.full_text.evidence import normalize_space, split_sections
from ad_lit_pipeline.topics.contract import normalize_tagging_label


STEP = StepSpec(
    name="extract_review_labels",
    inputs=["scope_screened_full_text_csv", "review_config_normalized_json"],
    outputs=["review_labels_raw_csv"],
    uses_llm=True,
    description="Extract paper-level labels used only for literature reviews.",
)

SYSTEM_MESSAGE = (
    "You extract literature-review evidence from scientific papers as strict JSON."
)
MAX_LABEL_EVIDENCE_CHARS = 2_500
REVIEW_TITLE_PATTERNS = [
    re.compile(pattern, re.IGNORECASE)
    for pattern in [
        r"\bsystematic\s+reviews?\b",
        r"\bscoping\s+reviews?\b",
        r"\bliterature\s+reviews?\b",
        r"\bnarrative\s+reviews?\b",
        r"\bumbrella\s+reviews?\b",
        r"\brapid\s+reviews?\b",
        r"\breviews?\s+and\s+meta[-\s]?analys(?:is|es)\b",
        r"\bmeta[-\s]?analys(?:is|es)\b",
        r"\bsurveys?\b",
        r"\boverviews?\b",
        r"\bcurrent\s+trends?\b",
        r"\bfuture\s+perspectives?\b",
        r"\bprogress,\s+challenges,\s+and\s+future\s+directions?\b",
        r"\bchallenges\s+and\s+future\s+directions?\b",
        r"\bstate[-\s]+of[-\s]+the[-\s]+art\b",
        r"\bbibliometric\b",
        r"\bscientometric\b",
        r"\breviews?\b",
    ]
]
REVIEW_ABSTRACT_PATTERNS = [
    re.compile(pattern, re.IGNORECASE)
    for pattern in [
        (
            r"\bin\s+this\s+review,\s+we\s+"
            r"(?:summarize|review|survey|discuss|examine|highlight|provide)\b"
        ),
        (
            r"\bthis\s+review\s+"
            r"(?:summarizes|reviews|surveys|discusses|examines|highlights|provides)\b"
        ),
        (
            r"\bwe\s+(?:summarize|review|survey)\s+"
            r"(?:recent|current|existing|the)\s+.*\bin\s+this\s+review\b"
        ),
    ]
]
REVIEW_METADATA_COLUMNS = [
    "type",
    "work_type",
    "publication_type",
    "publication_types",
    "article_type",
    "document_type",
    "paper_type",
]
METADATA_COLUMNS = [
    "paper_id",
    "title",
    "year",
    "doi",
    "authors",
    "venue",
    "source",
]


def read_csv_rows(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        return list(reader.fieldnames or []), list(reader)


def included_rows(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    return [
        row
        for row in rows
        if not row.get("scope_decision") or row.get("scope_decision") == "include"
    ]


def is_likely_review_paper(row: dict[str, str]) -> bool:
    title = normalize_space(row.get("title", ""))
    if title and any(pattern.search(title) for pattern in REVIEW_TITLE_PATTERNS):
        return True

    abstract = normalize_space(row.get("abstract", ""))
    if abstract and any(
        pattern.search(abstract) for pattern in REVIEW_ABSTRACT_PATTERNS
    ):
        return True

    for column in REVIEW_METADATA_COLUMNS:
        value = normalize_space(row.get(column, "")).casefold()
        values = {
            item.strip().replace("-", "_").replace(" ", "_")
            for item in re.split(r"[;,|]", value)
            if item.strip()
        }
        if "review" in values or "meta_analysis" in values:
            return True

    return False


def review_eligible_rows(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    return [row for row in included_rows(rows) if not is_likely_review_paper(row)]


def read_full_text(row: dict[str, str]) -> str:
    text_path = row.get("full_text_text_path", "")
    if not text_path:
        return ""
    path = Path(text_path).expanduser()
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8", errors="ignore")


def bounded_text(value: str, max_chars: int = MAX_LABEL_EVIDENCE_CHARS) -> str:
    text = normalize_space(value)
    if len(text) <= max_chars:
        return text
    return text[:max_chars].rsplit(" ", 1)[0].strip()


def split_full_text_sections(full_text: str) -> list[tuple[str, str, str]]:
    return split_sections(full_text)


def sections_by_key(full_text: str) -> dict[str, list[str]]:
    grouped: dict[str, list[str]] = {}
    for key, heading, body in split_full_text_sections(full_text):
        label = heading if heading != "body" else key.replace("_", " ").title()
        grouped.setdefault(key, []).append(f"[{label}]\n{body}")
    return grouped


def available_section_headings(full_text: str) -> list[dict[str, str]]:
    headings = []
    seen = set()
    for key, heading, _body in split_full_text_sections(full_text):
        marker = (key, heading)
        if marker in seen:
            continue
        headings.append({"section_key": key, "heading": heading})
        seen.add(marker)
    return headings


def label_evidence(
    row: dict[str, str],
    full_text: str,
    label: dict[str, Any],
) -> dict[str, str]:
    grouped_sections = sections_by_key(full_text)
    parts = []
    used_sections = []
    for section in label.get("evidence_sections", []):
        section_key = normalize_tagging_label(str(section))
        if section_key == "title" and row.get("title"):
            parts.append(f"[Title]\n{row['title']}")
            used_sections.append("title")
            continue
        if section_key == "abstract" and row.get("abstract"):
            parts.append(f"[Abstract]\n{row['abstract']}")
            used_sections.append("abstract")
            continue
        for body in grouped_sections.get(section_key, []):
            parts.append(body)
            used_sections.append(section_key)

    if not parts and row.get("abstract"):
        parts.append(f"[Abstract]\n{row['abstract']}")
        used_sections.append("abstract")

    return {
        "text": bounded_text("\n\n".join(parts)),
        "sections_used": "; ".join(dict.fromkeys(used_sections)),
    }


def enforce_max_words(value: str, max_words: int | None) -> str:
    normalized = normalize_tagging_label(value)
    if not max_words:
        return normalized
    words = [part for part in normalized.split("_") if part]
    return "_".join(words[:max_words])


def constrained_controlled_values(
    values: list[str],
    label: dict[str, Any],
) -> list[str]:
    max_words = label.get("max_words_per_value")
    max_values = label.get("max_values_per_paper")
    constrained = []
    seen = set()
    for value in values:
        normalized = enforce_max_words(value, max_words)
        if normalized and normalized not in seen:
            constrained.append(normalized)
            seen.add(normalized)
    if isinstance(max_values, int):
        constrained = constrained[:max_values]
    return constrained


def split_free_text_items(raw_value: str) -> list[str]:
    parts = []
    for line in str(raw_value or "").replace("\n", ";").split(";"):
        cleaned = normalize_space(line)
        if cleaned:
            parts.append(cleaned)
    return parts


def constrain_free_text_item(value: str, max_words: int | None) -> str:
    cleaned = normalize_space(value)
    if not max_words:
        return cleaned
    return " ".join(cleaned.split()[:max_words])


def constrained_free_text_value(value: str, label: dict[str, Any]) -> str:
    missing_value = str(label.get("missing_value") or "").strip()
    max_items = label.get("max_items_per_paper")
    max_words = label.get("max_words_per_item")
    items = split_free_text_items(value)
    if isinstance(max_items, int):
        items = items[:max_items]
    items = [
        item
        for item in (
            constrain_free_text_item(item, max_words)
            for item in items
        )
        if item
    ]
    if not items and missing_value:
        return missing_value
    return "; ".join(items)


def paper_payload(
    row: dict[str, str],
    full_text: str,
    review_config: dict[str, Any],
) -> dict[str, Any]:
    labels = review_config["review"]["labels"]
    evidence_by_label = {}
    sections_used = []
    for label in labels:
        evidence = label_evidence(row, full_text, label)
        evidence_by_label[str(label["label_id"])] = evidence["text"]
        if evidence["sections_used"]:
            sections_used.extend(evidence["sections_used"].split("; "))

    return {
        "paper_id": row.get("paper_id", ""),
        "title": row.get("title", ""),
        "year": row.get("year", ""),
        "doi": row.get("doi", ""),
        "authors": row.get("authors", ""),
        "venue": row.get("venue", ""),
        "abstract": row.get("abstract", ""),
        "available_section_headings": available_section_headings(full_text),
        "evidence_sections_available": sorted(set(sections_used)),
        "evidence_by_label": evidence_by_label,
    }


def label_by_id(config: dict[str, Any]) -> dict[str, dict[str, Any]]:
    labels = config.get("review", {}).get("labels")
    if not isinstance(labels, list):
        raise ValueError("Normalized review config must contain review.labels list.")
    return {str(label["label_id"]): label for label in labels}


def validate_and_normalize_labels(
    parsed: dict[str, Any],
    config: dict[str, Any],
) -> dict[str, Any]:
    labels = parsed.get("labels")
    if not isinstance(labels, dict):
        raise ValueError("Review-label response must contain labels object.")

    normalized: dict[str, Any] = {}
    for label_id, label in label_by_id(config).items():
        value_mode = str(label.get("value_mode") or "")
        value = labels.get(label_id)
        if value_mode in {"controlled_fixed", "controlled_auto"}:
            if not isinstance(value, list):
                raise ValueError(f"{label_id} must be a list.")
            values = constrained_controlled_values(
                [str(item) for item in value],
                label,
            )
            allowed = {
                str(item.get("value"))
                for item in label.get("allowed_values", [])
                if isinstance(item, dict)
            }
            if allowed:
                invalid = [item for item in values if item not in allowed]
                if invalid:
                    raise ValueError(f"{label_id} has invalid value(s): {invalid}")
            if label.get("selection") == "single" and len(values) > 1:
                values = values[:1]
            normalized[label_id] = values
        elif value_mode == "evidence_quote":
            if not isinstance(value, list):
                raise ValueError(f"{label_id} must be a list.")
            quotes = []
            for item in value:
                if not isinstance(item, dict):
                    raise ValueError(f"{label_id} quote items must be objects.")
                quote = str(item.get("quote") or "").strip()
                if not quote:
                    continue
                quotes.append(
                    {
                        "quote": quote,
                        "section": str(item.get("section") or "").strip(),
                        "reason": str(item.get("reason") or "").strip(),
                    }
                )
            normalized[label_id] = quotes
        else:
            normalized[label_id] = constrained_free_text_value(str(value or ""), label)

    return normalized


def call_llm(
    paper: dict[str, Any],
    review_config: dict[str, Any],
    model: str,
    client: JSONLLMClient,
    trace_writer: LLMTraceWriter | None = None,
) -> tuple[dict[str, Any], list[Path]]:
    prompt = render_extract_review_labels_prompt(paper, review_config)
    result = client.create_json(
        model=model,
        system_message=SYSTEM_MESSAGE,
        prompt=prompt,
        schema_name="review_labels",
        schema=review_labels_schema(review_config),
        step_name=STEP.name,
        call_id=str(paper.get("paper_id") or "paper"),
        trace_writer=trace_writer,
    )
    trace_paths = result.trace_paths.as_list() if result.trace_paths else []
    return result.parsed, trace_paths


def flatten_review_row(
    paper: dict[str, str],
    labels: dict[str, Any],
    parsed: dict[str, Any],
    config: dict[str, Any],
) -> dict[str, str]:
    row = {column: paper.get(column, "") for column in METADATA_COLUMNS}
    row["evidence_sections_used"] = "; ".join(
        str(section) for section in parsed.get("evidence_sections_used", [])
    )
    row["extraction_notes"] = "; ".join(
        str(note) for note in parsed.get("extraction_notes", [])
    )
    for label_id, label in label_by_id(config).items():
        value = labels[label_id]
        if label.get("value_mode") == "evidence_quote":
            row[label_id] = json.dumps(value, ensure_ascii=False)
        elif isinstance(value, list):
            row[label_id] = "; ".join(str(item) for item in value)
        else:
            row[label_id] = str(value)
    return row


def output_columns(config: dict[str, Any]) -> list[str]:
    return [
        *METADATA_COLUMNS,
        *label_by_id(config),
        "evidence_sections_used",
        "extraction_notes",
    ]


def write_rows(
    output_path: Path,
    rows: list[dict[str, str]],
    fieldnames: list[str],
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fieldnames})


def run(
    papers_path: Path,
    review_config_path: Path,
    output_path: Path,
    model: str,
    client: JSONLLMClient | None = None,
    trace_dir: Path | None = None,
    max_papers: int | None = None,
) -> StepResult:
    _input_columns, all_rows = read_csv_rows(papers_path)
    included = included_rows(all_rows)
    papers = review_eligible_rows(all_rows)
    if max_papers is not None:
        if max_papers < 1:
            raise ValueError("max_papers must be at least 1 when provided.")
        papers = papers[:max_papers]

    review_config = read_json_object(review_config_path)
    llm_client = client or OpenAIResponsesClient()
    trace_writer = LLMTraceWriter(trace_dir) if trace_dir is not None else None
    rows = []
    warnings = []
    trace_paths: list[Path] = []

    for index, paper in enumerate(papers, start=1):
        paper_id = paper.get("paper_id") or f"row_{index}"
        full_text = read_full_text(paper)
        if not full_text:
            warnings.append(f"Skipped paper '{paper_id}': no readable full text.")
            continue

        try:
            payload = paper_payload(paper, full_text, review_config)
            parsed, paths = call_llm(
                payload,
                review_config,
                model,
                llm_client,
                trace_writer,
            )
            labels = validate_and_normalize_labels(parsed, review_config)
            rows.append(flatten_review_row(paper, labels, parsed, review_config))
            trace_paths.extend(paths)
        except ValueError as error:
            warnings.append(f"Failed to extract review labels for '{paper_id}': {error}")

    write_rows(output_path, rows, output_columns(review_config))
    return StepResult(
        step_name=STEP.name,
        inputs={
            "scope_screened_full_text_csv": papers_path,
            "review_config_normalized_json": review_config_path,
        },
        outputs={"review_labels_raw_csv": output_path},
        row_counts={
            "review_candidate_papers": len(included),
            "review_skipped_review_papers": len(included) - len(papers),
            "review_labeled_papers": len(rows),
        },
        warnings=warnings,
        trace_paths=trace_paths,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Extract literature-review labels.")
    parser.add_argument("--papers", required=True, help="Full-text paper CSV.")
    parser.add_argument("--review-config", required=True, help="Normalized review JSON.")
    parser.add_argument("--output", required=True, help="Review labels CSV.")
    parser.add_argument(
        "--model",
        default=None,
        help="OpenAI model. Defaults to OPENAI_MODEL or gpt-4o-mini.",
    )
    parser.add_argument("--trace-dir", default=None, help="Optional trace directory.")
    parser.add_argument("--max-papers", type=int, default=None)
    args = parser.parse_args()

    load_dotenv()
    model = args.model or os.getenv("OPENAI_MODEL", "gpt-4o-mini")
    run(
        Path(args.papers),
        Path(args.review_config),
        Path(args.output),
        model,
        trace_dir=Path(args.trace_dir) if args.trace_dir else None,
        max_papers=args.max_papers,
    )


if __name__ == "__main__":
    main()
