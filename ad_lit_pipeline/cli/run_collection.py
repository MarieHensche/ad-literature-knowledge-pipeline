from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from ad_lit_pipeline.core.artifacts import collection_artifacts
from ad_lit_pipeline.core.env import load_dotenv
from ad_lit_pipeline.core.manifest import (
    ManifestRecorder,
    recorded_selected_steps,
    resume_step_from_manifest,
    resume_steps_from_manifest,
)
from ad_lit_pipeline.core.provenance import build_run_provenance
from ad_lit_pipeline.core.registry import (
    COLLECTION_PIPELINE,
    CollectionPipelineOptions,
    CONTRACT_BOOTSTRAP_PIPELINE,
    assemble_collection_pipeline,
)
from ad_lit_pipeline.core.runner import (
    attempt_trace_dir,
    default_trace_dir,
    run_selected_steps,
    select_steps,
)
from ad_lit_pipeline.core.step import StepResult
from ad_lit_pipeline.steps.full_text import prepare as prepare_full_text
from ad_lit_pipeline.topics.contract import load_topic_contract


SEARCH_BUDGET_HARD_CAP = 5000
SEARCH_BUDGET_MINIMUM = 30
SEARCH_BUDGET_MULTIPLIER = 4
DEFAULT_MAX_REVIEW_OVERVIEWS = 5
DEFAULT_MAX_CALIBRATION_PAPERS = 3
DEFAULT_BASE_CONTRACT = (
    Path(__file__).resolve().parents[2]
    / "configs"
    / "topics"
    / "topic_contract_template.yaml"
)


def candidate_search_budget(max_results: int | None) -> int | None:
    if max_results is None:
        return None
    return min(
        max(SEARCH_BUDGET_MINIMUM, max_results * SEARCH_BUDGET_MULTIPLIER),
        SEARCH_BUDGET_HARD_CAP,
    )


def explain(collection: str) -> None:
    artifacts = collection_artifacts(collection)
    print("Collection pipeline steps:")
    for step in COLLECTION_PIPELINE:
        print(f"  - {step}")
    print()
    print("Optional contract-bootstrap steps:")
    print("  - generate_topic_contract")
    print("  - fetch_review_overviews")
    print("  - prepare_review_full_text")
    print("  - refine_topic_contract")
    print()
    print("Conventional outputs:")
    for field, value in artifacts.__dict__.items():
        print(f"  {field}: {value}")


def generated_topic_contract_path(collection: str) -> Path:
    return Path("data") / "collection_plans" / f"{collection}_topic_contract.yaml"


def resolve_topic_contract_path(args: argparse.Namespace) -> Path:
    if args.topic_contract:
        return Path(args.topic_contract)
    return generated_topic_contract_path(args.collection)


def selected_collection_pipeline(args: argparse.Namespace) -> list[str]:
    requested_step = args.only_step or args.from_step
    return list(
        assemble_collection_pipeline(
            CollectionPipelineOptions(
                generate_topic_contract=args.generate_topic_contract,
                topic_contract_supplied=bool(args.topic_contract),
                contract_bootstrap_only=args.contract_bootstrap_only,
                requested_step=requested_step,
            )
        )
    )


def topic_description_from_contract(topic_contract_path: Path) -> str:
    """Derive collection prompt text from a reviewed topic contract."""
    contract = load_topic_contract(topic_contract_path)
    research_topic = contract["research_topic"]
    return (
        f"{research_topic['title']}\n\n{research_topic['description']}"
    ).strip()


def resolve_topic_description(
    args: argparse.Namespace,
    topic_contract_path: Path,
    selected_steps: list[str],
) -> str:
    """Return user topic text, or derive it from the contract when possible."""
    if args.topic:
        return args.topic.strip()

    if "generate_topic_contract" in selected_steps:
        raise ValueError("--topic is required when generating a topic contract.")

    return topic_description_from_contract(topic_contract_path)


