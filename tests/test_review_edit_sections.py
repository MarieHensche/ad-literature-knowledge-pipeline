from __future__ import annotations

import json
from pathlib import Path

from ad_lit_pipeline.llm.client import StaticJSONClient
from ad_lit_pipeline.steps.review.edit_sections import run


def evidence_map_payload() -> dict[str, object]:
    return {
        "research_topic": {"title": "Early AD detection"},
        "overview": {
            "review_type": "narrative",
            "paper_count": 1,
            "usable_paper_count": 1,
        },
        "quality": {"issue_count": 0},
        "papers": [
            {
                "paper_id": "p1",
                "title": "Paper one",
                "year": "2024",
                "doi": "10.123/one",
                "authors": "Smith",
                "venue": "Journal",
            }
        ],
        "sections": [
            {
                "section_id": "review_methodology",
                "paper_ids": ["p1"],
                "controlled_value_counts": {},
                "text_evidence": {},
                "quotes": [],
            },
            {
                "section_id": "conclusion",
                "paper_ids": ["p1"],
                "controlled_value_counts": {},
                "text_evidence": {},
                "quotes": [],
            }
        ],
    }


def draft_sections_payload() -> dict[str, object]:
    return {
        "research_topic": {"title": "Early AD detection"},
        "overview": {"usable_paper_count": 1},
        "papers": [
            {
                "paper_id": "p1",
                "title": "Paper one",
                "year": "2024",
                "doi": "10.123/one",
                "authors": "Smith",
                "venue": "Journal",
            }
        ],
        "sections": [
            {
                "section_id": "review_methodology",
                "title": "Review Methodology",
                "summary": "",
                "body_markdown": "The review used one paper (Smith, 2024).",
                "key_points": [],
                "methodological_patterns": [],
                "limitations_or_gaps": [],
                "citation_support": [
                    {"paper_id": "p1", "claim": "The review used one paper."}
                ],
                "cited_paper_ids": ["p1"],
                "quote_uses": [],
            },
            {
                "section_id": "conclusion",
                "title": "Conclusion",
                "summary": "",
                "body_markdown": "The evidence base was small (Smith, 2024).",
                "key_points": [],
                "methodological_patterns": [],
                "limitations_or_gaps": [],
                "citation_support": [
                    {"paper_id": "p1", "claim": "The evidence base was small."}
                ],
                "cited_paper_ids": ["p1"],
                "quote_uses": [],
            }
        ],
    }


def edited_section_payload(
    paper_id: str = "p1",
    section_id: str = "review_methodology",
) -> dict[str, object]:
    return {
        "sections": [
            {
                "section_id": section_id,
                "title": section_id.replace("_", " ").title(),
                "summary": "The evidence base was small.",
                "body_markdown": "The narrative review used one paper (Smith, 2024).",
                "key_points": ["One paper was used."],
                "methodological_patterns": [],
                "limitations_or_gaps": ["The evidence base was small."],
                "citation_support": [
                    {"paper_id": paper_id, "claim": "The review used one paper."}
                ],
                "cited_paper_ids": [paper_id],
                "quote_uses": [],
            }
        ]
    }


def edited_section_payload_with_extra_section() -> dict[str, object]:
    payload = edited_section_payload(section_id="review_methodology")
    payload["sections"].append(
        {
            "section_id": "methodology",
            "title": "Methodology",
            "summary": "Unrequested section.",
            "body_markdown": "This section was not requested.",
            "key_points": [],
            "methodological_patterns": [],
            "limitations_or_gaps": [],
            "citation_support": [],
            "cited_paper_ids": [],
            "quote_uses": [],
        }
    )
    return payload


def write_json(path: Path, payload: dict[str, object]) -> None:
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def test_edit_review_sections_writes_validated_sections(tmp_path: Path) -> None:
    evidence_path = tmp_path / "evidence.json"
    sections_path = tmp_path / "sections.json"
    output_path = tmp_path / "edited.json"
    write_json(evidence_path, evidence_map_payload())
    write_json(sections_path, draft_sections_payload())
    client = StaticJSONClient(
        [
            edited_section_payload(section_id="review_methodology"),
            edited_section_payload(section_id="conclusion"),
        ]
    )

    result = run(
        evidence_path,
        sections_path,
        output_path,
        "test-model",
        client=client,
        trace_dir=tmp_path / "traces",
    )
    payload = json.loads(output_path.read_text(encoding="utf-8"))

    assert result.row_counts["review_sections"] == 2
    assert result.trace_paths
    assert client.requests[0]["schema_name"] == "review_sections"
    assert client.requests[0]["call_id"] == "edit_review_methodology"
    assert client.requests[1]["call_id"] == "edit_conclusion"
    assert "Do not invent or alter author names" in client.requests[0]["prompt"]
    assert payload["sections"][0]["summary"] == "The evidence base was small."
    assert payload["sections"][1]["section_id"] == "conclusion"
    assert payload["source_review_sections"] == str(sections_path)


def test_edit_review_sections_drops_unknown_paper_id(tmp_path: Path) -> None:
    evidence_path = tmp_path / "evidence.json"
    sections_path = tmp_path / "sections.json"
    output_path = tmp_path / "edited.json"
    write_json(evidence_path, evidence_map_payload())
    write_json(sections_path, draft_sections_payload())
    client = StaticJSONClient(
        [edited_section_payload("p2"), edited_section_payload(section_id="conclusion")]
    )

    result = run(evidence_path, sections_path, output_path, "test-model", client=client)
    payload = json.loads(output_path.read_text(encoding="utf-8"))

    assert payload["sections"][0]["citation_support"] == []
    assert payload["sections"][0]["cited_paper_ids"] == []
    assert any(
        "Dropped citation_support item" in warning for warning in result.warnings
    )


def test_edit_review_sections_drops_extra_section_ids(tmp_path: Path) -> None:
    evidence_path = tmp_path / "evidence.json"
    sections_path = tmp_path / "sections.json"
    output_path = tmp_path / "edited.json"
    write_json(evidence_path, evidence_map_payload())
    write_json(sections_path, draft_sections_payload())
    client = StaticJSONClient(
        [
            edited_section_payload_with_extra_section(),
            edited_section_payload(section_id="conclusion"),
        ]
    )

    result = run(evidence_path, sections_path, output_path, "test-model", client=client)
    payload = json.loads(output_path.read_text(encoding="utf-8"))

    assert [section["section_id"] for section in payload["sections"]] == [
        "review_methodology",
        "conclusion",
    ]
    assert any(
        "Dropped extra edited review section ids" in warning
        for warning in result.warnings
    )
