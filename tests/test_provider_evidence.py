from __future__ import annotations

import json
from email.message import Message
from pathlib import Path

import pytest

from ad_lit_pipeline.io.json_io import write_json
from ad_lit_pipeline.io.jsonl_io import read_jsonl_objects
from ad_lit_pipeline.providers import openalex
from ad_lit_pipeline.providers.evidence import (
    CapturedJSONResponse,
    ProviderEvidenceArchive,
    candidate_evidence_errors,
    canonical_redacted_request_url,
    canonical_request_projection,
    read_provider_evidence_index,
    sha256_mapping,
    verify_provider_evidence,
)
from ad_lit_pipeline.providers.openalex import OpenAlexProvider
from ad_lit_pipeline.steps.collection import backfill_candidates, fetch_candidates
from ad_lit_pipeline.steps.collection.export_included import (
    structured_provenance_fields,
)


def captured_response(
    raw_bytes: bytes,
    *,
    retrieved_at: str = "2026-09-01T10:00:00+00:00",
) -> CapturedJSONResponse:
    return CapturedJSONResponse(
        json.loads(raw_bytes),
        raw_bytes=raw_bytes,
        retrieved_at=retrieved_at,
        response_url="https://api.openalex.org/works?page=1",
        status_code=200,
        media_type="application/json",
        content_encoding=None,
    )


def retrieval_context() -> dict[str, object]:
    return {
        "query_id": "query-1",
        "logical_query_id": "logical-1",
        "query_group_id": "tier-0",
        "query_tier": 0,
        "retrieval_iteration": 1,
        "retrieval_phase": "strict",
        "page_or_cursor": "page:1",
        "per_page": 25,
        "backfill_round": None,
    }


def test_canonical_request_removes_secrets_and_private_contact() -> None:
    left = canonical_request_projection(
        "get",
        "https://API.openalex.org/works?search=example&page=1&"
        "api_key=secret-one&mailto=one@example.test",
        {"User-Agent": "pipeline", "Authorization": "Bearer secret"},
    )
    right = canonical_request_projection(
        "GET",
        "https://api.openalex.org/works?page=1&mailto=two@example.test&"
        "api_key=secret-two&search=example",
        {"user-agent": "pipeline"},
    )

    assert left == right
    assert sha256_mapping(left) == sha256_mapping(right)
    serialized = json.dumps(left)
    assert "secret-one" not in serialized
    assert "one@example.test" not in serialized
    assert "api_key" not in serialized
    assert "mailto" not in serialized
    assert left["redacted_url"] == (
        "https://api.openalex.org/works?page=1&search=example"
    )


def test_archive_preserves_exact_page_bytes_and_resolvable_candidate_link(
    tmp_path: Path,
) -> None:
    index_path = tmp_path / "provider_evidence.jsonl"
    archive_root = tmp_path / "pages"
    raw_bytes = (
        b'{\n  "results": [{"id": "https://openalex.org/W1", '
        b'"updated_date": "2026-08-30T12:00:00Z"}], "meta": {}}\n'
    )
    response = captured_response(raw_bytes)
    archive = ProviderEvidenceArchive(archive_root, index_path)

    record = archive.archive_json_page(
        provider="openalex",
        request_url=(
            "https://api.openalex.org/works?search=example&page=1&"
            "api_key=do-not-store"
        ),
        request_headers={"User-Agent": "pipeline"},
        response=response,
        retrieval_context=retrieval_context(),
    )
    raw_record = response["results"][0]
    assert isinstance(raw_record, dict)
    link = archive.candidate_link(
        record,
        result_position=1,
        raw_record=raw_record,
    )
    candidate = {
        "provider": "openalex",
        "provider_id": "https://openalex.org/W1",
        "raw_record": raw_record,
        "provider_evidence": link,
    }

    stored_path = index_path.parent / record["response"]["artifact_uri"]
    assert stored_path.read_bytes() == raw_bytes
    assert "do-not-store" not in index_path.read_text(encoding="utf-8")
    verification = verify_provider_evidence(index_path, archive_root)
    assert verification.valid
    assert verification.record_count == 1
    assert verification.archive_file_count == 1
    assert verification.total_response_bytes == len(raw_bytes)
    assert candidate_evidence_errors(
        [candidate],
        read_provider_evidence_index(index_path),
        require_archived=True,
    ) == ()


def test_provider_evidence_detects_byte_tampering(tmp_path: Path) -> None:
    index_path = tmp_path / "provider_evidence.jsonl"
    archive_root = tmp_path / "pages"
    raw_bytes = b'{"results": [{"id": "https://openalex.org/W1"}]}'
    archive = ProviderEvidenceArchive(archive_root, index_path)
    record = archive.archive_json_page(
        provider="openalex",
        request_url="https://api.openalex.org/works?page=1",
        request_headers={"User-Agent": "pipeline"},
        response=captured_response(raw_bytes),
        retrieval_context=retrieval_context(),
    )
    stored_path = index_path.parent / record["response"]["artifact_uri"]
    stored_path.write_bytes(b'{"results": []}')

    verification = verify_provider_evidence(index_path, archive_root)

    assert verification.valid is False
    assert any("byte hash mismatch" in error for error in verification.errors)


