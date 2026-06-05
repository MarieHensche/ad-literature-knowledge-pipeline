from __future__ import annotations

import argparse
import os
from collections.abc import Callable
from pathlib import Path
from dotenv import load_dotenv

from ad_lit_pipeline.core.artifacts import main_pipeline_artifacts
from ad_lit_pipeline.core.manifest import ManifestRecorder, resume_step_from_manifest
from ad_lit_pipeline.core.registry import MAIN_PIPELINE
from ad_lit_pipeline.core.runner import default_trace_dir, run_selected_steps, select_steps
from ad_lit_pipeline.core.step import StepResult
from ad_lit_pipeline.steps.export import mantis
from ad_lit_pipeline.steps.full_text import prepare as prepare_full_text
from ad_lit_pipeline.steps.importers import bibtex, json_metadata, ris
from ad_lit_pipeline.steps.metadata import normalize
from ad_lit_pipeline.steps.screening import rule_based_scope
from ad_lit_pipeline.steps.tagging import (
    audit,
    calibrate_topic_contract,
    generate_rules,
    normalize_config,
    tag_papers,
)


ImporterRun = Callable[[Path, Path], StepResult]

IMPORTERS_BY_SUFFIX: dict[str, ImporterRun] = {
    ".bib": bibtex.run,
    ".bibtex": bibtex.run,
    ".json": json_metadata.run,
    ".jsonl": json_metadata.run,
    ".ris": ris.run,
}

SUPPORTED_PAPERS_FORMATS = [".csv", *sorted(IMPORTERS_BY_SUFFIX)]


def prepare_papers_csv(input_path: Path, imported_csv_path: Path) -> Path:
    suffix = input_path.suffix.lower()
    if suffix == ".csv":
        return input_path

    importer = IMPORTERS_BY_SUFFIX.get(suffix)
    if importer is None:
        supported = ", ".join(SUPPORTED_PAPERS_FORMATS)
        raise ValueError(
            f"Unsupported --papers format: {input_path.suffix or '<none>'}. "
            f"Supported formats: {supported}"
        )

    result = importer(input_path, imported_csv_path)
    print(
        f"Imported {result.row_counts['papers']} paper records from "
        f"{input_path} to {imported_csv_path}"
    )
    return imported_csv_path


def run_normalize_metadata(args: argparse.Namespace) -> StepResult:
    artifacts = main_pipeline_artifacts(args.collection)
    papers_csv = prepare_papers_csv(Path(args.papers), artifacts.raw_papers_csv)
    result = normalize.run(papers_csv, artifacts.normalized_papers_csv)
    result.metadata["original_papers_input"] = str(Path(args.papers))
    if papers_csv != Path(args.papers):
        result.metadata["imported_papers_csv"] = str(papers_csv)
    return result


def explain(collection: str) -> None:
    artifacts = main_pipeline_artifacts(collection)
    print("Main pipeline steps:")
    for step in MAIN_PIPELINE:
        print(f"  - {step}")
    print()
    print("Conventional outputs:")
    for field, value in artifacts.__dict__.items():
        print(f"  {field}: {value}")


def build_step_functions(
    args: argparse.Namespace,
    trace_dir: Path,
) -> dict[str, object]:
    artifacts = main_pipeline_artifacts(args.collection)
    topic_contract_path = Path(args.topic_contract)
    config_path = Path(args.tagging_config) if args.tagging_config else None
    model = args.model or os.getenv("OPENAI_MODEL", "gpt-4o-mini")

    return {
        "normalize_metadata": lambda: run_normalize_metadata(args),
        "screen_scope": lambda: rule_based_scope.run(
            artifacts.normalized_papers_csv,
            artifacts.scope_screened_csv,
            topic_contract_path,
        ),
        "prepare_full_text": lambda: prepare_full_text.run(
            artifacts.scope_screened_csv,
            artifacts.scope_screened_full_text_csv,
            artifacts.full_text_manifest_csv,
            Path(args.full_text_cache_dir).expanduser(),
            args.full_text_email,
            args.core_api_key,
        ),
        "calibrate_topic_contract": lambda: calibrate_topic_contract.run(
            artifacts.scope_screened_full_text_csv,
            topic_contract_path,
            model,
            trace_dir=trace_dir,
            max_primary_papers=args.max_calibration_papers,
        ),
        "normalize_tagging_config": lambda: normalize_config.run(
            artifacts.tagging_config_normalized_json,
            config_path,
            topic_contract_path,
        ),
        "generate_tagging_rules": lambda: generate_rules.run(
            artifacts.tagging_config_normalized_json,
            artifacts.tagging_rules_json,
            model,
            topic_contract_path,
            trace_dir=trace_dir,
        ),
        "tag_papers": lambda: tag_papers.run(
            artifacts.scope_screened_full_text_csv,
            artifacts.tagging_config_normalized_json,
            artifacts.tagging_rules_json,
            artifacts.extraction_filled_csv,
            model,
            topic_contract_path,
            trace_dir=trace_dir,
        ),
        "audit_extraction": lambda: audit.run(
            artifacts.extraction_filled_csv,
            artifacts.tagging_config_normalized_json,
            artifacts.tagging_rules_json,
            artifacts.extraction_audit_csv,
        ),
        "export_mantis": lambda: mantis.run(
            artifacts.extraction_filled_csv,
            artifacts.mantis_ready_csv,
        ),
    }


