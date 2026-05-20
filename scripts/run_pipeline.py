#!/usr/bin/env python3
"""Run the literature knowledge pipeline."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


def run_command(command: list[str]) -> None:
    print()
    print("Running:", " ".join(command))
    subprocess.run(command, check=True)


def processed_path(collection: str, suffix: str) -> str:
    return str(Path("data/processed") / f"{collection}_{suffix}")


def run_full_pipeline(args: argparse.Namespace) -> None:
    normalized_papers = processed_path(args.collection, "papers_normalized.csv")
    scope_screened = processed_path(args.collection, "scope_screened.csv")
    normalized_config = processed_path(args.collection, "tagging_config_normalized.json")
    tagging_rules = processed_path(args.collection, "tagging_rules.json")
    extraction_filled = processed_path(args.collection, "extraction_filled.csv")
    extraction_audit = processed_path(args.collection, "extraction_audit.csv")
    mantis_ready = processed_path(args.collection, "mantis_ready.csv")

    run_command(
        [
            sys.executable,
            "scripts/normalize_metadata.py",
            "--input",
            args.papers,
            "--output",
            normalized_papers,
        ]
    )

    run_command(
        [
            sys.executable,
            "scripts/screen_scope.py",
            "--input",
            normalized_papers,
            "--output",
            scope_screened,
        ]
    )

    run_command(
        [
            sys.executable,
            "scripts/normalize_tagging_config.py",
            "--config",
            args.tagging_config,
            "--output",
            normalized_config,
        ]
    )

    run_command(
        [
            sys.executable,
            "scripts/generate_tagging_rules.py",
            "--config",
            normalized_config,
            "--output",
            tagging_rules,
        ]
    )

    run_command(
        [
            sys.executable,
            "scripts/tag_papers_with_llm.py",
            "--papers",
            scope_screened,
            "--config",
            normalized_config,
            "--rules",
            tagging_rules,
            "--output",
            extraction_filled,
        ]
    )

    run_command(
        [
            sys.executable,
            "scripts/audit_extraction.py",
            "--input",
            extraction_filled,
            "--config",
            normalized_config,
            "--rules",
            tagging_rules,
            "--output",
            extraction_audit,
        ]
    )

    run_command(
        [
            sys.executable,
            "scripts/export_mantis_ready.py",
            "--input",
            extraction_filled,
            "--output",
            mantis_ready,
        ]
    )

    print()
    print("Pipeline complete.")
    print(f"Mantis-ready CSV: {mantis_ready}")
    print(f"Audit file: {extraction_audit}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the literature knowledge pipeline.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_parser = subparsers.add_parser("run", help="Run the full LLM tagging pipeline.")
    run_parser.add_argument(
        "--papers",
        required=True,
        help="Input paper metadata CSV.",
    )
    run_parser.add_argument(
        "--tagging-config",
        required=True,
        help="Input YAML file with research topic and tag categories.",
    )
    run_parser.add_argument(
        "--collection",
        required=True,
        help="Collection name used to prefix generated outputs.",
    )

    args = parser.parse_args()

    if args.command == "run":
        run_full_pipeline(args)


if __name__ == "__main__":
    main()