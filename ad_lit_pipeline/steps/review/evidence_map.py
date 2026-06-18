from __future__ import annotations

import argparse
import csv
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from ad_lit_pipeline.core.step import StepResult, StepSpec
from ad_lit_pipeline.io.json_io import read_json_object, write_json
from ad_lit_pipeline.steps.review.label_values import split_multi_value


STEP = StepSpec(
    name="build_review_evidence_map",
    inputs=[
        "review_labels_raw_csv",
        "review_label_values_json",
        "review_quality_report_csv",
    ],
    outputs=["review_evidence_map_json"],
    uses_llm=False,
    description="Aggregate review labels into compact, citation-linked evidence.",
)

METADATA_COLUMNS = ["paper_id", "title", "year", "doi", "authors", "venue", "source"]
PRIMARY_SECTION_LABEL = "main_topic"
PREFERRED_SECTION_LABELS = ["methodology", "main_topic"]
DEFAULT_SECTION_ID = "unassigned"
TEXT_EVIDENCE_LABELS = {
    "key_finding",
    "paper_limitation",
    "future_work_or_gap",
}
MAX_TEXT_ITEMS_PER_SECTION = 50
MAX_QUOTES_PER_SECTION = 20


def read_csv_rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def clean_text(value: object) -> str:
    return " ".join(str(value or "").split()).strip()


def labels_by_id(label_values: dict[str, Any]) -> dict[str, dict[str, Any]]:
    labels = label_values.get("review", {}).get("label_values")
    if not isinstance(labels, list):
        raise ValueError("review_label_values JSON must contain review.label_values.")
    return {
        str(label["label_id"]): label
        for label in labels
        if isinstance(label, dict) and label.get("label_id")
    }


def value_labels(label: dict[str, Any]) -> dict[str, str]:
    labels = {}
    for value in label.get("values", []):
        if not isinstance(value, dict):
            continue
        value_id = str(value.get("value") or "").strip()
        if value_id:
            labels[value_id] = str(value.get("label") or value_id)
    return labels


def paper_citation(row: dict[str, str]) -> str:
    authors = clean_text(row.get("authors"))
    year = clean_text(row.get("year"))
    title = clean_text(row.get("title"))
    lead_author = authors.split(";")[0].split(",")[0].strip() if authors else ""
    if lead_author and year:
        return f"{lead_author} ({year})"
    if title and year:
        return f"{title} ({year})"
    return title or clean_text(row.get("paper_id"))


def paper_record(row: dict[str, str]) -> dict[str, str]:
    record = {column: clean_text(row.get(column)) for column in METADATA_COLUMNS}
    record["citation_key"] = paper_citation(row)
    return record


def problematic_paper_ids(quality_rows: list[dict[str, str]]) -> set[str]:
    return {
        clean_text(row.get("paper_id"))
        for row in quality_rows
        if clean_text(row.get("paper_id")) and row.get("severity") == "error"
    }


def issue_counts(quality_rows: list[dict[str, str]]) -> dict[str, int]:
    counts: Counter[str] = Counter()
    for row in quality_rows:
        issue_type = clean_text(row.get("issue"))
        if issue_type:
            counts[issue_type] += 1
    return dict(sorted(counts.items()))


def year_range(rows: list[dict[str, str]]) -> list[int]:
    years = []
    for row in rows:
        raw_year = clean_text(row.get("year"))
        if raw_year.isdigit():
            years.append(int(raw_year))
    if not years:
        return []
    return [min(years), max(years)]


def controlled_label_ids(labels: dict[str, dict[str, Any]]) -> list[str]:
    return [
        label_id
        for label_id, label in labels.items()
        if str(label.get("value_mode") or "") in {"controlled_fixed", "controlled_auto"}
    ]


