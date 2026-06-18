from __future__ import annotations

import json
from pathlib import Path

from ad_lit_pipeline.steps.review.assemble_review import run


def write_sections(path: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "research_topic": {"title": "Early AD detection"},
                "overview": {
                    "paper_count": 2,
                    "usable_paper_count": 2,
                    "year_range": [2021, 2024],
                },
                "sections": [
                    {
                        "section_id": "early_detection",
                        "title": "Early detection",
                        "summary": "MRI classification evidence was prominent.",
                        "body_markdown": (
                            "MRI classification models improved early detection "
                            "in the included evidence [p1]."
                        ),
                        "key_points": ["MRI classification was central."],
                        "methodological_patterns": [
                            "The section was dominated by imaging methods."
                        ],
                        "limitations_or_gaps": ["The evidence base was small."],
                        "citation_support": [
                            {
                                "paper_id": "p1",
                                "claim": "MRI classification improved detection.",
                            }
                        ],
                        "quote_uses": [],
                    }
                ],
                "papers": [
                    {
                        "paper_id": "p1",
                        "title": "Paper one",
                        "year": "2024",
                        "doi": "10.123/one",
                        "authors": "Smith; Jones",
                        "venue": "Journal",
                    },
                    {
                        "paper_id": "p2",
                        "title": "Uncited paper",
                        "year": "2021",
                        "doi": "10.123/two",
                        "authors": "Doe",
                        "venue": "Conference",
                    },
                ],
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def test_assemble_literature_review_markdown(
    tmp_path: Path,
) -> None:
    sections_path = tmp_path / "review_sections.json"
    output_path = tmp_path / "literature_review.md"
    write_sections(sections_path)

    result = run(sections_path, output_path)
    markdown = output_path.read_text(encoding="utf-8")

    assert result.row_counts["review_sections"] == 1
    assert result.row_counts["review_references"] == 1
    assert markdown.startswith("# Early AD detection")
    assert "This review summarizes evidence from 2 papers." in markdown
    assert "The included evidence spans 2021 to 2024." in markdown
    assert "## Early detection" in markdown
    assert "MRI classification models improved early detection" in markdown
    assert "**Key points**" in markdown
    assert "- MRI classification was central." in markdown
    assert "## References" in markdown
    assert "[p1] Smith and Jones (2024). Paper one." in markdown
    assert "DOI: 10.123/one" in markdown
    assert "Uncited paper" not in markdown
