from __future__ import annotations

import csv
import hashlib
import json
from copy import deepcopy
from pathlib import Path

from ad_lit_pipeline.records import (
    make_payload_record_id,
    read_record_jsonl,
    record_from_dict,
    record_to_dict,
    validate_record_artifacts,
    write_record_jsonl,
)
from ad_lit_pipeline.steps.full_text import materialize_records
from ad_lit_pipeline.steps.full_text import prepare as full_text_prepare
from ad_lit_pipeline.steps.full_text.passages import (
    PageSpan,
    passage_slices,
    sha256_text,
)
from ad_lit_pipeline.steps.full_text.prepare import (
    completed_result,
    result_to_columns,
)
from tests.record_contract_fixtures import records_by_type


def _write_csv(path: Path, row: dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(row))
        writer.writeheader()
        writer.writerow(row)


def _fixture(tmp_path: Path) -> dict[str, Path]:
    payloads = deepcopy(records_by_type())
    source = payloads["source_version"]
    source["extensions"]["pipeline.corpus_materialization"] = {
        "paper_id": "fixture-paper-1"
    }
    record_types = (
        "corpus_snapshot",
        "scholarly_work",
        "source_version",
        "provider_record",
        "access_location",
    )
    corpus_path = tmp_path / "data" / "processed" / "fixture_corpus_records.jsonl"
    write_record_jsonl(
        corpus_path,
        [record_from_dict(payloads[record_type]) for record_type in record_types],
    )

    representation = (
        "Abstract\n"
        + "Synthetic abstract evidence with an exact source. " * 30
        + "\n\nMethods\n"
        + "A deterministic method paragraph for reproducible passage tests. " * 35
        + "\n\nDiscussion\n"
        + "Future work should validate the method in another population. " * 35
    )
    row = {
        "paper_id": "fixture-paper-1",
        "title": "Synthetic External Validation Study",
        "doi": "10.0000/step1.3.fixture",
        "full_text_is_open_access": "true",
    }
    result = completed_result(
        row,
        tmp_path / "cache",
        status="html_text_extracted",
        source="provider_metadata",
        url="https://example.invalid/full-text/fixture.html",
        license_value="CC-BY-4.0",
        source_bytes=(
            b"<html><body>Synthetic copyright-safe fixture</body></html>"
        ),
        source_media_type="text/html",
        text=representation,
        identity_status="verified_doi",
        identity_evidence="front_matter_doi_match=10.0000/step1.3.fixture",
        extraction_engine="synthetic-pdf-extractor",
        extraction_engine_version="1.0.0",
        retrieved_at="2026-08-27T07:40:00Z",
    )
    manifest_row = {**row, **result_to_columns(result)}
    manifest_path = tmp_path / "data" / "processed" / "full_text_manifest.csv"
    _write_csv(manifest_path, manifest_row)
    return {
        "root": tmp_path,
        "corpus": corpus_path,
        "manifest": manifest_path,
        "source": Path(result.source_artifact_path),
        "text": Path(result.text_path),
        "structure": Path(result.structure_path),
        "output": tmp_path / "data" / "processed" / "corpus_with_documents.jsonl",
        "integrity": tmp_path / "data" / "processed" / "document_integrity.json",
    }


def _run(
    paths: dict[str, Path],
    *,
    run_id: str = "document-run-1",
    suffix: str = "",
):
    output = paths["output"]
    integrity = paths["integrity"]
    if suffix:
        output = output.with_name(f"corpus_with_documents_{suffix}.jsonl")
        integrity = integrity.with_name(f"document_integrity_{suffix}.json")
    result = materialize_records.run(
        paths["corpus"],
        paths["manifest"],
        output,
        integrity,
        run_id,
        artifact_root=paths["root"],
        created_at="2026-09-02T10:00:00Z",
    )
    return result, output, integrity


