from __future__ import annotations

import argparse
from copy import deepcopy
import re
from pathlib import Path
from typing import Any

from ad_lit_pipeline.core.step import StepResult, StepSpec
from ad_lit_pipeline.io.json_io import read_json_object
from ad_lit_pipeline.steps.review.citations import (
    citation_sort_key,
    clean_text,
    doi_url,
    enrich_paper_citations,
    has_citation_metadata,
    harvard_reference,
    year_text,
)


STEP = StepSpec(
    name="assemble_literature_review",
    inputs=["review_sections_json"],
    outputs=["literature_review_md", "literature_review_latex_dir"],
    uses_llm=False,
    description="Assemble generated review sections into Markdown and LaTeX.",
)


PAPER_ID_MARKER_PATTERN = re.compile(r"\[(?:p\d+|[A-Za-z0-9_.:/-]+)(?:\s*;\s*(?:p\d+|[A-Za-z0-9_.:/-]+))*\]")
AUTHOR_YEAR_CITATION_PATTERN = re.compile(r"\(([^()]*\b\d{4}[a-z]?\b[^()]*)\)")
NARRATIVE_CITATION_PATTERN = re.compile(
    r"\b([A-Z][A-Za-z'’-]+(?: et al\.| and [A-Z][A-Za-z'’-]+)?) \((\d{4}[a-z]?)\)"
)
LATEX_SPECIAL_CHARS = {
    "\\": r"\textbackslash{}",
    "&": r"\&",
    "%": r"\%",
    "$": r"\$",
    "#": r"\#",
    "_": r"\_",
    "{": r"\{",
    "}": r"\}",
    "~": r"\textasciitilde{}",
    "^": r"\textasciicircum{}",
}
LATEX_CITATION_PLACEHOLDER = "§CITPH{}§"
MIT_CSAIL_CLASS = r"""%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%
%% CSAIL-style literature review class.
%% Adapted from the MIT CSAIL template shared under CC BY-SA 4.0.
%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%
\NeedsTeXFormat{LaTeX2e}
\ProvidesClass{MITcsail}[2022/05/31 MIT CSAIL Template]

\LoadClass[11pt]{article}

\RequirePackage{xcolor}
\RequirePackage{fancyhdr}
\RequirePackage{graphicx}
\RequirePackage[authoryear, sort&compress, round]{natbib}
\RequirePackage[colorlinks=true, citecolor=blue, linkcolor=black, urlcolor=blue]{hyperref}
\RequirePackage{amsmath}
\RequirePackage{amssymb}
\RequirePackage{booktabs}
\RequirePackage{caption}
\RequirePackage{mathpazo}
\RequirePackage{titlesec}

\titlelabel{\thetitle.\quad}
\captionsetup[figure]{font=small}
\captionsetup[table]{font=small}
\renewcommand*{\thefootnote}{\fnsymbol{footnote}}

\topmargin -1.0cm
\oddsidemargin -0.2cm
\textwidth 17cm
\textheight 22cm
\footskip 1cm
\setlength{\headheight}{21.25012pt}

\renewenvironment{abstract}
 {\bfseries
  \list{}{%
    \setlength{\leftmargin}{0mm}%
    \setlength{\rightmargin}{\leftmargin}%
  }%
  \item\relax}
 {\endlist}

\makeatletter
\renewcommand{\maketitle}{\bgroup\setlength{\parindent}{0pt}
\begin{flushleft}
  \textbf{\LARGE \@title}\vspace*{2.5em}

  \textbf{\@author}
\end{flushleft}\egroup
}

\pagestyle{fancy}
\fancypagestyle{firstpagestyle}{
    \fancyhf{}
    \fancyhead[L]{%
      \IfFileExists{images/CSAIL_Primary_Regular_RGB.png}{%
        \includegraphics[width=30pt]{images/CSAIL_Primary_Regular_RGB.png}%
      }{\textbf{Literature Review}}}}

\fancyhf{}
\chead{\@title}
\rfoot{\thepage}
\makeatother

\renewcommand{\figurename}{\textbf{Fig.}}
\renewcommand{\tablename}{\textbf{Table}}
\renewcommand{\thetable}{\textbf{\arabic{table}}}
\renewcommand{\thefigure}{\textbf{\arabic{figure}}}
"""


