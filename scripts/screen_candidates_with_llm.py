#!/usr/bin/env python3
"""Screen collected paper candidates for topic relevance using an LLM."""

from __future__ import annotations

import argparse
import csv
import json
import os
from pathlib import Path
from typing import Any

from openai import OpenAI


SCREENING_SCHEMA = {
    "type": "object",
    "properties": {
        "decision": {
            "type": "string",
            "enum": ["include", "exclude"],
        },
        "reason": {"type": "string"},
        "confidence": {
            "type": "string",
            "enum": ["high", "medium", "low"],
        },
    },
    "required": ["decision", "reason", "confidence"],
    "additionalProperties": False,
}


OUTPUT_COLUMNS = [
    "paper_id",
    "title",
    "year",
    "doi",
    "provider",
    "provider_id",
    "source_rank",
    "screening_decision",
    "screening_confidence",
    "screening_reason",
]


def load_dotenv(env_path: Path = Path(".env")) -> None:
    if not env_path.exists():
        return

    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows = []
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            line = line.strip()
            if not line:
                continue

            row = json.loads(line)
            if not isinstance(row, dict):
                raise ValueError(f"Expected JSON object in {path}:{line_number}")

            rows.append(row)

    return rows


def make_paper_id(candidate: dict[str, Any], index: int) -> str:
    doi = str(candidate.get("doi") or "").strip()
    if doi:
        return doi.replace("/", "_").replace(".", "_").replace("-", "_").lower()

    provider_id = str(candidate.get("provider_id") or "").strip()
    if provider_id:
        return (
            provider_id.replace("https://", "")
            .replace("http://", "")
            .replace("/", "_")
            .replace(".", "_")
            .replace("-", "_")
            .lower()
        )

    return f"candidate_{index:04d}"


def candidate_for_prompt(candidate: dict[str, Any]) -> dict[str, Any]:
    return {
        "title": candidate.get("title", ""),
        "year": candidate.get("year", ""),
        "doi": candidate.get("doi", ""),
        "abstract": candidate.get("abstract", ""),
        "authors": candidate.get("authors", ""),
        "venue": candidate.get("venue", ""),
        "provider": candidate.get("provider", ""),
        "query": candidate.get("query", ""),
    }


def build_prompt(topic: str, candidate: dict[str, Any]) -> str:
    return f"""
You are screening scholarly paper candidates for a literature knowledge pipeline.

Topic scope:
{topic}

Candidate paper:
{json.dumps(candidate_for_prompt(candidate), indent=2)}

Decide whether this candidate should enter the literature pipeline.

Use:
- include: the paper is directly about the topic and has enough metadata to justify inclusion.
- exclude: the paper is outside the topic, ambiguous, borderline, missing enough metadata, or would require human review.

Rules:
- Include computational/data-driven papers about early detection, screening, diagnosis, classification, prediction, or distinction of Alzheimer's disease, MCI, dementia, or dementia-related cognitive impairment.
- Exclude papers mainly about treatment, drug discovery, care support, biology/mechanism discovery without detection, or unrelated diseases.
- Exclude reviews if the topic asks for primary studies only. Otherwise, reviews can be included if they are useful candidates.
- If the abstract is missing or the candidate would require human review, choose exclude.
- Give one concise reason.
""".strip()


def call_openai(topic: str, candidate: dict[str, Any], model: str) -> dict[str, str]:
    client = OpenAI()

    response = client.responses.create(
        model=model,
        input=[
            {
                "role": "system",
                "content": "You screen literature search candidates as strict JSON.",
            },
            {
                "role": "user",
                "content": build_prompt(topic, candidate),
            },
        ],
        text={
            "format": {
                "type": "json_schema",
                "name": "candidate_screening",
                "strict": True,
                "schema": SCREENING_SCHEMA,
            }
        },
    )

    result = json.loads(response.output_text)

    if not isinstance(result, dict):
        raise ValueError("Expected JSON object from screening response.")

    return {
        "decision": str(result["decision"]),
        "reason": str(result["reason"]),
        "confidence": str(result["confidence"]),
    }


def screen_candidate(
    topic: str,
    candidate: dict[str, Any],
    index: int,
    model: str,
) -> dict[str, str]:
    result = call_openai(topic, candidate, model)

    return {
        "paper_id": make_paper_id(candidate, index),
        "title": str(candidate.get("title") or ""),
        "year": str(candidate.get("year") or ""),
        "doi": str(candidate.get("doi") or ""),
        "provider": str(candidate.get("provider") or ""),
        "provider_id": str(candidate.get("provider_id") or ""),
        "source_rank": str(candidate.get("rank") or ""),
        "screening_decision": result["decision"],
        "screening_confidence": result["confidence"],
        "screening_reason": result["reason"],
    }


def write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)

    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=OUTPUT_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description="Screen paper candidates with an LLM.")
    parser.add_argument("--input", required=True, help="Input deduplicated candidates JSONL.")
    parser.add_argument("--topic", required=True, help="Topic/scope description.")
    parser.add_argument("--output", required=True, help="Output screening CSV.")
    parser.add_argument("--limit", type=int, default=None, help="Optional candidate limit for testing.")
    parser.add_argument(
        "--model",
        default=None,
        help="OpenAI model. Defaults to OPENAI_MODEL or gpt-4o-mini.",
    )
    args = parser.parse_args()

    load_dotenv()

    model = args.model or os.getenv("OPENAI_MODEL", "gpt-4o-mini")
    candidates = read_jsonl(Path(args.input))

    if args.limit is not None:
        candidates = candidates[: args.limit]

    rows = []
    for index, candidate in enumerate(candidates, start=1):
        print(f"Screening candidate {index}/{len(candidates)}: {candidate.get('title')}")
        rows.append(screen_candidate(args.topic, candidate, index, model))

    write_csv(Path(args.output), rows)

    included = sum(1 for row in rows if row["screening_decision"] == "include")
    excluded = sum(1 for row in rows if row["screening_decision"] == "exclude")

    print(f"Screened candidates: {len(rows)}")
    print(f"Included: {included}")
    print(f"Excluded: {excluded}")
    print(f"Wrote {args.output}")


if __name__ == "__main__":
    main()