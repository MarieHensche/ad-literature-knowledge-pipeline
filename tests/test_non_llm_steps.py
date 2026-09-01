from __future__ import annotations

import csv
import json
import subprocess
import sys
from http.client import InvalidURL
from pathlib import Path

import pytest

from ad_lit_pipeline.io.jsonl_io import read_jsonl_objects, write_jsonl
from ad_lit_pipeline.steps.collection import fetch_candidates as fetch_candidates_step
from ad_lit_pipeline.steps.collection import verify_full_text_availability
from ad_lit_pipeline.steps.collection.export_included import run as run_export_included
from ad_lit_pipeline.steps.collection.fetch_review_overviews import (
    review_pool_size,
    run as run_fetch_review_overviews,
    select_best_review_overviews,
)
from ad_lit_pipeline.steps.collection import prepare_review_full_text
from ad_lit_pipeline.steps.collection.select_calibration_papers import (
    run as run_select_calibration_papers,
)
from ad_lit_pipeline.steps.full_text import prepare as full_text_prepare
from ad_lit_pipeline.steps.full_text.evidence import build_knowledge_evidence
from ad_lit_pipeline.steps.full_text.identity import assess_document_identity
from ad_lit_pipeline.steps.full_text.prepare import FullTextResult
from ad_lit_pipeline.steps.full_text.prepare import run as run_prepare_full_text
from ad_lit_pipeline.steps.export.mantis import run as run_export_mantis
from ad_lit_pipeline.steps.tagging.audit import run as run_audit_extraction
from ad_lit_pipeline.steps.tagging.evidence_policy import (
    EVIDENCE_POLICY_FULL_TEXT_REQUIRED,
    assess_tagging_evidence,
)
from ad_lit_pipeline.topics.contract import load_topic_contract
from ad_lit_pipeline.topics.matching import (
    annotate_candidate_topic_matches,
    topic_match_spec_from_contract,
)
from ad_lit_pipeline.topics.retrieval import build_query_groups_from_contract


ROOT = Path(__file__).resolve().parents[1]


