from __future__ import annotations

import json
from pathlib import Path

import pytest

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
                            "in the included evidence (Smith and Jones, 2024) [p1]."
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
                        "cited_paper_ids": ["p1"],
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
                        "doi": "",
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
    latex_dir = tmp_path / "literature_review_latex"
    write_sections(sections_path)

    result = run(sections_path, output_path, latex_dir)
    markdown = output_path.read_text(encoding="utf-8")
    latex = (latex_dir / "main.tex").read_text(encoding="utf-8")
    bib = (latex_dir / "references.bib").read_text(encoding="utf-8")
    cls = (latex_dir / "MITcsail.cls").read_text(encoding="utf-8")

    assert result.row_counts["review_sections"] == 1
    assert result.row_counts["review_references"] == 1
    assert result.row_counts["review_cited_papers"] == 1
    assert result.row_counts["citation_eligible_papers"] == 1
    assert result.row_counts["minimum_cited_papers"] == 1
    assert result.row_counts["latex_files"] == 3
    assert markdown.startswith("# Early AD detection")
    assert (
        "This narrative literature review summarizes evidence from 2 papers."
        in markdown
    )
    assert "The included evidence spans 2021 to 2024." in markdown
    assert "## Early detection" in markdown
    assert (
        "MRI classification models improved early detection in the included "
        "evidence (Smith and Jones, 2024)."
    ) in markdown
    assert "[p1]" not in markdown
    assert "**Key points**" in markdown
    assert "- MRI classification was central." in markdown
    assert "## References" in markdown
    assert "Smith; Jones (2024). Paper one." in markdown
    assert "DOI: https://doi.org/10.123/one" in markdown
    assert "Uncited paper" not in markdown
    assert "\\documentclass{MITcsail}" in latex
    assert "\\title{Early AD detection}" in latex
    assert "\\citep{ref_p1}" in latex
    assert "\\bibliography{references}" in latex
    assert "@article{ref_p1," in bib
    assert "author = {Smith and Jones}" in bib
    assert "CSAIL-style literature review class" in cls
    assert "images/CSAIL_Primary_Regular_RGB.png" in cls


def test_assemble_literature_review_requires_all_eligible_papers_below_20(
    tmp_path: Path,
) -> None:
    sections_path = tmp_path / "review_sections.json"
    output_path = tmp_path / "literature_review.md"
    write_sections(sections_path)
    payload = json.loads(sections_path.read_text(encoding="utf-8"))
    payload["papers"][1]["doi"] = "10.123/two"
    sections_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="too few citation-eligible papers"):
        run(sections_path, output_path)


def test_assemble_literature_review_rejects_internal_ids_in_lists(
    tmp_path: Path,
) -> None:
    sections_path = tmp_path / "review_sections.json"
    output_path = tmp_path / "literature_review.md"
    write_sections(sections_path)
    payload = json.loads(sections_path.read_text(encoding="utf-8"))
    payload["sections"][0]["key_points"] = ["Internal ids must not leak [p1]."]
    sections_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="internal paper-id markers"):
        run(sections_path, output_path)


def test_assemble_literature_review_rejects_unknown_harvard_author(
    tmp_path: Path,
) -> None:
    sections_path = tmp_path / "review_sections.json"
    output_path = tmp_path / "literature_review.md"
    write_sections(sections_path)
    payload = json.loads(sections_path.read_text(encoding="utf-8"))
    payload["sections"][0]["body_markdown"] = (
        "MRI classification models improved early detection "
        "in the included evidence (Collins, 2020)."
    )
    sections_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="do not match structured paper metadata"):
        run(sections_path, output_path)


def test_assemble_literature_review_repairs_unique_year_harvard_typo(
    tmp_path: Path,
) -> None:
    sections_path = tmp_path / "review_sections.json"
    output_path = tmp_path / "literature_review.md"
    write_sections(sections_path)
    payload = json.loads(sections_path.read_text(encoding="utf-8"))
    payload["sections"][0]["body_markdown"] = (
        "Network measures were useful (Suk et al., 2024), and "
        "Suk et al. (2024) described the result."
    )
    sections_path.write_text(json.dumps(payload), encoding="utf-8")

    run(sections_path, output_path)
    markdown = output_path.read_text(encoding="utf-8")

    assert "(Smith and Jones, 2024)" in markdown
    assert "Smith and Jones (2024)" in markdown
    assert "Suk et al." not in markdown


def test_assemble_latex_handles_embedded_markdown_headings(
    tmp_path: Path,
) -> None:
    sections_path = tmp_path / "review_sections.json"
    output_path = tmp_path / "literature_review.md"
    latex_dir = tmp_path / "literature_review_latex"
    write_sections(sections_path)
    payload = json.loads(sections_path.read_text(encoding="utf-8"))
    payload["sections"][0]["body_markdown"] = (
        "The evidence was mixed. ### Datasets and Samples Studies used "
        "clinical and imaging datasets (Smith and Jones, 2024)."
    )
    sections_path.write_text(json.dumps(payload), encoding="utf-8")

    run(sections_path, output_path, latex_dir)
    latex = (latex_dir / "main.tex").read_text(encoding="utf-8")

    assert r"\#\#\#" not in latex
    assert r"\subsection{Datasets and Samples Studies used clinical" not in latex
    assert "Datasets and Samples Studies used clinical" in latex
    assert r"\citep{ref_p1}" in latex


def test_assemble_literature_review_caps_cited_papers_at_40(
    tmp_path: Path,
) -> None:
    sections_path = tmp_path / "review_sections.json"
    output_path = tmp_path / "literature_review.md"
    paper_ids = [f"p{index}" for index in range(1, 42)]
    payload = {
        "research_topic": {"title": "Large review"},
        "overview": {"usable_paper_count": 41},
        "sections": [
            {
                "section_id": "large_section",
                "title": "Large section",
                "summary": "",
                "body_markdown": "Many studies contributed evidence.",
                "key_points": [],
                "methodological_patterns": [],
                "limitations_or_gaps": [],
                "citation_support": [
                    {"paper_id": paper_id, "claim": "Supported claim."}
                    for paper_id in paper_ids
                ],
                "cited_paper_ids": paper_ids,
                "quote_uses": [],
            }
        ],
        "papers": [
            {
                "paper_id": paper_id,
                "title": f"Paper {index}",
                "year": "2024",
                "doi": f"10.123/{index}",
                "authors": f"Author{index}",
                "venue": "Journal",
            }
            for index, paper_id in enumerate(paper_ids, start=1)
        ],
    }
    sections_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="too many citation-eligible papers"):
        run(sections_path, output_path)