def test_materializes_exact_document_and_resolvable_passages(tmp_path: Path) -> None:
    paths = _fixture(tmp_path)

    result, output, integrity_path = _run(paths)

    assert result.succeeded
    assert result.row_counts["documents"] == 1
    assert result.row_counts["passages"] >= 3
    records = read_record_jsonl(output)
    documents = [record for record in records if record.RECORD_TYPE == "document"]
    passages = [record for record in records if record.RECORD_TYPE == "passage"]
    assert len(documents) == 1
    document = documents[0]
    representation = (
        tmp_path / document.extensions["pipeline.text_representation"]["artifact_uri"]
    ).read_text(encoding="utf-8")
    for passage in passages:
        start = passage.locator["start_char"]
        end = passage.locator["end_char"]
        assert representation[start:end] == passage.text
        assert passage.locator["representation_sha256"] == sha256_text(
            representation
        )
    validation = validate_record_artifacts([output], artifact_root=tmp_path)
    assert validation.is_valid
    report = json.loads(integrity_path.read_text(encoding="utf-8"))
    assert report["status"] == "complete"
    assert report["record_integrity"]["is_valid"] is True


def test_document_and_passage_ids_are_stable_across_runs(tmp_path: Path) -> None:
    paths = _fixture(tmp_path)

    first, first_path, _ = _run(paths, run_id="document-run-1", suffix="first")
    second, second_path, _ = _run(paths, run_id="document-run-2", suffix="second")

    assert first.succeeded and second.succeeded
    first_ids = {
        record.record_id
        for record in read_record_jsonl(first_path)
        if record.RECORD_TYPE in {"document", "passage"}
    }
    second_ids = {
        record.record_id
        for record in read_record_jsonl(second_path)
        if record.RECORD_TYPE in {"document", "passage"}
    }
    assert first_ids == second_ids


def test_tampered_source_bytes_are_audited_without_document(tmp_path: Path) -> None:
    paths = _fixture(tmp_path)
    paths["source"].write_bytes(b"tampered")

    result, output, integrity_path = _run(paths)

    assert result.succeeded
    assert result.row_counts["documents"] == 0
    assert result.row_counts["document_failures"] == 1
    assert all(
        record.RECORD_TYPE not in {"document", "passage"}
        for record in read_record_jsonl(output)
    )
    assert sum(
        record.RECORD_TYPE == "access_location"
        for record in read_record_jsonl(output)
    ) == 1
    report = json.loads(integrity_path.read_text(encoding="utf-8"))
    assert report["status"] == "complete_with_failures"
    assert "source artifact hash mismatch" in report["materialization"][
        "failures"
    ][0]["message"]


def test_unverified_remote_identity_cannot_emit_document(tmp_path: Path) -> None:
    paths = _fixture(tmp_path)
    with paths["manifest"].open(newline="", encoding="utf-8") as handle:
        row = next(csv.DictReader(handle))
    row["full_text_identity_status"] = "mismatch"
    _write_csv(paths["manifest"], row)

    result, output, _ = _run(paths)

    assert result.succeeded
    assert result.row_counts["documents"] == 0
    assert all(
        record.RECORD_TYPE != "document" for record in read_record_jsonl(output)
    )


def test_structure_hash_mismatch_cannot_emit_passages(tmp_path: Path) -> None:
    paths = _fixture(tmp_path)
    paths["structure"].write_text("{}\n", encoding="utf-8")

    result, output, _ = _run(paths)

    assert result.succeeded
    assert result.row_counts["documents"] == 0
    assert result.row_counts["passages"] == 0
    assert all(
        record.RECORD_TYPE not in {"document", "passage"}
        for record in read_record_jsonl(output)
    )


def test_passage_segmentation_preserves_page_and_section_coordinates() -> None:
    text = "Methods\nFirst exact paragraph.\n\nResults\nSecond exact paragraph."
    page_boundary = text.index("Results")

    passages = passage_slices(
        text,
        (
            PageSpan(1, 0, page_boundary),
            PageSpan(2, page_boundary, len(text)),
        ),
    )

    assert [passage.section_path for passage in passages] == [
        ("Methods",),
        ("Results",),
    ]
    assert [(passage.page_start, passage.page_end) for passage in passages] == [
        (1, 1),
        (2, 2),
    ]
    assert all(text[item.start_char:item.end_char] == item.text for item in passages)


