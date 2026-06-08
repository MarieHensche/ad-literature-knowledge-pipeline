from __future__ import annotations

import pytest

from ad_lit_pipeline.llm.client import (
    DEFAULT_OPENAI_MAX_RETRIES,
    DEFAULT_OPENAI_TIMEOUT_SECONDS,
    OpenAIResponsesClient,
)


def test_openai_responses_client_uses_bounded_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENAI_TIMEOUT_SECONDS", raising=False)
    monkeypatch.delenv("OPENAI_MAX_RETRIES", raising=False)

    client = OpenAIResponsesClient()

    assert client.timeout_seconds == DEFAULT_OPENAI_TIMEOUT_SECONDS
    assert client.max_retries == DEFAULT_OPENAI_MAX_RETRIES


def test_openai_responses_client_reads_timeout_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_TIMEOUT_SECONDS", "12.5")
    monkeypatch.setenv("OPENAI_MAX_RETRIES", "1")

    client = OpenAIResponsesClient()

    assert client.timeout_seconds == 12.5
    assert client.max_retries == 1