def test_candidate_link_detects_wrong_result_position(tmp_path: Path) -> None:
    index_path = tmp_path / "provider_evidence.jsonl"
    archive = ProviderEvidenceArchive(tmp_path / "pages", index_path)
    raw_bytes = (
        b'{"results": [{"id": "https://openalex.org/W1"}, '
        b'{"id": "https://openalex.org/W2"}]}'
    )
    response = captured_response(raw_bytes)
    record = archive.archive_json_page(
        provider="openalex",
        request_url="https://api.openalex.org/works?page=1",
        request_headers={"User-Agent": "pipeline"},
        response=response,
        retrieval_context=retrieval_context(),
    )
    raw_record = response["results"][1]
    assert isinstance(raw_record, dict)
    link = archive.candidate_link(
        record,
        result_position=1,
        raw_record=raw_record,
    )

    errors = candidate_evidence_errors(
        [
            {
                "provider_id": "https://openalex.org/W2",
                "raw_record": raw_record,
                "provider_evidence": link,
            }
        ],
        read_provider_evidence_index(index_path),
        require_archived=True,
    )

    assert any("another item" in error for error in errors)


def test_candidate_link_detects_changed_raw_item_with_same_provider_id(
    tmp_path: Path,
) -> None:
    index_path = tmp_path / "provider_evidence.jsonl"
    archive = ProviderEvidenceArchive(tmp_path / "pages", index_path)
    raw_bytes = (
        b'{"results": [{"id": "https://openalex.org/W1", '
        b'"display_name": "Original title"}]}'
    )
    response = captured_response(raw_bytes)
    record = archive.archive_json_page(
        provider="openalex",
        request_url="https://api.openalex.org/works?page=1",
        request_headers={"User-Agent": "pipeline"},
        response=response,
        retrieval_context=retrieval_context(),
    )
    original = response["results"][0]
    assert isinstance(original, dict)
    link = archive.candidate_link(
        record,
        result_position=1,
        raw_record=original,
    )
    changed = {**original, "display_name": "Changed title"}
    changed_link = {
        **link,
        "raw_record_sha256": sha256_mapping(changed),
    }

    errors = candidate_evidence_errors(
        [
            {
                "provider_id": "https://openalex.org/W1",
                "raw_record": changed,
                "provider_evidence": changed_link,
            }
        ],
        read_provider_evidence_index(index_path),
        require_archived=True,
    )

    assert any("archived page item" in error for error in errors)


def test_archive_refuses_decoded_mapping_as_exact_transport_evidence(
    tmp_path: Path,
) -> None:
    archive = ProviderEvidenceArchive(
        tmp_path / "pages",
        tmp_path / "provider_evidence.jsonl",
    )

    with pytest.raises(ValueError, match="captured HTTP response"):
        openalex.archive_openalex_page(
            archive,
            {"results": []},
            "https://api.openalex.org/works?page=1",
            retrieval_context(),
        )


def test_fetch_json_retains_exact_transport_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    raw_bytes = b'{\n"results": []\n}'

    class FakeResponse:
        status = 206

        def __init__(self) -> None:
            self.headers = Message()
            self.headers["Content-Type"] = "application/json; charset=utf-8"

        def __enter__(self) -> "FakeResponse":
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def read(self) -> bytes:
            return raw_bytes

        def geturl(self) -> str:
            return "https://api.openalex.org/works?page=1"

    monkeypatch.setattr(openalex, "urlopen", lambda request, timeout: FakeResponse())

    response = openalex.fetch_json("https://api.openalex.org/works?page=1")

    assert isinstance(response, CapturedJSONResponse)
    assert response.raw_bytes == raw_bytes
    assert response.status_code == 206
    assert response.media_type == "application/json"


