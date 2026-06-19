from __future__ import annotations

import re
from typing import Any


def clean_text(value: object) -> str:
    return " ".join(str(value or "").split()).strip()


def author_parts(authors: object) -> list[str]:
    parts = [clean_text(part) for part in clean_text(authors).split(";")]
    return [part for part in parts if part]


def surname(author: str) -> str:
    cleaned = clean_text(author)
    if not cleaned:
        return ""
    if "," in cleaned:
        return clean_text(cleaned.split(",", 1)[0])
    tokens = cleaned.split()
    return tokens[-1] if tokens else ""


def author_label(authors: object) -> str:
    names = [surname(author) for author in author_parts(authors)]
    names = [name for name in names if name]
    if not names:
        return ""
    if len(names) == 1:
        return names[0]
    if len(names) == 2:
        return f"{names[0]} and {names[1]}"
    return f"{names[0]} et al."


def year_text(year: object) -> str:
    text = clean_text(year)
    match = re.search(r"\d{4}", text)
    return match.group(0) if match else ""


def has_citation_metadata(paper: dict[str, Any]) -> bool:
    return bool(
        clean_text(paper.get("paper_id"))
        and clean_text(paper.get("title"))
        and year_text(paper.get("year"))
        and author_label(paper.get("authors"))
        and clean_text(paper.get("doi"))
    )


def harvard_inline(paper: dict[str, Any]) -> str:
    author = author_label(paper.get("authors"))
    year = year_text(paper.get("year"))
    if author and year:
        return f"({author}, {year})"
    return ""


def harvard_narrative(paper: dict[str, Any]) -> str:
    author = author_label(paper.get("authors"))
    year = year_text(paper.get("year"))
    if author and year:
        return f"{author} ({year})"
    return ""


def doi_url(doi: object) -> str:
    doi_text = clean_text(doi)
    if not doi_text:
        return ""
    if doi_text.lower().startswith("http://") or doi_text.lower().startswith(
        "https://"
    ):
        return doi_text
    return f"https://doi.org/{doi_text}"


def harvard_reference(paper: dict[str, Any]) -> str:
    authors = clean_text(paper.get("authors")) or "Unknown author"
    year = year_text(paper.get("year")) or "n.d."
    title = clean_text(paper.get("title")) or clean_text(paper.get("paper_id"))
    venue = clean_text(paper.get("venue"))
    doi = clean_text(paper.get("doi"))

    parts = [f"{authors} ({year}). {title}."]
    if venue:
        parts.append(f"{venue}.")
    if doi:
        parts.append(f"DOI: {doi_url(doi)}")
    return " ".join(parts)


def citation_sort_key(paper: dict[str, Any]) -> tuple[str, str, str]:
    return (
        author_label(paper.get("authors")).lower(),
        year_text(paper.get("year")),
        clean_text(paper.get("title")).lower(),
    )


def enrich_paper_citations(paper: dict[str, Any]) -> dict[str, Any]:
    enriched = dict(paper)
    enriched["citation_metadata_complete"] = has_citation_metadata(paper)
    enriched["harvard_inline"] = harvard_inline(paper)
    enriched["harvard_narrative"] = harvard_narrative(paper)
    enriched["harvard_reference"] = harvard_reference(paper)
    return enriched
