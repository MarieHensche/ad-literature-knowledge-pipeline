from __future__ import annotations

import re


DEFAULT_MAX_EVIDENCE_CHARS = 24000
MIN_FULL_TEXT_CHARS = 1000

SECTION_PRIORITY = [
    "abstract",
    "conclusion",
    "results",
    "discussion",
    "introduction",
    "background",
    "implications",
    "limitations",
    "methods",
    "data",
    "analysis",
]

SECTION_PATTERNS = {
    "abstract": [
        r"\babstract\b",
        r"\bsummary\b",
    ],
    "conclusion": [
        r"\bconclusions?\b",
        r"\bconcluding remarks?\b",
        r"\bfinal remarks?\b",
    ],
    "results": [
        r"\bresults?\b",
        r"\bfindings?\b",
    ],
    "discussion": [
        r"\bdiscussion\b",
        r"\binterpretation\b",
    ],
    "introduction": [
        r"\bintroduction\b",
    ],
    "background": [
        r"\bbackground\b",
        r"\bliterature review\b",
        r"\brelated work\b",
    ],
    "implications": [
        r"\bimplications?\b",
        r"\bpolicy implications?\b",
        r"\bpractical implications?\b",
    ],
    "limitations": [
        r"\blimitations?\b",
        r"\bstrengths and limitations\b",
    ],
    "methods": [
        r"\bmethods?\b",
        r"\bmethodolog(?:y|ical)\b",
        r"\bmaterials?\s+(?:and\s+)?methods?\b",
        r"\bstudy design\b",
        r"\bresearch design\b",
        r"\bexperimental design\b",
        r"\bprocedure\b",
        r"\bprotocol\b",
    ],
    "data": [
        r"\bdata\b",
        r"\bdatasets?\b",
        r"\bparticipants?\b",
        r"\bsamples?\b",
        r"\bmeasures?\b",
        r"\bvariables?\b",
    ],
    "analysis": [
        r"\banalys(?:is|es)\b",
        r"\banalytic(?:al)? approach\b",
        r"\bstatistical analysis\b",
    ],
}


def clean_text(value: str) -> str:
    text = value.replace("\x00", " ")
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def normalize_heading(value: str) -> str:
    text = value.strip()
    text = re.sub(r"^(?:section\s+)?\d+(?:\.\d+)*\.?\s+", "", text, flags=re.I)
    text = re.sub(r"^[^\w]+|[^\w]+$", "", text)
    text = text.lower()
    text = re.sub(r"[_/\\&-]+", " ", text)
    text = re.sub(r"[^a-z0-9 ]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def is_possible_heading(value: str) -> bool:
    raw = value.strip()
    if not raw or len(raw) > 140:
        return False

    normalized = normalize_heading(raw)
    token_count = len(normalized.split())
    if not normalized or token_count > 12:
        return False

    if raw.endswith((".", "?", "!")) and token_count > 2:
        return False

    return True


def section_key_for_heading(value: str) -> str | None:
    if not is_possible_heading(value):
        return None

    heading = normalize_heading(value)
    for section in SECTION_PRIORITY:
        for pattern in SECTION_PATTERNS[section]:
            if re.search(pattern, heading):
                return section
    return None


def section_chunks(text: str) -> list[tuple[str, str]]:
    matches = [
        (match, section_key)
        for match in re.finditer(r"(?m)^(.+)$", text)
        if (section_key := section_key_for_heading(match.group(1))) is not None
    ]
    if not matches:
        return []

    chunks: list[tuple[str, str]] = []
    for index, (match, section_key) in enumerate(matches):
        start = match.end()
        end = matches[index + 1][0].start() if index + 1 < len(matches) else len(text)
        body = text[start:end].strip()
        if body:
            chunks.append((section_key, body))
    return chunks


def build_full_text_evidence(
    full_text: str,
    max_chars: int = DEFAULT_MAX_EVIDENCE_CHARS,
) -> str:
    """Build bounded full-text evidence for knowledge tagging."""
    cleaned = clean_text(full_text)
    if len(cleaned) <= max_chars:
        return cleaned

    chunks = section_chunks(cleaned)
    if not chunks:
        return cleaned[:max_chars].rstrip() + "\n\n[Full text truncated.]"

    selected: list[str] = []
    used_chars = 0
    seen_sections: set[str] = set()

    for wanted in SECTION_PRIORITY:
        for heading, body in chunks:
            if heading in seen_sections:
                continue
            if heading != wanted:
                continue

            section_text = f"{heading.upper()}\n{body}"
            remaining = max_chars - used_chars
            if remaining <= 0:
                break
            if len(section_text) > remaining:
                section_text = section_text[:remaining].rstrip()
            selected.append(section_text)
            used_chars += len(section_text)
            seen_sections.add(heading)
        if used_chars >= max_chars:
            break

    if not selected:
        return cleaned[:max_chars].rstrip() + "\n\n[Full text truncated.]"

    evidence = "\n\n".join(selected).strip()
    if len(evidence) >= max_chars or len(evidence) < len(cleaned):
        evidence += "\n\n[Full text evidence selected from a longer paper.]"
    return evidence