def strip_internal_citation_markers(value: str) -> str:
    cleaned = PAPER_ID_MARKER_PATTERN.sub("", value)
    cleaned = re.sub(r"\s+([.,;:])", r"\1", cleaned)
    cleaned = re.sub(r"\s{2,}", " ", cleaned)
    return cleaned.strip()


def strip_internal_markers_preserve_blocks(value: object) -> str:
    cleaned = PAPER_ID_MARKER_PATTERN.sub("", str(value or ""))
    cleaned = re.sub(r"[ \t]+([.,;:])", r"\1", cleaned)
    cleaned = re.sub(r"[ \t]{2,}", " ", cleaned)
    return cleaned.strip()


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
    review_type = clean_text(overview.get("review_type")) or "narrative"
    if isinstance(paper_count, int):
        lines.append(
            f"This {review_type.replace('_', ' ')} literature review summarizes "
            f"evidence from {paper_count} papers."
        )

    years = overview.get("year_range")
    if isinstance(years, list) and len(years) == 2:
        lines.append(f"The included evidence spans {years[0]} to {years[1]}.")

    if not lines:
        lines.append("This review summarizes the synthesized paper evidence.")
    return lines


def abstract_text(payload: dict[str, Any]) -> str:
    sections = payload.get("sections", [])
    if isinstance(sections, list):
        for section in sections:
            if not isinstance(section, dict) or section.get("section_id") != "abstract":
                continue
            body = strip_internal_citation_markers(
                clean_text(section.get("body_markdown"))
            )
            if body:
                return body
            summary = clean_text(section.get("summary"))
            if summary:
                return summary
    return " ".join(overview_lines(payload.get("overview", {})))


def normalize_heading(value: object, fallback: str) -> str:
    heading = clean_text(value)
    return heading or fallback


def section_heading_level(section: dict[str, Any]) -> int:
    level = section.get("heading_level", 1)
    return level if isinstance(level, int) and level in {1, 2} else 1


def render_section(section: dict[str, Any]) -> list[str]:
    section_id = clean_text(section.get("section_id")) or "section"
    title = normalize_heading(section.get("title"), section_id.replace("_", " "))
    body = strip_internal_citation_markers(clean_text(section.get("body_markdown")))
    summary = clean_text(section.get("summary"))

    markdown_level = section_heading_level(section) + 1
    lines = [f"{'#' * markdown_level} {title}", ""]
    if summary:
        lines.extend([f"_{summary}_", ""])
    if body:
        lines.extend([body, ""])
    return lines


def referenced_paper_ids(sections: list[dict[str, Any]]) -> set[str]:
    paper_ids = set()
    for section in sections:
        cited_paper_ids = section.get("cited_paper_ids")
        if isinstance(cited_paper_ids, list):
            for paper_id in cited_paper_ids:
                paper_id = clean_text(paper_id)
                if paper_id:
                    paper_ids.add(paper_id)
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
        references.append(enrich_paper_citations(paper))
        seen.add(paper_id)
    return sorted(references, key=citation_sort_key)


def bib_key(paper: dict[str, Any]) -> str:
    paper_id = clean_text(paper.get("paper_id")) or clean_text(paper.get("doi"))
    key = re.sub(r"[^A-Za-z0-9]+", "_", paper_id).strip("_").lower()
    return f"ref_{key or 'paper'}"


def latex_escape(value: object) -> str:
    return "".join(LATEX_SPECIAL_CHARS.get(char, char) for char in clean_text(value))


