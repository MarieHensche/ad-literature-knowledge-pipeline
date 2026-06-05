from __future__ import annotations

import argparse
import os
from pathlib import Path

from ad_lit_pipeline.core.artifacts import collection_artifacts
from ad_lit_pipeline.core.env import load_dotenv
from ad_lit_pipeline.core.manifest import ManifestRecorder, resume_step_from_manifest
from ad_lit_pipeline.core.registry import (
    COLLECTION_PIPELINE,
    COLLECTION_WITH_CONTRACT_PIPELINE,
    CONTRACT_BOOTSTRAP_PIPELINE,
)
from ad_lit_pipeline.core.runner import default_trace_dir, run_selected_steps, select_steps
from ad_lit_pipeline.steps.full_text import prepare as prepare_full_text
from ad_lit_pipeline.topics.contract import load_topic_contract


SEARCH_BUDGET_HARD_CAP = 5000
SEARCH_BUDGET_MINIMUM = 30
SEARCH_BUDGET_MULTIPLIER = 4
DEFAULT_MAX_REVIEW_OVERVIEWS = 5
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
    print("Optional preflight step:")
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
    if args.contract_bootstrap_only:
        return CONTRACT_BOOTSTRAP_PIPELINE
    if args.generate_topic_contract or not args.topic_contract:
        return COLLECTION_WITH_CONTRACT_PIPELINE
    requested_step = args.only_step or args.from_step
    if requested_step in CONTRACT_BOOTSTRAP_PIPELINE:
        return COLLECTION_WITH_CONTRACT_PIPELINE
    return COLLECTION_PIPELINE


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
) -> dict[str, object]:
    artifacts = collection_artifacts(args.collection)

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
        )

    def run_fetch_candidates() -> object:
        from ad_lit_pipeline.steps.collection import fetch_candidates

        return fetch_candidates.run(
            artifacts.plan_json,
            artifacts.candidates_jsonl,
            candidate_search_budget(args.max_results),
            mailto=args.mailto,
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
            limit=candidate_search_budget(args.max_results),
            trace_dir=trace_dir,
        )

    def run_export_included_candidates() -> object:
        from ad_lit_pipeline.steps.collection import export_included

        return export_included.run(
            artifacts.deduped_candidates_jsonl,
            artifacts.candidate_screening_csv,
            artifacts.papers_csv,
            args.max_results,
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
        "export_included_candidates": run_export_included_candidates,
    }


def run_collection(args: argparse.Namespace) -> None:
    load_dotenv()
    topic_contract_path = resolve_topic_contract_path(args)

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

    pipeline = selected_collection_pipeline(args)
    manifest = ManifestRecorder.create(
        collection=args.collection,
        pipeline_name="collection",
        run_id=args.run_id,
        topic_contract_path=topic_contract_path,
        model=args.model,
    )
    trace_dir = Path(args.trace_dir) if args.trace_dir else default_trace_dir(manifest)
    selected = select_steps(pipeline, args.only_step, args.from_step)
    topic_description = resolve_topic_description(args, topic_contract_path, selected)
    step_functions = build_step_functions(
        args,
        trace_dir,
        topic_contract_path,
        topic_description,
    )

    if args.dry_run:
        print(f"Run id: {manifest.run_id}")
        print(f"Manifest: {manifest.manifest_path}")

    run_selected_steps(selected, step_functions, manifest, args.dry_run)

    artifacts = collection_artifacts(args.collection)
    print()
    print("Collection complete.")
    print(f"Run id: {manifest.run_id}")
    print(f"Manifest: {manifest.manifest_path}")
    print(f"Topic contract: {topic_contract_path}")
    print(f"Plan: {artifacts.plan_json}")
    print(f"Candidate papers CSV: {artifacts.papers_csv}")
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
        help="Review/overview seed count used when generating a contract.",
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
