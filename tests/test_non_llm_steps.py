from __future__ import annotations

import csv
import json
import subprocess
import sys
from pathlib import Path

from ad_lit_pipeline.io.jsonl_io import read_jsonl_objects, write_jsonl
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
from ad_lit_pipeline.steps.full_text.prepare import FullTextResult
from ad_lit_pipeline.steps.full_text.evidence import build_knowledge_evidence
from ad_lit_pipeline.steps.full_text.prepare import run as run_prepare_full_text
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
            "notes",
            "abstract_available",
            "full_text_available",
            "metadata_notes",
            "scope_decision",
            "scope_reason",
            "scope_matched_include_terms",
            "scope_matched_exclude_terms",
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
    assert text_path.exists()
    assert manifest_rows[0]["paper_id"] == "p1"
    assert int(manifest_rows[0]["full_text_chars"]) >= 1000


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
    assert rows[0]["full_text_url"] == "https://example.org/full-text"
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
        + "<p>Postpartum digital mental health intervention evidence.</p>" * 40
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


def test_candidate_topic_matches_record_values_and_fields() -> None:
    contract = load_topic_contract(ROOT / "configs/topics/ai_in_education.yaml")
    for topic in contract["topic_structure"]["main_topics"]:
        topic["field"] = "title_or_abstract"
        if topic["topic_id"] == "ai":
            topic["retrieval_terms"] = ["deep learning"]

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
        "dedupe_key": "doi:10.123/example",
        "duplicate_count": 1,
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
    assert rows == [
        {
            "paper_id": "paper_1",
            "title": "Detection Study",
            "year": "2024",
            "doi": "10.123/example",
            "abstract": "Early detection abstract.",
            "authors": "A. Author",
            "venue": "Journal",
            "url": "https://example.test",
            "source": "collected:openalex",
            "full_text_path": "",
            "notes": (
                "provider=openalex; provider_id=W1; source_rank=1; "
                "retrieval_date=2026-05-25; screening_confidence=high; "
                "screening_reason=Directly relevant.; title_anchor_present=yes; "
                "title_relevance_tier=0; "
                "title_matched_main_topics=early_detection; disease_state; "
                "dedupe_key=doi:10.123/example; "
                "duplicate_count=1; "
                "topic_main_matches=disease_state=Alzheimer@abstract, "
                "early_detection=early detection@title; "
                "topic_secondary_matches=evidence_signal=biomarker@abstract"
            ),
        }
    ]


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
