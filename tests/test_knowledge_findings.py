from __future__ import annotations

from pathlib import Path

from ad_lit_pipeline.io.jsonl_io import read_jsonl_objects, write_jsonl
from ad_lit_pipeline.llm.client import StaticJSONClient
from ad_lit_pipeline.steps.knowledge.extract_findings import (
    extract_findings_for_source,
    ordered_topic_ids,
    run,
)


ROOT = Path(__file__).resolve().parents[1]
TOPIC_CONTRACT = ROOT / "configs/topics/early_detection_ad.yaml"


def source_record() -> dict[str, object]:
    return {
        "source_id": "paper_1",
        "title": "Example early detection study",
        "year": "2024",
        "doi": "10.123/example",
        "url": "https://example.org/paper",
        "abstract": "This paper reports an example result.",
        "authors": "Example Author",
        "venue": "Example Journal",
        "provider": "openalex",
        "provider_id": "W123",
        "source_type": "primary_study",
        "collection_provenance": {"query": "early detection"},
        "full_text_status": "available",
    }


def excerpt_record() -> dict[str, object]:
    return {
        "excerpt_id": "excerpt_1",
        "source_id": "paper_1",
        "text": "The method increased detection accuracy in the evaluated cohort.",
        "section": "results",
        "location": "Results",
        "extraction_method": "full_text_section_priority",
    }


def finding_response(
    *,
    evidence_excerpt_ids: list[str] | None = None,
) -> dict[str, object]:
    return {
        "findings": [
            {
                "claim_text": (
                    "The method increased detection accuracy in the evaluated cohort."
                ),
                "finding_type": "positive",
                "topic_ids": ["early_detection"],
                "method": "example_method",
                "outcome": "detection_accuracy",
                "study_context": "evaluated cohort",
                "direction": "increases",
                "evidence_excerpt_ids": evidence_excerpt_ids or ["excerpt_1"],
                "limitations": ["single source extraction"],
                "extraction_confidence": "high",
                "evidence_strength": "medium",
                "extraction_status": "extracted",
            }
        ]
    }


def test_ordered_topic_ids_includes_main_and_secondary_topics() -> None:
    topic_contract = {
        "topic_id": "topic_root",
        "topic_structure": {
            "anchor_topic_id": "main_a",
            "main_topics": [{"topic_id": "main_a"}, {"topic_id": "main_b"}],
            "secondary_topics": {
                "main_a": [{"secondary_topic_id": "secondary_a"}],
            },
        },
    }

    assert ordered_topic_ids(topic_contract) == [
        "topic_root",
        "main_a",
        "main_b",
        "secondary_a",
    ]


def test_extract_findings_for_source_validates_and_adds_stable_ids() -> None:
    topic_contract = {
        "research_topic": {"title": "Example"},
        "topic_structure": {
            "main_topics": [{"topic_id": "early_detection"}],
        },
    }
    client = StaticJSONClient([finding_response()])

    findings, trace_paths = extract_findings_for_source(
        source_record(),
        [excerpt_record()],
        topic_contract,
        "test-model",
        client,
    )

    assert trace_paths == []
    assert len(findings) == 1
    assert findings[0]["source_id"] == "paper_1"
    assert findings[0]["finding_id"].startswith("paper_1_finding_001_")
    assert findings[0]["evidence_excerpt_ids"] == ["excerpt_1"]
    assert client.requests[0]["schema_name"] == "knowledge_findings"
    assert "excerpt_1" in client.requests[0]["prompt"]


def test_run_writes_findings_jsonl(tmp_path: Path) -> None:
    sources_path = tmp_path / "sources.jsonl"
    excerpts_path = tmp_path / "evidence_excerpts.jsonl"
    output_path = tmp_path / "findings.jsonl"
    client = StaticJSONClient([finding_response()])

    write_jsonl(sources_path, [source_record()])
    write_jsonl(excerpts_path, [excerpt_record()])

    result = run(
        sources_path,
        excerpts_path,
        output_path,
        TOPIC_CONTRACT,
        "test-model",
        client=client,
    )
    findings = read_jsonl_objects(output_path)

    assert result.row_counts["sources"] == 1
    assert result.row_counts["sources_with_evidence"] == 1
    assert result.row_counts["findings"] == 1
    assert result.warnings == []
    assert findings[0]["topic_ids"] == ["early_detection"]


def test_run_warns_and_skips_invalid_evidence_links(tmp_path: Path) -> None:
    sources_path = tmp_path / "sources.jsonl"
    excerpts_path = tmp_path / "evidence_excerpts.jsonl"
    output_path = tmp_path / "findings.jsonl"
    client = StaticJSONClient(
        [finding_response(evidence_excerpt_ids=["missing_excerpt"])]
    )

    write_jsonl(sources_path, [source_record()])
    write_jsonl(excerpts_path, [excerpt_record()])

    result = run(
        sources_path,
        excerpts_path,
        output_path,
        TOPIC_CONTRACT,
        "test-model",
        client=client,
    )

    assert read_jsonl_objects(output_path) == []
    assert result.row_counts["findings"] == 0
    assert "unknown excerpt IDs: missing_excerpt" in result.warnings[0]


def test_run_warns_without_calling_llm_when_source_has_no_excerpts(
    tmp_path: Path,
) -> None:
    sources_path = tmp_path / "sources.jsonl"
    excerpts_path = tmp_path / "evidence_excerpts.jsonl"
    output_path = tmp_path / "findings.jsonl"
    client = StaticJSONClient([])

    write_jsonl(sources_path, [source_record()])
    write_jsonl(excerpts_path, [])

    result = run(
        sources_path,
        excerpts_path,
        output_path,
        TOPIC_CONTRACT,
        "test-model",
        client=client,
    )

    assert read_jsonl_objects(output_path) == []
    assert result.row_counts["sources_with_evidence"] == 0
    assert result.warnings == ["Skipped source 'paper_1': no evidence excerpts."]
    assert client.requests == []
