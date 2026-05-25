from __future__ import annotations

import os
from pathlib import Path

from ad_lit_pipeline.core.artifacts import (
    collection_artifacts,
    main_pipeline_artifacts,
)
from ad_lit_pipeline.core.context import RunContext
from ad_lit_pipeline.core.env import load_dotenv
from ad_lit_pipeline.core.step import StepResult
from ad_lit_pipeline.io.csv_io import read_csv_rows, write_csv_rows
from ad_lit_pipeline.io.json_io import read_json_object, write_json
from ad_lit_pipeline.io.jsonl_io import read_jsonl_objects, write_jsonl
from ad_lit_pipeline.io.yaml_io import read_yaml_object


def test_artifact_paths_match_existing_conventions() -> None:
    main = main_pipeline_artifacts("example")
    collection = collection_artifacts("example")

    assert main.normalized_papers_csv == Path(
        "data/processed/example_papers_normalized.csv"
    )
    assert main.mantis_ready_csv == Path("data/processed/example_mantis_ready.csv")
    assert collection.plan_json == Path("data/collection_plans/example_plan.json")
    assert collection.papers_csv == Path("data/raw/example_papers.csv")


def test_run_context_resolves_relative_paths(tmp_path: Path) -> None:
    context = RunContext(collection="example", base_dir=tmp_path)

    assert context.resolve("data/raw/example.csv") == tmp_path / "data/raw/example.csv"
    assert context.resolve(tmp_path / "absolute.csv") == tmp_path / "absolute.csv"


def test_step_result_success_property() -> None:
    assert StepResult(step_name="example").succeeded is True
    assert StepResult(step_name="example", error="boom").succeeded is False


def test_shared_io_helpers_round_trip(tmp_path: Path) -> None:
    csv_path = tmp_path / "rows.csv"
    json_path = tmp_path / "payload.json"
    jsonl_path = tmp_path / "rows.jsonl"
    yaml_path = tmp_path / "payload.yaml"

    write_csv_rows(csv_path, [{"id": "1", "value": "a"}], ["id", "value"])
    write_json(json_path, {"id": 1})
    write_jsonl(jsonl_path, [{"id": 1}, {"id": 2}])
    yaml_path.write_text("id: 1\n", encoding="utf-8")

    assert read_csv_rows(csv_path) == [{"id": "1", "value": "a"}]
    assert read_json_object(json_path) == {"id": 1}
    assert read_jsonl_objects(jsonl_path) == [{"id": 1}, {"id": 2}]
    assert read_yaml_object(yaml_path) == {"id": 1}


def test_load_dotenv_does_not_override_existing_values(
    tmp_path: Path,
    monkeypatch,
) -> None:
    env_path = tmp_path / ".env"
    env_path.write_text(
        "NEW_VALUE=from_file\nEXISTING_VALUE=from_file\n",
        encoding="utf-8",
    )
    monkeypatch.delenv("NEW_VALUE", raising=False)
    monkeypatch.setenv("EXISTING_VALUE", "from_env")

    load_dotenv(env_path)

    assert os.environ["NEW_VALUE"] == "from_file"
    assert os.environ["EXISTING_VALUE"] == "from_env"
