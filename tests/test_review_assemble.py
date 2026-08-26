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
                        "chapter_id": "background_and_related_literature",
                        "chapter_label": "Background and Related Literature",
                        "heading_level": 2,
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
    assert "## Abstract" in markdown
    assert "## Overview" not in markdown
    assert (
        "This narrative literature review summarizes evidence from 2 papers."
        in markdown
    )
    assert "The included evidence spans 2021 to 2024." in markdown
    assert "## Background and Related Literature" in markdown
    assert "### Early detection" in markdown
    assert (
        "MRI classification models improved early detection in the included "
        "evidence (Smith and Jones, 2024)."
    ) in markdown
    assert "[p1]" not in markdown
    source_payload = json.loads(sections_path.read_text(encoding="utf-8"))
    assert source_payload["sections"][0]["key_points"] == [
        "MRI classification was central."
    ]
    assert source_payload["sections"][0]["methodological_patterns"] == [
        "The section was dominated by imaging methods."
    ]
    assert source_payload["sections"][0]["limitations_or_gaps"] == [
        "The evidence base was small."
    ]
    assert "**Key points**" not in markdown
    assert "MRI classification was central." not in markdown
    assert "The section was dominated by imaging methods." not in markdown
    assert "The evidence base was small." not in markdown
    assert r"\subsection*{Key points}" not in latex
    assert "MRI classification was central." not in latex
    assert "The section was dominated by imaging methods." not in latex
    assert "The evidence base was small." not in latex
    assert "## References" in markdown
    assert "Smith; Jones (2024). Paper one." in markdown
    assert "DOI: https://doi.org/10.123/one" in markdown
    assert "Uncited paper" not in markdown
    assert "\\documentclass{MITcsail}" in latex
    assert "\\title{Early AD detection}" in latex
    assert "\\section{Background and Related Literature}" in latex
    assert "\\subsection{Early detection}" in latex
    assert "\\citep{ref_p1}" in latex
    assert "\\bibliography{references}" in latex
    assert "@article{ref_p1," in bib
    assert "author = {Smith and Jones}" in bib
    assert "CSAIL-style literature review class" in cls
    assert "images/CSAIL_Primary_Regular_RGB.png" in cls


def test_assemble_suppresses_introduction_summary_and_limits_other_summaries(
    tmp_path: Path,
) -> None:
    sections_path = tmp_path / "review_sections.json"
    output_path = tmp_path / "literature_review.md"
    latex_dir = tmp_path / "literature_review_latex"
    write_sections(sections_path)
    payload = json.loads(sections_path.read_text(encoding="utf-8"))
    payload["sections"][0]["section_id"] = "introduction"
    payload["sections"][0]["title"] = "Introduction"
    payload["sections"][0]["summary"] = (
        "This introduction summary should be hidden. It should not appear."
    )
    payload["sections"].append(
        {
            "section_id": "methods",
            "title": "Methods",
            "chapter_id": "background_and_related_literature",
            "chapter_label": "Background and Related Literature",
            "heading_level": 2,
            "summary": "Sentence one. Sentence two. Sentence three. Sentence four.",
            "body_markdown": "Methods body (Smith and Jones, 2024).",
            "key_points": [],
            "methodological_patterns": [],
            "limitations_or_gaps": [],
            "citation_support": [
                {"paper_id": "p1", "claim": "Methods body."}
            ],
            "cited_paper_ids": ["p1"],
            "quote_uses": [],
        }
    )
    sections_path.write_text(json.dumps(payload), encoding="utf-8")

    run(sections_path, output_path, latex_dir)
    markdown = output_path.read_text(encoding="utf-8")
    latex = (latex_dir / "main.tex").read_text(encoding="utf-8")

    assert "This introduction summary should be hidden" not in markdown
    assert "This introduction summary should be hidden" not in latex
    assert "_Sentence one. Sentence two. Sentence three._" in markdown
    assert "Sentence four." not in markdown
    assert r"\textit{Sentence one. Sentence two. Sentence three.}" in latex
    assert "Sentence four." not in latex


