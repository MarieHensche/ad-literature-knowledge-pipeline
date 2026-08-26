from __future__ import annotations

import csv
import json
from pathlib import Path

from ad_lit_pipeline.steps.review.extract_labels import is_likely_review_paper
from ad_lit_pipeline.steps.review.filter_papers import run


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict[str, str]], fieldnames: list[str]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def test_filter_review_papers_excludes_reviews_and_preserves_columns(
    tmp_path: Path,
) -> None:
    papers_path = tmp_path / "papers.csv"
    output_path = tmp_path / "review_eligible.csv"
    report_path = tmp_path / "review_filter_report.json"
    fieldnames = [
        "paper_id",
        "title",
        "year",
        "publication_type",
        "scope_decision",
        "full_text_text_path",
    ]
    write_csv(
        papers_path,
        [
            {
                "paper_id": "p1",
                "title": "Primary study of a method",
                "year": "2024",
                "publication_type": "article",
                "scope_decision": "include",
                "full_text_text_path": "/tmp/p1.txt",
            },
            {
                "paper_id": "p2",
                "title": "Systematic review of a method",
                "year": "2023",
                "publication_type": "article",
                "scope_decision": "include",
                "full_text_text_path": "/tmp/p2.txt",
            },
            {
                "paper_id": "p3",
                "title": "Evidence synthesis",
                "year": "2022",
                "publication_type": "review",
                "scope_decision": "include",
                "full_text_text_path": "/tmp/p3.txt",
            },
            {
                "paper_id": "p4",
                "title": "Excluded review",
                "year": "2021",
                "publication_type": "review",
                "scope_decision": "exclude",
                "full_text_text_path": "/tmp/p4.txt",
            },
        ],
        fieldnames,
    )

    result = run(papers_path, output_path, report_path)

    rows = read_csv(output_path)
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert result.row_counts["included_papers"] == 3
    assert result.row_counts["review_eligible_papers"] == 1
    assert result.row_counts["excluded_review_papers"] == 2
    assert report["counts"]["excluded_likely_review_papers"] == 2
    assert "verified original studies" in report["retention_rule"]
    assert rows == [
        {
            "paper_id": "p1",
            "title": "Primary study of a method",
            "year": "2024",
            "publication_type": "article",
            "scope_decision": "include",
            "full_text_text_path": "/tmp/p1.txt",
            "review_type_status": "primary_or_unclear",
            "review_filter_decision": "retain",
        }
    ]


def test_likely_review_detection_catches_review_like_title_and_abstract() -> None:
    assert is_likely_review_paper(
        {
            "title": "Deep learning for Alzheimer's disease diagnosis: A survey",
            "abstract": "",
            "publication_type": "article",
        }
    )
    assert is_likely_review_paper(
        {
            "title": (
                "Automatic detection of Alzheimer's disease using deep learning: "
                "Current trends and future perspectives"
            ),
            "abstract": "",
            "publication_type": "article",
        }
    )
    assert is_likely_review_paper(
        {
            "title": "Artificial intelligence for drug discovery in Alzheimer's",
            "abstract": (
                "In this review, we summarize AI-driven methodologies and "
                "future directions."
            ),
            "publication_type": "article",
        }
    )
    assert not is_likely_review_paper(
        {
            "title": "Primary validation of an Alzheimer's classifier",
            "abstract": "The introduction reviews prior imaging classifiers.",
            "publication_type": "article",
        }
    )