def build_step_functions(
    args: argparse.Namespace,
    trace_dir: Path,
    topic_contract_path: Path,
    topic_description: str,
    producing_run_id: str,
) -> dict[str, object]:
    artifacts = collection_artifacts(
        args.collection,
        prefer_existing_legacy=bool(
            args.resume or args.only_step or args.from_step
        ),
    )

    def full_text_availability_required() -> bool:
        from ad_lit_pipeline.steps.collection import verify_full_text_availability

        return (
            args.require_full_text_availability
            or verify_full_text_availability.full_text_required_from_contract(
                topic_contract_path
            )
        )

    def run_generate_topic_contract() -> object:
        from ad_lit_pipeline.steps.collection import generate_topic_contract

        return generate_topic_contract.run(
            topic_description,
            topic_contract_path,
            args.model,
            Path(args.base_contract),
            trace_dir=trace_dir,
            overwrite=args.overwrite_topic_contract,
        )

    def run_fetch_review_overviews() -> object:
        from ad_lit_pipeline.steps.collection import fetch_review_overviews

        return fetch_review_overviews.run(
            topic_contract_path,
            artifacts.review_overviews_jsonl,
            args.max_review_overviews,
            mailto=args.mailto,
            provider_evidence_index_path=(
                artifacts.review_provider_evidence_index_jsonl
            ),
            provider_response_pages_dir=(
                artifacts.review_provider_response_pages_dir
            ),
        )

    def run_prepare_review_full_text() -> object:
        from ad_lit_pipeline.steps.collection import prepare_review_full_text

        return prepare_review_full_text.run(
            artifacts.review_overviews_jsonl,
            artifacts.review_overviews_full_text_jsonl,
            artifacts.review_full_text_manifest_csv,
            Path(args.full_text_cache_dir).expanduser(),
            args.full_text_email,
            args.core_api_key,
        )

    def run_refine_topic_contract() -> object:
        from ad_lit_pipeline.steps.collection import refine_topic_contract

        review_overviews_path = (
            artifacts.review_overviews_full_text_jsonl
            if artifacts.review_overviews_full_text_jsonl.exists()
            else artifacts.review_overviews_jsonl
        )
        return refine_topic_contract.run(
            topic_description,
            topic_contract_path,
            review_overviews_path,
            args.model,
            trace_dir=trace_dir,
            max_review_overviews=args.max_review_overviews,
        )

    def run_plan_search() -> object:
        from ad_lit_pipeline.steps.collection import plan_search

        return plan_search.run(
            topic_description,
            artifacts.plan_json,
            args.max_results,
            args.model,
            topic_contract_path,
            trace_dir=trace_dir,
            require_full_text_availability=full_text_availability_required(),
        )

    def run_fetch_candidates() -> object:
        from ad_lit_pipeline.steps.collection import fetch_candidates

        return fetch_candidates.run(
            artifacts.plan_json,
            artifacts.candidates_jsonl,
            args.max_results,
            mailto=args.mailto,
            provider_evidence_index_path=(
                artifacts.provider_evidence_index_jsonl
            ),
            provider_response_pages_dir=(
                artifacts.provider_response_pages_dir
            ),
        )

    def run_deduplicate_candidates() -> object:
        from ad_lit_pipeline.steps.collection import deduplicate

        return deduplicate.run(
            [artifacts.candidates_jsonl],
            artifacts.deduped_candidates_jsonl,
        )

    def run_screen_title_relevance() -> object:
        from ad_lit_pipeline.steps.screening import title_relevance

        return title_relevance.run(
            artifacts.deduped_candidates_jsonl,
            artifacts.candidate_screening_csv,
            args.model,
            topic_contract_path,
            limit=args.max_results,
            trace_dir=trace_dir,
            defer_llm_until_full_text=full_text_availability_required(),
        )

    def run_verify_full_text_availability() -> object:
        from ad_lit_pipeline.steps.collection import verify_full_text_availability

        return verify_full_text_availability.run(
            artifacts.deduped_candidates_jsonl,
            artifacts.candidate_screening_csv,
            artifacts.full_text_availability_csv,
            topic_contract_path,
            require_full_text_availability=full_text_availability_required(),
            timeout_seconds=args.full_text_availability_timeout,
            workers=args.full_text_availability_workers,
            unpaywall_email=args.full_text_email,
            core_api_key=args.core_api_key,
        )

    def run_backfill_candidates() -> object:
        from ad_lit_pipeline.steps.collection import backfill_candidates

        return backfill_candidates.run(
            artifacts.plan_json,
            artifacts.candidates_jsonl,
            artifacts.deduped_candidates_jsonl,
            artifacts.candidate_screening_csv,
            topic_contract_path,
            args.model,
            args.max_results,
            mailto=args.mailto,
            trace_dir=trace_dir,
            availability_path=artifacts.full_text_availability_csv,
            require_full_text_availability=full_text_availability_required(),
            full_text_availability_timeout=args.full_text_availability_timeout,
            full_text_availability_workers=args.full_text_availability_workers,
            unpaywall_email=args.full_text_email,
            core_api_key=args.core_api_key,
            provider_evidence_index_path=(
                artifacts.provider_evidence_index_jsonl
            ),
            provider_response_pages_dir=(
                artifacts.provider_response_pages_dir
            ),
        )

    def run_select_calibration_papers() -> object:
        from ad_lit_pipeline.steps.collection import select_calibration_papers

        return select_calibration_papers.run(
            artifacts.deduped_candidates_jsonl,
            artifacts.candidate_screening_csv,
            artifacts.calibration_papers_csv,
            args.max_calibration_papers,
        )

    def run_prepare_calibration_full_text() -> object:
        try:
            result = prepare_full_text.run(
                artifacts.calibration_papers_csv,
                artifacts.calibration_papers_full_text_csv,
                artifacts.calibration_full_text_manifest_csv,
                Path(args.full_text_cache_dir).expanduser(),
                args.full_text_email,
                args.core_api_key,
            )
        except Exception as error:
            return StepResult(
                step_name="prepare_calibration_full_text",
                inputs={"calibration_papers_csv": artifacts.calibration_papers_csv},
                outputs={
                    "calibration_papers_full_text_csv": (
                        artifacts.calibration_papers_full_text_csv
                    ),
                    "calibration_full_text_manifest_csv": (
                        artifacts.calibration_full_text_manifest_csv
                    ),
                },
                warnings=[
                    "Collection-time calibration full-text preparation failed; "
                    "the collection will continue with the review-refined "
                    f"contract. Error: {error}"
                ],
                metadata={"calibration_skipped": True},
            )
        result.step_name = "prepare_calibration_full_text"
        result.inputs = {"calibration_papers_csv": artifacts.calibration_papers_csv}
        result.outputs = {
            "calibration_papers_full_text_csv": (
                artifacts.calibration_papers_full_text_csv
            ),
            "calibration_full_text_manifest_csv": (
                artifacts.calibration_full_text_manifest_csv
            ),
        }
        return result

    def run_calibrate_topic_contract() -> object:
        from ad_lit_pipeline.steps.tagging import calibrate_topic_contract

        try:
            result = calibrate_topic_contract.run(
                artifacts.calibration_papers_full_text_csv,
                topic_contract_path,
                args.model,
                trace_dir=trace_dir,
                max_primary_papers=args.max_calibration_papers,
            )
        except Exception as error:
            return StepResult(
                step_name="calibrate_topic_contract",
                inputs={
                    "calibration_papers_full_text_csv": (
                        artifacts.calibration_papers_full_text_csv
                    ),
                    "topic_contract_yaml": topic_contract_path,
                },
                outputs={"topic_contract_yaml": topic_contract_path},
                warnings=[
                    "Collection-time contract calibration failed; the "
                    "collection will continue with the review-refined contract. "
                    f"Error: {error}"
                ],
                metadata={"calibration_skipped": True},
            )
        result.inputs = {
            "calibration_papers_full_text_csv": (
                artifacts.calibration_papers_full_text_csv
            ),
            "topic_contract_yaml": topic_contract_path,
        }
        return result

    def run_export_included_candidates() -> object:
        from ad_lit_pipeline.steps.collection import export_included

        require_full_text = full_text_availability_required()
        return export_included.run(
            artifacts.deduped_candidates_jsonl,
            artifacts.candidate_screening_csv,
            artifacts.papers_csv,
            args.max_results,
            availability_path=(
                artifacts.full_text_availability_csv if require_full_text else None
            ),
            require_full_text_availability=require_full_text,
            fail_below_export_ratio=args.fail_below_export_ratio,
        )

    def run_materialize_corpus_snapshot() -> object:
        from ad_lit_pipeline.steps.collection import materialize_snapshot

        return materialize_snapshot.run(
            artifacts.deduped_candidates_jsonl,
            artifacts.papers_csv,
            artifacts.provider_evidence_index_jsonl,
            artifacts.provider_response_pages_dir,
            artifacts.plan_json,
            topic_contract_path,
            artifacts.corpus_records_jsonl,
            artifacts.corpus_snapshot_integrity_json,
            producing_run_id,
            artifact_root=Path.cwd(),
        )

    return {
        "generate_topic_contract": run_generate_topic_contract,
        "fetch_review_overviews": run_fetch_review_overviews,
        "prepare_review_full_text": run_prepare_review_full_text,
        "refine_topic_contract": run_refine_topic_contract,
        "plan_search": run_plan_search,
        "fetch_candidates": run_fetch_candidates,
        "deduplicate_candidates": run_deduplicate_candidates,
        "screen_title_relevance": run_screen_title_relevance,
        "verify_full_text_availability": run_verify_full_text_availability,
        "backfill_candidates": run_backfill_candidates,
        "select_calibration_papers": run_select_calibration_papers,
        "prepare_calibration_full_text": run_prepare_calibration_full_text,
        "calibrate_topic_contract": run_calibrate_topic_contract,
        "export_included_candidates": run_export_included_candidates,
        "materialize_corpus_snapshot": run_materialize_corpus_snapshot,
    }