def count_controlled_values(
    rows: list[dict[str, str]],
    labels: dict[str, dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    distributions = {}
    for label_id in controlled_label_ids(labels):
        counts: Counter[str] = Counter()
        for row in rows:
            counts.update(split_multi_value(row.get(label_id, "")))
        names = value_labels(labels[label_id])
        distributions[label_id] = [
            {
                "value": value,
                "label": names.get(value, value),
                "paper_count": count,
            }
            for value, count in counts.most_common()
        ]
    return distributions


def section_label_id(
    rows: list[dict[str, str]],
    labels: dict[str, dict[str, Any]],
) -> str:
    for label_id in PREFERRED_SECTION_LABELS:
        if label_id not in labels:
            continue
        if any(split_multi_value(row.get(label_id, "")) for row in rows):
            return label_id
    return PRIMARY_SECTION_LABEL


def section_ids(row: dict[str, str], label_id: str) -> list[str]:
    values = split_multi_value(row.get(label_id, ""))
    return values or [DEFAULT_SECTION_ID]


def text_evidence_item(
    row: dict[str, str],
    label_id: str,
    text: str,
) -> dict[str, str]:
    return {
        "paper_id": clean_text(row.get("paper_id")),
        "citation_key": paper_citation(row),
        "text": text,
        "label_id": label_id,
    }


def collect_text_evidence(
    rows: list[dict[str, str]],
) -> dict[str, list[dict[str, str]]]:
    evidence: dict[str, list[dict[str, str]]] = {
        label_id: [] for label_id in sorted(TEXT_EVIDENCE_LABELS)
    }
    for row in rows:
        for label_id in TEXT_EVIDENCE_LABELS:
            text = clean_text(row.get(label_id))
            if text:
                evidence[label_id].append(text_evidence_item(row, label_id, text))
    return {
        label_id: items[:MAX_TEXT_ITEMS_PER_SECTION]
        for label_id, items in evidence.items()
        if items
    }


def parse_quote_items(raw_value: str) -> list[dict[str, str]]:
    if not clean_text(raw_value):
        return []
    try:
        payload = json.loads(raw_value)
    except json.JSONDecodeError:
        return []
    if not isinstance(payload, list):
        return []

    quotes = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        quote = clean_text(item.get("quote"))
        if not quote:
            continue
        quotes.append(
            {
                "quote": quote,
                "section": clean_text(item.get("section")),
                "reason": clean_text(item.get("reason")),
            }
        )
    return quotes


def collect_quotes(
    rows: list[dict[str, str]],
    labels: dict[str, dict[str, Any]],
) -> list[dict[str, str]]:
    quote_label_ids = [
        label_id
        for label_id, label in labels.items()
        if str(label.get("value_mode") or "") == "evidence_quote"
    ]
    quotes = []
    for row in rows:
        for label_id in quote_label_ids:
            for quote in parse_quote_items(row.get(label_id, "")):
                quotes.append(
                    {
                        "paper_id": clean_text(row.get("paper_id")),
                        "citation_key": paper_citation(row),
                        "label_id": label_id,
                        **quote,
                    }
                )
    return quotes[:MAX_QUOTES_PER_SECTION]


def build_section(
    section_id: str,
    rows: list[dict[str, str]],
    labels: dict[str, dict[str, Any]],
    section_label_id_value: str,
) -> dict[str, Any]:
    section_label = value_labels(labels.get(section_label_id_value, {})).get(
        section_id,
        section_id.replace("_", " "),
    )
    return {
        "section_id": section_id,
        "label": section_label,
        "source_label": section_label_id_value,
        "paper_count": len(rows),
        "paper_ids": [clean_text(row.get("paper_id")) for row in rows],
        "controlled_value_counts": count_controlled_values(rows, labels),
        "text_evidence": collect_text_evidence(rows),
        "quotes": collect_quotes(rows, labels),
    }


def build_review_evidence_map(
    review_rows: list[dict[str, str]],
    label_values: dict[str, Any],
    quality_rows: list[dict[str, str]],
) -> dict[str, Any]:
    labels = labels_by_id(label_values)
    excluded_ids = problematic_paper_ids(quality_rows)
    usable_rows = []
    for row in review_rows:
        paper_id = clean_text(row.get("paper_id"))
        if paper_id and paper_id not in excluded_ids:
            usable_rows.append(row)

    rows_by_section: dict[str, list[dict[str, str]]] = defaultdict(list)
    selected_section_label = section_label_id(usable_rows, labels)
    for row in usable_rows:
        for section_id in section_ids(row, selected_section_label):
            rows_by_section[section_id].append(row)

    sections = [
        build_section(
            section_id,
            rows_by_section[section_id],
            labels,
            selected_section_label,
        )
        for section_id in sorted(rows_by_section)
    ]

    return {
        "research_topic": label_values.get("research_topic", {}),
        "overview": {
            "paper_count": len(review_rows),
            "usable_paper_count": len(usable_rows),
            "excluded_paper_count": len(review_rows) - len(usable_rows),
            "year_range": year_range(usable_rows),
            "section_label": selected_section_label,
            "controlled_value_counts": count_controlled_values(usable_rows, labels),
        },
        "quality": {
            "issue_count": len(quality_rows),
            "issue_counts": issue_counts(quality_rows),
            "excluded_paper_ids": sorted(excluded_ids),
        },
        "papers": [paper_record(row) for row in usable_rows],
        "sections": sections,
    }


def run(
    review_labels_path: Path,
    review_label_values_path: Path,
    review_quality_report_path: Path,
    output_path: Path,
) -> StepResult:
    review_rows = read_csv_rows(review_labels_path)
    label_values = read_json_object(review_label_values_path)
    quality_rows = read_csv_rows(review_quality_report_path)
    evidence_map = build_review_evidence_map(
        review_rows,
        label_values,
        quality_rows,
    )
    write_json(
        output_path,
        {
            "source_labels": str(review_labels_path),
            "source_label_values": str(review_label_values_path),
            "source_quality_report": str(review_quality_report_path),
            **evidence_map,
        },
    )
    return StepResult(
        step_name=STEP.name,
        inputs={
            "review_labels_raw_csv": review_labels_path,
            "review_label_values_json": review_label_values_path,
            "review_quality_report_csv": review_quality_report_path,
        },
        outputs={"review_evidence_map_json": output_path},
        row_counts={
            "review_label_rows": len(review_rows),
            "review_usable_papers": int(
                evidence_map["overview"]["usable_paper_count"]
            ),
            "review_sections": len(evidence_map["sections"]),
            "review_quality_issues": len(quality_rows),
        },
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build a compact evidence map for literature-review synthesis."
    )
    parser.add_argument("--labels", required=True, help="Raw review labels CSV.")
    parser.add_argument(
        "--label-values",
        required=True,
        help="Normalized review label values JSON.",
    )
    parser.add_argument(
        "--quality-report",
        required=True,
        help="Review quality report CSV.",
    )
    parser.add_argument("--output", required=True, help="Evidence map JSON.")
    args = parser.parse_args()

    run(
        Path(args.labels),
        Path(args.label_values),
        Path(args.quality_report),
        Path(args.output),
    )


if __name__ == "__main__":
    main()
