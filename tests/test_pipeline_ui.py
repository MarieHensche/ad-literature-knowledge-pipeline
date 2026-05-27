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
    assert "--generate-topic-contract" in command
    assert "--overwrite-topic-contract" in command
    assert "--only-step" in command
    assert "generate_topic_contract" in command
    assert "--topic-contract" not in command


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