def run_full_pipeline(args: argparse.Namespace) -> None:
    if not args.topic_contract:
        raise ValueError("run requires --topic-contract")

    if args.resume:
        if not args.run_id:
            raise ValueError("--resume requires --run-id")
        resume_from = resume_step_from_manifest(
            Path("runs") / args.run_id / "manifest.json"
        )
        if resume_from is None:
            print("Nothing to resume; previous manifest has no failed step.")
            return
        args.from_step = resume_from

    topic_contract_path = Path(args.topic_contract)
    model = args.model or os.getenv("OPENAI_MODEL", "gpt-4o-mini")
    manifest = ManifestRecorder.create(
        collection=args.collection,
        pipeline_name="main",
        run_id=args.run_id,
        topic_contract_path=topic_contract_path,
        model=model,
    )
    trace_dir = Path(args.trace_dir) if args.trace_dir else default_trace_dir(manifest)
    selected = select_steps(MAIN_PIPELINE, args.only_step, args.from_step)
    step_functions = build_step_functions(args, trace_dir)

    if args.dry_run:
        print(f"Run id: {manifest.run_id}")
        print(f"Manifest: {manifest.manifest_path}")

    run_selected_steps(selected, step_functions, manifest, args.dry_run)

    artifacts = main_pipeline_artifacts(args.collection)
    print()
    print("Pipeline complete.")
    print(f"Run id: {manifest.run_id}")
    print(f"Manifest: {manifest.manifest_path}")
    print(f"Mantis-ready CSV: {artifacts.mantis_ready_csv}")
    print(f"Audit file: {artifacts.extraction_audit_csv}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the literature knowledge pipeline.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_parser = subparsers.add_parser("run", help="Run the full LLM tagging pipeline.")
    run_parser.add_argument(
        "--papers",
        required=True,
        help="Input paper metadata file (.csv, .bib, .bibtex, .json, .jsonl, or .ris).",
    )
    run_parser.add_argument(
        "--tagging-config",
        default=None,
        help="Legacy YAML tagging config option; orchestrated runs use --topic-contract.",
    )
    run_parser.add_argument(
        "--topic-contract",
        required=True,
        help="Input YAML topic contract for scope and tagging policy.",
    )
    run_parser.add_argument(
        "--collection",
        required=True,
        help="Collection name used to prefix generated outputs.",
    )
    run_parser.add_argument(
        "--model",
        default=None,
        help="OpenAI model. Defaults to OPENAI_MODEL or gpt-4o-mini.",
    )
    run_parser.add_argument(
        "--full-text-email",
        default=os.getenv("UNPAYWALL_EMAIL"),
        help="Email for Unpaywall full-text lookup. Defaults to UNPAYWALL_EMAIL.",
    )
    run_parser.add_argument(
        "--full-text-cache-dir",
        default=str(prepare_full_text.default_cache_dir()),
        help=(
            "External directory for extracted full-text cache. Defaults to "
            "AD_LIT_FULL_TEXT_CACHE or ~/.cache/ad_lit_pipeline/full_text."
        ),
    )
    run_parser.add_argument(
        "--core-api-key",
        default=os.getenv("CORE_API_KEY"),
        help="Optional CORE API key for additional full-text lookup.",
    )
    run_parser.add_argument(
        "--max-calibration-papers",
        type=int,
        default=calibrate_topic_contract.DEFAULT_MAX_PRIMARY_PAPERS,
        help=(
            "Maximum included primary-paper full texts used to calibrate the "
            "topic-contract tagging ontology before tagging."
        ),
    )
    run_parser.add_argument("--run-id", default=None, help="Optional run id.")
    run_parser.add_argument("--dry-run", action="store_true", help="Print selected steps.")
    run_parser.add_argument("--only-step", default=None, help="Run only one step.")
    run_parser.add_argument("--from-step", default=None, help="Run from this step onward.")
    run_parser.add_argument("--resume", action="store_true", help="Resume failed run id.")
    run_parser.add_argument(
        "--trace-dir",
        default=None,
        help="Optional directory where LLM prompt/response traces are written.",
    )

    explain_parser = subparsers.add_parser("explain", help="Explain pipeline steps.")
    explain_parser.add_argument("--collection", default="example", help="Collection name.")
    return parser


def main() -> None:
    load_dotenv()

    parser = build_parser()
    args = parser.parse_args()

    if args.command == "run":
        run_full_pipeline(args)
    elif args.command == "explain":
        explain(args.collection)


if __name__ == "__main__":
    main()
