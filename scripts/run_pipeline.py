#!/usr/bin/env python3
"""Run the knowledge pipeline in managed stages."""

from __future__ import annotations

import argparse
import subprocess
from pathlib import Path


PYTHON = "python"


def run_command(command: list[str]) -> None:
    print()
    print("Running:", " ".join(command))
    subprocess.run(command, check=True)


def processed_path(collection: str, suffix: str) -> str:
    return str(Path("data/processed") / f"{collection}_{suffix}.csv")


def run_prepare(input_path: str, collection: str) -> None:
    normalized = processed_path(collection, "papers_normalized")
    screened = processed_path(collection, "scope_screened")
    template = processed_path(collection, "extraction_template")

    run_command(
        [
            PYTHON,
            "scripts/normalize_metadata.py",
            "--input",
            input_path,
            "--output",
            normalized,
        ]
    )

    run_command(
        [
            PYTHON,
            "scripts/screen_scope.py",
            "--input",
            normalized,
            "--output",
            screened,
        ]
    )

    run_command(
        [
            PYTHON,
            "scripts/create_extraction_template.py",
            "--screened",
            screened,
            "--output",
            template,
        ]
    )

    print()
    print("Prepare complete.")
    print(f"Extraction template: {template}")
    print("Next: fill/review the extraction template before running finalize.")


def run_finalize(collection: str) -> None:
    filled = processed_path(collection, "extraction_filled")
    audit = processed_path(collection, "extraction_audit")
    mantis_ready = processed_path(collection, "mantis_ready")

    if not Path(filled).exists():
        raise SystemExit(
            f"Missing filled extraction file: {filled}\n"
            "Create this file before running finalize."
        )

    run_command(
        [
            PYTHON,
            "scripts/audit_extraction.py",
            "--input",
            filled,
            "--output",
            audit,
        ]
    )

    run_command(
        [
            PYTHON,
            "scripts/export_mantis_ready.py",
            "--input",
            filled,
            "--output",
            mantis_ready,
        ]
    )

    print()
    print("Finalize complete.")
    print(f"Audit: {audit}")
    print(f"Mantis-ready CSV: {mantis_ready}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the knowledge pipeline.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    prepare = subparsers.add_parser("prepare", help="Normalize, screen, and create extraction template.")
    prepare.add_argument(
        "--input",
        required=True,
        help="Raw input CSV.",
    )
    prepare.add_argument(
        "--collection",
        required=True,
        help="Collection name used for output file prefixes.",
    )

    finalize = subparsers.add_parser("finalize", help="Audit filled extraction and export Mantis-ready CSV.")
    finalize.add_argument(
        "--collection",
        required=True,
        help="Collection name used for output file prefixes.",
    )

    args = parser.parse_args()

    if args.command == "prepare":
        run_prepare(input_path=args.input, collection=args.collection)
    elif args.command == "finalize":
        run_finalize(collection=args.collection)


if __name__ == "__main__":
    main()
    