def bibtex_escape(value: object) -> str:
    text = clean_text(value)
    return (
        text.replace("\\", "\\textbackslash{}")
        .replace("{", "\\{")
        .replace("}", "\\}")
        .replace("&", "\\&")
    )


def bibtex_authors(authors: object) -> str:
    parts = [clean_text(part) for part in clean_text(authors).split(";")]
    return " and ".join(part for part in parts if part)


def bibtex_entry(paper: dict[str, Any]) -> str:
    fields = {
        "title": bibtex_escape(paper.get("title")),
        "author": bibtex_escape(bibtex_authors(paper.get("authors"))),
        "year": bibtex_escape(year_text(paper.get("year"))),
        "journal": bibtex_escape(paper.get("venue")),
        "doi": bibtex_escape(paper.get("doi")),
        "url": bibtex_escape(doi_url(paper.get("doi"))),
    }
    lines = [f"@article{{{bib_key(paper)},"]
    for field, value in fields.items():
        if value:
            lines.append(f"  {field} = {{{value}}},")
    lines.append("}")
    return "\n".join(lines)


def citation_replacements(references: list[dict[str, Any]]) -> list[tuple[str, str]]:
    replacements: list[tuple[str, str]] = []
    for paper in references:
        enriched = enrich_paper_citations(paper)
        key = bib_key(enriched)
        inline = clean_text(enriched.get("harvard_inline"))
        narrative = clean_text(enriched.get("harvard_narrative"))
        if narrative:
            replacements.append((narrative, rf"\citet{{{key}}}"))
        if inline:
            replacements.append((inline, rf"\citep{{{key}}}"))
    return sorted(replacements, key=lambda item: len(item[0]), reverse=True)


def inline_citation_key_map(references: list[dict[str, Any]]) -> dict[str, str]:
    mappings = {}
    for paper in references:
        enriched = enrich_paper_citations(paper)
        inline = clean_text(enriched.get("harvard_inline"))
        if inline.startswith("(") and inline.endswith(")"):
            mappings[inline[1:-1]] = bib_key(enriched)
    return mappings


def protect_latex_citations(
    text: str,
    references: list[dict[str, Any]],
) -> tuple[str, dict[str, str]]:
    protected = text
    placeholders = {}
    inline_keys = inline_citation_key_map(references)

    def protect_inline_group(match: re.Match[str]) -> str:
        inner = clean_text(match.group(1))
        if re.fullmatch(r"\d{4}[a-z]?", inner):
            return match.group(0)
        parts = [clean_text(part) for part in inner.split(";")]
        keys = []
        for part in parts:
            key = inline_keys.get(part)
            if not key:
                return match.group(0)
            keys.append(key)
        placeholder = LATEX_CITATION_PLACEHOLDER.format(len(placeholders))
        placeholders[placeholder] = r"\citep{" + ",".join(keys) + "}"
        return placeholder

    protected = AUTHOR_YEAR_CITATION_PATTERN.sub(protect_inline_group, protected)
    for index, (source, target) in enumerate(citation_replacements(references)):
        placeholder = LATEX_CITATION_PLACEHOLDER.format(len(placeholders) + index)
        if source in protected:
            protected = protected.replace(source, placeholder)
            placeholders[placeholder] = target
    return protected, placeholders


def restore_latex_citations(text: str, placeholders: dict[str, str]) -> str:
    restored = text
    for placeholder, citation in placeholders.items():
        restored = restored.replace(latex_escape(placeholder), citation)
        restored = restored.replace(placeholder, citation)
    return restored


def latex_inline(text: object, references: list[dict[str, Any]]) -> str:
    protected, placeholders = protect_latex_citations(clean_text(text), references)
    escaped = latex_escape(protected)
    escaped = re.sub(r"\*\*(.+?)\*\*", r"\\textbf{\1}", escaped)
    escaped = re.sub(r"_(.+?)_", r"\\textit{\1}", escaped)
    return restore_latex_citations(escaped, placeholders)


