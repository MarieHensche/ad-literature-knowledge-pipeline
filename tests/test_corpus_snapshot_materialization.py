from __future__ import annotations

import csv
import hashlib
import json
from copy import deepcopy
from pathlib import Path

from ad_lit_pipeline.io.json_io import write_json
from ad_lit_pipeline.io.yaml_io import read_yaml_object, write_yaml_object
from ad_lit_pipeline.providers.evidence import (
    CapturedJSONResponse,
    ProviderEvidenceArchive,
    sha256_mapping,
)
from ad_lit_pipeline.records import read_record_jsonl, validate_record_artifacts
from ad_lit_pipeline.steps.collection import materialize_snapshot


ROOT = Path(__file__).resolve().parents[1]


def _fixture(tmp_path: Path, *, as_of: str = "2026-09-01") -> dict[str, Path]:
    raw_dir = tmp_path / "data" / "raw"
    processed_dir = tmp_path / "data" / "processed"
    plan_dir = tmp_path / "data" / "collection_plans"
    config_dir = tmp_path / "configs" / "topics"
    for directory in (raw_dir, processed_dir, plan_dir, config_dir):
        directory.mkdir(parents=True, exist_ok=True)

    contract = read_yaml_object(ROOT / "configs" / "topics" / "early_detection_ad.yaml")
    corpus = contract["collection"]["corpus_specification"]
    corpus["as_of"] = as_of
    corpus["as_of_resolution"] = "explicit"
    contract_path = config_dir / "snapshot_topic.yaml"
    write_yaml_object(contract_path, contract)

    plan_path = plan_dir / "snapshot_plan.json"
    write_json(
        plan_path,
        {
            "recommended_provider": "openalex",
            "provider_specific_plan": {
                "provider": "openalex",
                "query": "synthetic snapshot",
            },
            "query_groups": [
                {
                    "group_id": "tier_0",
                    "tier": 0,
                    "queries": [
                        {
                            "query_id": "snapshot_query_1",
                            "query": "synthetic snapshot",
                        }
                    ],
                }
            ],
        },
    )

    evidence_index = raw_dir / "snapshot_provider_evidence_index.jsonl"
    evidence_pages = raw_dir / "snapshot_provider_response_pages"
    archive = ProviderEvidenceArchive(evidence_pages, evidence_index)
    raw_record = {
        "id": "https://openalex.org/W-SNAPSHOT-1",
        "doi": "https://doi.org/10.1234/snapshot.example",
        "display_name": "Synthetic Snapshot Study",
        "publication_year": 2024,
        "publication_date": "2024-03-02",
        "updated_date": "2026-08-30T09:00:00Z",
        "type": "article",
        "language": "en",
        "authorships": [
            {
                "author": {
                    "display_name": "Synthetic Researcher",
                    "orcid": "https://orcid.org/0000-0001-2345-6789",
                }
            }
        ],
        "primary_location": {
            "version": "publishedVersion",
            "landing_page_url": "https://doi.org/10.1234/snapshot.example",
            "source": {
                "display_name": "Synthetic Journal",
                "host_organization_name": "Synthetic Publisher",
            },
        },
        "referenced_works": ["https://openalex.org/W-REFERENCE-1"],
    }
    raw_bytes = json.dumps(
        {"results": [raw_record], "meta": {}},
        separators=(",", ":"),
    ).encode("utf-8")
    response = CapturedJSONResponse(
        json.loads(raw_bytes),
        raw_bytes=raw_bytes,
        retrieved_at="2026-08-31T10:00:00+00:00",
        response_url=(
            "https://api.openalex.org/works?page=1&search=synthetic+snapshot"
        ),
        status_code=200,
        media_type="application/json",
        content_encoding=None,
    )
    page = archive.archive_json_page(
        provider="openalex",
        request_url=(
            "https://api.openalex.org/works?page=1&search=synthetic+snapshot"
        ),
        request_headers={"User-Agent": "pipeline"},
        response=response,
        retrieval_context={
            "query_id": "snapshot_query_1",
            "logical_query_id": "snapshot_query_1",
            "query_group_id": "tier_0",
            "query_tier": 0,
            "retrieval_iteration": 1,
            "retrieval_phase": "strict",
            "page_or_cursor": "page:1",
            "per_page": 25,
            "backfill_round": None,
        },
    )
    evidence = archive.candidate_link(
        page,
        result_position=1,
        raw_record=raw_record,
    )
    candidate = {
        "provider": "openalex",
        "provider_id": raw_record["id"],
        "doi": "10.1234/snapshot.example",
        "title": raw_record["display_name"],
        "publication_date": raw_record["publication_date"],
        "source_type": "article",
        "language": "en",
        "provider_record_updated_at": raw_record["updated_date"],
        "abstract": "A copyright-safe synthetic abstract.",
        "authors": "Synthetic Researcher",
        "venue": "Synthetic Journal",
        "url": "https://doi.org/10.1234/snapshot.example",
        "full_text_locations": [
            {
                "source": "synthetic_provider",
                "url": "https://example.invalid/snapshot.pdf",
                "kind": "pdf",
                "license": "CC-BY-4.0",
                "is_open_access": True,
            }
        ],
        "rank": 1,
        "retrieved_at": "2026-08-31T10:00:00+00:00",
        "retrieval_query_id": "snapshot_query_1",
        "provider_evidence": evidence,
        "raw_record": raw_record,
        "duplicate_count": 1,
    }
    candidates_path = raw_dir / "snapshot_provider_candidates_deduped.jsonl"
    candidates_path.write_text(
        json.dumps(candidate, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    papers_path = raw_dir / "snapshot_papers.csv"
    paper = {
        "paper_id": "snapshot-paper-1",
        "doi": candidate["doi"],
        "provider": "openalex",
        "provider_id": candidate["provider_id"],
        "full_text_availability_status": "verified",
        "full_text_availability_source": "synthetic_http_check",
        "full_text_url": "https://example.invalid/snapshot.pdf",
        "full_text_url_kind": "pdf",
        "full_text_url_checked_at": "2026-08-31T11:00:00Z",
        "full_text_url_content_type": "application/pdf",
        "full_text_license": "CC-BY-4.0",
        "full_text_is_open_access": "true",
    }
    with papers_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(paper))
        writer.writeheader()
        writer.writerow(paper)

    return {
        "artifact_root": tmp_path,
        "candidates": candidates_path,
        "papers": papers_path,
        "evidence_index": evidence_index,
        "evidence_pages": evidence_pages,
        "plan": plan_path,
        "contract": contract_path,
        "records": processed_dir / "snapshot_corpus_records.jsonl",
        "integrity": processed_dir / "snapshot_corpus_snapshot_integrity.json",
    }


def _run(paths: dict[str, Path], *, run_id: str, frozen_at: str, suffix: str = ""):
    records = paths["records"]
    integrity = paths["integrity"]
    if suffix:
        records = records.with_name(f"snapshot{suffix}_corpus_records.jsonl")
        integrity = integrity.with_name(
            f"snapshot{suffix}_corpus_snapshot_integrity.json"
        )
    return materialize_snapshot.run(
        paths["candidates"],
        paths["papers"],
        paths["evidence_index"],
        paths["evidence_pages"],
        paths["plan"],
        paths["contract"],
        records,
        integrity,
        run_id,
        artifact_root=paths["artifact_root"],
        frozen_at=frozen_at,
    ), records, integrity


def test_materializes_frozen_corpus_with_resolvable_provider_bytes(
    tmp_path: Path,
) -> None:
    paths = _fixture(tmp_path)

    result, records_path, integrity_path = _run(
        paths,
        run_id="snapshot-run-1",
        frozen_at="2026-09-01T12:00:00Z",
    )

    assert result.succeeded
    records = read_record_jsonl(records_path)
    by_type = {record.RECORD_TYPE: record for record in records}
    assert set(by_type) == {
        "corpus_snapshot",
        "scholarly_work",
        "source_version",
        "provider_record",
        "access_location",
    }
    assert by_type["corpus_snapshot"].snapshot_status.value == "frozen"
    assert by_type["corpus_snapshot"].coverage.status.value == "adequate_for_rule"
    assert by_type["source_version"].temporal_eligibility.value == "eligible"
    provider = by_type["provider_record"]
    page_bytes = (tmp_path / provider.raw_record_uri).read_bytes()
    assert provider.raw_record_sha256 == hashlib.sha256(page_bytes).hexdigest()
    extension = provider.extensions["provider.evidence"]
    assert extension["raw_record_sha256"] == sha256_mapping(
        json.loads(page_bytes)["results"][0]
    )
    verification = validate_record_artifacts(
        [records_path],
        artifact_root=tmp_path,
    )
    assert verification.is_valid
    report = json.loads(integrity_path.read_text(encoding="utf-8"))
    assert report["freeze_allowed"] is True
    assert report["snapshot_id"] == by_type["corpus_snapshot"].record_id
    assert report["record_integrity"]["is_valid"] is True


def test_unchanged_inputs_produce_stable_record_and_snapshot_ids(
    tmp_path: Path,
) -> None:
    paths = _fixture(tmp_path)
    first, first_path, _ = _run(
        paths,
        run_id="snapshot-run-1",
        frozen_at="2026-09-01T12:00:00Z",
        suffix="_first",
    )
    second, second_path, _ = _run(
        paths,
        run_id="snapshot-run-2",
        frozen_at="2026-09-01T13:00:00Z",
        suffix="_second",
    )

    assert first.succeeded and second.succeeded
    assert [record.record_id for record in read_record_jsonl(first_path)] == [
        record.record_id for record in read_record_jsonl(second_path)
    ]


def test_fractional_freeze_timestamp_uses_chronological_order(tmp_path: Path) -> None:
    paths = _fixture(tmp_path)

    result, _, _ = _run(
        paths,
        run_id="snapshot-run-fractional-time",
        frozen_at="2026-08-31T11:00:00.500Z",
    )

    assert result.succeeded


def test_tampered_provider_page_prevents_freezing(tmp_path: Path) -> None:
    paths = _fixture(tmp_path)
    page_path = next(paths["evidence_pages"].rglob("*.json"))
    page_path.write_bytes(b'{"results":[]}')

    result, records_path, integrity_path = _run(
        paths,
        run_id="snapshot-run-tampered",
        frozen_at="2026-09-01T12:00:00Z",
    )

    assert not result.succeeded
    assert not records_path.exists()
    report = json.loads(integrity_path.read_text(encoding="utf-8"))
    assert report["freeze_allowed"] is False
    codes = {issue["code"] for issue in report["input_integrity"]["issues"]}
    assert "provider_evidence_integrity_error" in codes


def test_after_cutoff_version_prevents_freezing(tmp_path: Path) -> None:
    paths = _fixture(tmp_path, as_of="2023-12-31")

    result, records_path, integrity_path = _run(
        paths,
        run_id="snapshot-run-cutoff",
        frozen_at="2026-09-01T12:00:00Z",
    )

    assert not result.succeeded
    assert not records_path.exists()
    report = json.loads(integrity_path.read_text(encoding="utf-8"))
    codes = {issue["code"] for issue in report["input_integrity"]["issues"]}
    assert "snapshot_cutoff_violation" in codes


def test_competing_doi_identity_prevents_freezing(tmp_path: Path) -> None:
    paths = _fixture(tmp_path)
    candidate = json.loads(paths["candidates"].read_text(encoding="utf-8"))
    candidate["dois"] = [
        "10.1234/snapshot.example",
        "10.1234/competing.example",
    ]
    paths["candidates"].write_text(json.dumps(candidate) + "\n", encoding="utf-8")

    result, records_path, integrity_path = _run(
        paths,
        run_id="snapshot-run-identity",
        frozen_at="2026-09-01T12:00:00Z",
    )

    assert not result.succeeded
    assert not records_path.exists()
    report = json.loads(integrity_path.read_text(encoding="utf-8"))
    codes = {issue["code"] for issue in report["input_integrity"]["issues"]}
    assert "work_identity_unresolved" in codes


def test_failed_rebuild_preserves_prior_snapshot_but_marks_it_stale(
    tmp_path: Path,
) -> None:
    paths = _fixture(tmp_path)
    first, records_path, _ = _run(
        paths,
        run_id="snapshot-run-good",
        frozen_at="2026-09-01T12:00:00Z",
    )
    assert first.succeeded
    original = records_path.read_bytes()
    with paths["papers"].open(newline="", encoding="utf-8") as handle:
        paper_rows = list(csv.DictReader(handle))
    changed = deepcopy(paper_rows[0])
    changed["provider_id"] = "https://openalex.org/W-MISSING"
    with paths["papers"].open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(changed))
        writer.writeheader()
        writer.writerow(changed)

    failed, _, integrity_path = _run(
        paths,
        run_id="snapshot-run-failed",
        frozen_at="2026-09-01T13:00:00Z",
    )

    assert not failed.succeeded
    assert records_path.read_bytes() == original
    report = json.loads(integrity_path.read_text(encoding="utf-8"))
    assert report["output"]["stale_existing_artifact_preserved"] is True
