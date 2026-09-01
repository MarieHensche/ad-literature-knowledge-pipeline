from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Callable
from pathlib import Path
from dotenv import load_dotenv

from ad_lit_pipeline.core.artifacts import (
    collection_artifacts,
    knowledge_artifacts,
    main_pipeline_artifacts,
)
from ad_lit_pipeline.core.manifest import (
    ManifestRecorder,
    recorded_selected_steps,
    resume_step_from_manifest,
    resume_steps_from_manifest,
)
from ad_lit_pipeline.core.provenance import build_run_provenance
from ad_lit_pipeline.core.registry import (
    KNOWLEDGE_FINDINGS_PIPELINE,
    KNOWLEDGE_PIPELINE,
    MAIN_PIPELINE,
    MainPipelineOptions,
    REVIEW_PIPELINE,
    assemble_main_pipeline,
)
from ad_lit_pipeline.core.runner import (
    attempt_trace_dir,
    default_trace_dir,
    run_selected_steps,
    select_steps,
)
from ad_lit_pipeline.core.step import StepResult
from ad_lit_pipeline.steps.export import mantis
from ad_lit_pipeline.steps.full_text import prepare as prepare_full_text
from ad_lit_pipeline.steps.importers import bibtex, json_metadata, ris
from ad_lit_pipeline.steps.knowledge import (
    export_evidence_excerpts as knowledge_evidence_excerpts,
    export_sources as knowledge_sources,
    extract_findings as knowledge_findings,
)
from ad_lit_pipeline.steps.metadata import normalize
from ad_lit_pipeline.steps.review import assemble_review as review_assemble
from ad_lit_pipeline.steps.review import config as review_config
from ad_lit_pipeline.steps.review import coverage_report as review_coverage_report
from ad_lit_pipeline.steps.review import edit_sections as review_edit_sections
from ad_lit_pipeline.steps.review import evidence_map as review_evidence_map
from ad_lit_pipeline.steps.review import extract_labels as review_extract_labels
from ad_lit_pipeline.steps.review import filter_papers as review_filter_papers
from ad_lit_pipeline.steps.review import label_value_review as review_label_review
from ad_lit_pipeline.steps.review import label_values as review_label_values
from ad_lit_pipeline.steps.review import synthesize_sections as review_synthesize
from ad_lit_pipeline.steps.review import validate_labels as review_validate_labels
from ad_lit_pipeline.steps.screening import rule_based_scope
from ad_lit_pipeline.steps.tagging import (
    audit,
    calibrate_topic_contract,
    generate_rules,
    normalize_config,
    review_categories,
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
    knowledge_paths = knowledge_artifacts(collection)
    print("Main pipeline steps:")
    for step in MAIN_PIPELINE:
        print(f"  - {step}")
    print()
    print("Optional main-time calibration step:")
    print("  - calibrate_topic_contract")
    print()
    print("Optional human review step:")
    print("  - review_tagging_categories")
    print()
    print("Optional knowledge export steps:")
    for step in KNOWLEDGE_PIPELINE:
        print(f"  - {step}")
    print()
    print("Optional knowledge finding extraction step:")
    print("  - extract_knowledge_findings")
    print()
    print("Optional literature-review generation steps:")
    for step in REVIEW_PIPELINE:
        print(f"  - {step}")
    print("Optional literature-review label-value review step:")
    print("  - review_review_label_values")
    print()
    print("Conventional outputs:")
    for field, value in artifacts.__dict__.items():
        print(f"  {field}: {value}")
    for field, value in knowledge_paths.__dict__.items():
        print(f"  {field}: {value}")


def selected_main_pipeline(args: argparse.Namespace) -> list[str]:
    requested_step = args.only_step or args.from_step
    return list(
        assemble_main_pipeline(
            MainPipelineOptions(
                calibrate_topic_contract=args.calibrate_topic_contract,
                review_tagging_categories=args.review_tagging_categories,
                export_knowledge=args.export_knowledge,
                extract_knowledge_findings=args.extract_knowledge_findings,
                extract_review_labels=args.extract_review_labels,
                generate_review=args.generate_review,
                review_review_label_values=args.review_review_label_values,
                requested_step=requested_step,
            )
        )
    )


def review_label_extraction_enabled(args: argparse.Namespace) -> bool:
    return (
        args.generate_review
        or args.extract_review_labels
        or args.review_review_label_values
    )


def build_step_functions(
    args: argparse.Namespace,
    trace_dir: Path,
) -> dict[str, object]:
    artifacts = main_pipeline_artifacts(args.collection)
    knowledge_paths = knowledge_artifacts(args.collection)
    collection_paths = collection_artifacts(
        args.collection,
        prefer_existing_legacy=True,
    )
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
        "export_knowledge_sources": lambda: knowledge_sources.run(
            artifacts.scope_screened_full_text_csv,
            knowledge_paths.sources_jsonl,
        ),
        "export_knowledge_evidence_excerpts": lambda: knowledge_evidence_excerpts.run(
            artifacts.scope_screened_full_text_csv,
            knowledge_paths.evidence_excerpts_jsonl,
        ),
        "extract_knowledge_findings": lambda: knowledge_findings.run(
            knowledge_paths.sources_jsonl,
            knowledge_paths.evidence_excerpts_jsonl,
            knowledge_paths.findings_jsonl,
            topic_contract_path,
            model,
            trace_dir=trace_dir,
        ),
        "calibrate_topic_contract": lambda: calibrate_topic_contract.run(
            artifacts.scope_screened_full_text_csv,
            topic_contract_path,
            model,
            trace_dir=trace_dir,
            max_primary_papers=args.max_calibration_papers,
        ),
        "review_tagging_categories": lambda: review_categories.run(
            topic_contract_path,
            artifacts.tagging_categories_review_yaml,
            model,
            review_overviews_path=collection_paths.review_overviews_full_text_jsonl,
            papers_path=artifacts.scope_screened_full_text_csv,
            trace_dir=trace_dir,
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
            review_config_path=(
                artifacts.review_config_normalized_json
                if review_label_extraction_enabled(args)
                else None
            ),
            review_output_path=(
                artifacts.review_labels_raw_csv
                if review_label_extraction_enabled(args)
                else None
            ),
            review_papers_path=(
                artifacts.review_eligible_papers_csv
                if review_label_extraction_enabled(args)
                else None
            ),
            review_max_papers=args.review_max_papers,
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
        "normalize_review_config": lambda: review_config.run(
            topic_contract_path,
            artifacts.review_config_normalized_json,
        ),
        "filter_review_papers": lambda: review_filter_papers.run(
            artifacts.scope_screened_full_text_csv,
            artifacts.review_eligible_papers_csv,
            artifacts.review_filter_report_json,
        ),
        "extract_review_labels": lambda: review_extract_labels.run(
            artifacts.review_eligible_papers_csv,
            artifacts.review_config_normalized_json,
            artifacts.review_labels_raw_csv,
            model,
            trace_dir=trace_dir,
            max_papers=args.review_max_papers,
        ),
        "normalize_review_label_values": lambda: review_label_values.run(
            artifacts.review_labels_raw_csv,
            artifacts.review_config_normalized_json,
            artifacts.review_label_values_json,
        ),
        "review_review_label_values": lambda: review_label_review.run(
            artifacts.review_label_values_json,
            artifacts.review_label_values_review_yaml,
        ),
        "validate_review_labels": lambda: review_validate_labels.run(
            artifacts.review_labels_raw_csv,
            artifacts.review_label_values_json,
            artifacts.review_quality_report_csv,
        ),
        "build_review_coverage_report": lambda: review_coverage_report.run(
            artifacts.review_eligible_papers_csv,
            artifacts.review_labels_raw_csv,
            artifacts.review_label_values_json,
            artifacts.review_quality_report_csv,
            artifacts.review_coverage_report_json,
            artifacts.review_filter_report_json,
        ),
        "build_review_evidence_map": lambda: review_evidence_map.run(
            artifacts.review_labels_raw_csv,
            artifacts.review_label_values_json,
            artifacts.review_quality_report_csv,
            artifacts.review_evidence_map_json,
            artifacts.review_filter_report_json,
        ),
        "synthesize_review_sections": lambda: review_synthesize.run(
            artifacts.review_evidence_map_json,
            artifacts.review_sections_json,
            model,
            trace_dir=trace_dir,
        ),
        "edit_review_sections": lambda: review_edit_sections.run(
            artifacts.review_evidence_map_json,
            artifacts.review_sections_json,
            artifacts.review_edited_sections_json,
            model,
            trace_dir=trace_dir,
        ),
        "assemble_literature_review": lambda: review_assemble.run(
            (
                artifacts.review_edited_sections_json
                if artifacts.review_edited_sections_json.exists()
                else artifacts.review_sections_json
            ),
            artifacts.literature_review_md,
            artifacts.literature_review_latex_dir,
        ),
    }


def run_full_pipeline(args: argparse.Namespace) -> None:
    if not args.topic_contract:
        raise ValueError("run requires --topic-contract")

    resume_manifest_path: Path | None = None
    if args.resume:
        if not args.run_id:
            raise ValueError("--resume requires --run-id")
        if args.dry_run:
            raise ValueError("--resume cannot be combined with --dry-run")
        if args.only_step or args.from_step:
            raise ValueError(
                "--resume uses the original selected steps and cannot be combined "
                "with --only-step or --from-step"
            )
        resume_manifest_path = Path("runs") / args.run_id / "manifest.json"
        resume_payload = ManifestRecorder.load(resume_manifest_path)
        resume_from = resume_step_from_manifest(resume_manifest_path)
        if resume_from is None and (
            resume_payload.get("status") in {"succeeded", "dry_run"}
            or recorded_selected_steps(resume_payload) is None
        ):
            print("Nothing to resume; the original selection has no incomplete step.")
            return
        if resume_from is not None:
            args.from_step = resume_from

    topic_contract_path = Path(args.topic_contract)
    model = args.model or os.getenv("OPENAI_MODEL", "gpt-4o-mini")
    pipeline = selected_main_pipeline(args)
    selected = select_steps(
        pipeline,
        args.only_step,
        args.from_step,
    )
    if resume_manifest_path is not None:
        selected = resume_steps_from_manifest(
            resume_manifest_path,
            fallback_steps=selected,
        )
    provenance = build_run_provenance(
        project_root=Path.cwd(),
        argv=sys.argv,
        options=vars(args),
        selected_steps=selected,
        pipeline_steps=pipeline,
        topic_contract_path=topic_contract_path,
        model=model,
    )
    manifest = ManifestRecorder.create(
        collection=args.collection,
        pipeline_name="main",
        run_id=args.run_id,
        topic_contract_path=topic_contract_path,
        model=model,
        provenance=provenance,
        resume=args.resume,
    )
    trace_dir = (
        attempt_trace_dir(manifest, Path(args.trace_dir))
        if args.trace_dir
        else default_trace_dir(manifest)
    )
    step_functions = build_step_functions(args, trace_dir)

    if args.dry_run:
        print(f"Run id: {manifest.run_id}")
        print(f"Manifest: {manifest.manifest_path}")

    status = run_selected_steps(selected, step_functions, manifest, args.dry_run)
    if status == "paused":
        artifacts = main_pipeline_artifacts(args.collection)
        paused_step = None
        if manifest.payload.get("steps"):
            paused_step = manifest.payload["steps"][-1].get("step_name")
        print()
        if paused_step == "review_review_label_values":
            print("Pipeline paused for review label-value review.")
            print(f"Run id: {manifest.run_id}")
            print(f"Manifest: {manifest.manifest_path}")
            print(f"Review file: {artifacts.review_label_values_review_yaml}")
            return

        if paused_step == "build_review_coverage_report":
            print("Pipeline paused for critical literature-review coverage.")
            print(f"Run id: {manifest.run_id}")
            print(f"Manifest: {manifest.manifest_path}")
            print(f"Coverage report: {artifacts.review_coverage_report_json}")
            return

        print("Pipeline paused for tagging category review.")
        print(f"Run id: {manifest.run_id}")
        print(f"Manifest: {manifest.manifest_path}")
        print(f"Review file: {artifacts.tagging_categories_review_yaml}")
        return

    artifacts = main_pipeline_artifacts(args.collection)
    print()
    print("Pipeline complete.")
    print(f"Run id: {manifest.run_id}")
    print(f"Manifest: {manifest.manifest_path}")
    print(f"Mantis-ready CSV: {artifacts.mantis_ready_csv}")
    print(f"Audit file: {artifacts.extraction_audit_csv}")
    if args.generate_review:
        print(f"Literature review Markdown: {artifacts.literature_review_md}")
        print(f"Literature review LaTeX: {artifacts.literature_review_latex_dir}")
    elif args.extract_review_labels:
        print(f"Review labels CSV: {artifacts.review_labels_raw_csv}")
    knowledge_paths = knowledge_artifacts(args.collection)
    if "export_knowledge_sources" in selected:
        print(f"Sources JSONL: {knowledge_paths.sources_jsonl}")
    if "export_knowledge_evidence_excerpts" in selected:
        print(f"Evidence excerpts JSONL: {knowledge_paths.evidence_excerpts_jsonl}")
    if "extract_knowledge_findings" in selected:
        print(f"Findings JSONL: {knowledge_paths.findings_jsonl}")


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
            "topic-contract tagging ontology before tagging when "
            "--calibrate-topic-contract is enabled."
        ),
    )
    run_parser.add_argument(
        "--calibrate-topic-contract",
        action="store_true",
        help=(
            "Opt into legacy main-pipeline contract calibration against "
            "selected included primary-paper full texts."
        ),
    )
    run_parser.add_argument(
        "--review-tagging-categories",
        action="store_true",
        help=(
            "Pause before tagging-rule generation so the user can review and "
            "edit tagging categories and values."
        ),
    )
    run_parser.add_argument(
        "--export-knowledge",
        action="store_true",
        help=(
            "Export knowledge-layer sources.jsonl and evidence_excerpts.jsonl "
            "after full-text preparation."
        ),
    )
    run_parser.add_argument(
        "--extract-knowledge-findings",
        action="store_true",
        help=(
            "Extract LLM-based findings.jsonl after exporting knowledge-layer "
            "sources and evidence excerpts."
        ),
    )
    run_parser.add_argument(
        "--extract-review-labels",
        action="store_true",
        help=(
            "Opt into optional literature-review label extraction. This writes "
            "review-only artifacts without changing the Mantis export."
        ),
    )
    run_parser.add_argument(
        "--generate-review",
        action="store_true",
        help=(
            "Opt into optional literature-review generation. This implies "
            "--extract-review-labels."
        ),
    )
    run_parser.add_argument(
        "--review-review-label-values",
        action="store_true",
        help=(
            "Pause for a human review of auto-discovered literature-review "
            "label values before review synthesis."
        ),
    )
    run_parser.add_argument(
        "--review-max-papers",
        type=int,
        default=None,
        help=(
            "Maximum included full-text papers to use for review generation. "
            "Omit to allow all included papers."
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