def latex_body_lines(body: str) -> list[str]:
    normalized = re.sub(r"\s+(#{2,4})\s+", r"\n\1 ", body)
    return normalized.splitlines()


def split_clean_markdown_heading(line: str) -> tuple[str, str] | None:
    heading_match = re.match(r"^(#{2,4})\s+(.+)$", line)
    if not heading_match:
        return None
    marker, heading = heading_match.groups()
    heading = clean_text(heading)
    words = heading.split()
    if len(words) > 8:
        return None
    if re.search(r"[.!?;:]", heading):
        return None
    command = "subsection" if len(marker) <= 3 else "subsubsection"
    return command, heading


def strip_markdown_heading_marker(line: str) -> str:
    return re.sub(r"^#{2,4}\s+", "", line).strip()


def latex_abstract(payload: dict[str, Any]) -> str:
    return abstract_text(payload)


def latex_section_lines(
    section: dict[str, Any],
    references: list[dict[str, Any]],
) -> list[str]:
    section_id = clean_text(section.get("section_id")) or "section"
    title = normalize_heading(section.get("title"), section_id.replace("_", " "))
    body = strip_internal_markers_preserve_blocks(section.get("body_markdown"))
    summary = clean_text(section.get("summary"))
    heading_level = section_heading_level(section)
    heading_command = "section" if heading_level == 1 else "subsection"
    lines = [rf"\{heading_command}{{{latex_escape(title)}}}", ""]
    if summary:
        lines.extend([rf"\textit{{{latex_inline(summary, references)}}}", ""])
    if body:
        current_paragraph: list[str] = []
        for raw_line in latex_body_lines(body):
            line = raw_line.strip()
            if not line:
                if current_paragraph:
                    paragraph = clean_text(" ".join(current_paragraph))
                    lines.extend([latex_inline(paragraph, references), ""])
                    current_paragraph = []
                continue
            clean_heading = split_clean_markdown_heading(line)
            if clean_heading:
                if current_paragraph:
                    paragraph = clean_text(" ".join(current_paragraph))
                    lines.extend([latex_inline(paragraph, references), ""])
                    current_paragraph = []
                _, heading = clean_heading
                command = "subsection" if heading_level == 1 else "subsubsection"
                lines.extend(
                    [
                        rf"\{command}{{{latex_escape(heading)}}}",
                        "",
                    ]
                )
                continue
            line = strip_markdown_heading_marker(line)
            current_paragraph.append(line)
        if current_paragraph:
            paragraph = clean_text(" ".join(current_paragraph))
            lines.extend([latex_inline(paragraph, references), ""])

    return lines


def render_latex_main(payload: dict[str, Any], references: list[dict[str, Any]]) -> str:
    cited_keys = [bib_key(paper) for paper in references]
    sections = payload.get("sections", [])
    lines = [
        r"\documentclass{MITcsail}",
        "",
        rf"\title{{{latex_escape(title_from_payload(payload))}}}",
        r"\author{AD Literature Knowledge Pipeline\\",
        r"\vspace{1em}",
        r"\normalfont{\small Automated narrative literature review}}",
        "",
        r"\begin{document}",
        "",
        r"\maketitle",
        r"\thispagestyle{firstpagestyle}",
        "",
        r"\begin{abstract}",
        latex_inline(latex_abstract(payload), references),
        r"\end{abstract}",
        "",
    ]
    active_chapter = ""
    for section in sections:
        if isinstance(section, dict):
            if clean_text(section.get("section_id")) == "abstract":
                continue
            chapter_id = clean_text(section.get("chapter_id"))
            chapter_label = clean_text(section.get("chapter_label"))
            if chapter_id and chapter_id != active_chapter:
                lines.extend([rf"\section{{{latex_escape(chapter_label)}}}", ""])
            active_chapter = chapter_id
            lines.extend(latex_section_lines(section, references))

    if cited_keys:
        lines.extend(
            [
                r"\clearpage",
                r"\bibliographystyle{abbrvnat}",
                r"\nocite{" + ",".join(cited_keys) + "}",
                r"\bibliography{references}",
                "",
            ]
        )

    lines.extend(
        [
            r"\section*{Acknowledgments}",
            (
                "This document was generated from structured literature-review "
                "evidence produced by the AD literature knowledge pipeline."
            ),
            "",
            r"\end{document}",
            "",
        ]
    )
    return "\n".join(lines)


