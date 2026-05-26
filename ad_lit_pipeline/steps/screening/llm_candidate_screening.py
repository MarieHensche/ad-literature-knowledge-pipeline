from __future__ import annotations

import argparse
import csv
import json
import os
from pathlib import Path
from typing import Any

from ad_lit_pipeline.core.step import StepResult, StepSpec
from ad_lit_pipeline.llm.client import JSONLLMClient, OpenAIResponsesClient
from ad_lit_pipeline.llm.schemas import SCREENING_SCHEMA
from ad_lit_pipeline.llm.trace import LLMTraceWriter
from ad_lit_pipeline.prompts.render import render_screen_candidate_prompt
from ad_lit_pipeline.topics.contract import load_topic_contract


STEP = StepSpec(
    name="screen_candidates",
    inputs=["deduped_candidates_jsonl", "topic_contract_yaml"],
    outputs=["candidate_screening_csv"],
    uses_llm=True,
    description="Screen collected paper candidates for topic relevance using an LLM.",
)

SYSTEM_MESSAGE = "You screen literature search candidates as strict JSON."

OUTPUT_COLUMNS = [
    "paper_id",
    "title",
    "year",
    "doi",
    "provider",
    "provider_id",
    "source_rank",
    "source_query",
    "source_query_reason",
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
        "query_index": candidate.get("query_index", ""),
        "query_reason": candidate.get("query_reason", ""),
    }


def call_llm(
    topic_description: str,
    topic_contract: dict[str, Any],
    candidate: dict[str, Any],
    model: str,
    client: JSONLLMClient,
    trace_writer: LLMTraceWriter | None = None,
    call_id: str = "candidate",
) -> tuple[dict[str, str], list[Path]]:
    prompt = render_screen_candidate_prompt(
        topic_contract,
        candidate_for_prompt(candidate),
        topic_description,
    )
    result = client.create_json(
        model=model,
        system_message=SYSTEM_MESSAGE,
        prompt=prompt,
        schema_name="candidate_screening",
        schema=SCREENING_SCHEMA,
        step_name=STEP.name,
        call_id=call_id,
        trace_writer=trace_writer,
    )
    parsed = result.parsed
    output = {
        "decision": str(parsed["decision"]),
        "reason": str(parsed["reason"]),
        "confidence": str(parsed["confidence"]),
    }
    trace_paths = result.trace_paths.as_list() if result.trace_paths else []
    return output, trace_paths


def screen_candidate(
    topic_description: str,
    topic_contract: dict[str, Any],
    candidate: dict[str, Any],
    index: int,
    model: str,
    client: JSONLLMClient,
    trace_writer: LLMTraceWriter | None = None,
) -> tuple[dict[str, str], list[Path]]:
    paper_id = make_paper_id(candidate, index)
    result, trace_paths = call_llm(
        topic_description,
        topic_contract,
        candidate,
        model,
        client,
        trace_writer,
        paper_id,
    )

    return (
        {
            "paper_id": paper_id,
            "title": str(candidate.get("title") or ""),
            "year": str(candidate.get("year") or ""),
            "doi": str(candidate.get("doi") or ""),
            "provider": str(candidate.get("provider") or ""),
            "provider_id": str(candidate.get("provider_id") or ""),
            "source_rank": str(candidate.get("rank") or ""),
            "source_query": str(candidate.get("query") or ""),
            "source_query_reason": str(candidate.get("query_reason") or ""),
            "screening_decision": result["decision"],
            "screening_confidence": result["confidence"],
            "screening_reason": result["reason"],
        },
        trace_paths,
    )


def write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)

    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=OUTPUT_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)


def run(
    input_path: Path,
    topic_description: str,
    output_path: Path,
    model: str,
    topic_contract_path: Path,
    limit: int | None = None,
    client: JSONLLMClient | None = None,
    trace_dir: Path | None = None,
) -> StepResult:
    topic_contract = load_topic_contract(topic_contract_path)
    candidates = read_jsonl(input_path)
    if limit is not None:
        candidates = candidates[:limit]

    llm_client = client or OpenAIResponsesClient()
    trace_writer = LLMTraceWriter(trace_dir) if trace_dir is not None else None
    rows = []
    all_trace_paths: list[Path] = []
    for index, candidate in enumerate(candidates, start=1):
        print(f"Screening candidate {index}/{len(candidates)}: {candidate.get('title')}")
        row, trace_paths = screen_candidate(
            topic_description,
            topic_contract,
            candidate,
            index,
            model,
            llm_client,
            trace_writer,
        )
        rows.append(row)
        all_trace_paths.extend(trace_paths)

    write_csv(output_path, rows)
    included = sum(1 for row in rows if row["screening_decision"] == "include")
    excluded = sum(1 for row in rows if row["screening_decision"] == "exclude")
    return StepResult(
        step_name=STEP.name,
        inputs={
            "deduped_candidates_jsonl": input_path,
            "topic_contract_yaml": topic_contract_path,
        },
        outputs={"candidate_screening_csv": output_path},
        row_counts={
            "screened_candidates": len(rows),
            "included": included,
            "excluded": excluded,
        },
        trace_paths=all_trace_paths,
    )


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
    parser.add_argument(
        "--topic-contract",
        required=True,
        help="Topic contract YAML with screening policy.",
    )
    parser.add_argument(
        "--trace-dir",
        default=None,
        help="Optional directory where prompt/response traces are written.",
    )
    args = parser.parse_args()

    load_dotenv()
    model = args.model or os.getenv("OPENAI_MODEL", "gpt-4o-mini")
    trace_dir = Path(args.trace_dir) if args.trace_dir else None
    result = run(
        Path(args.input),
        args.topic,
        Path(args.output),
        model,
        Path(args.topic_contract),
        args.limit,
        trace_dir=trace_dir,
    )

    print(f"Screened candidates: {result.row_counts['screened_candidates']}")
    print(f"Included: {result.row_counts['included']}")
    print(f"Excluded: {result.row_counts['excluded']}")
    print(f"Wrote {args.output}")
