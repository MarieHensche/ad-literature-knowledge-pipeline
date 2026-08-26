from __future__ import annotations

from pathlib import Path
from typing import Any

from ad_lit_pipeline.io.json_io import read_json_object
from ad_lit_pipeline.io.jsonl_io import read_jsonl_objects
from ad_lit_pipeline.knowledge.schemas import (
    EVIDENCE_EXCERPT_CONTRACT,
    FINDING_CONTRACT,
    GAP_CONTRACT,
    RELATIONSHIP_CONTRACT,
    SOURCE_CONTRACT,
    SYNTHESIS_CLAIM_CONTRACT,
)
from ad_lit_pipeline.knowledge.validation import (
    validate_field_summary,
    validate_records,
)


def validate_sources_jsonl(path: Path) -> int:
    """Validate a sources JSONL artifact and return its record count."""
    rows = read_jsonl_objects(path)
    validate_records(rows, SOURCE_CONTRACT)
    return len(rows)


def validate_evidence_excerpts_jsonl(path: Path) -> int:
    """Validate an evidence excerpts JSONL artifact and return its record count."""
    rows = read_jsonl_objects(path)
    validate_records(rows, EVIDENCE_EXCERPT_CONTRACT)
    return len(rows)


def validate_findings_jsonl(path: Path) -> int:
    """Validate a findings JSONL artifact and return its record count."""
    rows = read_jsonl_objects(path)
    validate_records(rows, FINDING_CONTRACT)
    return len(rows)


def validate_relationships_jsonl(path: Path) -> int:
    """Validate a relationships JSONL artifact and return its record count."""
    rows = read_jsonl_objects(path)
    validate_records(rows, RELATIONSHIP_CONTRACT)
    return len(rows)


def validate_gaps_jsonl(path: Path) -> int:
    """Validate a gaps JSONL artifact and return its record count."""
    rows = read_jsonl_objects(path)
    validate_records(rows, GAP_CONTRACT)
    return len(rows)


def validate_synthesis_claims_jsonl(path: Path) -> int:
    """Validate a synthesis claims JSONL artifact and return its record count."""
    rows = read_jsonl_objects(path)
    validate_records(rows, SYNTHESIS_CLAIM_CONTRACT)
    return len(rows)


def validate_field_summary_json(path: Path) -> dict[str, Any]:
    """Validate a field summary JSON artifact and return its payload."""
    payload = read_json_object(path)
    validate_field_summary(payload)
    return payload