def test_assemble_uses_generated_abstract_in_both_formats(tmp_path: Path) -> None:
    sections_path = tmp_path / "review_sections.json"
    output_path = tmp_path / "literature_review.md"
    latex_dir = tmp_path / "literature_review_latex"
    write_sections(sections_path)
    payload = json.loads(sections_path.read_text(encoding="utf-8"))
    payload["sections"].insert(
        0,
        {
            "section_id": "abstract",
            "title": "Abstract",
            "summary": "",
            "body_markdown": (
                "This narrative review synthesizes two papers and identifies "
                "prominent evidence patterns, limitations, and implications."
            ),
            "key_points": [],
            "methodological_patterns": [],
            "limitations_or_gaps": [],
            "citation_support": [],
            "cited_paper_ids": [],
            "quote_uses": [],
        },
    )
    sections_path.write_text(json.dumps(payload), encoding="utf-8")

    run(sections_path, output_path, latex_dir)
    markdown = output_path.read_text(encoding="utf-8")
    latex = (latex_dir / "main.tex").read_text(encoding="utf-8")

    abstract = (
        "This narrative review synthesizes two papers and identifies prominent "
        "evidence patterns, limitations, and implications."
    )
    assert f"## Abstract\n\n{abstract}" in markdown
    assert f"\\begin{{abstract}}\n{abstract}\n\\end{{abstract}}" in latex
    assert "\\section{Abstract}" not in latex


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


def test_assemble_literature_review_hides_internal_ids_in_quality_fields(
    tmp_path: Path,
) -> None:
    sections_path = tmp_path / "review_sections.json"
    output_path = tmp_path / "literature_review.md"
    latex_dir = tmp_path / "literature_review_latex"
    write_sections(sections_path)
    payload = json.loads(sections_path.read_text(encoding="utf-8"))
    payload["sections"][0]["key_points"] = ["Internal ids must not leak [p1]."]
    sections_path.write_text(json.dumps(payload), encoding="utf-8")

    run(sections_path, output_path, latex_dir)

    assert "Internal ids must not leak" not in output_path.read_text(encoding="utf-8")
    assert "Internal ids must not leak" not in (latex_dir / "main.tex").read_text(
        encoding="utf-8"
    )


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


def test_assemble_repairs_leading_qualifier_inside_parenthetical_citation(
    tmp_path: Path,
) -> None:
    sections_path = tmp_path / "review_sections.json"
    output_path = tmp_path / "literature_review.md"
    diagnostic_json = tmp_path / "literature_review_citation_diagnostics.json"
    diagnostic_md = tmp_path / "literature_review_citation_diagnostics.md"
    write_sections(sections_path)
    diagnostic_json.write_text("{}", encoding="utf-8")
    diagnostic_md.write_text("old failure", encoding="utf-8")
    payload = json.loads(sections_path.read_text(encoding="utf-8"))
    payload["sections"][0]["body_markdown"] = (
        "Multimodal models supported diagnosis "
        "(e.g., Golovanevsky et al., 2022; Smith, 2022)."
    )
    payload["sections"][0]["citation_support"] = [
        {"paper_id": "p1", "claim": "Multimodal models supported diagnosis."},
        {"paper_id": "p2", "claim": "A second 2022 paper was cited."},
    ]
    payload["sections"][0]["cited_paper_ids"] = ["p1", "p2"]
    payload["papers"] = [
        {
            "paper_id": "p1",
            "title": "Multimodal attention diagnosis",
            "year": "2022",
            "doi": "10.123/golovanevsky",
            "authors": "Golovanevsky; Eickhoff; Singh",
            "venue": "Journal",
        },
        {
            "paper_id": "p2",
            "title": "Second paper",
            "year": "2022",
            "doi": "10.123/smith",
            "authors": "Smith",
            "venue": "Journal",
        },
    ]
    sections_path.write_text(json.dumps(payload), encoding="utf-8")

    run(sections_path, output_path)

    markdown = output_path.read_text(encoding="utf-8")
    assert "e.g., (Golovanevsky et al., 2022; Smith, 2022)" in markdown
    assert "(e.g., Golovanevsky et al., 2022)" not in markdown
    assert not diagnostic_json.exists()
    assert not diagnostic_md.exists()


