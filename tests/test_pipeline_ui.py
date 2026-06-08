from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

from pipeline_ui import server


def test_resolve_workspace_path_rejects_parent_traversal(tmp_path: Path) -> None:
    with pytest.raises(server.UiError, match="leaves the workspace"):
        server.resolve_workspace_path("../outside.yaml", tmp_path)


def test_save_contract_allows_only_contract_locations(tmp_path: Path) -> None:
    contract_path = "configs/topics/example.yaml"
    saved = server.save_contract(
        {"path": contract_path, "content": "research_topic:\n  title: Example\n"},
        tmp_path,
    )

    assert saved["path"] == contract_path
    assert (tmp_path / contract_path).exists()

    with pytest.raises(server.UiError, match="Contracts can only be saved"):
        server.save_contract(
            {"path": "data/raw/example.yaml", "content": "id: 1\n"},
            tmp_path,
        )


def test_build_main_command_uses_existing_pipeline_cli(tmp_path: Path) -> None:
    command = server.build_main_command(
        {
            "collection": "example",
            "papers": "data/raw/example_papers.csv",
            "topicContract": "configs/topics/early_detection_ad.yaml",
            "model": "gpt-4o-mini",
            "runId": "ui-test-main",
            "dryRun": True,
            "onlyStep": "normalize_metadata",
        },
        tmp_path,
    )

    assert command.run_id == "ui-test-main"
    assert command.manifest_path == "runs/ui-test-main/manifest.json"
    assert command.command[:3] == [sys.executable, "scripts/run_pipeline.py", "run"]
    assert "--papers" in command.command
    assert "data/raw/example_papers.csv" in command.command
    assert "--dry-run" in command.command
    only_step_index = command.command.index("--only-step")
    assert command.command[only_step_index + 1] == "normalize_metadata"


def test_build_main_command_can_enable_tag_review(tmp_path: Path) -> None:
    command = server.build_main_command(
        {
            "collection": "example",
            "papers": "data/raw/example_papers.csv",
            "topicContract": "configs/topics/early_detection_ad.yaml",
            "runId": "ui-test-main-review",
            "reviewTaggingCategories": True,
        },
        tmp_path,
    ).command

    assert command[:3] == [sys.executable, "scripts/run_pipeline.py", "run"]
    assert "--review-tagging-categories" in command


def test_ui_has_main_contract_dropdown() -> None:
    html = (Path(__file__).resolve().parents[1] / "pipeline_ui/static/index.html").read_text(
        encoding="utf-8"
    )

    assert 'id="paperInputSelect"' in html
    assert 'id="mainContractSelect"' in html
    assert 'id="mainContractPath"' in html


def test_build_contract_generation_job_uses_collection_cli(tmp_path: Path) -> None:
    commands = server.build_job_commands(
        {
            "workflow": "contract",
            "topic": "How does climate change affect health?",
            "collection": "climate_health",
            "model": "gpt-4o-mini",
            "runId": "ui-contract",
            "baseContract": "configs/topics/topic_contract_template.yaml",
            "overwriteTopicContract": True,
        },
        tmp_path,
    )

    assert len(commands) == 1
    command = commands[0].command
    assert command[:3] == [sys.executable, "scripts/run_collection.py", "run"]
    assert commands[0].label == "Create contract"
    assert "--generate-topic-contract" in command
    assert "--max-review-overviews" in command
    assert "--overwrite-topic-contract" in command
    assert "--contract-bootstrap-only" in command
    assert "--only-step" not in command
    assert "--topic-contract" not in command


def test_build_collection_without_contract_generates_one(tmp_path: Path) -> None:
    command = server.build_collection_command(
        {
            "workflow": "collection",
            "topic": "How does climate change affect health?",
            "collection": "climate_health",
            "model": "gpt-4o-mini",
            "runId": "ui-collection",
        },
        tmp_path,
    ).command

    assert "--generate-topic-contract" in command
    assert "--max-review-overviews" in command
    assert "--topic-contract" not in command


def test_build_collection_with_contract_does_not_require_topic(tmp_path: Path) -> None:
    command = server.build_collection_command(
        {
            "workflow": "collection",
            "collection": "climate_health",
            "topicContract": "configs/topics/early_detection_ad.yaml",
            "model": "gpt-4o-mini",
            "runId": "ui-existing-contract",
        },
        tmp_path,
    ).command

    assert "--topic-contract" in command
    assert "configs/topics/early_detection_ad.yaml" in command
    assert "--generate-topic-contract" not in command
    assert "--topic" not in command


def test_build_collection_with_contract_ignores_stale_bootstrap_step(
    tmp_path: Path,
) -> None:
    command = server.build_collection_command(
        {
            "workflow": "collection",
            "collection": "climate_health",
            "topicContract": "configs/topics/early_detection_ad.yaml",
            "model": "gpt-4o-mini",
            "runId": "ui-existing-contract-review",
            "fromStep": "fetch_review_overviews",
        },
        tmp_path,
    ).command

    assert "--topic-contract" in command
    assert "--generate-topic-contract" not in command
    assert "--from-step" not in command


def test_build_collection_requires_topic_when_generating_contract(
    tmp_path: Path,
) -> None:
    with pytest.raises(server.UiError, match="topic is required"):
        server.build_collection_command(
            {
                "workflow": "collection",
                "collection": "climate_health",
                "model": "gpt-4o-mini",
                "runId": "ui-missing-topic",
            },
            tmp_path,
        )


def test_build_collection_without_contract_can_run_main_afterward(
    tmp_path: Path,
) -> None:
    commands = server.build_job_commands(
        {
            "workflow": "collection",
            "topic": "How does climate change affect health?",
            "collection": "climate_health",
            "model": "gpt-4o-mini",
            "runId": "ui-collection",
            "runMainAfterCollection": True,
        },
        tmp_path,
    )

    assert len(commands) == 2
    main_command = commands[1].command
    assert "data/raw/climate_health_papers.csv" in main_command
    contract_index = main_command.index("--topic-contract")
    assert (
        main_command[contract_index + 1]
        == "data/collection_plans/climate_health_topic_contract.yaml"
    )


def test_list_manifests_returns_newest_first(tmp_path: Path) -> None:
    first = tmp_path / "runs" / "run-a" / "manifest.json"
    second = tmp_path / "runs" / "run-b" / "manifest.json"
    first.parent.mkdir(parents=True)
    second.parent.mkdir(parents=True)
    first.write_text(
        json.dumps(
            {
                "run_id": "run-a",
                "collection": "example",
                "pipeline_name": "main",
                "status": "succeeded",
                "steps": [],
            }
        ),
        encoding="utf-8",
    )
    second.write_text(
        json.dumps(
            {
                "run_id": "run-b",
                "collection": "example",
                "pipeline_name": "collection",
                "status": "failed",
                "failed_step": "fetch_candidates",
                "steps": [{"step_name": "fetch_candidates"}],
            }
        ),
        encoding="utf-8",
    )
    os.utime(first, (1_700_000_000, 1_700_000_000))
    os.utime(second, (1_700_000_100, 1_700_000_100))

    manifests = server.list_manifests(tmp_path)

    assert [item["runId"] for item in manifests] == ["run-b", "run-a"]
    assert manifests[0]["stepCount"] == 1
    assert manifests[0]["failedStep"] == "fetch_candidates"
