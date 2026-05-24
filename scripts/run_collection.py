#!/usr/bin/env python3
"""Run the paper-collection workflow before the main knowledge pipeline."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


def run_command(command: list[str]) -> None:
    print()
    print("Running:", " ".join(command))
    subprocess.run(command, check=True)


def raw_path(collection: str, suffix: str) -> str:
    return str(Path("data/raw") / f"{collection}_{suffix}")


def plan_path(collection: str) -> str:
    return str(Path("data/collection_plans") / f"{collection}_plan.json")


def run_collection(args: argparse.Namespace) -> None:
    plan_output = plan_path(args.collection)
    candidates = raw_path(args.collection, "openalex_candidates.jsonl")
    deduped = raw_path(args.collection, "openalex_candidates_deduped.jsonl")
    screening = raw_path(args.collection, "candidate_screening.csv")
    papers = raw_path(args.collection, "papers.csv")

    run_command(
        [
            sys.executable,
            "scripts/plan_library_search.py",
            "--topic",
            args.topic,
            "--output",
            plan_output,
            "--max-results",
            str(args.max_results),
            "--model",
            args.model,
        ]
    )

    run_command(
        [
            sys.executable,
            "scripts/fetch_openalex_candidates.py",
            "--plan",
            plan_output,
            "--output",
            candidates,
            "--max-results",
            str(args.max_results),
        ]
    )

    run_command(
        [
            sys.executable,
            "scripts/deduplicate_candidates.py",
            "--input",
            candidates,
            "--output",
            deduped,
        ]
    )

    run_command(
        [
            sys.executable,
            "scripts/screen_candidates_with_llm.py",
            "--input",
            deduped,
            "--topic",
            args.topic,
            "--output",
            screening,
            "--model",
            args.model,
        ]
    )

    run_command(
        [
            sys.executable,
            "scripts/export_screened_candidates_to_csv.py",
            "--candidates",
            deduped,
            "--screening",
            screening,
            "--output",
            papers,
        ]
    )

    print()
    print("Collection complete.")
    print(f"Plan: {plan_output}")
    print(f"Candidate papers CSV: {papers}")
    print()
    print("Next run:")
    print(
        "python scripts/run_pipeline.py run "
        f"--papers {papers} "
        "--tagging-config configs/early_detection_tagging_config.yaml "
        f"--collection {args.collection}"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Run automated paper collection.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_parser = subparsers.add_parser("run", help="Run the collection workflow.")
    run_parser.add_argument("--topic", required=True, help="Topic description.")
    run_parser.add_argument("--collection", required=True, help="Collection name.")
    run_parser.add_argument("--max-results", type=int, default=25, help="Candidate count to fetch.")
    run_parser.add_argument(
        "--model",
        default="gpt-4o-mini",
        help="OpenAI model for planning and screening.",
    )

    args = parser.parse_args()

    if args.command == "run":
        run_collection(args)


if __name__ == "__main__":
    main()