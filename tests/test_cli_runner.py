from __future__ import annotations

import csv
import subprocess
import sys
from pathlib import Path

from ad_lit_pipeline.cli.run_pipeline import prepare_papers_csv


ROOT = Path(__file__).resolve().parents[1]


def run_script(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, *args],
        cwd=ROOT,
        check=True,
        text=True,
        capture_output=True,
    )


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


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
        "--topic-contract",
        "configs/topics/early_detection_ad.yaml",
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


def test_run_pipeline_prepares_supported_non_csv_papers(tmp_path: Path) -> None:
    inputs = [
        ROOT / "data/raw/example_papers.bib",
        ROOT / "data/raw/example_papers.jsonl",
        ROOT / "data/raw/example_papers.ris",
    ]

    for input_path in inputs:
        output = tmp_path / f"{input_path.suffix[1:]}_papers.csv"

        prepared = prepare_papers_csv(input_path, output)

        rows = read_csv(prepared)
        assert prepared == output
        assert len(rows) == 3
        assert rows[0]["paper_id"]
        assert rows[0]["title"]


def test_run_pipeline_leaves_csv_papers_unchanged(tmp_path: Path) -> None:
    input_path = ROOT / "data/raw/example_papers.csv"
    output = tmp_path / "should_not_be_written.csv"

    prepared = prepare_papers_csv(input_path, output)

    assert prepared == input_path
    assert not output.exists()


def test_run_collection_explain_lists_steps() -> None:
    result = run_script("scripts/run_collection.py", "explain", "--collection", "example")

    assert "plan_search" in result.stdout
    assert "fetch_candidates" in result.stdout
    assert "generate_topic_contract" in result.stdout
    assert "example_openalex_candidates.jsonl" in result.stdout


def test_run_collection_dry_run_can_generate_contract_first() -> None:
    result = run_script(
        "scripts/run_collection.py",
        "run",
        "--topic",
        "How does climate change affect human health?",
        "--collection",
        "pytest_contract_dry_run",
        "--generate-topic-contract",
        "--only-step",
        "generate_topic_contract",
        "--dry-run",
        "--run-id",
        "pytest-collection-contract-dry-run",
    )

    assert "Would run step: generate_topic_contract" in result.stdout
    assert "pytest_contract_dry_run_topic_contract.yaml" in result.stdout


def test_run_collection_can_run_contract_bootstrap_only() -> None:
    result = run_script(
        "scripts/run_collection.py",
        "run",
        "--topic",
        "How does climate change affect human health?",
        "--collection",
        "pytest_contract_bootstrap_dry_run",
        "--contract-bootstrap-only",
        "--dry-run",
        "--run-id",
        "pytest-contract-bootstrap-dry-run",
    )

    assert "Would run step: generate_topic_contract" in result.stdout
    assert "Would run step: fetch_review_overviews" in result.stdout
    assert "Would run step: refine_topic_contract" in result.stdout
    assert "Would run step: plan_search" not in result.stdout


def test_run_collection_dry_run_without_contract_auto_generates_contract() -> None:
    result = run_script(
        "scripts/run_collection.py",
        "run",
        "--topic",
        "How does climate change affect human health?",
        "--collection",
        "pytest_auto_contract_dry_run",
        "--only-step",
        "generate_topic_contract",
        "--dry-run",
        "--run-id",
        "pytest-auto-contract-dry-run",
    )

    assert "Would run step: generate_topic_contract" in result.stdout
    assert "pytest_auto_contract_dry_run_topic_contract.yaml" in result.stdout


def test_run_collection_with_contract_does_not_require_topic() -> None:
    result = run_script(
        "scripts/run_collection.py",
        "run",
        "--collection",
        "pytest_existing_contract_dry_run",
        "--topic-contract",
        "configs/topics/early_detection_ad.yaml",
        "--only-step",
        "plan_search",
        "--dry-run",
        "--run-id",
        "pytest-existing-contract-dry-run",
    )

    assert "Would run step: plan_search" in result.stdout
    assert "generate_topic_contract" not in result.stdout


def test_run_collection_requires_topic_when_generating_contract() -> None:
    result = subprocess.run(
        [
            sys.executable,
            "scripts/run_collection.py",
            "run",
            "--collection",
            "pytest_missing_topic",
            "--only-step",
            "generate_topic_contract",
            "--dry-run",
            "--run-id",
            "pytest-missing-topic",
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
    )

    assert result.returncode != 0
    assert "--topic is required when generating a topic contract" in result.stderr
