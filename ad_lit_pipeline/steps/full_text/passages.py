from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ad_lit_pipeline.records import canonical_json
from ad_lit_pipeline.steps.full_text.evidence import heading_to_key, looks_like_heading


REPRESENTATION_SCHEMA_VERSION = "1.0.0"
PASSAGE_SEGMENTATION_VERSION = "1.0.0"
DEFAULT_MAX_PASSAGE_CHARACTERS = 4_000


@dataclass(frozen=True)
class PageSpan:
    page_number: int
    start_char: int
    end_char: int


@dataclass(frozen=True)
class PassageSlice:
    sequence_index: int
    passage_kind: str
    text: str
    start_char: int
    end_char: int
    page_start: int | None
    page_end: int | None
    paragraph_index: int
    section_path: tuple[str, ...]


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def extraction_config_sha256(max_characters: int) -> str:
    return hashlib.sha256(
        canonical_json(
            {
                "segmentation_version": PASSAGE_SEGMENTATION_VERSION,
                "strategy": "document_order_section_paragraph_offsets",
                "max_passage_characters": max_characters,
                "split_preference": "last_whitespace_after_half_window",
            }
        ).encode("utf-8")
    ).hexdigest()


def read_representation_structure(
    path: Path,
    *,
    representation_sha256: str,
) -> tuple[PageSpan, ...]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping):
        raise ValueError("Representation structure must be a JSON object.")
    if payload.get("schema_version") != REPRESENTATION_SCHEMA_VERSION:
        raise ValueError("Unsupported representation structure schema.")
    if payload.get("representation_sha256") != representation_sha256:
        raise ValueError("Representation structure identifies different text.")
    values = payload.get("page_spans")
    if not isinstance(values, list):
        raise ValueError("Representation structure page_spans must be a list.")
    spans: list[PageSpan] = []
    previous_end = 0
    previous_page = 0
    for index, item in enumerate(values):
        if not isinstance(item, Mapping):
            raise ValueError(f"Page span {index} is not an object.")
        page_number = item.get("page_number")
        start = item.get("start_char")
        end = item.get("end_char")
        if (
            isinstance(page_number, bool)
            or not isinstance(page_number, int)
            or page_number <= previous_page
            or isinstance(start, bool)
            or not isinstance(start, int)
            or start < previous_end
            or isinstance(end, bool)
            or not isinstance(end, int)
            or end <= start
        ):
            raise ValueError(f"Page span {index} has invalid coordinates.")
        spans.append(PageSpan(page_number, start, end))
        previous_end = end
        previous_page = page_number
    return tuple(spans)


def _page_range(
    start: int,
    end: int,
    page_spans: Sequence[PageSpan],
) -> tuple[int | None, int | None]:
    pages = [
        span.page_number
        for span in page_spans
        if span.start_char < end and span.end_char > start
    ]
    return (min(pages), max(pages)) if pages else (None, None)


def _bounded_ranges(start: int, end: int, text: str, maximum: int):
    cursor = start
    while cursor < end:
        while cursor < end and text[cursor].isspace():
            cursor += 1
        if cursor >= end:
            return
        boundary = min(cursor + maximum, end)
        if boundary < end:
            preferred = max(
                text.rfind("\n", cursor + maximum // 2, boundary),
                text.rfind(" ", cursor + maximum // 2, boundary),
            )
            if preferred > cursor:
                boundary = preferred
        while boundary > cursor and text[boundary - 1].isspace():
            boundary -= 1
        if boundary <= cursor:
            boundary = min(cursor + maximum, end)
        yield cursor, boundary
        cursor = boundary


def _blocks(text: str) -> list[tuple[int, int]]:
    blocks: list[tuple[int, int]] = []
    cursor = 0
    for separator in re.finditer(r"\n[ \t]*\n", text):
        start = cursor
        end = separator.start()
        while start < end and text[start].isspace():
            start += 1
        while end > start and text[end - 1].isspace():
            end -= 1
        if start < end:
            blocks.append((start, end))
        cursor = separator.end()
    start = cursor
    end = len(text)
    while start < end and text[start].isspace():
        start += 1
    while end > start and text[end - 1].isspace():
        end -= 1
    if start < end:
        blocks.append((start, end))
    return blocks


def _trimmed_range(text: str, start: int, end: int) -> tuple[int, int] | None:
    while start < end and text[start].isspace():
        start += 1
    while end > start and text[end - 1].isspace():
        end -= 1
    return (start, end) if start < end else None


def _structural_units(
    text: str,
) -> list[tuple[int, int, str, str]]:
    units: list[tuple[int, int, str, str]] = []
    current_section = "body"
    current_kind = "paragraph"
    for block_start, block_end in _blocks(text):
        content_start = block_start
        for match in re.finditer(r"[^\n]+", text[block_start:block_end]):
            line_start = block_start + match.start()
            line_end = block_start + match.end()
            line = text[line_start:line_end].strip()
            if not looks_like_heading(line):
                continue
            preceding = _trimmed_range(text, content_start, line_start)
            if preceding is not None:
                units.append((*preceding, current_section, current_kind))
            current_section = line
            current_kind = (
                "abstract" if heading_to_key(line) == "abstract" else "paragraph"
            )
            content_start = line_end
        trailing = _trimmed_range(text, content_start, block_end)
        if trailing is not None:
            units.append((*trailing, current_section, current_kind))
    return units


def passage_slices(
    text: str,
    page_spans: Sequence[PageSpan] = (),
    *,
    max_characters: int = DEFAULT_MAX_PASSAGE_CHARACTERS,
) -> tuple[PassageSlice, ...]:
    if max_characters < 200 or max_characters > 8_000:
        raise ValueError("max_characters must be between 200 and 8000.")
    if not text.strip():
        return ()

    slices: list[PassageSlice] = []
    for paragraph_index, (
        body_start,
        block_end,
        current_section,
        current_kind,
    ) in enumerate(_structural_units(text)):
        for start, end in _bounded_ranges(
            body_start,
            block_end,
            text,
            max_characters,
        ):
            page_start, page_end = _page_range(start, end, page_spans)
            slices.append(
                PassageSlice(
                    sequence_index=len(slices),
                    passage_kind=current_kind,
                    text=text[start:end],
                    start_char=start,
                    end_char=end,
                    page_start=page_start,
                    page_end=page_end,
                    paragraph_index=paragraph_index,
                    section_path=(current_section,),
                )
            )

    if slices:
        return tuple(slices)
    for start, end in _bounded_ranges(0, len(text), text, max_characters):
        page_start, page_end = _page_range(start, end, page_spans)
        slices.append(
            PassageSlice(
                sequence_index=len(slices),
                passage_kind="paragraph",
                text=text[start:end],
                start_char=start,
                end_char=end,
                page_start=page_start,
                page_end=page_end,
                paragraph_index=0,
                section_path=("body",),
            )
        )
    return tuple(slices)
