from __future__ import annotations

import json
from pathlib import Path

from ad_lit_pipeline.llm.client import StaticJSONClient
from ad_lit_pipeline.llm.trace import LLMTraceWriter


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
    assert metadata["model"] == "test-model"
    assert metadata["schema_name"] == "decision_schema"
