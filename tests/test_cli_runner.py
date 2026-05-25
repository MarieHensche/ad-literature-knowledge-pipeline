from __future__ import annotations

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def run_script(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, *args],
        cwd=ROOT,
        check=True,
        text=True,
        capture_output=True,
    )


def test_run_pipeline_explain_lists_steps() -> None:
    result = run_script("scripts/run_pipeline.py", "explain", "--collection", "example")

    assert "normalize_metadata" in result.stdout
    assert "export_mantis" in result.stdout
    assert "example_mantis_ready.csv" in result.stdout


def test_run_pipeline_dry_run_selects_only_step() -> None:
    result = run_script(
        "scripts/run_pipeline.py",
        "run",
        "--papers",
        "data/raw/example_papers.csv",
        "--tagging-config",
        "configs/early_detection_tagging_config.yaml",
        "--collection",
        "example",
        "--only-step",
        "normalize_metadata",
        "--dry-run",
        "--run-id",
        "pytest-main-dry-run",
    )

    assert "Would run step: normalize_metadata" in result.stdout
    assert "Would run step: screen_scope" not in result.stdout


def test_run_collection_explain_lists_steps() -> None:
    result = run_script("scripts/run_collection.py", "explain", "--collection", "example")

    assert "plan_search" in result.stdout
    assert "fetch_candidates" in result.stdout
    assert "example_openalex_candidates.jsonl" in result.stdout