def write_latex_package(
    payload: dict[str, Any],
    output_dir: Path,
    references: list[dict[str, Any]],
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "MITcsail.cls").write_text(MIT_CSAIL_CLASS + "\n", encoding="utf-8")
    (output_dir / "main.tex").write_text(
        render_latex_main(payload, references),
        encoding="utf-8",
    )
    (output_dir / "references.bib").write_text(
        "\n\n".join(bibtex_entry(paper) for paper in references) + "\n",
        encoding="utf-8",
    )


def citation_target(citation_eligible_count: int) -> dict[str, int]:
    if citation_eligible_count < 20:
        minimum = citation_eligible_count
        maximum = citation_eligible_count
    else:
        minimum = 20
        maximum = min(40, citation_eligible_count)
    return {
        "minimum": minimum,
        "maximum": maximum,
        "target": maximum,
    }


def citation_eligible_paper_ids(payload: dict[str, Any]) -> set[str]:
    papers = payload.get("papers", [])
    if not isinstance(papers, list):
        return set()
    eligible = set()
    for paper in papers:
        if not isinstance(paper, dict):
            continue
        paper_id = clean_text(paper.get("paper_id"))
        if paper_id and has_citation_metadata(paper):
            eligible.add(paper_id)
    return eligible


def validate_citation_coverage(payload: dict[str, Any]) -> dict[str, Any]:
    sections = payload.get("sections", [])
    if not isinstance(sections, list):
        raise ValueError("review_sections JSON must contain sections list.")

    section_list = [section for section in sections if isinstance(section, dict)]
    cited_ids = referenced_paper_ids(section_list)
    eligible_ids = citation_eligible_paper_ids(payload)
    target = citation_target(len(eligible_ids))

    ineligible_citations = sorted(cited_ids - eligible_ids)
    if ineligible_citations:
        raise ValueError(
            "Review cites paper(s) without complete citation metadata: "
            + ", ".join(ineligible_citations)
        )

    cited_eligible_count = len(cited_ids & eligible_ids)
    if cited_eligible_count < target["minimum"]:
        missing = sorted(eligible_ids - cited_ids)
        raise ValueError(
            "Review cites too few citation-eligible papers: "
            f"{cited_eligible_count} cited, minimum is {target['minimum']}. "
            f"Missing cited paper ids: {', '.join(missing)}"
        )
    if cited_eligible_count > target["maximum"]:
        raise ValueError(
            "Review cites too many citation-eligible papers: "
            f"{cited_eligible_count} cited, maximum is {target['maximum']}."
        )

    return {
        "citation_eligible_papers": len(eligible_ids),
        "cited_eligible_papers": cited_eligible_count,
        "minimum_cited_papers": target["minimum"],
        "maximum_cited_papers": target["maximum"],
        "target_cited_papers": target["target"],
    }


