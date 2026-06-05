from __future__ import annotations

import argparse
import csv
import os
from pathlib import Path

from ad_lit_pipeline.core.env import load_dotenv
from ad_lit_pipeline.core.step import StepResult, StepSpec
from ad_lit_pipeline.llm.client import JSONLLMClient, OpenAIResponsesClient
from ad_lit_pipeline.llm.trace import LLMTraceWriter
from ad_lit_pipeline.steps.tagging import audit, tag_papers
from ad_lit_pipeline.steps.tagging.calibrate_topic_contract import (
    DEFAULT_MAX_PRIMARY_PAPERS,
    select_primary_papers_for_calibration,
)
from ad_lit_pipeline.topics.contract import load_topic_contract


STEP = StepSpec(
    name="smoke_test_tagging_contract",
    inputs=[
        "scope_screened_full_text_csv",
        "tagging_config_json",
        "tagging_rules_json",
        "topic_contract_yaml",
    ],
    outputs=["tagging_smoke_test_csv", "tagging_smoke_audit_csv"],
    uses_llm=True,
    description=(
        "Tag a small full-text sample and audit ontology distribution before "
        "tagging the full corpus."
    ),
)

NO_SMOKE_SAMPLE_WARNING = (
    "No included papers had readable extracted full text for the tagging smoke "
    "test; full-corpus tagging will proceed without early distribution audit."
)


def read_rows(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        return list(reader.fieldnames or []), list(reader)


def run(
    papers_path: Path,
    config_path: Path,
    rules_path: Path,
    output_path: Path,
    audit_path: Path,
    model: str,
    topic_contract_path: Path,
    client: JSONLLMClient | None = None,
    trace_dir: Path | None = None,
    max_smoke_test_papers: int = DEFAULT_MAX_PRIMARY_PAPERS,
) -> StepResult:
    input_columns, all_papers = read_rows(papers_path)
    topic_contract = load_topic_contract(topic_contract_path)
    selected_papers, compact_papers = select_primary_papers_for_calibration(
        topic_contract,
        all_papers,
        max_smoke_test_papers,
    )
    if not compact_papers:
        return StepResult(
            step_name=STEP.name,
            inputs={
                "scope_screened_full_text_csv": papers_path,
                "tagging_config_json": config_path,
                "tagging_rules_json": rules_path,
                "topic_contract_yaml": topic_contract_path,
            },
            outputs={
                "tagging_smoke_test_csv": output_path,
                "tagging_smoke_audit_csv": audit_path,
            },
            row_counts={
                "smoke_test_papers_selected": 0,
                "smoke_test_papers_tagged": 0,
                "smoke_test_papers_skipped": 0,
            },
            warnings=[NO_SMOKE_SAMPLE_WARNING],
        )

    config = tag_papers.load_json(config_path)
    rules = tag_papers.load_json(rules_path)
    llm_client = client or OpenAIResponsesClient()
    trace_writer = (
        LLMTraceWriter(trace_dir / STEP.name) if trace_dir is not None else None
    )

    rows = []
    warnings = []
    trace_paths: list[Path] = []
    for index, paper in enumerate(selected_papers, start=1):
        paper_id = paper.get("paper_id") or f"row_{index}"
        print(
            "Smoke-tagging paper "
            f"{index}/{len(selected_papers)} before full tagging: {paper_id}"
        )
        try:
            tagged, call_trace_paths = tag_papers.call_llm(
                paper,
                config,
                rules,
                model,
                llm_client,
                topic_contract,
                trace_writer,
            )
            tag_papers.validate_tagged_row(tagged, config, rules)
            rows.append(tag_papers.flatten_tagged_row(paper, tagged, config))
            trace_paths.extend(call_trace_paths)
        except ValueError as error:
            warning = (
                f"Failed smoke-test tagging for paper {paper_id!r}: {error}"
            )
            warnings.append(warning)
            print(f"  Warning: {warning}")

    tag_papers.write_rows(
        output_path,
        rows,
        config,
        tag_papers.output_columns(input_columns, config),
    )

    try:
        audit_result = audit.run(output_path, config_path, rules_path, audit_path)
    except ValueError as error:
        raise ValueError(
            "Tagging smoke test failed before full-corpus tagging. "
            f"Inspect {audit_path}. {error}"
        ) from error

    return StepResult(
        step_name=STEP.name,
        inputs={
            "scope_screened_full_text_csv": papers_path,
            "tagging_config_json": config_path,
            "tagging_rules_json": rules_path,
            "topic_contract_yaml": topic_contract_path,
        },
        outputs={
            "tagging_smoke_test_csv": output_path,
            "tagging_smoke_audit_csv": audit_path,
        },
        row_counts={
            "smoke_test_papers_selected": len(selected_papers),
            "smoke_test_papers_tagged": len(rows),
            "smoke_test_papers_skipped": len(selected_papers) - len(rows),
            "smoke_test_audit_issues": audit_result.row_counts.get(
                "issues_found",
                0,
            ),
        },
        warnings=warnings,
        trace_paths=trace_paths,
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Smoke-test a generated tagging contract before full tagging."
    )
    parser.add_argument("--papers", required=True, help="Scope-screened full-text CSV.")
    parser.add_argument("--config", required=True, help="Normalized tagging config JSON.")
    parser.add_argument("--rules", required=True, help="Generated tagging rules JSON.")
    parser.add_argument("--output", required=True, help="Smoke-test tagged CSV.")
    parser.add_argument("--audit-output", required=True, help="Smoke-test audit CSV.")
    parser.add_argument("--topic-contract", required=True, help="Topic contract YAML.")
    parser.add_argument(
        "--model",
        default=None,
        help="OpenAI model. Defaults to OPENAI_MODEL or gpt-4o-mini.",
    )
    parser.add_argument(
        "--trace-dir",
        default=None,
        help="Optional directory where LLM prompt/response traces are written.",
    )
    parser.add_argument(
        "--max-smoke-test-papers",
        type=int,
        default=DEFAULT_MAX_PRIMARY_PAPERS,
        help="Maximum full-text papers used for the smoke test.",
    )
    args = parser.parse_args()

    load_dotenv()
    model = args.model or os.getenv("OPENAI_MODEL", "gpt-4o-mini")
    trace_dir = Path(args.trace_dir) if args.trace_dir else None
    result = run(
        Path(args.papers),
        Path(args.config),
        Path(args.rules),
        Path(args.output),
        Path(args.audit_output),
        model,
        Path(args.topic_contract),
        trace_dir=trace_dir,
        max_smoke_test_papers=args.max_smoke_test_papers,
    )

    print(f"Smoke-test papers tagged: {result.row_counts['smoke_test_papers_tagged']}")
    print(f"Wrote {args.output}")
    print(f"Wrote {args.audit_output}")


if __name__ == "__main__":
    main()