def run_collection(args: argparse.Namespace) -> None:
    load_dotenv()
    topic_contract_path = resolve_topic_contract_path(args)

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

    pipeline = selected_collection_pipeline(args)
    selected = select_steps(pipeline, args.only_step, args.from_step)
    if resume_manifest_path is not None:
        selected = resume_steps_from_manifest(
            resume_manifest_path,
            fallback_steps=selected,
        )
    topic_description = resolve_topic_description(args, topic_contract_path, selected)
    provenance = build_run_provenance(
        project_root=Path.cwd(),
        argv=sys.argv,
        options=vars(args),
        selected_steps=selected,
        pipeline_steps=pipeline,
        topic_contract_path=topic_contract_path,
        model=args.model,
        configured_provider_names=("openalex",),
    )
    manifest = ManifestRecorder.create(
        collection=args.collection,
        pipeline_name="collection",
        run_id=args.run_id,
        topic_contract_path=topic_contract_path,
        model=args.model,
        provenance=provenance,
        resume=args.resume,
    )
    trace_dir = (
        attempt_trace_dir(manifest, Path(args.trace_dir))
        if args.trace_dir
        else default_trace_dir(manifest)
    )
    step_functions = build_step_functions(
        args,
        trace_dir,
        topic_contract_path,
        topic_description,
        manifest.run_id,
    )

    if args.dry_run:
        print(f"Run id: {manifest.run_id}")
        print(f"Manifest: {manifest.manifest_path}")

    run_selected_steps(selected, step_functions, manifest, args.dry_run)

    artifacts = collection_artifacts(
        args.collection,
        prefer_existing_legacy=bool(
            args.resume or args.only_step or args.from_step
        ),
    )
    print()
    print("Collection complete.")
    print(f"Run id: {manifest.run_id}")
    print(f"Manifest: {manifest.manifest_path}")
    print(f"Topic contract: {topic_contract_path}")
    print(f"Plan: {artifacts.plan_json}")
    print(f"Candidate papers CSV: {artifacts.papers_csv}")
    if artifacts.corpus_records_jsonl.exists():
        print(f"Corpus records: {artifacts.corpus_records_jsonl}")
    if artifacts.corpus_snapshot_integrity_json.exists():
        print(
            "Corpus snapshot integrity: "
            f"{artifacts.corpus_snapshot_integrity_json}"
        )
    print()
    print("Next run:")
    print(
        "python scripts/run_pipeline.py run "
        f"--papers {artifacts.papers_csv} "
        f"--topic-contract {topic_contract_path} "
        f"--collection {args.collection}"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run automated paper collection.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_parser = subparsers.add_parser("run", help="Run the collection workflow.")
    run_parser.add_argument(
        "--topic",
        default=None,
        help=(
            "Topic description. Required when generating a topic contract; "
            "optional when --topic-contract is supplied."
        ),
    )
    run_parser.add_argument("--collection", required=True, help="Collection name.")
    run_parser.add_argument(
        "--max-results",
        type=int,
        default=25,
        help="Target selected paper count. Raw candidate search uses a scaled budget.",
    )
    run_parser.add_argument(
        "--max-review-overviews",
        type=int,
        default=DEFAULT_MAX_REVIEW_OVERVIEWS,
        help=(
            "Extracted review full-text seed count used when refining a "
            "generated contract. Review fetch retrieves a larger candidate pool."
        ),
    )
    run_parser.add_argument(
        "--max-calibration-papers",
        type=int,
        default=DEFAULT_MAX_CALIBRATION_PAPERS,
        help=(
            "Compatibility parameter for registered collection-calibration "
            "components. The default assembled collection workflow does not "
            "run those components."
        ),
    )
    run_parser.add_argument(
        "--mailto",
        default=None,
        help="Optional email for OpenAlex polite pool requests.",
    )
    run_parser.add_argument(
        "--full-text-email",
        default=os.getenv("UNPAYWALL_EMAIL"),
        help=(
            "Email for Unpaywall review full-text lookup. "
            "Defaults to UNPAYWALL_EMAIL."
        ),
    )
    run_parser.add_argument(
        "--full-text-cache-dir",
        default=str(prepare_full_text.default_cache_dir()),
        help=(
            "External directory for extracted review full-text cache. Defaults to "
            "AD_LIT_FULL_TEXT_CACHE or ~/.cache/ad_lit_pipeline/full_text."
        ),
    )
    run_parser.add_argument(
        "--core-api-key",
        default=os.getenv("CORE_API_KEY"),
        help="Optional CORE API key for additional review full-text lookup.",
    )
    run_parser.add_argument(
        "--require-full-text-availability",
        action="store_true",
        help=(
            "Require included collection results to have a verified reachable "
            "full-text URL before they count toward --max-results."
        ),
    )
    run_parser.add_argument(
        "--full-text-availability-timeout",
        type=float,
        default=5.0,
        help="Per-URL timeout in seconds for lightweight full-text URL checks.",
    )
    run_parser.add_argument(
        "--full-text-availability-workers",
        type=int,
        default=8,
        help="Parallel workers for collection-time full-text URL checks.",
    )
    run_parser.add_argument(
        "--model",
        default="gpt-4o-mini",
        help="OpenAI model for planning and screening.",
    )
    run_parser.add_argument(
        "--topic-contract",
        default=None,
        help=(
            "Topic contract YAML for provider and screening policy. "
            "If omitted, a contract is generated before collection."
        ),
    )
    run_parser.add_argument(
        "--generate-topic-contract",
        action="store_true",
        help=(
            "Generate a topic contract draft before running collection. "
            "This is implied when --topic-contract is omitted."
        ),
    )
    run_parser.add_argument(
        "--base-contract",
        default=str(DEFAULT_BASE_CONTRACT),
        help="Base topic contract template used when generating a contract.",
    )
    run_parser.add_argument(
        "--overwrite-topic-contract",
        action="store_true",
        help="Replace the generated topic contract if it already exists.",
    )
    run_parser.add_argument(
        "--contract-bootstrap-only",
        action="store_true",
        help=(
            "Run only the contract bootstrap steps: generate the draft, fetch "
            "review/overview seeds, and refine the contract."
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
    run_parser.add_argument(
        "--fail-below-export-ratio",
        type=float,
        default=None,
        help=(
            "Fail the collection if exported papers divided by --max-results "
            "is below this ratio. Omit to warn only."
        ),
    )

    explain_parser = subparsers.add_parser("explain", help="Explain collection steps.")
    explain_parser.add_argument("--collection", default="example", help="Collection name.")
    return parser


def main() -> None:
    load_dotenv()
    parser = build_parser()
    args = parser.parse_args()

    if args.command == "run":
        run_collection(args)
    elif args.command == "explain":
        explain(args.collection)


if __name__ == "__main__":
    main()