def assemble_markdown(payload: dict[str, Any]) -> str:
    sections = payload.get("sections", [])
    if not isinstance(sections, list):
        raise ValueError("review_sections JSON must contain sections list.")

    lines = [
        f"# {title_from_payload(payload)}",
        "",
        "## Abstract",
        "",
        abstract_text(payload),
        "",
    ]

    active_chapter = ""
    for section in sections:
        if isinstance(section, dict):
            if clean_text(section.get("section_id")) == "abstract":
                continue
            chapter_id = clean_text(section.get("chapter_id"))
            chapter_label = clean_text(section.get("chapter_label"))
            if chapter_id and chapter_id != active_chapter:
                lines.extend([f"## {chapter_label}", ""])
            active_chapter = chapter_id
            lines.extend(render_section(section))

    references = ordered_reference_papers(payload)
    if references:
        lines.append("## References")
        lines.append("")
        for paper in references:
            lines.append(f"- {harvard_reference(paper)}")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def validate_markdown(markdown: str) -> None:
    markers = sorted(set(PAPER_ID_MARKER_PATTERN.findall(markdown)))
    if markers:
        raise ValueError(
            "Literature review Markdown still contains internal paper-id markers: "
            + ", ".join(markers)
        )

    if "## References" in markdown and "[" in markdown:
        bracket_markers = sorted(set(PAPER_ID_MARKER_PATTERN.findall(markdown)))
        if bracket_markers:
            raise ValueError(
                "Literature review references contain internal paper-id markers: "
                + ", ".join(bracket_markers)
            )


def allowed_harvard_citation_texts(payload: dict[str, Any]) -> set[str]:
    papers = payload.get("papers", [])
    allowed = set()
    if not isinstance(papers, list):
        return allowed
    for paper in papers:
        if not isinstance(paper, dict):
            continue
        enriched = enrich_paper_citations(paper)
        inline = clean_text(enriched.get("harvard_inline"))
        if inline.startswith("(") and inline.endswith(")"):
            allowed.add(inline[1:-1])
    return allowed


def allowed_harvard_narrative_texts(payload: dict[str, Any]) -> set[str]:
    papers = payload.get("papers", [])
    allowed = set()
    if not isinstance(papers, list):
        return allowed
    for paper in papers:
        if not isinstance(paper, dict):
            continue
        narrative = clean_text(enrich_paper_citations(paper).get("harvard_narrative"))
        if narrative:
            allowed.add(narrative)
    return allowed


def citation_text_by_year(payload: dict[str, Any]) -> dict[str, dict[str, str]]:
    papers = payload.get("papers", [])
    by_year: dict[str, list[dict[str, str]]] = {}
    if not isinstance(papers, list):
        return {}
    for paper in papers:
        if not isinstance(paper, dict):
            continue
        enriched = enrich_paper_citations(paper)
        year = clean_text(year_text(enriched.get("year")))
        inline = clean_text(enriched.get("harvard_inline"))
        narrative = clean_text(enriched.get("harvard_narrative"))
        if year and inline and narrative:
            by_year.setdefault(year, []).append(
                {
                    "inline": inline,
                    "narrative": narrative,
                }
            )
    return {
        year: records[0]
        for year, records in by_year.items()
        if len(records) == 1
    }


def repair_harvard_citations(markdown: str, payload: dict[str, Any]) -> str:
    unique_years = citation_text_by_year(payload)
    allowed_inline = allowed_harvard_citation_texts(payload)
    allowed_narrative = allowed_harvard_narrative_texts(payload)
    prose, separator, references = markdown.partition("\n## References")

    def repair_inline(match: re.Match[str]) -> str:
        inner = clean_text(match.group(1))
        if re.fullmatch(r"\d{4}[a-z]?", inner):
            return match.group(0)
        parts = [clean_text(part) for part in inner.split(";")]
        repaired_parts = []
        changed = False
        for part in parts:
            year_match = re.search(r"\b(\d{4}[a-z]?)\b", part)
            if not year_match or part in allowed_inline:
                repaired_parts.append(part)
                continue
            replacement = unique_years.get(year_match.group(1), {}).get("inline")
            if replacement and replacement.startswith("(") and replacement.endswith(")"):
                repaired_parts.append(replacement[1:-1])
                changed = True
            else:
                repaired_parts.append(part)
        return f"({'; '.join(repaired_parts)})" if changed else match.group(0)

    repaired = AUTHOR_YEAR_CITATION_PATTERN.sub(repair_inline, prose)

    def repair_narrative(match: re.Match[str]) -> str:
        citation = f"{match.group(1)} ({match.group(2)})"
        if citation in allowed_narrative:
            return citation
        return unique_years.get(match.group(2), {}).get("narrative", citation)

    repaired = NARRATIVE_CITATION_PATTERN.sub(repair_narrative, repaired)
    return repaired + separator + references