def test_fetch_step_archives_page_and_links_candidate_without_secrets(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan_path = tmp_path / "plan.json"
    candidates_path = tmp_path / "example_provider_candidates.jsonl"
    index_path = tmp_path / "example_provider_evidence_index.jsonl"
    archive_root = tmp_path / "example_provider_response_pages"
    write_json(
        plan_path,
        {
            "recommended_provider": "openalex",
            "provider_specific_plan": {
                "provider": "openalex",
                "query": "evidence archive example",
                "max_results_recommendation": 1,
            },
        },
    )
    raw_bytes = json.dumps(
        {
            "results": [
                {
                    "id": "https://openalex.org/W123",
                    "display_name": "Provider Evidence Example",
                    "publication_year": 2024,
                    "publication_date": "2024-03-01",
                    "updated_date": "2026-08-30T12:00:00Z",
                    "type": "article",
                }
            ]
        },
        separators=(",", ":"),
    ).encode("utf-8")

    class FakeResponse:
        status = 200

        def __init__(self) -> None:
            self.headers = Message()
            self.headers["Content-Type"] = "application/json"

        def __enter__(self) -> "FakeResponse":
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def read(self) -> bytes:
            return raw_bytes

        def geturl(self) -> str:
            return "https://api.openalex.org/works?page=1"

    monkeypatch.setenv("OPENALEX_API_KEY", "never-store-this")
    monkeypatch.setattr(openalex, "urlopen", lambda request, timeout: FakeResponse())
    monkeypatch.setitem(
        fetch_candidates.PROVIDERS,
        "openalex",
        OpenAlexProvider(),
    )

    result = fetch_candidates.run(
        plan_path,
        candidates_path,
        max_results=1,
        mailto="private@example.test",
        sleep_seconds=0,
        provider_evidence_index_path=index_path,
        provider_response_pages_dir=archive_root,
    )

    candidates = read_jsonl_objects(candidates_path)
    assert len(candidates) == 1
    evidence = candidates[0]["provider_evidence"]
    assert evidence["status"] == "archived"
    assert evidence["result_position"] == 1
    assert result.row_counts["provider_response_pages"] == 1
    serialized_index = index_path.read_text(encoding="utf-8")
    serialized_candidate = candidates_path.read_text(encoding="utf-8")
    assert "never-store-this" not in serialized_index
    assert "never-store-this" not in serialized_candidate
    assert "private@example.test" not in serialized_index
    assert verify_provider_evidence(index_path, archive_root).valid


def test_backfill_appends_exact_page_evidence_for_new_candidate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    raw_bytes = json.dumps(
        {
            "results": [
                {
                    "id": "https://openalex.org/W1",
                    "doi": "https://doi.org/10.1234/existing",
                    "display_name": "Existing Work",
                    "publication_year": 2024,
                },
                {
                    "id": "https://openalex.org/W2",
                    "doi": "https://doi.org/10.1234/new",
                    "display_name": "New Work",
                    "publication_year": 2024,
                },
            ]
        },
        separators=(",", ":"),
    ).encode("utf-8")

    class FakeResponse:
        status = 200

        def __init__(self) -> None:
            self.headers = Message()
            self.headers["Content-Type"] = "application/json"

        def __enter__(self) -> "FakeResponse":
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def read(self) -> bytes:
            return raw_bytes

        def geturl(self) -> str:
            return "https://api.openalex.org/works?page=1"

    monkeypatch.setattr(openalex, "urlopen", lambda request, timeout: FakeResponse())
    monkeypatch.setitem(
        fetch_candidates.PROVIDERS,
        "openalex",
        OpenAlexProvider(),
    )
    index_path = tmp_path / "provider_evidence.jsonl"
    archive_root = tmp_path / "pages"
    archive = ProviderEvidenceArchive(
        archive_root,
        index_path,
        append_existing=True,
    )
    plan = {
        "recommended_provider": "openalex",
        "provider_specific_plan": {
            "provider": "openalex",
            "query": "backfill evidence",
        },
    }

    additional, diagnostics = backfill_candidates.fetch_additional_candidates(
        plan,
        [
            {
                "provider": "openalex",
                "provider_id": "https://openalex.org/W1",
                "doi": "10.1234/existing",
            }
        ],
        missing=1,
        per_page=25,
        mailto=None,
        sleep_seconds=0,
        backfill_round=1,
        evidence_archive=archive,
    )

    assert [candidate["provider_id"] for candidate in additional] == [
        "https://openalex.org/W2"
    ]
    assert additional[0]["provider_evidence"]["status"] == "archived"
    assert additional[0]["provider_evidence"]["result_position"] == 2
    assert diagnostics["provider_evidence_supported"] is True
    assert verify_provider_evidence(index_path, archive_root).valid


def test_redacted_url_requires_a_hostname() -> None:
    with pytest.raises(ValueError, match="hostname"):
        canonical_redacted_request_url("not-a-url")


def test_compatibility_csv_fields_preserve_provider_page_link() -> None:
    evidence = {
        "schema_version": "1.0.0",
        "status": "archived",
        "page_evidence_id": "provider_page_example",
        "request_sha256": "a" * 64,
        "redacted_request_url": "https://api.openalex.org/works?page=1",
        "response_sha256": "b" * 64,
        "response_uri": "example_pages/openalex/bb/example.json",
        "response_media_type": "application/json",
        "retrieved_at": "2026-09-01T10:00:00+00:00",
        "page_or_cursor": "page:1",
        "result_position": 2,
        "result_count": 25,
        "raw_record_sha256": "c" * 64,
        "raw_record_json_pointer": "/results/1",
    }

    fields = structured_provenance_fields(
        {
            "provider": "openalex",
            "provider_id": "W2",
            "provider_evidence": evidence,
            "raw_record": {"id": "W2", "type": "article"},
        }
    )

    assert fields["provider_evidence_status"] == "archived"
    assert fields["provider_page_evidence_id"] == "provider_page_example"
    assert fields["provider_result_position"] == "2"
    assert json.loads(fields["provider_evidence_json"]) == evidence
