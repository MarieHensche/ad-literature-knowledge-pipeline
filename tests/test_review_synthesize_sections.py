from __future__ import annotations

import json
from pathlib import Path

import pytest

from ad_lit_pipeline.llm.client import StaticJSONClient
from ad_lit_pipeline.steps.review.synthesize_sections import run


def write_evidence_map(path: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "research_topic": {"title": "Early AD detection"},
                "overview": {
                    "review_type": "narrative",
                    "paper_count": 1,
                    "usable_paper_count": 1,
                    "year_range": [2024, 2024],
                    "method_hierarchy_hints": [
                        {
                            "parent_value": "machine_learning",
                            "child_value": "deep_learning",
                        }
                    ],
                },
                "scope": {"include_criteria": ["Include relevant papers."]},
                "collection": {"preferred_provider": "openalex"},
                "quality": {"issue_count": 0, "issue_counts": {}},
                "papers": [
                    {
                        "paper_id": "p1",
                        "title": "Paper one",
                        "year": "2024",
                        "doi": "10.123/one",
                        "authors": "Smith",
                        "citation_key": "Smith (2024)",
                    }
                ],
                "sections": [
                    {
                        "section_id": "early_detection",
                        "label": "Early detection",
                        "paper_count": 1,
                        "paper_ids": ["p1"],
                        "controlled_value_counts": {
                            "methodology": [
                                {
                                    "value": "mri_classification",
                                    "label": "mri classification",
                                    "paper_count": 1,
                                }
                            ]
                        },
                        "text_evidence": {
                            "key_finding": [
                                {
                                    "paper_id": "p1",
                                    "citation_key": "Smith (2024)",
                                    "text": "MRI models improved early detection.",
                                    "label_id": "key_finding",
                                }
                            ]
                        },
                        "quotes": [
                            {
                                "paper_id": "p1",
                                "citation_key": "Smith (2024)",
                                "label_id": "direct_quote",
                                "quote": "classification improved",
                                "section": "Results",
                                "reason": "supports finding",
                            }
                        ],
                    }
                ],
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def section_payload(paper_id: str = "p1") -> dict[str, object]:
    return {
        "section_id": "early_detection",
        "title": "Early detection",
        "summary": "MRI classification evidence suggests improved detection.",
        "body_markdown": (
            "MRI classification models improved early detection in the included "
            "evidence (Smith, 2024)."
        ),
        "key_points": ["MRI classification was the central method."],
        "methodological_patterns": ["One paper used MRI classification."],
        "limitations_or_gaps": ["The evidence base is thin."],
        "citation_support": [
            {
                "paper_id": paper_id,
                "claim": "MRI classification improved early detection.",
            }
        ],
        "cited_paper_ids": [paper_id],
        "quote_uses": [
            {
                "paper_id": paper_id,
                "quote": "classification improved",
                "reason": "supports finding",
            }
        ],
    }


def test_synthesize_review_sections_writes_grounded_sections(
    tmp_path: Path,
) -> None:
    evidence_path = tmp_path / "review_evidence_map.json"
    output_path = tmp_path / "review_sections.json"
    write_evidence_map(evidence_path)
    client = StaticJSONClient([section_payload()])

    result = run(
        evidence_path,
        output_path,
        "test-model",
        client=client,
        trace_dir=tmp_path / "traces",
    )
    payload = json.loads(output_path.read_text(encoding="utf-8"))

    assert result.row_counts["review_evidence_sections"] == 1
    assert result.row_counts["review_sections"] == 1
    assert result.trace_paths
    assert client.requests[0]["call_id"] == "early_detection"
    assert client.requests[0]["schema_name"] == "review_section"
    assert "Do not directly compare or rank performance scores" in client.requests[0][
        "prompt"
    ]
    assert "method_hierarchy_hints" in client.requests[0]["prompt"]
    assert payload["source_evidence_map"] == str(evidence_path)
    assert payload["overview"]["review_type"] == "narrative"
    assert payload["collection"]["preferred_provider"] == "openalex"
    assert payload["quality"]["issue_count"] == 0
    assert payload["sections"][0]["section_id"] == "early_detection"
    assert payload["sections"][0]["cited_paper_ids"] == ["p1"]
    assert payload["sections"][0]["citation_support"][0]["paper_id"] == "p1"
    assert payload["papers"][0]["harvard_inline"] == "(Smith, 2024)"
    assert payload["papers"][0]["paper_id"] == "p1"


def test_synthesize_review_sections_rejects_unknown_citation_paper(
    tmp_path: Path,
) -> None:
    evidence_path = tmp_path / "review_evidence_map.json"
    output_path = tmp_path / "review_sections.json"
    write_evidence_map(evidence_path)
    client = StaticJSONClient([section_payload("p2")])

    with pytest.raises(ValueError, match="not present in section"):
        run(evidence_path, output_path, "test-model", client=client)


def test_synthesize_review_sections_repairs_unambiguous_paper_id_typo(
    tmp_path: Path,
) -> None:
    evidence_path = tmp_path / "review_evidence_map.json"
    output_path = tmp_path / "review_sections.json"
    write_evidence_map(evidence_path)
    payload = section_payload("10_1148_radiol_2016180958")
    payload["cited_paper_ids"] = ["10_1148_radiol_2016180958"]
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    evidence["papers"][0]["paper_id"] = "10_1148_radiol_2018180958"
    evidence["sections"][0]["paper_ids"] = ["10_1148_radiol_2018180958"]
    evidence_path.write_text(json.dumps(evidence), encoding="utf-8")
    client = StaticJSONClient([payload])

    result = run(evidence_path, output_path, "test-model", client=client)
    output = json.loads(output_path.read_text(encoding="utf-8"))

    assert result.row_counts["review_sections"] == 1
    assert output["sections"][0]["cited_paper_ids"] == [
        "10_1148_radiol_2018180958"
    ]
    assert output["sections"][0]["citation_support"][0]["paper_id"] == (
        "10_1148_radiol_2018180958"
    )
