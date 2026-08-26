from __future__ import annotations

import argparse
import hashlib
import os
import re
from pathlib import Path
from typing import Any

from ad_lit_pipeline.core.env import load_dotenv
from ad_lit_pipeline.core.errors import ValidationError
from ad_lit_pipeline.core.step import StepResult, StepSpec
from ad_lit_pipeline.io.jsonl_io import read_jsonl_objects, write_jsonl
from ad_lit_pipeline.knowledge.files import (
    validate_evidence_excerpts_jsonl,
    validate_findings_jsonl,
    validate_sources_jsonl,
)
from ad_lit_pipeline.knowledge.schemas import (
    DIRECTIONS,
    EVIDENCE_STRENGTHS,
    EXTRACTION_CONFIDENCES,
    EXTRACTION_STATUSES,
    FINDING_TYPES,
)
from ad_lit_pipeline.knowledge.validation import validate_finding
from ad_lit_pipeline.llm.client import JSONLLMClient, OpenAIResponsesClient
from ad_lit_pipeline.llm.trace import LLMTraceWriter
from ad_lit_pipeline.prompts.render import render_extract_knowledge_findings_prompt
from ad_lit_pipeline.topics.contract import load_topic_contract


STEP = StepSpec(
    name="extract_knowledge_findings",
    inputs=["sources_jsonl", "evidence_excerpts_jsonl", "topic_contract"],
    outputs=["findings_jsonl"],
    uses_llm=True,
    description="Extract first-class knowledge Finding records from evidence excerpts.",
)

SYSTEM_MESSAGE = (
    "You extract evidence-grounded scientific findings as strict JSON."
)


def findings_response_schema(topic_ids: list[str]) -> dict[str, Any]:
    """Build the strict LLM response schema for one source's findings."""
    topic_item_schema: dict[str, Any] = {"type": "string"}
    if topic_ids:
        topic_item_schema["enum"] = topic_ids

    finding_schema = {
        "type": "object",
        "properties": {
            "claim_text": {"type": "string"},
            "finding_type": {"type": "string", "enum": list(FINDING_TYPES)},
            "topic_ids": {
                "type": "array",
                "minItems": 1,
                "items": topic_item_schema,
            },
            "method": {"type": "string"},
            "outcome": {"type": "string"},
            "study_context": {"type": "string"},
            "direction": {"type": "string", "enum": list(DIRECTIONS)},
            "evidence_excerpt_ids": {
                "type": "array",
                "minItems": 1,
                "items": {"type": "string"},
            },
            "limitations": {
                "type": "array",
                "items": {"type": "string"},
            },
            "extraction_confidence": {
                "type": "string",
                "enum": list(EXTRACTION_CONFIDENCES),
            },
            "evidence_strength": {
                "type": "string",
                "enum": list(EVIDENCE_STRENGTHS),
            },
            "extraction_status": {
                "type": "string",
                "enum": list(EXTRACTION_STATUSES),
            },
        },
        "required": [
            "claim_text",
            "finding_type",
            "topic_ids",
            "method",
            "outcome",
            "study_context",
            "direction",
            "evidence_excerpt_ids",
            "limitations",
            "extraction_confidence",
            "evidence_strength",
            "extraction_status",
        ],
        "additionalProperties": False,
    }

    return {
        "type": "object",
        "properties": {
            "findings": {
                "type": "array",
                "items": finding_schema,
            }
        },
        "required": ["findings"],
        "additionalProperties": False,
    }


def ordered_topic_ids(topic_contract: dict[str, Any]) -> list[str]:
    """Return topic IDs from the contract in stable prompt order."""
    topic_ids: list[str] = []
    seen: set[str] = set()

    def add(value: object) -> None:
        topic_id = str(value or "").strip()
        if topic_id and topic_id not in seen:
            topic_ids.append(topic_id)
            seen.add(topic_id)

    add(topic_contract.get("topic_id"))
    topic_structure = topic_contract.get("topic_structure", {})
    if isinstance(topic_structure, dict):
        add(topic_structure.get("anchor_topic_id"))
        for topic in topic_structure.get("main_topics", []):
            if isinstance(topic, dict):
                add(topic.get("topic_id"))
        secondary_topics = topic_structure.get("secondary_topics", {})
        if isinstance(secondary_topics, dict):
            for group in secondary_topics.values():
                if not isinstance(group, list):
                    continue
                for topic in group:
                    if isinstance(topic, dict):
                        add(topic.get("secondary_topic_id"))

    return topic_ids