def repaired_text_value(value: object, payload: dict[str, Any]) -> str:
    text = clean_text(value)
    return repair_harvard_citations(text, payload) if text else ""


def payload_with_repaired_citations(payload: dict[str, Any]) -> dict[str, Any]:
    repaired = deepcopy(payload)
    sections = repaired.get("sections")
    if not isinstance(sections, list):
        return repaired
    for section in sections:
        if not isinstance(section, dict):
            continue
        for key in ["title", "summary", "body_markdown"]:
            if key in section:
                section[key] = repaired_text_value(section.get(key), payload)
        for key in ["key_points", "methodological_patterns", "limitations_or_gaps"]:
            values = section.get(key)
            if isinstance(values, list):
                section[key] = [
                    repaired_text_value(value, payload)
                    for value in values
                ]
    return repaired


def validate_harvard_citations(markdown: str, payload: dict[str, Any]) -> None:
    allowed = allowed_harvard_citation_texts(payload)
    allowed_narrative = allowed_harvard_narrative_texts(payload)
    if not allowed and not allowed_narrative:
        return

    prose = markdown.split("\n## References", 1)[0]
    invalid = set()
    for match in AUTHOR_YEAR_CITATION_PATTERN.finditer(prose):
        inner = clean_text(match.group(1))
        if re.fullmatch(r"\d{4}[a-z]?", inner):
            continue
        parts = [clean_text(part) for part in inner.split(";")]
        for part in parts:
            if part and re.search(r"\b\d{4}[a-z]?\b", part) and part not in allowed:
                invalid.add(f"({part})")
    for match in NARRATIVE_CITATION_PATTERN.finditer(prose):
        citation = f"{match.group(1)} ({match.group(2)})"
        if citation not in allowed_narrative:
            invalid.add(citation)

    if invalid:
        raise ValueError(
            "Literature review contains Harvard citations that do not match "
            "structured paper metadata: "
            + ", ".join(sorted(invalid))
        )


def run(
    review_sections_path: Path,
    output_path: Path,
    latex_dir: Path | None = None,
) -> StepResult:
    payload = read_json_object(review_sections_path)
    coverage = validate_citation_coverage(payload)
    markdown = assemble_markdown(payload)
    markdown = repair_harvard_citations(markdown, payload)
    validate_markdown(markdown)
    validate_harvard_citations(markdown, payload)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(markdown, encoding="utf-8")
    sections = payload.get("sections", [])
    references = ordered_reference_papers(payload)
    outputs = {"literature_review_md": output_path}
    if latex_dir is not None:
        write_latex_package(payload_with_repaired_citations(payload), latex_dir, references)
        outputs["literature_review_latex_dir"] = latex_dir
    cited_ids = referenced_paper_ids(
        [section for section in sections if isinstance(section, dict)]
    )
    return StepResult(
        step_name=STEP.name,
        inputs={"review_sections_json": review_sections_path},
        outputs=outputs,
        row_counts={
            "review_sections": len(sections) if isinstance(sections, list) else 0,
            "review_references": len(references),
            "review_cited_papers": len(cited_ids),
            **coverage,
            "literature_review_chars": len(markdown),
            "latex_files": 3 if latex_dir is not None else 0,
        },
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Assemble Markdown and optional LaTeX literature-review outputs."
    )
    parser.add_argument("--sections", required=True, help="Review sections JSON.")
    parser.add_argument("--output", required=True, help="Markdown output path.")
    parser.add_argument(
        "--latex-dir",
        default=None,
        help="Optional directory for CSAIL-style LaTeX package.",
    )
    args = parser.parse_args()

    run(
        Path(args.sections),
        Path(args.output),
        Path(args.latex_dir) if args.latex_dir else None,
    )


if __name__ == "__main__":
    main()
