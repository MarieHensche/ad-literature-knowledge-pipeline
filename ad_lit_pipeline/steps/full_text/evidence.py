from __future__ import annotations

import re
from pathlib import Path


DEFAULT_MAX_EVIDENCE_CHARS = 24_000
MIN_USABLE_FULL_TEXT_CHARS = 1_000

SECTION_PRIORITY = [
    "abstract",
    "conclusion",
    "discussion",
    "limitations",
    "future_work",
    "results",
    "findings",
    "introduction",
    "background",
    "literature_review",
    "related_work",
    "methods",
    "methodology",
    "materials_and_methods",
    "study_design",
    "procedure",
    "approach",
    "protocol",
    "data",
    "sample",
    "participants",
    "population",
    "cohort",
    "analysis",
]

SECTION_PATTERNS = {
    "abstract": [r"abstract"],
    "introduction": [r"introduct"],
    "background": [r"background", r"context"],
    "literature_review": [r"literature\s+review", r"review\s+of\s+literature"],
    "related_work": [r"related\s+work"],
    "methods": [r"method", r"methods"],
    "methodology": [r"methodolog"],
    "materials_and_methods": [r"materials?\s+and\s+methods?"],
    "study_design": [r"study\s+design", r"research\s+design", r"\bdesign\b"],
    "procedure": [r"procedures?", r"study\s+procedures?", r"experimental\s+procedures?"],
    "approach": [r"approach", r"analytical\s+approach", r"analytic\s+approach"],
    "protocol": [r"protocol", r"study\s+protocol"],
    "data": [r"data", r"datasets?"],
    "sample": [r"samples?"],
    "participants": [r"participants?", r"subjects?"],
    "population": [r"population"],
    "cohort": [r"cohort"],
    "analysis": [r"analys", r"statistical\s+analysis", r"data\s+analysis"],
    "results": [r"results?", r"outcomes?"],
    "findings": [r"findings?"],
    "discussion": [r"discussion"],
    "limitations": [r"limitations?"],
    "future_work": [
        r"future\s+work",
        r"future\s+directions?",
        r"future\s+research",
        r"research\s+gaps?",
        r"open\s+questions?",
    ],
    "conclusion": [r"conclusions?", r"summary", r"implications?"],
}


def normalize_space(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def heading_to_key(heading: str) -> str | None:
    normalized = heading.strip().lower()
    normalized = re.sub(r"^\d+(\.\d+)*[.)]?\s+", "", normalized)
    normalized = re.sub(r"^[ivxlcdm]+[.)]\s+", "", normalized)
    normalized = normalize_space(normalized)

    for key, patterns in SECTION_PATTERNS.items():
        if any(re.search(pattern, normalized) for pattern in patterns):
            return key

    return None


def looks_like_heading(line: str) -> bool:
    stripped = line.strip()
    if not stripped or len(stripped) > 120:
        return False
    if stripped.endswith(".") and len(stripped.split()) > 4:
        return False
    if re.match(r"^(\d+(\.\d+)*|[IVXLCDM]+)[.)]?\s+\S+", stripped):
        return True
    if stripped.isupper() and len(stripped.split()) <= 8:
        return True
    return heading_to_key(stripped) is not None and len(stripped.split()) <= 10


def split_sections(text: str) -> list[tuple[str, str, str]]:
    sections: list[tuple[str, str, str]] = []
    current_heading = "body"
    current_key = "body"
    buffer: list[str] = []

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if looks_like_heading(line):
            if buffer:
                sections.append(
                    (current_key, current_heading, normalize_space("\n".join(buffer)))
                )
                buffer = []
            current_heading = line
            current_key = heading_to_key(line) or "body"
            continue

        if line:
            buffer.append(line)

    if buffer:
        sections.append(
            (current_key, current_heading, normalize_space("\n".join(buffer)))
        )

    return [(key, heading, body) for key, heading, body in sections if body]


def prioritized_sections(text: str) -> list[tuple[str, str, str]]:
    sections = split_sections(text)
    if not sections:
        return [("body", "Full text", normalize_space(text))]

    priority = {key: index for index, key in enumerate(SECTION_PRIORITY)}
    return sorted(
        sections,
        key=lambda section: (
            priority.get(section[0], len(priority)),
            sections.index(section),
        ),
    )


def append_bounded(parts: list[str], text: str, max_chars: int) -> bool:
    used = sum(len(part) + 2 for part in parts)
    remaining = max_chars - used
    if remaining <= 0:
        return False
    if len(text) > remaining:
        text = text[:remaining].rsplit(" ", 1)[0].strip()
    if text:
        parts.append(text)
    return used + len(text) < max_chars


def build_knowledge_evidence(
    text: str,
    max_chars: int = DEFAULT_MAX_EVIDENCE_CHARS,
) -> str:
    """Build bounded full-text evidence for knowledge tagging."""
    clean_text = text.strip()
    if not clean_text:
        return ""

    parts: list[str] = []
    for key, heading, body in prioritized_sections(clean_text):
        if not body:
            continue
        label = heading if heading != "body" else key.replace("_", " ").title()
        snippet = f"[{label}]\n{body}"
        if not append_bounded(parts, snippet, max_chars):
            break

    return "\n\n".join(parts)


def read_text_evidence(
    text_path: str,
    max_chars: int = DEFAULT_MAX_EVIDENCE_CHARS,
) -> str:
    if not text_path:
        return ""

    path = Path(text_path).expanduser()
    if not path.exists():
        return ""

    return build_knowledge_evidence(path.read_text(encoding="utf-8"), max_chars)