def test_passage_segmentation_detects_single_newline_section_boundaries() -> None:
    text = (
        "Abstract\nFirst exact paragraph.\n"
        "Methods\nSecond exact paragraph.\n"
        "Results\nThird exact paragraph."
    )

    passages = passage_slices(text)

    assert [item.section_path for item in passages] == [
        ("Abstract",),
        ("Methods",),
        ("Results",),
    ]
    assert [item.passage_kind for item in passages] == [
        "abstract",
        "paragraph",
        "paragraph",
    ]
    assert all(text[item.start_char:item.end_char] == item.text for item in passages)


def test_pdf_without_page_boundaries_cannot_emit_document(tmp_path: Path) -> None:
    paths = _fixture(tmp_path)
    with paths["manifest"].open(newline="", encoding="utf-8") as handle:
        row = next(csv.DictReader(handle))
    row["full_text_source_media_type"] = "application/pdf"
    row["full_text_page_count"] = ""
    _write_csv(paths["manifest"], row)

    result, output, integrity_path = _run(paths)

    assert result.succeeded
    assert result.row_counts["documents"] == 0
    assert result.row_counts["passages"] == 0
    report = json.loads(integrity_path.read_text(encoding="utf-8"))
    assert "independently resolvable page boundaries" in report[
        "materialization"
    ]["failures"][0]["message"]
    assert all(
        record.RECORD_TYPE not in {"document", "passage"}
        for record in read_record_jsonl(output)
    )


def test_post_materialization_structure_tampering_is_detected(
    tmp_path: Path,
) -> None:
    paths = _fixture(tmp_path)
    _, output, _ = _run(paths)
    document = next(
        record
        for record in read_record_jsonl(output)
        if record.RECORD_TYPE == "document"
    )
    structure_path = (
        tmp_path
        / document.extensions["pipeline.text_representation"][
            "structure_artifact_uri"
        ]
    )
    structure_path.write_text("{}\n", encoding="utf-8")

    validation = validate_record_artifacts([output], artifact_root=tmp_path)

    assert not validation.is_valid
    assert "local_artifact_hash_mismatch" in {
        issue.code for issue in validation.errors
    }


def test_passage_page_locator_is_checked_against_verified_structure(
    tmp_path: Path,
) -> None:
    paths = _fixture(tmp_path)
    _, output, _ = _run(paths)
    payloads = [record_to_dict(record) for record in read_record_jsonl(output)]
    passage = next(item for item in payloads if item["record_type"] == "passage")
    passage["locator"]["page_start"] = 1
    passage["locator"]["page_end"] = 1
    passage["record_id"] = make_payload_record_id(
        "passage",
        passage,
        schema_version=passage["schema_version"],
    )
    write_record_jsonl(output, [record_from_dict(item) for item in payloads])

    validation = validate_record_artifacts([output], artifact_root=tmp_path)

    assert not validation.is_valid
    assert "passage_page_locator_mismatch" in {
        issue.code for issue in validation.errors
    }


def test_content_addressed_source_cache_repairs_corrupt_entry(
    tmp_path: Path,
) -> None:
    source_bytes = b"Synthetic exact local source text. " * 80
    row = {"paper_id": "cache-repair", "title": "Cache repair fixture"}
    first = completed_result(
        row,
        tmp_path / "cache",
        status="local_text_extracted",
        source="local_file",
        url="fixture.txt",
        license_value="",
        source_bytes=source_bytes,
        source_media_type="text/plain",
        text=source_bytes.decode("utf-8"),
        identity_status="trusted_local",
        identity_evidence="explicit_local_file",
        extraction_engine="local_text",
        extraction_engine_version="1.0.0",
    )
    source_path = Path(first.source_artifact_path)
    source_path.write_bytes(b"corrupt")

    second = completed_result(
        row,
        tmp_path / "cache",
        status="local_text_extracted",
        source="local_file",
        url="fixture.txt",
        license_value="",
        source_bytes=source_bytes,
        source_media_type="text/plain",
        text=source_bytes.decode("utf-8"),
        identity_status="trusted_local",
        identity_evidence="explicit_local_file",
        extraction_engine="local_text",
        extraction_engine_version="1.0.0",
    )

    assert Path(second.source_artifact_path).read_bytes() == source_bytes
    assert second.source_sha256 == hashlib.sha256(source_bytes).hexdigest()


