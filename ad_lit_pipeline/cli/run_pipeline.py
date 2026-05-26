from __future__ import annotations

import argparse
import os
from pathlib import Path
from dotenv import load_dotenv

from ad_lit_pipeline.core.artifacts import main_pipeline_artifacts
from ad_lit_pipeline.core.manifest import ManifestRecorder, resume_step_from_manifest
from ad_lit_pipeline.core.registry import MAIN_PIPELINE
from ad_lit_pipeline.core.runner import default_trace_dir, run_selected_steps, select_steps
from ad_lit_pipeline.steps.export import mantis
from ad_lit_pipeline.steps.metadata import normalize
from ad_lit_pipeline.steps.screening import rule_based_scope
from ad_lit_pipeline.steps.tagging import audit, generate_rules, normalize_config, tag_papers


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
    topic_contract_path = Path(args.topic_contract) if args.topic_contract else None
    config_path = Path(args.tagging_config) if args.tagging_config else None
    model = args.model or os.getenv("OPENAI_MODEL", "gpt-4o-mini")

    return {
        "normalize_metadata": lambda: normalize.run(
            Path(args.papers), artifacts.normalized_papers_csv
        ),
        "screen_scope": lambda: rule_based_scope.run(
            artifacts.normalized_papers_csv,
            artifacts.scope_screened_csv,
            topic_contract_path or rule_based_scope.DEFAULT_TOPIC_CONTRACT_PATH,
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
            artifacts.scope_screened_csv,
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
    if not args.tagging_config and not args.topic_contract:
        raise ValueError("run requires either --tagging-config or --topic-contract")

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

    topic_contract_path = Path(args.topic_contract) if args.topic_contract else None
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
    run_parser.add_argument("--papers", required=True, help="Input paper metadata CSV.")
    run_parser.add_argument(
        "--tagging-config",
        default=None,
        help="Input YAML file with research topic and tag categories.",
    )
    run_parser.add_argument(
        "--topic-contract",
        default=None,
        help="Input YAML topic contract. Overrides --tagging-config.",
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