def excerpts_by_source(
    evidence_excerpts: list[dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for excerpt in evidence_excerpts:
        source_id = str(excerpt.get("source_id") or "").strip()
        if source_id:
            grouped.setdefault(source_id, []).append(excerpt)
    return grouped


def stable_finding_id(source_id: str, position: int, finding: dict[str, Any]) -> str:
    """Create a deterministic ID from the source and finding content."""
    safe_source_id = re.sub(r"[^A-Za-z0-9_.-]+", "_", source_id).strip("_")
    safe_source_id = safe_source_id or "source"
    identity = {
        "claim_text": finding.get("claim_text", ""),
        "evidence_excerpt_ids": finding.get("evidence_excerpt_ids", []),
        "method": finding.get("method", ""),
        "outcome": finding.get("outcome", ""),
        "study_context": finding.get("study_context", ""),
    }
    digest = hashlib.sha1(repr(identity).encode("utf-8")).hexdigest()[:12]
    return f"{safe_source_id}_finding_{position:03d}_{digest}"


def finding_record_from_response(
    source_id: str,
    position: int,
    raw_finding: dict[str, Any],
) -> dict[str, Any]:
    """Attach pipeline-owned identity fields to one LLM finding."""
    finding = {
        "finding_id": stable_finding_id(source_id, position, raw_finding),
        "source_id": source_id,
        "claim_text": raw_finding.get("claim_text", ""),
        "finding_type": raw_finding.get("finding_type", ""),
        "topic_ids": raw_finding.get("topic_ids", []),
        "method": raw_finding.get("method", ""),
        "outcome": raw_finding.get("outcome", ""),
        "study_context": raw_finding.get("study_context", ""),
        "direction": raw_finding.get("direction", ""),
        "evidence_excerpt_ids": raw_finding.get("evidence_excerpt_ids", []),
        "limitations": raw_finding.get("limitations", []),
        "extraction_confidence": raw_finding.get("extraction_confidence", ""),
        "evidence_strength": raw_finding.get("evidence_strength", ""),
        "extraction_status": raw_finding.get("extraction_status", ""),
    }
    return finding


def validate_finding_links(
    finding: dict[str, Any],
    *,
    known_topic_ids: set[str],
    known_excerpt_ids: set[str],
) -> None:
    """Validate semantic links that the generic record contract cannot see."""
    validate_finding(finding)

    topic_ids = finding["topic_ids"]
    if not topic_ids:
        raise ValidationError("Finding.topic_ids must contain at least one topic ID.")
    unknown_topic_ids = sorted(set(topic_ids) - known_topic_ids)
    if unknown_topic_ids:
        raise ValidationError(
            "Finding.topic_ids contains unknown topic IDs: "
            + ", ".join(unknown_topic_ids)
        )

    excerpt_ids = finding["evidence_excerpt_ids"]
    if not excerpt_ids:
        raise ValidationError(
            "Finding.evidence_excerpt_ids must contain at least one excerpt ID."
        )
    unknown_excerpt_ids = sorted(set(excerpt_ids) - known_excerpt_ids)
    if unknown_excerpt_ids:
        raise ValidationError(
            "Finding.evidence_excerpt_ids contains unknown excerpt IDs: "
            + ", ".join(unknown_excerpt_ids)
        )


def validate_and_normalize_findings(
    parsed: dict[str, Any],
    source_id: str,
    evidence_excerpts: list[dict[str, Any]],
    topic_ids: list[str],
) -> list[dict[str, Any]]:
    """Convert one LLM response into validated Finding records."""
    raw_findings = parsed.get("findings")
    if not isinstance(raw_findings, list):
        raise ValidationError("Finding extraction response must contain findings list.")

    known_topic_ids = set(topic_ids)
    known_excerpt_ids = {
        str(excerpt.get("excerpt_id") or "").strip()
        for excerpt in evidence_excerpts
        if str(excerpt.get("excerpt_id") or "").strip()
    }
    findings: list[dict[str, Any]] = []
    for position, raw_finding in enumerate(raw_findings, start=1):
        if not isinstance(raw_finding, dict):
            raise ValidationError(f"Finding {position} must be a JSON object.")
        finding = finding_record_from_response(source_id, position, raw_finding)
        try:
            validate_finding_links(
                finding,
                known_topic_ids=known_topic_ids,
                known_excerpt_ids=known_excerpt_ids,
            )
        except ValidationError as exc:
            raise ValidationError(
                f"Finding {position} for source '{source_id}' is invalid: {exc}"
            ) from exc
        findings.append(finding)

    return findings


def call_llm(
    source: dict[str, Any],
    evidence_excerpts: list[dict[str, Any]],
    topic_contract: dict[str, Any],
    topic_ids: list[str],
    model: str,
    client: JSONLLMClient,
    trace_writer: LLMTraceWriter | None = None,
) -> tuple[dict[str, Any], list[Path]]:
    prompt = render_extract_knowledge_findings_prompt(
        topic_contract,
        source,
        evidence_excerpts,
        topic_ids,
    )
    source_id = str(source.get("source_id") or "source")
    result = client.create_json(
        model=model,
        system_message=SYSTEM_MESSAGE,
        prompt=prompt,
        schema_name="knowledge_findings",
        schema=findings_response_schema(topic_ids),
        step_name=STEP.name,
        call_id=source_id,
        trace_writer=trace_writer,
    )
    trace_paths = result.trace_paths.as_list() if result.trace_paths else []
    return result.parsed, trace_paths


def extract_findings_for_source(
    source: dict[str, Any],
    evidence_excerpts: list[dict[str, Any]],
    topic_contract: dict[str, Any],
    model: str,
    client: JSONLLMClient,
    trace_writer: LLMTraceWriter | None = None,
) -> tuple[list[dict[str, Any]], list[Path]]:
    source_id = str(source.get("source_id") or "").strip()
    if not source_id:
        raise ValidationError("Source record has no source_id.")

    topic_ids = ordered_topic_ids(topic_contract)
    parsed, trace_paths = call_llm(
        source,
        evidence_excerpts,
        topic_contract,
        topic_ids,
        model,
        client,
        trace_writer,
    )
    findings = validate_and_normalize_findings(
        parsed,
        source_id,
        evidence_excerpts,
        topic_ids,
    )
    return findings, trace_paths


def run(
    sources_path: Path,
    evidence_excerpts_path: Path,
    output_path: Path,
    topic_contract_path: Path,
    model: str,
    client: JSONLLMClient | None = None,
    trace_dir: Path | None = None,
) -> StepResult:
    """Extract and write findings.jsonl for all sources with evidence excerpts."""
    validate_sources_jsonl(sources_path)
    validate_evidence_excerpts_jsonl(evidence_excerpts_path)
    sources = read_jsonl_objects(sources_path)
    evidence_excerpts = read_jsonl_objects(evidence_excerpts_path)
    topic_contract = load_topic_contract(topic_contract_path)
    grouped_excerpts = excerpts_by_source(evidence_excerpts)
    llm_client = client or OpenAIResponsesClient()
    trace_writer = LLMTraceWriter(trace_dir) if trace_dir is not None else None

    findings: list[dict[str, Any]] = []
    warnings: list[str] = []
    trace_paths: list[Path] = []
    attempted_sources = 0

    for source in sources:
        source_id = str(source.get("source_id") or "").strip()
        source_excerpts = grouped_excerpts.get(source_id, [])
        if not source_excerpts:
            warnings.append(f"Skipped source '{source_id}': no evidence excerpts.")
            continue

        attempted_sources += 1
        try:
            source_findings, paths = extract_findings_for_source(
                source,
                source_excerpts,
                topic_contract,
                model,
                llm_client,
                trace_writer,
            )
            findings.extend(source_findings)
            trace_paths.extend(paths)
        except (ValidationError, ValueError) as error:
            warnings.append(
                f"Failed to extract findings for source '{source_id}': {error}"
            )

    write_jsonl(output_path, findings)
    validate_findings_jsonl(output_path)

    return StepResult(
        step_name=STEP.name,
        inputs={
            "sources_jsonl": sources_path,
            "evidence_excerpts_jsonl": evidence_excerpts_path,
            "topic_contract": topic_contract_path,
        },
        outputs={"findings_jsonl": output_path},
        row_counts={
            "sources": len(sources),
            "sources_with_evidence": attempted_sources,
            "findings": len(findings),
        },
        warnings=warnings,
        trace_paths=trace_paths,
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Extract knowledge-layer Finding records."
    )
    parser.add_argument("--sources", required=True, help="Input sources JSONL.")
    parser.add_argument(
        "--evidence-excerpts",
        required=True,
        help="Input evidence excerpts JSONL.",
    )
    parser.add_argument("--output", required=True, help="Output findings JSONL.")
    parser.add_argument(
        "--topic-contract",
        required=True,
        help="Input YAML topic contract.",
    )
    parser.add_argument(
        "--model",
        default=None,
        help="OpenAI model. Defaults to OPENAI_MODEL or gpt-4o-mini.",
    )
    parser.add_argument("--trace-dir", default=None, help="Optional trace directory.")
    args = parser.parse_args()

    load_dotenv()
    model = args.model or os.getenv("OPENAI_MODEL", "gpt-4o-mini")
    result = run(
        Path(args.sources),
        Path(args.evidence_excerpts),
        Path(args.output),
        Path(args.topic_contract),
        model,
        trace_dir=Path(args.trace_dir) if args.trace_dir else None,
    )

    print(f"Extracted {result.row_counts['findings']} findings")
    print(f"Wrote {args.output}")
    for warning in result.warnings:
        print(f"Warning: {warning}")


if __name__ == "__main__":
    main()