def test_access_uri_preserves_scientific_query_and_removes_private_values() -> None:
    value = (
        "https://EXAMPLE.invalid/article?download=pdf&token=secret&language=en"
    )

    assert materialize_records._safe_access_uri(value) == (
        "https://example.invalid/article?download=pdf&language=en"
    )


def test_full_text_preparation_preserves_exact_remote_source_bytes(
    tmp_path: Path,
    monkeypatch,
) -> None:
    source_bytes = (
        b"<html><body><h1>Synthetic exact remote study</h1>"
        + b"<p>Evidence paragraph for exact-byte retention.</p>" * 40
        + b"</body></html>"
    )
    monkeypatch.setattr(
        full_text_prepare,
        "request_bytes",
        lambda url: (source_bytes, "text/html; charset=utf-8", url),
    )
    input_path = tmp_path / "scope.csv"
    output_path = tmp_path / "full_text.csv"
    manifest_path = tmp_path / "manifest.csv"
    row = {
        "paper_id": "remote-1",
        "title": "Synthetic exact remote study",
        "doi": "",
        "abstract": "Synthetic abstract.",
        "full_text_url": "https://example.invalid/exact",
        "scope_decision": "include",
    }
    _write_csv(input_path, row)

    result = full_text_prepare.run(
        input_path,
        output_path,
        manifest_path,
        tmp_path / "cache",
    )

    assert result.succeeded
    with manifest_path.open(newline="", encoding="utf-8") as handle:
        prepared = next(csv.DictReader(handle))
    source_path = Path(prepared["full_text_source_artifact_path"])
    structure_path = Path(prepared["full_text_structure_path"])
    assert source_path.read_bytes() == source_bytes
    assert prepared["full_text_source_sha256"] == hashlib.sha256(
        source_bytes
    ).hexdigest()
    assert prepared["full_text_source_byte_size"] == str(len(source_bytes))
    assert prepared["full_text_source_media_type"] == "text/html"
    assert prepared["full_text_extraction_contract_version"] == "3.0.0"
    assert hashlib.sha256(structure_path.read_bytes()).hexdigest() == prepared[
        "full_text_structure_sha256"
    ]


def test_historical_remote_text_without_source_bytes_is_refetched(
    tmp_path: Path,
    monkeypatch,
) -> None:
    historical_text = tmp_path / "historical.txt"
    historical_text.write_text("Historical remote extraction. " * 60, encoding="utf-8")
    replacement = (
        b"<html><body><h1>Refetched remote study</h1>"
        + b"<p>Fresh identity-verified evidence.</p>" * 50
        + b"</body></html>"
    )
    requests: list[str] = []

    def fake_request(url: str):
        requests.append(url)
        return replacement, "text/html", url

    monkeypatch.setattr(full_text_prepare, "request_bytes", fake_request)
    input_path = tmp_path / "scope.csv"
    output_path = tmp_path / "full_text.csv"
    manifest_path = tmp_path / "manifest.csv"
    _write_csv(
        input_path,
        {
            "paper_id": "remote-old",
            "title": "Refetched remote study",
            "doi": "",
            "abstract": "Synthetic abstract.",
            "full_text_url": "https://example.invalid/refetch",
            "full_text_resolved_url": "https://example.invalid/refetch",
            "full_text_source": "provider_metadata",
            "full_text_status": "html_text_extracted",
            "full_text_text_path": str(historical_text),
            "full_text_extraction_contract_version": "2.0.0",
            "scope_decision": "include",
        },
    )

    full_text_prepare.run(
        input_path,
        output_path,
        manifest_path,
        tmp_path / "cache",
    )

    assert requests == ["https://example.invalid/refetch"]
    with manifest_path.open(newline="", encoding="utf-8") as handle:
        prepared = next(csv.DictReader(handle))
    assert Path(prepared["full_text_source_artifact_path"]).read_bytes() == replacement