def run_script(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, *args],
        cwd=ROOT,
        check=True,
        text=True,
        capture_output=True,
    )


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict[str, str]], fieldnames: list[str]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def write_json(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


class FakeReviewProvider:
    name = "openalex"

    def __init__(self) -> None:
        self.plan: dict[str, object] | None = None
        self.max_results: int | None = None

    def validate_plan(self, plan: dict[str, object]) -> None:
        self.plan = plan

    def fetch_candidates(
        self,
        plan: dict[str, object],
        max_results: int,
        per_page: int,
        mailto: str | None,
        sleep_seconds: float,
    ) -> list[dict[str, object]]:
        self.plan = plan
        self.max_results = max_results
        return [
            {
                "provider": "openalex",
                "provider_id": "W1",
                "title": "A Review of Early Detection",
                "abstract": "Review evidence about biomarkers and models.",
                "query": "early detection review overview",
                "rank": 1,
            },
            {
                "provider": "openalex",
                "provider_id": "W2",
                "title": "A Review of Unrelated Hospital Staffing",
                "abstract": "Review evidence about nursing staffing models.",
                "query": "unrelated review overview",
                "rank": 2,
            },
        ]


def test_normalize_metadata_example_cli(tmp_path: Path) -> None:
    output = tmp_path / "papers_normalized.csv"

    run_script(
        "scripts/normalize_metadata.py",
        "--input",
        "data/raw/example_papers.csv",
        "--output",
        str(output),
    )

    rows = read_csv(output)
    assert len(rows) == 3
    assert rows[0]["paper_id"] == "example_001"
    assert rows[0]["doi"] == "10.1145/3644116.3644192"
    assert rows[0]["abstract_available"] == "yes"
    assert rows[0]["full_text_available"] == "no"
    assert rows[0]["metadata_notes"] == "missing_full_text_path"


def test_normalize_metadata_preserves_unknown_structured_columns(
    tmp_path: Path,
) -> None:
    input_path = tmp_path / "papers.csv"
    output_path = tmp_path / "normalized.csv"
    write_csv(
        input_path,
        [
            {
                "paper_id": "p1",
                "title": "Provenance-preserving study",
                "year": "2024",
                "doi": "10.1/example",
                "abstract": "A sufficiently detailed abstract for testing.",
                "provider_id": "W123",
                "publication_date": "2024-03-04",
                "duplicate_provenance_json": '[{"query_id":"q2"}]',
            }
        ],
        [
            "paper_id",
            "title",
            "year",
            "doi",
            "abstract",
            "provider_id",
            "publication_date",
            "duplicate_provenance_json",
        ],
    )

    run_script(
        "scripts/normalize_metadata.py",
        "--input",
        str(input_path),
        "--output",
        str(output_path),
    )

    rows = read_csv(output_path)
    assert rows[0]["provider_id"] == "W123"
    assert rows[0]["publication_date"] == "2024-03-04"
    assert rows[0]["duplicate_provenance_json"] == '[{"query_id":"q2"}]'


def test_fetch_review_overviews_builds_review_only_openalex_plan(tmp_path: Path) -> None:
    output_path = tmp_path / "review_overviews.jsonl"
    provider = FakeReviewProvider()

    result = run_fetch_review_overviews(
        ROOT / "configs/topics/early_detection_ad.yaml",
        output_path,
        max_results=1,
        provider=provider,
    )

    rows = read_jsonl_objects(output_path)
    assert rows[0]["provider_id"] == "W1"
    assert len(rows) == 2
    assert all("review_selection_score" in row for row in rows)
    assert result.row_counts["review_overviews"] == 2
    assert result.row_counts["review_overview_candidates"] == 2
    assert result.row_counts["review_candidate_pool"] == 2
    assert result.metadata["max_review_overviews"] == 1
    assert provider.max_results == review_pool_size(1)
    assert provider.plan is not None
    assert provider.plan["filters"] == {
        "publication_types": ["review"],
        "open_access_only": True,
        "has_abstract": True,
        "has_full_text": True,
    }
    assert provider.plan["search_queries"][0]["query"].endswith("review overview")


def test_review_seed_selection_prefers_topic_fit_over_citations() -> None:
    contract = load_topic_contract(ROOT / "configs/topics/ai_in_education.yaml")
    candidates = [
        {
            "provider_id": "nursing-review",
            "title": "Application Scenarios for Artificial Intelligence in Nursing Care",
            "year": 2024,
            "abstract": "A rapid review of AI applications in nursing care.",
            "raw_record": {"cited_by_count": 500},
        },
        {
            "provider_id": "education-review",
            "title": "Systematic review of artificial intelligence in education",
            "year": 2022,
            "abstract": (
                "This review examines AI in education, student learning, "
                "teaching, classroom use, and learning outcomes."
            ),
            "raw_record": {"cited_by_count": 35},
        },
    ]

    selected = select_best_review_overviews(contract, candidates, max_results=1)

    assert selected[0]["provider_id"] == "education-review"
    assert selected[0]["review_selection_score"] > 0
    assert selected[0]["review_topic_evidence"]


def test_prepare_review_full_text_adapts_openalex_locations(
    tmp_path: Path,
    monkeypatch,
) -> None:
    input_path = tmp_path / "review_overviews.jsonl"
    output_path = tmp_path / "review_overviews_full_text.jsonl"
    manifest_path = tmp_path / "review_full_text_manifest.csv"
    cache_dir = tmp_path / "cache"
    captured_rows = []
    write_jsonl(
        input_path,
        [
            {
                "provider_id": "https://openalex.org/W1",
                "doi": "10.123/review",
                "title": "Review of drinking water microplastics",
                "abstract": "A review.",
                "url": "https://doi.org/10.123/review",
                "raw_record": {
                    "content_urls": {
                        "pdf": "https://content.openalex.org/works/W1.pdf"
                    },
                    "best_oa_location": {
                        "pdf_url": "https://example.org/best.pdf",
                        "landing_page_url": "https://example.org/article",
                    },
                },
            }
        ],
    )

    def fake_resolve_full_text(
        row: dict[str, str],
        cache_dir: Path,
        unpaywall_email: str | None,
        core_api_key: str | None,
    ) -> FullTextResult:
        captured_rows.append(row)
        return FullTextResult(
            status="pdf_text_extracted",
            source="provider_metadata",
            url=row["full_text_url"],
            text_path=str(cache_dir / "texts" / "review.txt"),
            chars=1234,
        )

    monkeypatch.setattr(
        prepare_review_full_text,
        "resolve_full_text",
        fake_resolve_full_text,
    )

    result = prepare_review_full_text.run(
        input_path,
        output_path,
        manifest_path,
        cache_dir,
    )

    rows = read_jsonl_objects(output_path)
    manifest_rows = read_csv(manifest_path)
    assert result.row_counts["review_overviews"] == 1
    assert result.row_counts["local_texts"] == 1
    assert captured_rows[0]["paper_id"] == "https://openalex.org/W1"
    assert (
        captured_rows[0]["full_text_url"]
        == "https://content.openalex.org/works/W1.pdf"
    )
    assert captured_rows[0]["pdf_url"] == "https://example.org/best.pdf"
    assert rows[0]["full_text_status"] == "pdf_text_extracted"
    assert rows[0]["full_text_text_path"].endswith("review.txt")
    assert manifest_rows[0]["paper_id"] == "https://openalex.org/W1"


def test_screen_scope_preserves_metadata_and_appends_contract_fields(
    tmp_path: Path,
) -> None:
    normalized = tmp_path / "papers_normalized.csv"
    screened = tmp_path / "scope_screened.csv"

    run_script(
        "scripts/normalize_metadata.py",
        "--input",
        "data/raw/example_papers.csv",
        "--output",
        str(normalized),
    )
    run_script(
        "scripts/screen_scope.py",
        "--input",
        str(normalized),
        "--output",
        str(screened),
        "--topic-contract",
        "configs/topics/early_detection_ad.yaml",
    )

    with screened.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        assert reader.fieldnames == [
            "paper_id",
            "title",
            "year",
            "doi",
            "abstract",
            "authors",
            "venue",
            "url",
            "source",
            "full_text_path",
            "full_text_availability_status",
            "full_text_availability_source",
            "full_text_url",
            "full_text_url_kind",
            "full_text_url_checked_at",
            "full_text_url_content_type",
            "full_text_license",
            "full_text_is_open_access",
            "full_text_availability_error",
            "notes",
            "abstract_available",
            "full_text_available",
            "metadata_notes",
            "scope_decision",
            "scope_reason",
            "scope_matched_include_terms",
            "scope_matched_exclude_terms",
            "scope_publication_window_status",
        ]
        rows = list(reader)

    assert [row["scope_decision"] for row in rows] == [
        "include",
        "include",
        "exclude_or_route_elsewhere",
    ]
    assert rows[0]["authors"] == "Li et al."
    assert rows[0]["venue"] == "ACM"
    assert "Matched exclude term(s): drug repurposing, treatment" in rows[2][
        "scope_reason"
    ]
    assert "screening" in rows[2]["scope_matched_include_terms"]
    assert rows[2]["scope_matched_exclude_terms"] == "drug repurposing; treatment"


def test_screen_scope_exclude_wins_and_defaults_to_include(tmp_path: Path) -> None:
    input_path = tmp_path / "normalized.csv"
    output_path = tmp_path / "screened.csv"
    write_csv(
        input_path,
        [
            {
                "paper_id": "p1",
                "title": "Treatment classification",
                "year": "2024",
                "doi": "",
                "abstract": "A treatment paper with classification language.",
                "authors": "A. Author",
            },
            {
                "paper_id": "p2",
                "title": "Unrelated clinical note",
                "year": "2024",
                "doi": "",
                "abstract": "No matching language.",
                "authors": "B. Author",
            },
        ],
        ["paper_id", "title", "year", "doi", "abstract", "authors"],
    )

    run_script(
        "scripts/screen_scope.py",
        "--input",
        str(input_path),
        "--output",
        str(output_path),
        "--topic-contract",
        "configs/topics/early_detection_ad.yaml",
    )

    rows = read_csv(output_path)
    assert rows[0]["scope_decision"] == "exclude_or_route_elsewhere"
    assert rows[0]["scope_matched_include_terms"] == "classification"
    assert rows[0]["scope_matched_exclude_terms"] == "treatment"
    assert rows[0]["authors"] == "A. Author"
    assert rows[1]["scope_decision"] == "include"
    assert rows[1]["scope_reason"] == (
        "No exclude term matched; included for downstream tagging."
    )


def test_prepare_full_text_uses_local_text_and_writes_manifest(
    tmp_path: Path,
) -> None:
    full_text = tmp_path / "paper.txt"
    full_text.write_text(
        (
            "Introduction\nThis paper studies AI use in schools.\n\n"
            "Results\nStudents improved academic performance.\n\n"
            "Conclusion\nAI classroom use supported learning outcomes.\n\n"
        )
        * 20,
        encoding="utf-8",
    )
    input_path = tmp_path / "scope_screened.csv"
    output_path = tmp_path / "scope_screened_full_text.csv"
    manifest_path = tmp_path / "full_text_manifest.csv"
    cache_dir = tmp_path / "cache"
    write_csv(
        input_path,
        [
            {
                "paper_id": "p1",
                "title": "AI in schools",
                "year": "2024",
                "doi": "10.123/example",
                "abstract": "AI use in schools.",
                "full_text_path": str(full_text),
                "scope_decision": "include",
            }
        ],
        [
            "paper_id",
            "title",
            "year",
            "doi",
            "abstract",
            "full_text_path",
            "scope_decision",
        ],
    )

    result = run_prepare_full_text(
        input_path,
        output_path,
        manifest_path,
        cache_dir,
    )

    rows = read_csv(output_path)
    manifest_rows = read_csv(manifest_path)
    text_path = Path(rows[0]["full_text_text_path"])
    assert result.row_counts["local_texts"] == 1
    assert rows[0]["full_text_status"] == "local_text_extracted"
    assert rows[0]["full_text_source"] == "local_file"
    assert rows[0]["full_text_usable_for_tagging"] == "yes"
    assert text_path.exists()
    assert manifest_rows[0]["paper_id"] == "p1"
    assert int(manifest_rows[0]["full_text_chars"]) >= 1000


def test_prepare_full_text_reuses_existing_text_path(tmp_path: Path) -> None:
    full_text = tmp_path / "prepared_full_text.txt"
    full_text.write_text(
        (
            "Introduction\nThis prepared text was already extracted.\n\n"
            "Results\nThe paper reports useful evidence for review generation.\n\n"
        )
        * 20,
        encoding="utf-8",
    )
    input_path = tmp_path / "scope_screened.csv"
    output_path = tmp_path / "scope_screened_full_text.csv"
    manifest_path = tmp_path / "full_text_manifest.csv"
    cache_dir = tmp_path / "cache"
    write_csv(
        input_path,
        [
            {
                "paper_id": "p1",
                "title": "Prepared paper",
                "year": "2024",
                "doi": "10.123/prepared",
                "abstract": "Prepared evidence.",
                "full_text_path": "",
                "full_text_text_path": str(full_text),
                "full_text_status": "local_text_extracted",
                "full_text_source": "collection_workflow",
                "scope_decision": "include",
            }
        ],
        [
            "paper_id",
            "title",
            "year",
            "doi",
            "abstract",
            "full_text_path",
            "full_text_text_path",
            "full_text_status",
            "full_text_source",
            "scope_decision",
        ],
    )

    result = run_prepare_full_text(
        input_path,
        output_path,
        manifest_path,
        cache_dir,
    )

    rows = read_csv(output_path)
    manifest_rows = read_csv(manifest_path)
    assert result.row_counts["local_texts"] == 1
    assert rows[0]["full_text_status"] == "local_text_extracted"
    assert rows[0]["full_text_source"] == "collection_workflow"
    assert rows[0]["full_text_text_path"] == str(full_text)
    assert rows[0]["full_text_usable_for_tagging"] == "yes"
    assert int(rows[0]["full_text_chars"]) >= 1000
    assert manifest_rows[0]["full_text_text_path"] == str(full_text)


def test_prepare_full_text_distinguishes_verified_url_from_usable_text(
    tmp_path: Path,
    monkeypatch,
) -> None:
    input_path = tmp_path / "scope_screened.csv"
    output_path = tmp_path / "scope_screened_full_text.csv"
    manifest_path = tmp_path / "full_text_manifest.csv"
    cache_dir = tmp_path / "cache"
    write_csv(
        input_path,
        [
            {
                "paper_id": "p1",
                "title": "Reachable landing page without extractable text",
                "abstract": "",
                "full_text_available": "yes",
                "full_text_availability_status": "verified",
                "full_text_url": "https://example.org/landing",
                "scope_decision": "include",
            }
        ],
        [
            "paper_id",
            "title",
            "abstract",
            "full_text_available",
            "full_text_availability_status",
            "full_text_url",
            "scope_decision",
        ],
    )
    monkeypatch.setattr(
        full_text_prepare,
        "resolve_full_text",
        lambda row, cache_dir, unpaywall_email, core_api_key: FullTextResult(
            status="extraction_failed",
            error="landing page contained no extractable scholarly text",
        ),
    )

    result = run_prepare_full_text(
        input_path,
        output_path,
        manifest_path,
        cache_dir,
    )

    row = read_csv(output_path)[0]
    manifest_row = read_csv(manifest_path)[0]
    assert row["full_text_available"] == "yes"
    assert row["full_text_availability_status"] == "verified"
    assert row["full_text_status"] == "extraction_failed"
    assert row["full_text_usable_for_tagging"] == "no"
    assert manifest_row["full_text_usable_for_tagging"] == "no"
    assert result.row_counts["usable_full_texts"] == 0
    assert result.row_counts["extraction_failures"] == 1


def test_prepare_full_text_continues_after_invalid_pdf_response(
    tmp_path: Path,
    monkeypatch,
) -> None:
    input_path = tmp_path / "scope_screened.csv"
    output_path = tmp_path / "scope_screened_full_text.csv"
    manifest_path = tmp_path / "full_text_manifest.csv"
    cache_dir = tmp_path / "cache"
    html_text = (
        "<html><body>"
        + "<p>Microplastics in drinking water exposure and human health risk.</p>"
        * 40
        + "</body></html>"
    ).encode("utf-8")

    def fake_request_bytes(url: str) -> tuple[bytes, str, str]:
        if url == "https://example.org/bad.pdf":
            return b"\n\n\n\n<html>not a pdf</html>", "application/pdf", url
        return html_text, "text/html", "https://example.org/full-text"

    monkeypatch.setattr(full_text_prepare, "request_bytes", fake_request_bytes)
    write_csv(
        input_path,
        [
            {
                "paper_id": "p1",
                "title": "Microplastics in drinking water and health risk",
                "year": "2024",
                "doi": "",
                "abstract": "Microplastics in drinking water.",
                "full_text_path": "",
                "full_text_url": "https://example.org/bad.pdf",
                "pdf_url": "https://example.org/full-text",
                "scope_decision": "include",
            }
        ],
        [
            "paper_id",
            "title",
            "year",
            "doi",
            "abstract",
            "full_text_path",
            "full_text_url",
            "pdf_url",
            "scope_decision",
        ],
    )

    result = run_prepare_full_text(
        input_path,
        output_path,
        manifest_path,
        cache_dir,
    )

    rows = read_csv(output_path)
    assert result.row_counts["local_texts"] == 1
    assert rows[0]["full_text_status"] == "html_text_extracted"
    assert rows[0]["full_text_url"] == "https://example.org/bad.pdf"
    assert rows[0]["full_text_resolved_url"] == "https://example.org/full-text"
    assert int(rows[0]["full_text_chars"]) >= 1000


def test_prepare_full_text_ignores_template_download_links(
    tmp_path: Path,
    monkeypatch,
) -> None:
    input_path = tmp_path / "scope_screened.csv"
    output_path = tmp_path / "scope_screened_full_text.csv"
    manifest_path = tmp_path / "full_text_manifest.csv"
    cache_dir = tmp_path / "cache"
    html_text = (
        "<html><body>"
        '<a href="/plosone/article/figure/image?size=original&download=&id=<%= doi %>">'
        "download</a>"
        + (
            "<p>Digital intervention for postpartum depression: "
            "mental health evidence.</p>"
        )
        * 40
        + "</body></html>"
    ).encode("utf-8")
    requested_urls = []

    def fake_request_bytes(url: str) -> tuple[bytes, str, str]:
        requested_urls.append(url)
        if "<%" in url or " " in url:
            raise AssertionError(f"Template URL should have been filtered: {url}")
        return html_text, "text/html", "https://example.org/full-text"

    monkeypatch.setattr(full_text_prepare, "request_bytes", fake_request_bytes)
    write_csv(
        input_path,
        [
            {
                "paper_id": "p1",
                "title": "Digital intervention for postpartum depression",
                "year": "2024",
                "doi": "",
                "abstract": "Digital postpartum intervention.",
                "full_text_path": "",
                "full_text_url": "https://example.org/full-text",
                "scope_decision": "include",
            }
        ],
        [
            "paper_id",
            "title",
            "year",
            "doi",
            "abstract",
            "full_text_path",
            "full_text_url",
            "scope_decision",
        ],
    )

    result = run_prepare_full_text(
        input_path,
        output_path,
        manifest_path,
        cache_dir,
    )

    rows = read_csv(output_path)
    assert requested_urls == ["https://example.org/full-text"]
    assert result.row_counts["local_texts"] == 1
    assert rows[0]["full_text_status"] == "html_text_extracted"
    assert rows[0]["full_text_error"] == ""


def test_document_identity_requires_front_matter_doi_or_compact_full_title() -> None:
    row = {
        "doi": "10.1234/target",
        "title": "Artificial intelligence for Alzheimer disease research",
    }
    title_match = assess_document_identity(
        {**row, "doi": ""},
        (
            "Artificial intelligence for Alzheimer disease research\n"
            + "Methods and findings. " * 100
        ),
    )
    doi_match = assess_document_identity(
        row,
        "Article header DOI 10.1234/target\n" + "Body text. " * 100,
    )
    generic_overlap = assess_document_identity(
        {**row, "doi": ""},
        (
            "Artificial intelligence methods are surveyed. "
            + "unrelated material " * 20
            + "Alzheimer disease research is discussed elsewhere."
        ),
    )
    references_only_doi = assess_document_identity(
        row,
        "Unrelated article front matter. " * 900 + "10.1234/target",
    )
    doi_prefix_only = assess_document_identity(
        row,
        "Article header DOI 10.1234/target-extra\n" + "Body text. " * 100,
    )

    assert title_match.status == "verified_title"
    assert doi_match.status == "verified_doi"
    assert generic_overlap.status == "mismatch"
    assert references_only_doi.status == "mismatch"
    assert doi_prefix_only.status == "mismatch"


def test_prepare_full_text_preserves_section_boundaries() -> None:
    cleaned = full_text_prepare.clean_extracted_text(
        " Methods  \n  Participants and design.  \n\n\n Results\n Outcome. "
    )

    assert cleaned == (
        "Methods\nParticipants and design.\n\nResults\nOutcome."
    )


def test_prepare_full_text_rejects_wrong_remote_document_identity(
    tmp_path: Path,
    monkeypatch,
) -> None:
    input_path = tmp_path / "scope.csv"
    output_path = tmp_path / "full_text.csv"
    manifest_path = tmp_path / "full_text_manifest.csv"
    cache_dir = tmp_path / "cache"
    wrong_text = (
        "ADNI data use acknowledgements and administrative information.\n"
        * 40
    )

    monkeypatch.setattr(
        full_text_prepare,
        "request_bytes",
        lambda url: (b"%PDF-mocked", "application/pdf", url),
    )
    monkeypatch.setattr(
        full_text_prepare,
        "extract_pdf_text",
        lambda data: wrong_text,
    )
    write_csv(
        input_path,
        [
            {
                "paper_id": "p1",
                "title": (
                    "Machine learning for Alzheimer disease diagnosis using MRI"
                ),
                "year": "2024",
                "doi": "",
                "abstract": "A diagnostic imaging study.",
                "full_text_url": "https://example.org/wrong.pdf",
                "scope_decision": "include",
            }
        ],
        [
            "paper_id",
            "title",
            "year",
            "doi",
            "abstract",
            "full_text_url",
            "scope_decision",
        ],
    )

    result = run_prepare_full_text(
        input_path,
        output_path,
        manifest_path,
        cache_dir,
    )

    row = read_csv(output_path)[0]
    assert row["full_text_status"] == "identity_mismatch"
    assert row["full_text_identity_status"] == "mismatch"
    assert row["full_text_usable_for_tagging"] == "no"
    assert row["full_text_text_path"] == ""
    assert row["full_text_url"] == "https://example.org/wrong.pdf"
    assert row["full_text_resolved_url"] == "https://example.org/wrong.pdf"
    assert result.row_counts["identity_failures"] == 1


def test_tagging_evidence_policy_rejects_placeholders_and_unverified_text(
    tmp_path: Path,
) -> None:
    wrong_text_path = tmp_path / "wrong.txt"
    wrong_text_path.write_text(
        "Administrative acknowledgements from another dataset.\n" * 40,
        encoding="utf-8",
    )
    placeholder = assess_tagging_evidence(
        {"abstract": "N/A", "full_text_status": "extraction_failed"}
    )
    abstract_only_strict = assess_tagging_evidence(
        {
            "abstract": "A substantive abstract reports diagnostic performance.",
            "full_text_status": "not_available",
        },
        evidence_policy=EVIDENCE_POLICY_FULL_TEXT_REQUIRED,
    )
    wrong_remote = assess_tagging_evidence(
        {
            "title": "Artificial intelligence for Alzheimer diagnosis",
            "doi": "",
            "abstract": "A substantive abstract remains a valid fallback.",
            "full_text_status": "pdf_text_extracted",
            "full_text_resolved_url": "https://example.org/wrong.pdf",
            "full_text_text_path": str(wrong_text_path),
        }
    )

    assert placeholder.eligible is False
    assert placeholder.basis == "none"
    assert abstract_only_strict.eligible is False
    assert "fallback is disabled" in abstract_only_strict.warning
    assert wrong_remote.eligible is True
    assert wrong_remote.basis == "abstract"
    assert "document identity did not match" in wrong_remote.warning


def test_candidate_locations_ignore_core_timeout(monkeypatch) -> None:
    def fake_core_locations(doi: str, title: str, api_key: str | None):
        raise TimeoutError("The read operation timed out")

    monkeypatch.setattr(
        full_text_prepare,
        "unpaywall_locations",
        lambda doi, email: [],
    )
    monkeypatch.setattr(full_text_prepare, "europe_pmc_locations", lambda doi: [])
    monkeypatch.setattr(full_text_prepare, "core_locations", fake_core_locations)

    locations = full_text_prepare.candidate_locations(
        {
            "doi": "10.1371/journal.pone.0257065",
            "title": "Perinatal depression screening using smartphone technology",
            "url": "https://doi.org/10.1371/journal.pone.0257065",
        },
        unpaywall_email=None,
        core_api_key="core-key",
    )

    assert [(location.source, location.url) for location in locations] == [
        ("provider_metadata", "https://doi.org/10.1371/journal.pone.0257065"),
    ]


def test_knowledge_evidence_uses_flexible_section_headings() -> None:
    text = (
        "1. Methods\nParticipants completed a classroom intervention.\n\n"
        "2. Results\nStudents improved grades after AI-supported lessons.\n\n"
        "CONCLUSIONS\nAI use in school education improved learning outcomes.\n\n"
    )

    evidence = build_knowledge_evidence(text, max_chars=500)

    assert "[CONCLUSIONS]" in evidence
    assert "[2. Results]" in evidence
    assert evidence.index("[CONCLUSIONS]") < evidence.index("[1. Methods]")


def test_screen_scope_matches_abbreviations_without_tag_values(tmp_path: Path) -> None:
    input_path = tmp_path / "normalized.csv"
    output_path = tmp_path / "screened.csv"
    contract_path = tmp_path / "topic_contract.yaml"
    write_csv(
        input_path,
        [
            {
                "paper_id": "p1",
                "title": "ML tools for college student learning",
                "year": "2024",
                "doi": "",
                "abstract": "The paper evaluates classroom outcomes.",
                "authors": "A. Author",
            },
            {
                "paper_id": "p2",
                "title": "Grade point average and wellbeing",
                "year": "2024",
                "doi": "",
                "abstract": "The paper studies student GPA.",
                "authors": "B. Author",
            },
        ],
        ["paper_id", "title", "year", "doi", "abstract", "authors"],
    )
    contract_path.write_text(
        """
topic_id: education_test
research_topic:
  title: Education test
  description: Test topic.
topic_structure:
  anchor_topic_id: ai
  anchor_reason: AI is the required intervention focus.
  main_topics:
    - topic_id: ai
      label: Artificial intelligence
      terms:
        - machine learning
        - ML
    - topic_id: education
      label: Education
      terms:
        - student learning
        - classroom outcomes
  secondary_topics:
    education:
      - wellbeing
scope:
  include_criteria:
    - Include education papers.
  exclude_criteria:
    - Exclude hard negatives.
  boundary_rules:
    - Include adjacent papers.
rule_based_screening:
  include_terms:
    - machine learning
  exclude_terms: []
  exclude_wins: false
candidate_screening:
  missing_abstract_policy: include
  borderline_policy: include
  human_review_policy: include
tagging:
  fallback_policy: {}
  categories:
    main_topic_category:
      values:
        - student_outcomes
        - unclear
    research_target:
      values:
        - grade_point_average
        - unclear
collection:
  allowed_providers:
    - openalex
  preferred_provider: openalex
  search_queries: []
""".lstrip(),
        encoding="utf-8",
    )

    run_script(
        "scripts/screen_scope.py",
        "--input",
        str(input_path),
        "--output",
        str(output_path),
        "--topic-contract",
        str(contract_path),
    )

    rows = read_csv(output_path)
    assert rows[0]["scope_decision"] == "include"
    assert "machine learning" in rows[0]["scope_matched_include_terms"]
    assert "student outcomes" not in rows[0]["scope_matched_include_terms"]
    assert rows[1]["scope_decision"] == "include"
    assert "grade point average" not in rows[1]["scope_matched_include_terms"]


def test_screen_scope_does_not_report_missing_phrase_qualifiers(
    tmp_path: Path,
) -> None:
    input_path = tmp_path / "normalized.csv"
    output_path = tmp_path / "screened.csv"
    contract_path = tmp_path / "contract.yaml"
    write_csv(
        input_path,
        [
            {
                "paper_id": "p1",
                "title": "Alzheimer's disease diagnosis",
                "year": "2024",
                "doi": "",
                "abstract": "A dementia diagnosis model.",
            },
            {
                "paper_id": "p2",
                "title": "Prodromal Alzheimer's disease",
                "year": "2024",
                "doi": "",
                "abstract": "Differential diagnosis of dementia.",
            },
        ],
        ["paper_id", "title", "year", "doi", "abstract"],
    )
    contract = load_topic_contract(ROOT / "configs/topics/early_detection_ad.yaml")
    contract["rule_based_screening"]["include_terms"] = [
        "Alzheimer's disease",
        "prodromal Alzheimer's disease",
        "dementia differential diagnosis",
        "differential diagnosis of dementia",
    ]
    from ad_lit_pipeline.io.yaml_io import write_yaml_object

    write_yaml_object(contract_path, contract)

    run_script(
        "scripts/screen_scope.py",
        "--input",
        str(input_path),
        "--output",
        str(output_path),
        "--topic-contract",
        str(contract_path),
    )

    rows = read_csv(output_path)
    first_matches = rows[0]["scope_matched_include_terms"].split("; ")
    second_matches = rows[1]["scope_matched_include_terms"].split("; ")
    assert "Alzheimer's disease" in first_matches
    assert "prodromal Alzheimer's disease" not in first_matches
    assert "dementia differential diagnosis" not in first_matches
    assert "differential diagnosis of dementia" not in first_matches
    assert "Alzheimer's disease" in second_matches
    assert "prodromal Alzheimer's disease" in second_matches
    assert "differential diagnosis of dementia" in second_matches
    assert "dementia differential diagnosis" not in second_matches


def test_screen_scope_enforces_exact_publication_window_boundaries(
    tmp_path: Path,
) -> None:
    input_path = tmp_path / "normalized.csv"
    output_path = tmp_path / "screened.csv"
    contract_path = tmp_path / "contract.yaml"
    rows = [
        {
            "paper_id": paper_id,
            "title": "Artificial intelligence in Alzheimer disease",
            "year": year,
            "publication_date": publication_date,
            "doi": "",
            "abstract": "A relevant Alzheimer disease study.",
        }
        for paper_id, year, publication_date in [
            ("start", "2020", "2020-01-01"),
            ("end", "2026", "2026-06-19"),
            ("after", "2026", "2026-06-20"),
            ("year_mismatch", "2025", "2024-06-20"),
            ("whole_year", "2021", ""),
            ("boundary_without_date", "2026", ""),
        ]
    ]
    write_csv(
        input_path,
        rows,
        [
            "paper_id",
            "title",
            "year",
            "publication_date",
            "doi",
            "abstract",
        ],
    )
    contract = load_topic_contract(ROOT / "configs/topics/early_detection_ad.yaml")
    contract["collection"]["publication_window"] = {
        "start": "2020-01-01",
        "end": "2026-06-19",
    }
    from ad_lit_pipeline.io.yaml_io import write_yaml_object

    write_yaml_object(contract_path, contract)

    run_script(
        "scripts/screen_scope.py",
        "--input",
        str(input_path),
        "--output",
        str(output_path),
        "--topic-contract",
        str(contract_path),
    )

    screened = {row["paper_id"]: row for row in read_csv(output_path)}
    assert screened["start"]["scope_decision"] == "include"
    assert screened["start"]["scope_publication_window_status"] == (
        "eligible_exact_date"
    )
    assert screened["end"]["scope_decision"] == "include"
    assert screened["after"]["scope_decision"] == "exclude_or_route_elsewhere"
    assert screened["after"]["scope_publication_window_status"] == (
        "after_publication_window"
    )
    assert screened["year_mismatch"]["scope_decision"] == (
        "exclude_or_route_elsewhere"
    )
    assert screened["year_mismatch"]["scope_publication_window_status"] == (
        "publication_date_year_mismatch"
    )
    assert screened["whole_year"]["scope_decision"] == "include"
    assert screened["whole_year"]["scope_publication_window_status"] == (
        "eligible_whole_year"
    )
    assert screened["boundary_without_date"]["scope_decision"] == (
        "exclude_or_route_elsewhere"
    )
    assert screened["boundary_without_date"][
        "scope_publication_window_status"
    ] == "missing_exact_boundary_date"


def test_screen_scope_enforces_publication_window_carried_by_corpus_row(
    tmp_path: Path,
) -> None:
    input_path = tmp_path / "normalized.csv"
    output_path = tmp_path / "screened.csv"
    write_csv(
        input_path,
        [
            {
                "paper_id": "p1",
                "title": "Artificial intelligence in Alzheimer disease",
                "year": "2026",
                "publication_date": "2026-06-20",
                "doi": "",
                "abstract": "A relevant Alzheimer disease study.",
                "corpus_publication_window_start": "2020-01-01",
                "corpus_publication_window_end": "2026-06-19",
            }
        ],
        [
            "paper_id",
            "title",
            "year",
            "publication_date",
            "doi",
            "abstract",
            "corpus_publication_window_start",
            "corpus_publication_window_end",
        ],
    )

    run_script(
        "scripts/screen_scope.py",
        "--input",
        str(input_path),
        "--output",
        str(output_path),
        "--topic-contract",
        "configs/topics/early_detection_ad.yaml",
    )

    row = read_csv(output_path)[0]
    assert row["scope_decision"] == "exclude_or_route_elsewhere"
    assert row["scope_publication_window_status"] == "after_publication_window"


def test_screen_scope_rejects_contract_and_corpus_window_mismatch(
    tmp_path: Path,
) -> None:
    input_path = tmp_path / "normalized.csv"
    output_path = tmp_path / "screened.csv"
    contract_path = tmp_path / "contract.yaml"
    write_csv(
        input_path,
        [
            {
                "paper_id": "p1",
                "title": "Artificial intelligence in Alzheimer disease",
                "year": "2024",
                "publication_date": "2024-01-01",
                "doi": "",
                "abstract": "A relevant Alzheimer disease study.",
                "corpus_publication_window_start": "2019-01-01",
                "corpus_publication_window_end": "2026-06-19",
                "corpus_publication_window_inclusive": "true",
            }
        ],
        [
            "paper_id",
            "title",
            "year",
            "publication_date",
            "doi",
            "abstract",
            "corpus_publication_window_start",
            "corpus_publication_window_end",
            "corpus_publication_window_inclusive",
        ],
    )
    contract = load_topic_contract(ROOT / "configs/topics/early_detection_ad.yaml")
    contract["collection"]["publication_window"] = {
        "start": "2020-01-01",
        "end": "2026-06-19",
    }
    from ad_lit_pipeline.io.yaml_io import write_yaml_object

    write_yaml_object(contract_path, contract)

    run_script(
        "scripts/screen_scope.py",
        "--input",
        str(input_path),
        "--output",
        str(output_path),
        "--topic-contract",
        str(contract_path),
    )

    row = read_csv(output_path)[0]
    assert row["scope_decision"] == "exclude_or_route_elsewhere"
    assert row["scope_publication_window_status"] == (
        "publication_window_constraint_mismatch"
    )


def test_deduplicate_candidates_prefers_doi_and_abstract(tmp_path: Path) -> None:
    input_path = tmp_path / "candidates.jsonl"
    output_path = tmp_path / "deduped.jsonl"
    rows = [
        {
            "provider": "openalex",
            "provider_id": "W1",
            "doi": "https://doi.org/10.123/example",
            "title": "Example",
            "year": 2024,
            "abstract": "",
            "rank": 1,
            "full_text_locations": [
                {
                    "source": "provider_a",
                    "url": "https://example.test/a.pdf",
                    "kind": "pdf",
                }
            ],
            "topic_matches": {
                "anchor_topic_id": "early_detection",
                "main_topic_values": {
                    "early_detection": [
                        {"value": "early detection", "field": "title"}
                    ]
                },
                "secondary_topic_values": {"early_detection": []},
            },
        },
        {
            "provider": "openalex",
            "provider_id": "W2",
            "doi": "10.123/example",
            "title": "Example",
            "year": 2024,
            "abstract": "Useful abstract.",
            "rank": 2,
            "full_text_locations": [
                {
                    "source": "provider_b",
                    "url": "https://example.test/b.pdf",
                    "kind": "pdf",
                },
                {
                    "source": "provider_b_duplicate",
                    "url": "https://example.test/a.pdf",
                    "kind": "pdf",
                },
            ],
            "topic_matches": {
                "anchor_topic_id": "early_detection",
                "main_topic_values": {
                    "early_detection": [
                        {"value": "screening", "field": "abstract"}
                    ]
                },
                "secondary_topic_values": {"early_detection": []},
            },
        },
    ]
    input_path.write_text(
        "".join(json.dumps(row) + "\n" for row in rows),
        encoding="utf-8",
    )

    run_script(
        "scripts/deduplicate_candidates.py",
        "--input",
        str(input_path),
        "--output",
        str(output_path),
    )

    output_rows = [
        json.loads(line)
        for line in output_path.read_text(encoding="utf-8").splitlines()
    ]
    assert len(output_rows) == 1
    assert output_rows[0]["provider_id"] == "W2"
    assert output_rows[0]["dedupe_key"] == "doi:10.123/example"
    assert output_rows[0]["duplicate_count"] == 2
    assert output_rows[0]["topic_matches"]["main_topic_values"][
        "early_detection"
    ] == [
        {"value": "screening", "field": "abstract"},
        {"value": "early detection", "field": "title"},
    ]
    assert output_rows[0]["full_text_locations"] == [
        {"source": "provider_b", "url": "https://example.test/b.pdf", "kind": "pdf"},
        {
            "source": "provider_b_duplicate",
            "url": "https://example.test/a.pdf",
            "kind": "pdf",
        },
    ]


def test_candidate_topic_matches_record_values_and_fields() -> None:
    contract = load_topic_contract(ROOT / "configs/topics/ai_in_education.yaml")
    for topic in contract["topic_structure"]["main_topics"]:
        topic["field"] = "title_or_abstract"
        if topic["topic_id"] == "ai":
            topic["retrieval_terms"] = ["deep learning"]
    for groups in contract["topic_structure"]["secondary_topics"].values():
        for group in groups:
            group["field"] = "title_or_abstract"

    candidate = {
        "title": "Deep learning in K-12 classroom instruction",
        "abstract": (
            "This university study reports student achievement and well-being "
            "after classroom AI use."
        ),
    }

    annotated = annotate_candidate_topic_matches(
        candidate,
        topic_match_spec_from_contract(contract),
    )
    matches = annotated["topic_matches"]

    assert {"value": "deep learning", "field": "title"} in matches[
        "main_topic_values"
    ]["ai"]
    assert {"value": "K-12", "field": "title"} in matches["main_topic_values"][
        "formal_education"
    ]
    assert {"value": "student achievement", "field": "abstract"} in matches[
        "main_topic_values"
    ]["learning_impact"]
    assert {"value": "university", "field": "abstract"} in matches[
        "secondary_topic_values"
    ]["formal_education"]
    assert {"value": "well-being", "field": "abstract"} in matches[
        "secondary_topic_values"
    ]["learning_impact"]
    assert matches["matched_main_topics"] == [
        "ai",
        "formal_education",
        "learning_impact",
    ]
    assert matches["anchor_present"] is True


def test_candidate_topic_matches_handles_markup_dashes_and_plurals() -> None:
    contract = load_topic_contract(ROOT / "configs/topics/ai_in_education.yaml")
    for topic in contract["topic_structure"]["main_topics"]:
        topic["field"] = "title"
        if topic["topic_id"] == "ai":
            topic["matching_terms"] = ["LLM"]
        elif topic["topic_id"] == "formal_education":
            topic["matching_terms"] = ["middle school"]
        elif topic["topic_id"] == "learning_impact":
            topic["matching_terms"] = ["student performance"]

    candidate = {
        "title": (
            "<scp>LLMs</scp> for Middle\u2011School Students' "
            "Performance"
        ),
        "abstract": "",
    }

    annotated = annotate_candidate_topic_matches(
        candidate,
        topic_match_spec_from_contract(contract),
    )
    matches = annotated["topic_matches"]

    assert {"value": "LLM", "field": "title"} in matches["main_topic_values"][
        "ai"
    ]
    assert {"value": "middle school", "field": "title"} in matches[
        "main_topic_values"
    ]["formal_education"]
    assert {"value": "student performance", "field": "title"} in matches[
        "main_topic_values"
    ]["learning_impact"]
    assert matches["anchor_present"] is True
    assert matches["missing_main_topics"] == []


def test_query_groups_keep_secondary_replacement_groups_separate() -> None:
    contract = {
        "topic_structure": {
            "anchor_topic_id": "ai",
            "main_topics": [
                {
                    "topic_id": "ai",
                    "label": "AI",
                    "field": "title",
                    "terms": ["artificial intelligence", "machine learning"],
                    "retrieval_terms": ["artificial intelligence", "machine learning"],
                },
                {
                    "topic_id": "school_setting",
                    "label": "School setting",
                    "field": "title",
                    "terms": ["school", "classroom"],
                    "retrieval_terms": ["school", "classroom"],
                },
                {
                    "topic_id": "student_performance",
                    "label": "Student performance",
                    "field": "title_or_abstract",
                    "terms": ["student performance", "learning outcomes"],
                    "retrieval_terms": ["student performance", "learning outcomes"],
                },
            ],
            "secondary_topics": {
                "school_setting": [
                    {
                        "secondary_topic_id": "higher_education",
                        "label": "Higher education",
                        "field": "title",
                        "terms": ["higher education", "university", "college"],
                        "retrieval_terms": ["higher education", "university"],
                    },
                    {
                        "secondary_topic_id": "workplace_learning",
                        "label": "Workplace learning",
                        "field": "title",
                        "terms": ["workplace", "internship", "office"],
                        "retrieval_terms": ["workplace", "internship"],
                    },
                ]
            },
        }
    }

    strategy = build_query_groups_from_contract(contract, max_results=20)
    strict_tier_0 = strategy["query_groups"][0]
    relaxed_tier_0 = strategy["query_groups"][1]
    tier_1 = strategy["query_groups"][2]

    assert strict_tier_0["group_id"] == "tier_0_title"
    assert strict_tier_0["queries"][0]["query_id"] == "tier_0_all_main_title"
    assert strict_tier_0["queries"][0]["requires_title_screening"] is False
    assert {
        block["topic_id"]: block["field"]
        for block in strict_tier_0["queries"][0]["blocks"]
    } == {
        "ai": "title",
        "school_setting": "title",
        "student_performance": "title",
    }
    assert relaxed_tier_0["group_id"] == "tier_0"
    assert relaxed_tier_0["queries"][0]["query_id"] == "tier_0_all_main"
    assert relaxed_tier_0["queries"][0]["requires_title_screening"] is True
    assert {
        block["topic_id"]: block["field"]
        for block in relaxed_tier_0["queries"][0]["blocks"]
    }["student_performance"] == "title_or_abstract"
    assert len(tier_1["queries"]) == 2
    tier_1_queries = {query["query_id"]: query for query in tier_1["queries"]}
    assert (
        "tier_1_replace_school_setting_with_higher_education" in tier_1_queries
    )
    assert (
        "tier_1_replace_school_setting_with_workplace_learning" in tier_1_queries
    )
    higher_query = tier_1_queries[
        "tier_1_replace_school_setting_with_higher_education"
    ]
    workplace_query = tier_1_queries[
        "tier_1_replace_school_setting_with_workplace_learning"
    ]
    assert "university" in higher_query["query"]
    assert "workplace" not in higher_query["query"]
    assert "workplace" in workplace_query["query"]
    assert "university" not in workplace_query["query"]
    assert higher_query["replacement_secondary_groups"] == [
        {
            "main_topic_id": "school_setting",
            "secondary_topic_id": "higher_education",
            "label": "Higher education",
        }
    ]


def test_export_included_candidates_to_canonical_csv(tmp_path: Path) -> None:
    candidates_path = tmp_path / "deduped.jsonl"
    screening_path = tmp_path / "screening.csv"
    output_path = tmp_path / "papers.csv"

    candidate = {
        "provider": "openalex",
        "provider_id": "W1",
        "doi": "10.123/example",
        "title": "Detection Study",
        "year": 2024,
        "abstract": "Early detection abstract.",
        "authors": "A. Author",
        "venue": "Journal",
        "url": "https://example.test",
        "rank": 1,
        "retrieval_date": "2026-05-25",
        "retrieved_at": "2026-05-25T10:11:12+00:00",
        "corpus_publication_window_start": "2020-01-01",
        "corpus_publication_window_end": "2026-06-19",
        "corpus_publication_window_inclusive": True,
        "query": "early detection Alzheimer",
        "query_index": 2,
        "query_rank": 3,
        "query_reason": "Primary retrieval query.",
        "query_url": "https://api.openalex.org/works?filter=example",
        "retrieval_group_id": "tier_0",
        "retrieval_tier": 0,
        "retrieval_query_id": "tier_0_all_main",
        "retrieval_logical_query_id": "tier_0_all_main",
        "retrieval_iteration": 1,
        "retrieval_phase": "strict",
        "dedupe_key": "doi:10.123/example",
        "duplicate_count": 1,
        "in_fetch_duplicate_count": 1,
        "duplicate_provenance": [
            {
                "provider_id": "W2",
                "retrieval_query_id": "tier_1_secondary",
            }
        ],
        "in_fetch_duplicate_provenance": [
            {
                "provider_id": "W1",
                "query_index": 4,
                "retrieval_query_id": "tier_0_repeat",
            }
        ],
        "retrieval_query_blocks": [
            {"topic_id": "early_detection", "terms": ["early detection"]}
        ],
        "full_text_locations": [
            {"url": "https://example.test/full.pdf", "is_oa": True}
        ],
        "raw_record": {
            "id": "W1",
            "publication_date": "2024-03-04",
            "updated_date": "2026-05-20T10:00:00Z",
            "type": "article",
            "type_crossref": "journal-article",
            "language": "en",
            "is_retracted": False,
            "cited_by_count": 12,
        },
        "topic_matches": {
            "main_topic_values": {
                "early_detection": [{"value": "early detection", "field": "title"}],
                "disease_state": [{"value": "Alzheimer", "field": "abstract"}],
            },
            "secondary_topic_values": {
                "evidence_signal": [{"value": "biomarker", "field": "abstract"}],
            },
        },
    }
    candidates_path.write_text(json.dumps(candidate) + "\n", encoding="utf-8")
    write_csv(
        screening_path,
        [
            {
                "paper_id": "paper_1",
                "title": "Detection Study",
                "year": "2024",
                "doi": "10.123/example",
                "provider": "openalex",
                "provider_id": "W1",
                "source_rank": "1",
                "screening_decision": "include",
                "screening_confidence": "high",
                "screening_reason": "Directly relevant.",
                "title_anchor_present": "yes",
                "title_relevance_tier": "0",
                "title_matched_main_topics": "early_detection; disease_state",
                "title_matched_secondary_topics": "",
                "title_missing_main_topics": "",
            }
        ],
        [
            "paper_id",
            "title",
            "year",
            "doi",
            "provider",
            "provider_id",
            "source_rank",
            "screening_decision",
            "screening_confidence",
            "screening_reason",
            "title_anchor_present",
            "title_relevance_tier",
            "title_matched_main_topics",
            "title_matched_secondary_topics",
            "title_missing_main_topics",
        ],
    )

    run_script(
        "scripts/export_screened_candidates_to_csv.py",
        "--candidates",
        str(candidates_path),
        "--screening",
        str(screening_path),
        "--output",
        str(output_path),
    )

    rows = read_csv(output_path)
    assert len(rows) == 1
    row = rows[0]
    assert row["paper_id"] == "paper_1"
    assert row["title"] == "Detection Study"
    assert row["provider"] == "openalex"
    assert row["provider_id"] == "W1"
    assert row["publication_date"] == "2024-03-04"
    assert row["corpus_publication_window_start"] == "2020-01-01"
    assert row["corpus_publication_window_end"] == "2026-06-19"
    assert row["corpus_publication_window_inclusive"] == "true"
    assert row["provider_record_updated_at"] == "2026-05-20T10:00:00Z"
    assert row["provider_source_type"] == "article"
    assert row["canonical_work_kind"] == "research_article"
    assert row["source_type_classification_status"] == "resolved"
    assert json.loads(row["source_type_classification_evidence_json"]) == [
        "provider_type:type=article"
    ]
    assert json.loads(row["source_type_review_reasons_json"]) == []
    assert row["provider_crossref_type"] == "journal-article"
    assert row["language"] == "en"
    assert row["is_retracted"] == "false"
    assert row["cited_by_count"] == "12"
    assert row["source_rank"] == "1"
    assert row["retrieval_date"] == "2026-05-25"
    assert row["retrieved_at"] == "2026-05-25T10:11:12+00:00"
    assert row["source_query"] == "early detection Alzheimer"
    assert row["source_query_index"] == "2"
    assert row["source_query_rank"] == "3"
    assert row["source_query_reason"] == "Primary retrieval query."
    assert row["retrieval_tier"] == "0"
    assert row["retrieval_phase"] == "strict"
    assert row["dedupe_key"] == "doi:10.123/example"
    assert row["duplicate_count"] == "1"
    assert row["in_fetch_duplicate_count"] == "1"
    assert json.loads(row["duplicate_provenance_json"])[0]["provider_id"] == "W2"
    assert json.loads(row["in_fetch_duplicate_provenance_json"])[0][
        "query_index"
    ] == 4
    assert json.loads(row["retrieval_query_blocks_json"])[0]["topic_id"] == (
        "early_detection"
    )
    assert json.loads(row["full_text_locations_json"])[0]["is_oa"] is True
    assert len(row["candidate_observation_sha256"]) == 64
    assert len(row["raw_record_sha256"]) == 64
    assert row["raw_record_source_path"] == str(candidates_path)
    assert row["raw_record_source_line"] == "1"
    assert len(row["raw_record_source_file_sha256"]) == 64
    assert "screening_reason=Directly relevant." in row["notes"]


def test_export_included_candidates_orders_by_title_tier_and_caps(
    tmp_path: Path,
) -> None:
    candidates_path = tmp_path / "deduped.jsonl"
    screening_path = tmp_path / "screening.csv"
    output_path = tmp_path / "papers.csv"
    candidates = [
        {
            "provider": "openalex",
            "provider_id": "W1",
            "doi": "10.123/tier1",
            "title": "Tier One",
            "year": 2024,
            "rank": 1,
        },
        {
            "provider": "openalex",
            "provider_id": "W2",
            "doi": "10.123/tier0",
            "title": "Tier Zero",
            "year": 2024,
            "rank": 2,
        },
    ]
    candidates_path.write_text(
        "".join(json.dumps(candidate) + "\n" for candidate in candidates),
        encoding="utf-8",
    )
    fieldnames = [
        "paper_id",
        "title",
        "year",
        "doi",
        "provider",
        "provider_id",
        "source_rank",
        "screening_decision",
        "screening_confidence",
        "screening_reason",
        "title_relevance_tier",
    ]
    write_csv(
        screening_path,
        [
            {
                "paper_id": "tier_1",
                "title": "Tier One",
                "year": "2024",
                "doi": "10.123/tier1",
                "provider": "openalex",
                "provider_id": "W1",
                "source_rank": "1",
                "screening_decision": "include",
                "screening_confidence": "high",
                "screening_reason": "Adjacent replacement.",
                "title_relevance_tier": "1",
            },
            {
                "paper_id": "tier_0",
                "title": "Tier Zero",
                "year": "2024",
                "doi": "10.123/tier0",
                "provider": "openalex",
                "provider_id": "W2",
                "source_rank": "2",
                "screening_decision": "include",
                "screening_confidence": "high",
                "screening_reason": "All main topics.",
                "title_relevance_tier": "0",
            },
        ],
        fieldnames,
    )

    run_script(
        "scripts/export_screened_candidates_to_csv.py",
        "--candidates",
        str(candidates_path),
        "--screening",
        str(screening_path),
        "--output",
        str(output_path),
        "--max-results",
        "1",
    )

    rows = read_csv(output_path)
    assert len(rows) == 1
    assert rows[0]["paper_id"] == "tier_0"


def test_export_included_warns_when_below_requested_count(tmp_path: Path) -> None:
    candidates_path = tmp_path / "deduped.jsonl"
    screening_path = tmp_path / "screening.csv"
    output_path = tmp_path / "papers.csv"
    write_jsonl(
        candidates_path,
        [
            {
                "provider": "openalex",
                "provider_id": "W1",
                "doi": "10.123/one",
                "title": "Only Included",
                "year": 2024,
                "rank": 1,
            }
        ],
    )
    write_csv(
        screening_path,
        [
            {
                "paper_id": "one",
                "title": "Only Included",
                "year": "2024",
                "doi": "10.123/one",
                "provider": "openalex",
                "provider_id": "W1",
                "source_rank": "1",
                "screening_decision": "include",
                "screening_confidence": "high",
                "screening_reason": "Relevant.",
                "title_relevance_tier": "0",
            }
        ],
        [
            "paper_id",
            "title",
            "year",
            "doi",
            "provider",
            "provider_id",
            "source_rank",
            "screening_decision",
            "screening_confidence",
            "screening_reason",
            "title_relevance_tier",
        ],
    )

    result = run_export_included(
        candidates_path,
        screening_path,
        output_path,
        max_results=2,
    )

    assert result.row_counts["included_rows_exported"] == 1
    assert result.metadata["target_export_rows"] == 2
    assert result.metadata["export_target_policy"] == "requested_max_results"
    assert "fewer included papers than requested" in result.warnings[0]


def test_export_included_quality_gate_sets_error_below_threshold(
    tmp_path: Path,
) -> None:
    candidates_path = tmp_path / "deduped.jsonl"
    screening_path = tmp_path / "screening.csv"
    output_path = tmp_path / "papers.csv"
    write_jsonl(
        candidates_path,
        [
            {
                "provider": "openalex",
                "provider_id": "W1",
                "doi": "10.123/one",
                "title": "Only Included",
                "year": 2024,
                "rank": 1,
            }
        ],
    )
    write_csv(
        screening_path,
        [
            {
                "paper_id": "one",
                "title": "Only Included",
                "year": "2024",
                "doi": "10.123/one",
                "provider": "openalex",
                "provider_id": "W1",
                "source_rank": "1",
                "screening_decision": "include",
                "screening_confidence": "high",
                "screening_reason": "Relevant.",
                "title_relevance_tier": "0",
            }
        ],
        [
            "paper_id",
            "title",
            "year",
            "doi",
            "provider",
            "provider_id",
            "source_rank",
            "screening_decision",
            "screening_confidence",
            "screening_reason",
            "title_relevance_tier",
        ],
    )

    result = run_export_included(
        candidates_path,
        screening_path,
        output_path,
        max_results=2,
        fail_below_export_ratio=0.75,
    )

    assert output_path.exists()
    assert result.row_counts["included_rows_exported"] == 1
    assert result.metadata["export_ratio"] == 0.5
    assert result.metadata["fail_below_export_ratio"] == 0.75
    assert result.error is not None
    assert "Export quality gate failed" in result.error


def test_verify_full_text_availability_checks_provider_neutral_locations(
    tmp_path: Path,
) -> None:
    candidates_path = tmp_path / "deduped.jsonl"
    screening_path = tmp_path / "screening.csv"
    availability_path = tmp_path / "availability.csv"
    contract_path = tmp_path / "contract.yaml"
    contract_path.write_text(
        "collection:\n  require_full_text_availability: true\n",
        encoding="utf-8",
    )
    write_jsonl(
        candidates_path,
        [
            {
                "provider": "other_library",
                "provider_id": "P1",
                "doi": "10.123/full",
                "title": "Full Text Paper",
                "full_text_locations": [
                    {
                        "source": "other_library_record",
                        "url": "https://example.test/full.pdf",
                        "kind": "pdf",
                        "license": "cc-by",
                        "is_open_access": True,
                    }
                ],
            }
        ],
    )
    write_csv(
        screening_path,
        [
            {
                "paper_id": "full_text_paper",
                "title": "Full Text Paper",
                "doi": "10.123/full",
                "provider": "other_library",
                "provider_id": "P1",
                "screening_decision": "include",
            }
        ],
        [
            "paper_id",
            "title",
            "doi",
            "provider",
            "provider_id",
            "screening_decision",
        ],
    )

    def fake_checker(
        location: verify_full_text_availability.FullTextLocation,
        timeout_seconds: float,
    ) -> verify_full_text_availability.AvailabilityResult:
        assert location.source == "other_library_record"
        assert location.kind == "pdf"
        assert timeout_seconds == 1.5
        return verify_full_text_availability.AvailabilityResult(
            status=verify_full_text_availability.STATUS_VERIFIED,
            source=location.source,
            url=location.url,
            kind=location.kind,
            checked_at="2026-06-11T00:00:00+00:00",
            content_type="application/pdf",
            license=location.license,
            is_open_access=location.is_open_access,
        )

    result = verify_full_text_availability.run(
        candidates_path,
        screening_path,
        availability_path,
        contract_path,
        timeout_seconds=1.5,
        checker=fake_checker,
    )

    rows = read_csv(availability_path)
    assert result.row_counts["verified_full_text_rows"] == 1
    assert rows[0]["full_text_availability_status"] == "verified"
    assert rows[0]["full_text_url"] == "https://example.test/full.pdf"
    assert rows[0]["full_text_license"] == "cc-by"
    assert rows[0]["full_text_is_open_access"] == "yes"


def test_fetch_candidates_defaults_to_provider_max_per_page(
    tmp_path: Path,
    monkeypatch,
) -> None:
    plan_path = tmp_path / "plan.json"
    output_path = tmp_path / "candidates.jsonl"
    plan_path.write_text(
        json.dumps(
            {
                "recommended_provider": "openalex",
                "provider_specific_plan": {
                    "provider": "openalex",
                    "query": "AI school performance",
                },
            }
        ),
        encoding="utf-8",
    )

    class FakeProvider:
        name = "openalex"
        max_per_page = 100
        last_fetch_diagnostics = {}

        def __init__(self) -> None:
            self.per_page: int | None = None

        def validate_plan(self, plan: dict[str, object]) -> None:
            pass

        def fetch_candidates(
            self,
            plan: dict[str, object],
            max_results: int,
            per_page: int,
            mailto: str | None,
            sleep_seconds: float,
        ) -> list[dict[str, object]]:
            self.per_page = per_page
            return [
                {
                    "provider": "openalex",
                    "provider_id": "W1",
                    "doi": "10.1/example",
                    "title": "Example",
                }
            ]

    provider = FakeProvider()
    monkeypatch.setitem(fetch_candidates_step.PROVIDERS, "openalex", provider)

    result = fetch_candidates_step.run(plan_path, output_path, max_results=1)

    assert provider.per_page == 100
    assert result.metadata["per_page"] == 100
    assert result.metadata["provider_max_per_page"] == 100


def test_fetch_candidates_rejects_unproven_publication_window_rows(
    tmp_path: Path,
    monkeypatch,
) -> None:
    plan_path = tmp_path / "plan.json"
    output_path = tmp_path / "candidates.jsonl"
    write_json(
        plan_path,
        {
            "recommended_provider": "openalex",
            "provider_specific_plan": {
                "provider": "openalex",
                "query": "AI Alzheimer",
            },
            "corpus_constraints": {
                "publication_window": {
                    "start": "2020-01-01",
                    "end": "2026-06-19",
                    "inclusive": True,
                }
            },
        },
    )

    class FakeProvider:
        name = "openalex"
        max_per_page = 100
        last_fetch_diagnostics = {}

        def validate_plan(self, plan: dict[str, object]) -> None:
            pass

        def fetch_candidates(
            self,
            plan: dict[str, object],
            max_results: int,
            per_page: int,
            mailto: str | None,
            sleep_seconds: float,
        ) -> list[dict[str, object]]:
            return [
                {
                    "provider": "openalex",
                    "provider_id": provider_id,
                    "publication_date": publication_date,
                }
                for provider_id, publication_date in [
                    ("before", "2019-12-31"),
                    ("start", "2020-01-01"),
                    ("end", "2026-06-19"),
                    ("after", "2026-06-20"),
                    ("missing", ""),
                ]
            ]

    monkeypatch.setitem(
        fetch_candidates_step.PROVIDERS,
        "openalex",
        FakeProvider(),
    )

    result = fetch_candidates_step.run(
        plan_path,
        output_path,
        max_results=5,
    )

    assert [row["provider_id"] for row in read_jsonl_objects(output_path)] == [
        "start",
        "end",
    ]
    for row in read_jsonl_objects(output_path):
        assert row["corpus_publication_window_start"] == "2020-01-01"
        assert row["corpus_publication_window_end"] == "2026-06-19"
        assert row["corpus_publication_window_inclusive"] is True
    assert result.row_counts["provider_candidates_returned"] == 5
    assert result.row_counts["publication_window_rejections"] == 3
    assert result.row_counts["fetched_candidates"] == 2
    assert {
        row["reason"]
        for row in result.metadata["publication_window_rejections"]
    } == {
        "before_publication_window",
        "after_publication_window",
        "missing_or_invalid_exact_publication_date",
    }


def test_fetch_candidates_reports_target_limited_query_coverage(
    tmp_path: Path,
    monkeypatch,
) -> None:
    plan_path = tmp_path / "plan.json"
    output_path = tmp_path / "candidates.jsonl"
    write_json(
        plan_path,
        {
            "recommended_provider": "openalex",
            "provider_specific_plan": {
                "provider": "openalex",
                "query": "AI Alzheimer",
            },
        },
    )

    class FakeProvider:
        name = "openalex"
        max_per_page = 100
        last_fetch_diagnostics = {
            "planned_logical_query_count": 3,
            "planned_execution_query_count": 3,
            "executed_logical_query_count": 1,
            "executed_query_count": 1,
        }

        def validate_plan(self, plan: dict[str, object]) -> None:
            pass

        def fetch_candidates(
            self,
            plan: dict[str, object],
            max_results: int,
            per_page: int,
            mailto: str | None,
            sleep_seconds: float,
        ) -> list[dict[str, object]]:
            return [{"provider": "openalex", "provider_id": "W1"}]

    monkeypatch.setitem(
        fetch_candidates_step.PROVIDERS,
        "openalex",
        FakeProvider(),
    )

    result = fetch_candidates_step.run(
        plan_path,
        output_path,
        max_results=1,
    )

    assert result.row_counts["planned_execution_query_count"] == 3
    assert result.row_counts["executed_query_count"] == 1
    assert result.warnings == [
        "Tiered retrieval reached the unique-candidate target before all "
        "planned execution queries ran: executed=1 planned=3."
    ]


def test_verify_full_text_availability_skips_excluded_candidates(
    tmp_path: Path,
) -> None:
    candidates_path = tmp_path / "deduped.jsonl"
    screening_path = tmp_path / "screening.csv"
    availability_path = tmp_path / "availability.csv"
    contract_path = tmp_path / "contract.yaml"
    contract_path.write_text(
        "collection:\n  require_full_text_availability: true\n",
        encoding="utf-8",
    )
    write_jsonl(
        candidates_path,
        [
            {
                "provider": "openalex",
                "provider_id": "W1",
                "doi": "10.123/include",
                "title": "Included Candidate",
                "full_text_locations": [
                    {"source": "provider", "url": "https://example.test/one.pdf"}
                ],
            },
            {
                "provider": "openalex",
                "provider_id": "W2",
                "doi": "10.123/exclude",
                "title": "Excluded Candidate",
                "full_text_locations": [
                    {"source": "provider", "url": "https://example.test/two.pdf"}
                ],
            },
        ],
    )
    fieldnames = [
        "paper_id",
        "title",
        "doi",
        "provider",
        "provider_id",
        "screening_decision",
    ]
    write_csv(
        screening_path,
        [
            {
                "paper_id": "included",
                "title": "Included Candidate",
                "doi": "10.123/include",
                "provider": "openalex",
                "provider_id": "W1",
                "screening_decision": "include",
            },
            {
                "paper_id": "excluded",
                "title": "Excluded Candidate",
                "doi": "10.123/exclude",
                "provider": "openalex",
                "provider_id": "W2",
                "screening_decision": "exclude",
            },
        ],
        fieldnames,
    )
    checked_urls: list[str] = []

    def fake_checker(
        location: verify_full_text_availability.FullTextLocation,
        timeout_seconds: float,
    ) -> verify_full_text_availability.AvailabilityResult:
        checked_urls.append(location.url)
        return verify_full_text_availability.AvailabilityResult(
            status=verify_full_text_availability.STATUS_VERIFIED,
            source=location.source,
            url=location.url,
            kind=location.kind,
            checked_at="2026-06-11T00:00:00+00:00",
        )

    result = verify_full_text_availability.run(
        candidates_path,
        screening_path,
        availability_path,
        contract_path,
        checker=fake_checker,
    )

    rows = read_csv(availability_path)
    assert checked_urls == ["https://example.test/one.pdf"]
    assert [row["full_text_availability_status"] for row in rows] == [
        "verified",
        "skipped_not_included",
    ]
    assert result.row_counts["availability_rows"] == 2
    assert result.row_counts["verified_rows"] == 1
    assert result.row_counts["skipped_not_included_rows"] == 1
    assert result.row_counts["verified_full_text_rows"] == 1


def test_verify_full_text_availability_reuses_url_cache(
    tmp_path: Path,
) -> None:
    candidates_path = tmp_path / "deduped.jsonl"
    screening_path = tmp_path / "screening.csv"
    availability_path = tmp_path / "availability.csv"
    contract_path = tmp_path / "contract.yaml"
    contract_path.write_text(
        "collection:\n  require_full_text_availability: true\n",
        encoding="utf-8",
    )
    shared_url = "https://example.test/shared.pdf"
    write_jsonl(
        candidates_path,
        [
            {
                "provider": "openalex",
                "provider_id": "W1",
                "doi": "10.123/one",
                "title": "One",
                "full_text_locations": [{"source": "provider", "url": shared_url}],
            },
            {
                "provider": "openalex",
                "provider_id": "W2",
                "doi": "10.123/two",
                "title": "Two",
                "full_text_locations": [{"source": "provider", "url": shared_url}],
            },
        ],
    )
    fieldnames = [
        "paper_id",
        "title",
        "doi",
        "provider",
        "provider_id",
        "screening_decision",
    ]
    write_csv(
        screening_path,
        [
            {
                "paper_id": "one",
                "title": "One",
                "doi": "10.123/one",
                "provider": "openalex",
                "provider_id": "W1",
                "screening_decision": "include",
            },
            {
                "paper_id": "two",
                "title": "Two",
                "doi": "10.123/two",
                "provider": "openalex",
                "provider_id": "W2",
                "screening_decision": "include",
            },
        ],
        fieldnames,
    )
    checked_urls: list[str] = []

    def fake_checker(
        location: verify_full_text_availability.FullTextLocation,
        timeout_seconds: float,
    ) -> verify_full_text_availability.AvailabilityResult:
        checked_urls.append(location.url)
        return verify_full_text_availability.AvailabilityResult(
            status=verify_full_text_availability.STATUS_VERIFIED,
            source=location.source,
            url=location.url,
            kind=location.kind,
            checked_at="2026-06-11T00:00:00+00:00",
        )

    result = verify_full_text_availability.run(
        candidates_path,
        screening_path,
        availability_path,
        contract_path,
        checker=fake_checker,
        workers=1,
    )

    rows = read_csv(availability_path)
    assert checked_urls == [shared_url]
    assert result.row_counts["url_cache_hits"] == 1
    assert [row["full_text_availability_status"] for row in rows] == [
        "verified",
        "verified",
    ]


def test_full_text_availability_uses_unpaywall_fallback(
    monkeypatch,
) -> None:
    requested_urls: list[str] = []

    def fake_request_json(
        url: str,
        timeout_seconds: float,
        headers: dict[str, str] | None = None,
    ) -> dict[str, object]:
        requested_urls.append(url)
        return {
            "best_oa_location": {
                "url_for_pdf": "https://example.test/unpaywall.pdf",
                "license": "cc-by",
            }
        }

    def fake_checker(
        location: verify_full_text_availability.FullTextLocation,
        timeout_seconds: float,
    ) -> verify_full_text_availability.AvailabilityResult:
        return verify_full_text_availability.AvailabilityResult(
            status=verify_full_text_availability.STATUS_VERIFIED,
            source=location.source,
            url=location.url,
            kind=location.kind,
            license=location.license,
        )

    monkeypatch.setattr(
        verify_full_text_availability,
        "request_json",
        fake_request_json,
    )

    result = verify_full_text_availability.verify_candidate(
        {"doi": "10.123/example", "title": "Example"},
        checker=fake_checker,
        unpaywall_email="test@example.com",
    )

    assert "api.unpaywall.org" in requested_urls[0]
    assert result.status == "verified"
    assert result.source == "unpaywall"
    assert result.url == "https://example.test/unpaywall.pdf"
    assert result.license == "cc-by"


def test_full_text_availability_uses_provider_metadata_before_resolvers(
    monkeypatch,
) -> None:
    def fail_request_json(
        url: str,
        timeout_seconds: float,
        headers: dict[str, str] | None = None,
    ) -> dict[str, object]:
        raise AssertionError("External resolver should not be called.")

    def fake_checker(
        location: verify_full_text_availability.FullTextLocation,
        timeout_seconds: float,
    ) -> verify_full_text_availability.AvailabilityResult:
        return verify_full_text_availability.AvailabilityResult(
            status=verify_full_text_availability.STATUS_VERIFIED,
            source=location.source,
            url=location.url,
            kind=location.kind,
        )

    monkeypatch.setattr(
        verify_full_text_availability,
        "request_json",
        fail_request_json,
    )

    result = verify_full_text_availability.verify_candidate(
        {
            "doi": "10.123/example",
            "title": "Example",
            "full_text_locations": [
                {
                    "source": "provider_record",
                    "url": "https://example.test/provider.pdf",
                    "kind": "pdf",
                }
            ],
        },
        checker=fake_checker,
        unpaywall_email="test@example.com",
        core_api_key="core-key",
    )

    assert result.status == "verified"
    assert result.source == "provider_record"
    assert result.url == "https://example.test/provider.pdf"


def test_full_text_availability_uses_core_fallback(
    monkeypatch,
) -> None:
    requested: list[tuple[str, dict[str, str] | None]] = []

    def fake_request_json(
        url: str,
        timeout_seconds: float,
        headers: dict[str, str] | None = None,
    ) -> dict[str, object]:
        requested.append((url, headers))
        return {
            "results": [
                {
                    "downloadUrl": "https://example.test/core.pdf",
                }
            ]
        }

    def fake_checker(
        location: verify_full_text_availability.FullTextLocation,
        timeout_seconds: float,
    ) -> verify_full_text_availability.AvailabilityResult:
        return verify_full_text_availability.AvailabilityResult(
            status=verify_full_text_availability.STATUS_VERIFIED,
            source=location.source,
            url=location.url,
            kind=location.kind,
        )

    monkeypatch.setattr(
        verify_full_text_availability,
        "request_json",
        fake_request_json,
    )

    result = verify_full_text_availability.verify_candidate(
        {"doi": "10.123/example", "title": "Example"},
        checker=fake_checker,
        core_api_key="core-key",
    )

    assert "api.core.ac.uk" in requested[0][0]
    assert requested[0][1] == {"Authorization": "Bearer core-key"}
    assert result.status == "verified"
    assert result.source == "core"
    assert result.url == "https://example.test/core.pdf"


def test_full_text_availability_marks_invalid_provider_urls_unverified(
    monkeypatch,
) -> None:
    def invalid_request_url(
        url: str,
        method: str,
        timeout_seconds: float,
    ) -> tuple[int, str, str]:
        raise InvalidURL("URL can't contain control characters")

    monkeypatch.setattr(
        verify_full_text_availability,
        "request_url",
        invalid_request_url,
    )

    result = verify_full_text_availability.check_location(
        verify_full_text_availability.FullTextLocation(
            source="provider_redirect",
            url="https://example.test/download",
            kind="pdf",
        )
    )

    assert result.status == verify_full_text_availability.STATUS_UNVERIFIED
    assert "InvalidURL" in result.error


def test_full_text_availability_request_url_percent_encodes_spaces() -> None:
    assert (
        verify_full_text_availability.request_safe_url(
            "https://example.test/Downloads/Paper Name.pdf?file=Paper Name.pdf"
        )
        == "https://example.test/Downloads/Paper%20Name.pdf?file=Paper%20Name.pdf"
    )


def test_export_included_requires_verified_full_text_when_enabled(
    tmp_path: Path,
) -> None:
    candidates_path = tmp_path / "deduped.jsonl"
    screening_path = tmp_path / "screening.csv"
    availability_path = tmp_path / "availability.csv"
    output_path = tmp_path / "papers.csv"
    write_jsonl(
        candidates_path,
        [
            {
                "provider": "openalex",
                "provider_id": "W1",
                "doi": "10.123/verified",
                "title": "Verified Full Text",
                "year": 2024,
                "rank": 1,
            },
            {
                "provider": "openalex",
                "provider_id": "W2",
                "doi": "10.123/unverified",
                "title": "Unverified Full Text",
                "year": 2024,
                "rank": 2,
            },
        ],
    )
    screening_fieldnames = [
        "paper_id",
        "title",
        "year",
        "doi",
        "provider",
        "provider_id",
        "source_rank",
        "screening_decision",
        "screening_confidence",
        "screening_reason",
        "title_relevance_tier",
    ]
    write_csv(
        screening_path,
        [
            {
                "paper_id": "verified",
                "title": "Verified Full Text",
                "year": "2024",
                "doi": "10.123/verified",
                "provider": "openalex",
                "provider_id": "W1",
                "source_rank": "1",
                "screening_decision": "include",
                "screening_confidence": "high",
                "screening_reason": "Relevant.",
                "title_relevance_tier": "0",
            },
            {
                "paper_id": "unverified",
                "title": "Unverified Full Text",
                "year": "2024",
                "doi": "10.123/unverified",
                "provider": "openalex",
                "provider_id": "W2",
                "source_rank": "2",
                "screening_decision": "include",
                "screening_confidence": "high",
                "screening_reason": "Relevant.",
                "title_relevance_tier": "0",
            },
        ],
        screening_fieldnames,
    )
    write_csv(
        availability_path,
        [
            {
                "paper_id": "verified",
                "title": "Verified Full Text",
                "doi": "10.123/verified",
                "provider": "openalex",
                "provider_id": "W1",
                "screening_decision": "include",
                "full_text_availability_status": "verified",
                "full_text_availability_source": "openalex_best_oa_location",
                "full_text_url": "https://example.test/verified.pdf",
                "full_text_url_kind": "pdf",
                "full_text_url_checked_at": "2026-06-11T00:00:00+00:00",
                "full_text_url_content_type": "application/pdf",
                "full_text_license": "cc-by",
                "full_text_is_open_access": "yes",
                "full_text_availability_error": "",
            },
            {
                "paper_id": "unverified",
                "title": "Unverified Full Text",
                "doi": "10.123/unverified",
                "provider": "openalex",
                "provider_id": "W2",
                "screening_decision": "include",
                "full_text_availability_status": "unverified",
                "full_text_availability_source": "openalex_best_oa_location",
                "full_text_url": "https://example.test/unverified.pdf",
                "full_text_url_kind": "pdf",
                "full_text_url_checked_at": "2026-06-11T00:00:00+00:00",
                "full_text_url_content_type": "",
                "full_text_license": "",
                "full_text_is_open_access": "yes",
                "full_text_availability_error": "HEAD: HTTP 403",
            },
        ],
        verify_full_text_availability.AVAILABILITY_COLUMNS,
    )

    result = run_export_included(
        candidates_path,
        screening_path,
        output_path,
        max_results=2,
        availability_path=availability_path,
        require_full_text_availability=True,
    )

    rows = read_csv(output_path)
    assert [row["paper_id"] for row in rows] == ["verified"]
    assert rows[0]["full_text_url"] == "https://example.test/verified.pdf"
    assert result.row_counts["verified_full_text_rows"] == 1
    assert result.row_counts["skipped_full_text_unverified"] == 1
    assert "verified-full-text papers" in result.warnings[0]


def test_select_calibration_papers_skips_reviews_and_protocols(tmp_path: Path) -> None:
    candidates_path = tmp_path / "deduped.jsonl"
    screening_path = tmp_path / "screening.csv"
    output_path = tmp_path / "calibration.csv"
    candidates = [
        {
            "provider": "openalex",
            "provider_id": "W_review",
            "doi": "10.123/review",
            "title": "Systematic review of mobile health interventions",
            "year": 2024,
            "rank": 1,
            "raw_record": {"type": "review"},
        },
        {
            "provider": "openalex",
            "provider_id": "W_protocol",
            "doi": "10.123/protocol",
            "title": "Trial protocol for a mobile health app",
            "year": 2024,
            "rank": 2,
            "raw_record": {"type": "article"},
        },
        {
            "provider": "openalex",
            "provider_id": "W_primary",
            "doi": "10.123/primary",
            "title": "Randomized trial of a mobile health app",
            "year": 2024,
            "rank": 3,
            "abstract": "Trial results.",
            "raw_record": {"type": "article"},
        },
    ]
    write_jsonl(candidates_path, candidates)
    fieldnames = [
        "paper_id",
        "title",
        "year",
        "doi",
        "provider",
        "provider_id",
        "source_rank",
        "screening_decision",
        "screening_confidence",
        "screening_reason",
        "title_relevance_tier",
    ]
    write_csv(
        screening_path,
        [
            {
                "paper_id": "paper_review",
                "title": "Systematic review of mobile health interventions",
                "year": "2024",
                "doi": "10.123/review",
                "provider": "openalex",
                "provider_id": "W_review",
                "source_rank": "1",
                "screening_decision": "include",
                "screening_confidence": "high",
                "screening_reason": "Relevant review.",
                "title_relevance_tier": "0",
            },
            {
                "paper_id": "paper_protocol",
                "title": "Trial protocol for a mobile health app",
                "year": "2024",
                "doi": "10.123/protocol",
                "provider": "openalex",
                "provider_id": "W_protocol",
                "source_rank": "2",
                "screening_decision": "include",
                "screening_confidence": "high",
                "screening_reason": "Relevant protocol.",
                "title_relevance_tier": "0",
            },
            {
                "paper_id": "paper_primary",
                "title": "Randomized trial of a mobile health app",
                "year": "2024",
                "doi": "10.123/primary",
                "provider": "openalex",
                "provider_id": "W_primary",
                "source_rank": "3",
                "screening_decision": "include",
                "screening_confidence": "high",
                "screening_reason": "Relevant primary study.",
                "title_relevance_tier": "0",
            },
        ],
        fieldnames,
    )

    result = run_select_calibration_papers(
        candidates_path,
        screening_path,
        output_path,
        max_papers=2,
    )

    rows = read_csv(output_path)
    assert [row["paper_id"] for row in rows] == ["paper_primary"]
    assert rows[0]["scope_decision"] == "include"
    assert result.row_counts["selected_calibration_papers"] == 1
    assert result.row_counts["skipped_review_candidates"] == 1
    assert result.row_counts["skipped_non_primary_candidates"] == 1


def test_audit_extraction_writes_expected_issues(tmp_path: Path) -> None:
    extraction_path = tmp_path / "extraction.csv"
    config_path = tmp_path / "config.json"
    rules_path = tmp_path / "rules.json"
    output_path = tmp_path / "audit.csv"

    write_csv(
        extraction_path,
        [{"paper_id": "p1", "target": "ad; invalid", "review_status": ""}],
        ["paper_id", "target", "review_status"],
    )
    write_json(
        config_path,
        {
            "categories": [
                {
                    "category_id": "target",
                    "allowed_values": [{"value": "ad"}, {"value": "mci"}],
                },
                {
                    "category_id": "review_status",
                    "allowed_values": [{"value": "ai_tagged"}],
                },
            ]
        },
    )
    write_json(
        rules_path,
        {
            "rules": [
                {"category_id": "target", "selection": "single", "required": True},
                {
                    "category_id": "review_status",
                    "selection": "single",
                    "required": True,
                },
            ]
        },
    )

    run_script(
        "scripts/audit_extraction.py",
        "--input",
        str(extraction_path),
        "--config",
        str(config_path),
        "--rules",
        str(rules_path),
        "--output",
        str(output_path),
    )

    rows = read_csv(output_path)
    assert rows == [
        {
            "paper_id": "p1",
            "field": "target",
            "value": "invalid",
            "issue": "invalid_value",
        },
        {
            "paper_id": "p1",
            "field": "target",
            "value": "ad; invalid",
            "issue": "single_selection_has_multiple_values",
        },
        {
            "paper_id": "p1",
            "field": "review_status",
            "value": "",
            "issue": "required_missing",
        },
    ]


def test_audit_extraction_flags_dominant_value_distribution(tmp_path: Path) -> None:
    extraction_path = tmp_path / "extraction.csv"
    config_path = tmp_path / "config.json"
    rules_path = tmp_path / "rules.json"
    output_path = tmp_path / "audit.csv"

    rows = [
        {"paper_id": f"p{index}", "data_source": "clinical_trials"}
        for index in range(1, 6)
    ]
    write_csv(extraction_path, rows, ["paper_id", "data_source"])
    write_json(
        config_path,
        {
            "categories": [
                {
                    "category_id": "data_source",
                    "allowed_values": [
                        {"value": "clinical_trials"},
                        {"value": "surveys"},
                        {"value": "interviews"},
                    ],
                }
            ]
        },
    )
    write_json(
        rules_path,
        {
            "rules": [
                {
                    "category_id": "data_source",
                    "selection": "single",
                    "required": True,
                },
            ]
        },
    )

    run_script(
        "scripts/audit_extraction.py",
        "--input",
        str(extraction_path),
        "--config",
        str(config_path),
        "--rules",
        str(rules_path),
        "--output",
        str(output_path),
    )

    audit_rows = read_csv(output_path)
    assert audit_rows == [
        {
            "paper_id": "",
            "field": "data_source",
            "value": "surveys",
            "issue": "unused_value_distribution_warning:0_of_5_applicable_rows",
        },
        {
            "paper_id": "",
            "field": "data_source",
            "value": "interviews",
            "issue": "unused_value_distribution_warning:0_of_5_applicable_rows",
        },
        {
            "paper_id": "",
            "field": "data_source",
            "value": "clinical_trials",
            "issue": "dominant_value_distribution_warning:5_of_5_applicable_rows",
        }
    ]


def test_audit_extraction_respects_conditional_required_categories(
    tmp_path: Path,
) -> None:
    extraction_path = tmp_path / "extraction.csv"
    config_path = tmp_path / "config.json"
    rules_path = tmp_path / "rules.json"
    output_path = tmp_path / "audit.csv"

    write_csv(
        extraction_path,
        [
            {
                "paper_id": "p1",
                "research_focus": "screening_detection",
                "screening_tool_type": "",
            },
            {
                "paper_id": "p2",
                "research_focus": "treatment_effectiveness",
                "screening_tool_type": "",
            },
        ],
        ["paper_id", "research_focus", "screening_tool_type"],
    )
    write_json(
        config_path,
        {
            "categories": [
                {
                    "category_id": "research_focus",
                    "allowed_values": [
                        {"value": "screening_detection"},
                        {"value": "treatment_effectiveness"},
                    ],
                },
                {
                    "category_id": "screening_tool_type",
                    "allowed_values": [
                        {"value": "symptom_scale"},
                        {"value": "risk_model"},
                    ],
                    "applies_when": {
                        "category_id": "research_focus",
                        "values": ["screening_detection"],
                    },
                },
            ]
        },
    )
    write_json(
        rules_path,
        {
            "rules": [
                {
                    "category_id": "research_focus",
                    "selection": "single",
                    "required": True,
                },
                {
                    "category_id": "screening_tool_type",
                    "selection": "single",
                    "required": True,
                    "applies_when": {
                        "category_id": "research_focus",
                        "values": ["screening_detection"],
                    },
                },
            ]
        },
    )

    run_script(
        "scripts/audit_extraction.py",
        "--input",
        str(extraction_path),
        "--config",
        str(config_path),
        "--rules",
        str(rules_path),
        "--output",
        str(output_path),
    )

    audit_rows = read_csv(output_path)
    assert audit_rows == [
        {
            "paper_id": "p1",
            "field": "screening_tool_type",
            "value": "",
            "issue": "required_missing",
        }
    ]


def test_audit_extraction_reports_distribution_warnings(
    tmp_path: Path,
) -> None:
    extraction_path = tmp_path / "extraction.csv"
    config_path = tmp_path / "config.json"
    rules_path = tmp_path / "rules.json"
    output_path = tmp_path / "audit.csv"

    rows = [
        {"paper_id": f"p{index}", "research_focus": "treatment_effectiveness"}
        for index in range(1, 7)
    ]
    write_csv(extraction_path, rows, ["paper_id", "research_focus"])
    write_json(
        config_path,
        {
            "categories": [
                {
                    "category_id": "research_focus",
                    "allowed_values": [
                        {"value": "treatment_effectiveness"},
                        {"value": "screening_detection"},
                        {"value": "engagement_acceptability"},
                    ],
                }
            ]
        },
    )
    write_json(
        rules_path,
        {
            "rules": [
                {
                    "category_id": "research_focus",
                    "selection": "single",
                    "required": True,
                    "fallback_value": None,
                },
            ]
        },
    )

    run_script(
        "scripts/audit_extraction.py",
        "--input",
        str(extraction_path),
        "--config",
        str(config_path),
        "--rules",
        str(rules_path),
        "--output",
        str(output_path),
    )

    audit_rows = read_csv(output_path)
    assert {
        "paper_id": "",
        "field": "research_focus",
        "value": "screening_detection",
        "issue": "unused_value_distribution_warning:0_of_6_applicable_rows",
    } in audit_rows
    assert {
        "paper_id": "",
        "field": "research_focus",
        "value": "treatment_effectiveness",
        "issue": (
            "dominant_value_distribution_warning:6_of_6_applicable_rows"
        ),
    } in audit_rows


def test_export_mantis_ready_filters_to_core_and_adjacent_topics(tmp_path: Path) -> None:
    extraction_path = tmp_path / "extraction.csv"
    output_path = tmp_path / "mantis.csv"
    write_csv(
        extraction_path,
        [
            {
                "paper_id": "p1",
                "title": "Detection Study",
                "year": "2024",
                "doi": "10.123/example",
                "main_knowledge_claim": "The paper detects early AD.",
                "main_topic_category": "core_topic",
                "research_target": "mci",
                "review_status": "ai_tagged",
            },
            {
                "paper_id": "p2",
                "title": "Adjacent Study",
                "year": "2023",
                "doi": "",
                "main_knowledge_claim": "The paper is adjacent but useful.",
                "main_topic_category": "adjacent_but_relevant",
                "research_target": "dementia",
                "review_status": "ai_tagged",
            },
            {
                "paper_id": "p3",
                "title": "Weak Study",
                "year": "2022",
                "doi": "",
                "main_knowledge_claim": "The paper is not close enough.",
                "main_topic_category": "out_of_scope",
                "research_target": "unclear",
                "review_status": "ai_tagged",
            }
        ],
        [
            "paper_id",
            "title",
            "year",
            "doi",
            "main_knowledge_claim",
            "main_topic_category",
            "research_target",
            "review_status",
        ],
    )

    result = run_script(
        "scripts/export_mantis_ready.py",
        "--input",
        str(extraction_path),
        "--output",
        str(output_path),
    )

    rows = read_csv(output_path)
    assert len(rows) == 2
    assert rows[0]["title"] == "Detection Study"
    assert rows[0]["categoric"] == "core_topic"
    assert rows[0]["semantic"] == "The paper detects early AD."
    assert rows[0]["review_status"] == "ai_tagged"
    assert rows[1]["title"] == "Adjacent Study"
    assert rows[1]["categoric"] == "adjacent_but_relevant"
    assert "Exported 2 Mantis rows" in result.stdout


def test_audit_and_mantis_preserve_but_do_not_publish_untaggable_rows(
    tmp_path: Path,
) -> None:
    extraction_path = tmp_path / "extraction.csv"
    config_path = tmp_path / "config.json"
    rules_path = tmp_path / "rules.json"
    audit_path = tmp_path / "audit.csv"
    mantis_path = tmp_path / "mantis.csv"
    write_csv(
        extraction_path,
        [
            {
                "paper_id": "p1",
                "title": "Evidence-backed study",
                "year": "2024",
                "doi": "10.123/evidence",
                "tagging_status": "tagged",
                "tagging_evidence_basis": "abstract",
                "tagging_error": "",
                "main_knowledge_claim": "The abstract reports a result.",
                "review_status": "ai_tagged",
            },
            {
                "paper_id": "p2",
                "title": "Title-only paper",
                "year": "2023",
                "doi": "10.123/title-only",
                "tagging_status": "skipped_insufficient_evidence",
                "tagging_evidence_basis": "none",
                "tagging_error": (
                    "no usable abstract or extracted full text is available "
                    "(full_text_status=extraction_failed)"
                ),
                "main_knowledge_claim": "",
                "review_status": "",
            },
        ],
        [
            "paper_id",
            "title",
            "year",
            "doi",
            "tagging_status",
            "tagging_evidence_basis",
            "tagging_error",
            "main_knowledge_claim",
            "review_status",
        ],
    )
    write_json(
        config_path,
        {
            "categories": [
                {
                    "category_id": "review_status",
                    "allowed_values": [{"value": "ai_tagged"}],
                }
            ]
        },
    )
    write_json(
        rules_path,
        {
            "rules": [
                {
                    "category_id": "review_status",
                    "selection": "single",
                    "required": True,
                }
            ]
        },
    )

    audit_result = run_audit_extraction(
        extraction_path,
        config_path,
        rules_path,
        audit_path,
    )
    mantis_result = run_export_mantis(extraction_path, mantis_path)

    assert read_csv(audit_path) == [
        {
            "paper_id": "p2",
            "field": "tagging_evidence_basis",
            "value": "none",
            "issue": "tagging_skipped_insufficient_evidence",
        }
    ]
    assert audit_result.row_counts == {"rows_audited": 2, "issues_found": 1}
    assert [row["paper_id"] for row in read_csv(mantis_path)] == ["p1"]
    assert mantis_result.row_counts == {
        "input_rows": 2,
        "mantis_rows": 1,
        "skipped_not_mantis_relevant": 1,
    }


def test_audit_rejects_inconsistent_tagging_state_rows(tmp_path: Path) -> None:
    extraction_path = tmp_path / "extraction.csv"
    config_path = tmp_path / "config.json"
    rules_path = tmp_path / "rules.json"
    audit_path = tmp_path / "audit.csv"
    write_csv(
        extraction_path,
        [
            {
                "paper_id": "tagged_without_evidence",
                "tagging_status": "tagged",
                "tagging_evidence_basis": "none",
                "tagging_error": "",
                "main_knowledge_claim": "A stale claim.",
                "review_status": "ai_tagged",
            },
            {
                "paper_id": "skipped_with_stale_tags",
                "tagging_status": "skipped_insufficient_evidence",
                "tagging_evidence_basis": "none",
                "tagging_error": "Insufficient evidence.",
                "main_knowledge_claim": "Must not survive.",
                "review_status": "ai_tagged",
            },
            {
                "paper_id": "failed_without_error",
                "tagging_status": "failed",
                "tagging_evidence_basis": "abstract",
                "tagging_error": "",
                "main_knowledge_claim": "",
                "review_status": "",
            },
        ],
        [
            "paper_id",
            "tagging_status",
            "tagging_evidence_basis",
            "tagging_error",
            "main_knowledge_claim",
            "review_status",
        ],
    )
    write_json(
        config_path,
        {
            "categories": [
                {
                    "category_id": "review_status",
                    "allowed_values": [{"value": "ai_tagged"}],
                }
            ]
        },
    )
    write_json(
        rules_path,
        {
            "rules": [
                {
                    "category_id": "review_status",
                    "selection": "single",
                    "required": True,
                }
            ]
        },
    )

    run_audit_extraction(
        extraction_path,
        config_path,
        rules_path,
        audit_path,
    )

    issues = {
        (row["paper_id"], row["field"], row["issue"])
        for row in read_csv(audit_path)
    }
    assert (
        "tagged_without_evidence",
        "tagging_evidence_basis",
        "tagged_without_usable_evidence",
    ) in issues
    assert (
        "skipped_with_stale_tags",
        "main_knowledge_claim",
        "non_tagged_row_has_stale_extraction",
    ) in issues
    assert (
        "skipped_with_stale_tags",
        "review_status",
        "non_tagged_row_has_stale_extraction",
    ) in issues
    assert (
        "failed_without_error",
        "tagging_error",
        "non_tagged_row_missing_error",
    ) in issues
    assert (
        "failed_without_error",
        "tagging_evidence_basis",
        "tagging_failed",
    ) in issues


def test_mantis_export_fails_when_all_new_schema_rows_are_ineligible(
    tmp_path: Path,
) -> None:
    extraction_path = tmp_path / "extraction.csv"
    output_path = tmp_path / "mantis.csv"
    write_csv(
        extraction_path,
        [
            {
                "paper_id": "p1",
                "title": "Title-only paper",
                "tagging_status": "skipped_insufficient_evidence",
                "tagging_evidence_basis": "none",
                "tagging_error": "No usable evidence.",
                "main_knowledge_claim": "",
                "review_status": "",
            }
        ],
        [
            "paper_id",
            "title",
            "tagging_status",
            "tagging_evidence_basis",
            "tagging_error",
            "main_knowledge_claim",
            "review_status",
        ],
    )

    with pytest.raises(ValueError, match="No evidence-backed tagged rows"):
        run_export_mantis(extraction_path, output_path)

    assert not output_path.exists()
