from __future__ import annotations

import argparse
from pathlib import Path

from ad_lit_pipeline.core.artifacts import collection_artifacts
from ad_lit_pipeline.core.env import load_dotenv
from ad_lit_pipeline.core.manifest import ManifestRecorder, resume_step_from_manifest
from ad_lit_pipeline.core.registry import COLLECTION_PIPELINE
from ad_lit_pipeline.core.runner import default_trace_dir, run_selected_steps, select_steps
from ad_lit_pipeline.steps.collection import deduplicate, export_included, fetch_candidates, plan_search
from ad_lit_pipeline.steps.screening import llm_candidate_screening


def explain(collection: str) -> None:
    artifacts = collection_artifacts(collection)
    print("Collection pipeline steps:")
    for step in COLLECTION_PIPELINE:
        print(f"  - {step}")
    print()
    print("Conventional outputs:")
    for field, value in artifacts.__dict__.items():
        print(f"  {field}: {value}")


def build_step_functions(
    args: argparse.Namespace,
    trace_dir: Path,
) -> dict[str, object]:
    artifacts = collection_artifacts(args.collection)
    topic_contract_path = Path(args.topic_contract)

    return {
        "plan_search": lambda: plan_search.run(
            args.topic,
            artifacts.plan_json,
            args.max_results,
            args.model,
            topic_contract_path,
            trace_dir=trace_dir,
        ),
        "fetch_candidates": lambda: fetch_candidates.run(
            artifacts.plan_json,
            artifacts.candidates_jsonl,
            args.max_results,
        ),
        "deduplicate_candidates": lambda: deduplicate.run(
            [artifacts.candidates_jsonl],
            artifacts.deduped_candidates_jsonl,
        ),
        "screen_candidates": lambda: llm_candidate_screening.run(
            artifacts.deduped_candidates_jsonl,
            args.topic,
            artifacts.candidate_screening_csv,
            args.model,
            topic_contract_path,
            trace_dir=trace_dir,
        ),
        "export_included_candidates": lambda: export_included.run(
            artifacts.deduped_candidates_jsonl,
            artifacts.candidate_screening_csv,
            artifacts.papers_csv,
        ),
    }


def run_collection(args: argparse.Namespace) -> None:
    load_dotenv()

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
    manifest = ManifestRecorder.create(
        collection=args.collection,
        pipeline_name="collection",
        run_id=args.run_id,
        topic_contract_path=topic_contract_path,
        model=args.model,
    )
    trace_dir = Path(args.trace_dir) if args.trace_dir else default_trace_dir(manifest)
    selected = select_steps(COLLECTION_PIPELINE, args.only_step, args.from_step)
    step_functions = build_step_functions(args, trace_dir)

    if args.dry_run:
        print(f"Run id: {manifest.run_id}")
        print(f"Manifest: {manifest.manifest_path}")

    run_selected_steps(selected, step_functions, manifest, args.dry_run)

    artifacts = collection_artifacts(args.collection)
    print()
    print("Collection complete.")
    print(f"Run id: {manifest.run_id}")
    print(f"Manifest: {manifest.manifest_path}")
    print(f"Plan: {artifacts.plan_json}")
    print(f"Candidate papers CSV: {artifacts.papers_csv}")
    print()
    print("Next run:")
    print(
        "python scripts/run_pipeline.py run "
        f"--papers {artifacts.papers_csv} "
        f"--topic-contract {args.topic_contract} "
        f"--collection {args.collection}"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run automated paper collection.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_parser = subparsers.add_parser("run", help="Run the collection workflow.")
    run_parser.add_argument("--topic", required=True, help="Topic description.")
    run_parser.add_argument("--collection", required=True, help="Collection name.")
    run_parser.add_argument(
        "--max-results",
        type=int,
        default=25,
        help="Candidate count to fetch.",
    )
    run_parser.add_argument(
        "--model",
        default="gpt-4o-mini",
        help="OpenAI model for planning and screening.",
    )
    run_parser.add_argument(
        "--topic-contract",
        default="configs/topics/early_detection_ad.yaml",
        help="Topic contract YAML for provider and screening policy.",
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

    explain_parser = subparsers.add_parser("explain", help="Explain collection steps.")
    explain_parser.add_argument("--collection", default="example", help="Collection name.")
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    if args.command == "run":
        run_collection(args)
    elif args.command == "explain":
        explain(args.collection)


if __name__ == "__main__":
    main()
