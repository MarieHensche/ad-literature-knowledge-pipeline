from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from ad_lit_pipeline.core.step import StepResult, StepSpec
from ad_lit_pipeline.io.json_io import read_json_object


STEP = StepSpec(
    name="assemble_literature_review",
    inputs=["review_sections_json"],
    outputs=["literature_review_md"],
    uses_llm=False,
    description="Assemble generated review sections into Markdown.",
)


def clean_text(value: object) -> str:
    return " ".join(str(value or "").split()).strip()


def title_from_payload(payload: dict[str, Any]) -> str:
    topic = payload.get("research_topic", {})
    if isinstance(topic, dict):
        title = clean_text(topic.get("title") or topic.get("description"))
        if title:
            return title
    return "Literature Review"


def overview_lines(overview: dict[str, Any]) -> list[str]:
    lines = []
    paper_count = overview.get("usable_paper_count", overview.get("paper_count"))
    if isinstance(paper_count, int):
        lines.append(f"This review summarizes evidence from {paper_count} papers.")

    years = overview.get("year_range")
    if isinstance(years, list) and len(years) == 2:
        lines.append(f"The included evidence spans {years[0]} to {years[1]}.")

    if not lines:
        lines.append("This review summarizes the synthesized paper evidence.")
    return lines


def normalize_heading(value: object, fallback: str) -> str:
    heading = clean_text(value)
    return heading or fallback


def render_key_list(title: str, values: object) -> list[str]:
    if not isinstance(values, list) or not values:
        return []
    lines = [f"**{title}**"]
    lines.extend(f"- {clean_text(value)}" for value in values if clean_text(value))
    return lines


def render_section(section: dict[str, Any]) -> list[str]:
    section_id = clean_text(section.get("section_id")) or "section"
    title = normalize_heading(section.get("title"), section_id.replace("_", " "))
    body = clean_text(section.get("body_markdown"))
    summary = clean_text(section.get("summary"))

    lines = [f"## {title}", ""]
    if summary:
        lines.extend([f"_{summary}_", ""])
    if body:
        lines.extend([body, ""])

    for list_title, key in [
        ("Key points", "key_points"),
        ("Methodological patterns", "methodological_patterns"),
        ("Limitations and gaps", "limitations_or_gaps"),
    ]:
        list_lines = render_key_list(list_title, section.get(key))
        if list_lines:
            lines.extend(list_lines)
            lines.append("")
    return lines


def author_text(paper: dict[str, Any]) -> str:
    authors = clean_text(paper.get("authors"))
    if not authors:
        return "Unknown author"
    parts = [clean_text(part) for part in authors.split(";")]
    parts = [part for part in parts if part]
    if not parts:
        return "Unknown author"
    if len(parts) == 1:
        return parts[0]
    if len(parts) == 2:
        return f"{parts[0]} and {parts[1]}"
    return f"{parts[0]} et al."


def reference_line(paper: dict[str, Any]) -> str:
    authors = author_text(paper)
    year = clean_text(paper.get("year")) or "n.d."
    title = clean_text(paper.get("title")) or clean_text(paper.get("paper_id"))
    venue = clean_text(paper.get("venue"))
    doi = clean_text(paper.get("doi"))
    parts = [f"{authors} ({year}). {title}."]
    if venue:
        parts.append(venue + ".")
    if doi:
        parts.append(f"DOI: {doi}")
    return " ".join(parts)


def referenced_paper_ids(sections: list[dict[str, Any]]) -> set[str]:
    paper_ids = set()
    for section in sections:
        for group_name in ["citation_support", "quote_uses"]:
            group = section.get(group_name)
            if not isinstance(group, list):
                continue
            for item in group:
                if isinstance(item, dict):
                    paper_id = clean_text(item.get("paper_id"))
                    if paper_id:
                        paper_ids.add(paper_id)
    return paper_ids


def ordered_reference_papers(payload: dict[str, Any]) -> list[dict[str, Any]]:
    sections = payload.get("sections", [])
    papers = payload.get("papers", [])
    if not isinstance(sections, list) or not isinstance(papers, list):
        return []

    cited_ids = referenced_paper_ids(
        [section for section in sections if isinstance(section, dict)]
    )
    seen = set()
    references = []
    for paper in papers:
        if not isinstance(paper, dict):
            continue
        paper_id = clean_text(paper.get("paper_id"))
        if not paper_id or paper_id in seen:
            continue
        if cited_ids and paper_id not in cited_ids:
            continue
        references.append(paper)
        seen.add(paper_id)
    return references


def assemble_markdown(payload: dict[str, Any]) -> str:
    sections = payload.get("sections", [])
    if not isinstance(sections, list):
        raise ValueError("review_sections JSON must contain sections list.")

    lines = [f"# {title_from_payload(payload)}", ""]
    lines.append("## Overview")
    lines.extend(overview_lines(payload.get("overview", {})))
    lines.append("")

    for section in sections:
        if isinstance(section, dict):
            lines.extend(render_section(section))

    references = ordered_reference_papers(payload)
    if references:
        lines.append("## References")
        lines.append("")
        for paper in references:
            paper_id = clean_text(paper.get("paper_id"))
            lines.append(f"- [{paper_id}] {reference_line(paper)}")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def run(review_sections_path: Path, output_path: Path) -> StepResult:
    payload = read_json_object(review_sections_path)
    markdown = assemble_markdown(payload)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(markdown, encoding="utf-8")
    sections = payload.get("sections", [])
    references = ordered_reference_papers(payload)
    return StepResult(
        step_name=STEP.name,
        inputs={"review_sections_json": review_sections_path},
        outputs={"literature_review_md": output_path},
        row_counts={
            "review_sections": len(sections) if isinstance(sections, list) else 0,
            "review_references": len(references),
            "literature_review_chars": len(markdown),
        },
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Assemble a Markdown literature review from section drafts."
    )
    parser.add_argument("--sections", required=True, help="Review sections JSON.")
    parser.add_argument("--output", required=True, help="Markdown output path.")
    args = parser.parse_args()

    run(Path(args.sections), Path(args.output))


if __name__ == "__main__":
    main()
