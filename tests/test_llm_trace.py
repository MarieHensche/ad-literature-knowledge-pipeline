from __future__ import annotations

import json
from pathlib import Path

import pytest

from ad_lit_pipeline.core.manifest import ManifestRecorder
from ad_lit_pipeline.core.runner import attempt_trace_dir
from ad_lit_pipeline.llm.client import StaticJSONClient
from ad_lit_pipeline.llm.trace import TRACE_SCHEMA_VERSION, LLMTraceWriter, file_sha256


def test_static_json_client_records_request_and_writes_trace(tmp_path: Path) -> None:
    trace_writer = LLMTraceWriter(tmp_path / "traces")
    client = StaticJSONClient([{"decision": "include"}])

    result = client.create_json(
        model="test-model",
        system_message="System",
        prompt="Prompt",
        schema_name="decision_schema",
        schema={"type": "object"},
        step_name="screen_candidates",
        call_id="paper/1",
        trace_writer=trace_writer,
    )

    assert result.parsed == {"decision": "include"}
    assert client.requests[0]["prompt"] == "Prompt"
    assert result.trace_paths is not None
    assert result.trace_paths.prompt.read_text(encoding="utf-8") == "Prompt"
    assert json.loads(result.trace_paths.parsed_response.read_text()) == {
        "decision": "include"
    }
    metadata = json.loads(result.trace_paths.metadata.read_text())
    assert metadata["trace_schema_version"] == TRACE_SCHEMA_VERSION
    assert metadata["model"] == "test-model"
    assert metadata["schema_name"] == "decision_schema"
    assert metadata["request_parameters"] == {
        "client": "static_json",
        "response_format": "json_schema",
    }
    assert metadata["response_metadata"] == {}
    assert metadata["artifacts"]["prompt"]["sha256"] == file_sha256(
        result.trace_paths.prompt
    )
    assert metadata["artifacts"]["schema"]["sha256"] == file_sha256(
        result.trace_paths.schema
    )


def test_trace_writer_refuses_to_overwrite_same_call(tmp_path: Path) -> None:
    writer = LLMTraceWriter(tmp_path / "traces")
    kwargs = {
        "step_name": "screen_candidates",
        "call_id": "paper-1",
        "system_message": "System",
        "prompt": "Original prompt",
        "model": "test-model",
        "schema_name": "schema",
        "schema": {"type": "object"},
        "raw_response": {"decision": "include"},
        "parsed_response": {"decision": "include"},
    }
    paths = writer.write_trace(**kwargs)
    before = paths.prompt.read_bytes()

    with pytest.raises(FileExistsError, match="Refusing to overwrite"):
        writer.write_trace(**{**kwargs, "prompt": "Changed prompt"})

    assert paths.prompt.read_bytes() == before


def test_attempt_trace_directories_are_distinct_on_resume(tmp_path: Path) -> None:
    recorder = ManifestRecorder.create(
        collection="test",
        pipeline_name="main",
        runs_dir=tmp_path / "runs",
        run_id="run-1",
        model="test-model",
    )
    first = attempt_trace_dir(recorder)
    recorder.finish(status="failed")
    resumed = ManifestRecorder.create(
        collection="test",
        pipeline_name="main",
        runs_dir=tmp_path / "runs",
        run_id="run-1",
        model="test-model",
        resume=True,
    )
    second = attempt_trace_dir(resumed)

    assert first.name == "attempt-0001"
    assert second.name == "attempt-0002"
    assert first != second