def test_assemble_writes_citation_diagnostics_for_invalid_harvard_text(
    tmp_path: Path,
) -> None:
    sections_path = tmp_path / "review_sections.json"
    output_path = tmp_path / "literature_review.md"
    write_sections(sections_path)
    payload = json.loads(sections_path.read_text(encoding="utf-8"))
    payload["sections"][0]["body_markdown"] = (
        "Multimodal models supported diagnosis "
        "(e.g., Collins et al., 2022; Smith, 2022)."
    )
    payload["sections"][0]["citation_support"] = [
        {"paper_id": "p1", "claim": "Multimodal models supported diagnosis."},
        {"paper_id": "p2", "claim": "A second 2022 paper was cited."},
    ]
    payload["sections"][0]["cited_paper_ids"] = ["p1", "p2"]
    payload["papers"] = [
        {
            "paper_id": "p1",
            "title": "Multimodal attention diagnosis",
            "year": "2022",
            "doi": "10.123/golovanevsky",
            "authors": "Golovanevsky; Eickhoff; Singh",
            "venue": "Journal",
        },
        {
            "paper_id": "p2",
            "title": "Second paper",
            "year": "2022",
            "doi": "10.123/smith",
            "authors": "Smith",
            "venue": "Journal",
        },
    ]
    sections_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match=r"\(e\.g\., Collins et al\., 2022\)"):
        run(sections_path, output_path)

    diagnostic_json = tmp_path / "literature_review_citation_diagnostics.json"
    diagnostic_md = tmp_path / "literature_review_citation_diagnostics.md"
    assert diagnostic_json.exists()
    assert diagnostic_md.exists()
    diagnostic = json.loads(diagnostic_json.read_text(encoding="utf-8"))
    assert diagnostic["invalid_citations"][0]["citation"] == (
        "(e.g., Collins et al., 2022)"
    )
    assert diagnostic["invalid_citations"][0]["nearest_heading"] == "### Early detection"
    assert "`(e.g., Collins et al., 2022)`" in diagnostic_md.read_text(
        encoding="utf-8"
    )


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


def test_assemble_repairs_section_local_harvard_typo_when_year_is_ambiguous(
    tmp_path: Path,
) -> None:
    sections_path = tmp_path / "review_sections.json"
    output_path = tmp_path / "literature_review.md"
    write_sections(sections_path)
    payload = json.loads(sections_path.read_text(encoding="utf-8"))
    payload["sections"][0]["body_markdown"] = (
        "MRI classification models improved early detection (Almond et al., 2024)."
    )
    payload["sections"].append(
        {
            "section_id": "other_evidence",
            "title": "Other evidence",
            "summary": "",
            "body_markdown": "A second study contributed evidence (Doe, 2024).",
            "key_points": [],
            "methodological_patterns": [],
            "limitations_or_gaps": [],
            "citation_support": [
                {"paper_id": "p2", "claim": "A second study contributed evidence."}
            ],
            "cited_paper_ids": ["p2"],
            "quote_uses": [],
        }
    )
    payload["papers"][1]["year"] = "2024"
    payload["papers"][1]["doi"] = "10.123/two"
    sections_path.write_text(json.dumps(payload), encoding="utf-8")

    run(sections_path, output_path)
    markdown = output_path.read_text(encoding="utf-8")

    assert "(Smith and Jones, 2024)" in markdown
    assert "(Doe, 2024)" in markdown
    assert "Almond et al." not in markdown


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

    result = run(sections_path, output_path)
    markdown = output_path.read_text(encoding="utf-8")

    assert result.row_counts["review_references"] == 40
    assert result.row_counts["review_cited_papers"] == 40
    assert result.row_counts["maximum_cited_papers"] == 40
    assert result.metadata["citation_references_before_trim"] == 41
    assert result.metadata["citation_references_after_trim"] == 40
    assert result.warnings
    assert "Paper 1" in markdown
    assert "Paper 40" in markdown
    assert "Paper 41" not in markdown
