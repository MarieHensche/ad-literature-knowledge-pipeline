from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from ad_lit_pipeline.core.step import StepResult, StepSpec
from ad_lit_pipeline.corpus.identity import (
    SourceVersionAssessment,
    WorkIdentityAssessment,
    assess_source_version,
    assess_work_identity,
    normalize_doi,
)
from ad_lit_pipeline.corpus.source_types import (
    CLASSIFICATION_NEEDS_REVIEW,
    SourceTypeAssessment,
    classify_source_type,
)
from ad_lit_pipeline.corpus.specification import (
    CorpusSpecification,
    corpus_specification_from_contract,
    resolve_as_of,
)
from ad_lit_pipeline.corpus.temporal import assess_temporal_eligibility
from ad_lit_pipeline.io.json_io import read_json_object
from ad_lit_pipeline.providers.evidence import (
    PROVIDER_EVIDENCE_ARCHIVED,
    PROVIDER_EVIDENCE_SCHEMA_VERSION,
    candidate_evidence_errors,
    json_object_from_response_bytes,
    read_provider_evidence_index,
    sha256_mapping,
    verify_provider_evidence,
)
from ad_lit_pipeline.records import (
    SCHEMA_VERSION,
    canonical_json,
    make_payload_record_id,
    make_record_id,
    record_from_dict,
    record_to_dict,
    validate_record_artifacts,
)
from ad_lit_pipeline.records.models import (
    IdentityStatus,
    PartialDate,
    PartialDateCertainty,
    PartialDatePrecision,
    RecordEnvelope,
    TemporalEligibility,
)
from ad_lit_pipeline.topics.contract import load_topic_contract


STEP = StepSpec(
    name="materialize_corpus_snapshot",
    inputs=[
        "deduped_candidates_jsonl",
        "papers_csv",
        "provider_evidence_index_jsonl",
        "provider_response_pages_dir",
        "collection_plan_json",
        "topic_contract_yaml",
    ],
    outputs=["corpus_records_jsonl", "corpus_snapshot_integrity_json"],
    uses_llm=False,
    description=(
        "Materialize strict v1 corpus records and atomically freeze a verified "
        "corpus snapshot."
    ),
)

SNAPSHOT_INTEGRITY_SCHEMA_VERSION = "1.0.0"
SNAPSHOT_MATERIALIZATION_POLICY_VERSION = "1.0.0"
MATERIALIZATION_EXTENSION = "pipeline.corpus_materialization"
PROVIDER_EXTENSION = "provider.evidence"
PRODUCING_STEP_ID = STEP.name


@dataclass(frozen=True)
class SnapshotBuild:
    records: tuple[RecordEnvelope, ...]
    snapshot_id: str
    record_counts: Mapping[str, int]
    coverage_status: str
    coverage_dimensions: Mapping[str, Any]
    limitations: tuple[str, ...]
    input_hashes: Mapping[str, str]
    provider_evidence_summary: Mapping[str, Any]


@dataclass(frozen=True)
class ResolvedObservation:
    provider: str
    provider_item_id: str
    evidence: Mapping[str, Any]
    page_record: Mapping[str, Any]
    raw_record: Mapping[str, Any]
    artifact_path: Path


class SnapshotFreezeError(ValueError):
    """A structured pre-freeze failure that must not emit frozen records."""

    def __init__(self, issues: Sequence[Mapping[str, Any]]) -> None:
        normalized = tuple(dict(issue) for issue in issues)
        self.issues = normalized
        first = normalized[0] if normalized else {"message": "unknown failure"}
        super().__init__(
            "Corpus snapshot freeze denied: " + str(first.get("message") or first)
        )


def _sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _sha256_file(path: Path) -> str:
    return _sha256_bytes(path.read_bytes())


def _canonical_sha256(value: Any) -> str:
    return _sha256_bytes(canonical_json(value).encode("utf-8"))


def _atomic_write(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
    finally:
        if temporary_path.exists():
            temporary_path.unlink()


def _json_bytes(payload: Mapping[str, Any]) -> bytes:
    return (
        json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True) + "\n"
    ).encode("utf-8")


def _records_bytes(records: Sequence[RecordEnvelope]) -> bytes:
    return b"".join(
        canonical_json(record_to_dict(record)).encode("utf-8") + b"\n"
        for record in records
    )


def _utc_datetime(value: str, *, assume_utc: bool = False) -> datetime:
    candidate = str(value or "").strip()
    if not candidate:
        raise ValueError("timestamp is empty")
    parsed = datetime.fromisoformat(candidate.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        if not assume_utc:
            raise ValueError(f"timestamp has no UTC offset: {candidate!r}")
        parsed = parsed.replace(tzinfo=timezone.utc)
    if parsed.utcoffset() != timezone.utc.utcoffset(parsed):
        parsed = parsed.astimezone(timezone.utc)
    return parsed


def _utc_timestamp(value: str, *, assume_utc: bool = False) -> str:
    return _utc_datetime(value, assume_utc=assume_utc).isoformat().replace(
        "+00:00",
        "Z",
    )


def _now_utc() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _artifact_reference(path: Path, artifact_root: Path) -> str:
    resolved = path.resolve()
    root = artifact_root.resolve()
    if not resolved.is_relative_to(root):
        raise ValueError(
            f"Artifact {resolved} is outside declared artifact root {root}."
        )
    return resolved.relative_to(root).as_posix()


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid JSON at {path}:{line_number}.") from exc
            if not isinstance(row, dict):
                raise ValueError(f"Expected JSON object at {path}:{line_number}.")
            rows.append(row)
    return rows


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _candidate_key(row: Mapping[str, Any]) -> tuple[str, str]:
    return (
        normalize_doi(row.get("doi")),
        str(row.get("provider_id") or "").strip(),
    )


def _issue(code: str, message: str, **context: Any) -> dict[str, Any]:
    return {
        "code": code,
        "message": message,
        **{key: value for key, value in context.items() if value is not None},
    }


def _placeholder_id(record_type: str) -> str:
    return make_record_id(
        record_type,
        {"phase": "materialize_corpus_snapshot", "record_type": record_type},
        schema_version=SCHEMA_VERSION,
    )


def _base_payload(
    record_type: str,
    *,
    snapshot_id: str,
    created_at: str,
    producing_run_id: str,
    provenance: Sequence[Mapping[str, Any]],
    parent_record_ids: Sequence[str] = (),
    source_record_ids: Sequence[str] = (),
    warnings: Sequence[Mapping[str, Any]] = (),
    policy_versions: Mapping[str, str] | None = None,
    extensions: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "record_type": record_type,
        "schema_version": SCHEMA_VERSION,
        "record_id": _placeholder_id(record_type),
        "created_at": created_at,
        "corpus_snapshot_id": snapshot_id,
        "producing_run_id": producing_run_id,
        "producing_step_id": PRODUCING_STEP_ID,
        "parent_record_ids": sorted(set(parent_record_ids)),
        "source_record_ids": sorted(set(source_record_ids)),
        "provenance": [dict(item) for item in provenance],
        "record_status": "active",
        "validation_warnings": sorted(
            (dict(item) for item in warnings),
            key=lambda item: (
                str(item.get("code") or ""),
                str(item.get("field_path") or ""),
            ),
        ),
        "policy_versions": {
            "record_contracts": SCHEMA_VERSION,
            "corpus_specification": "1.0.0",
            "snapshot_materialization": SNAPSHOT_MATERIALIZATION_POLICY_VERSION,
            **dict(policy_versions or {}),
        },
        "extensions": dict(extensions or {}),
    }


def _refresh_id(payload: dict[str, Any]) -> str:
    record_id = make_payload_record_id(
        str(payload["record_type"]),
        payload,
        schema_version=str(payload["schema_version"]),
    )
    payload["record_id"] = record_id
    return record_id


def _provenance(reference: str, sha256: str, relation: str) -> dict[str, Any]:
    return {
        "kind": "artifact",
        "relation": relation,
        "reference": reference,
        "sha256": sha256,
    }


def _validation_warning(
    code: str,
    message: str,
    field_path: str | None = None,
) -> dict[str, Any]:
    return {"code": code, "message": message, "field_path": field_path}


def _observations(candidate: Mapping[str, Any]) -> list[dict[str, Any]]:
    values: list[dict[str, Any]] = [dict(candidate)]
    for field in ("duplicate_provenance", "in_fetch_duplicate_provenance"):
        items = candidate.get(field)
        if not isinstance(items, list):
            continue
        values.extend(dict(item) for item in items if isinstance(item, Mapping))

    unique: dict[tuple[str, Any, str], dict[str, Any]] = {}
    for value in values:
        evidence = value.get("provider_evidence")
        evidence_map = evidence if isinstance(evidence, Mapping) else {}
        key = (
            str(evidence_map.get("page_evidence_id") or ""),
            evidence_map.get("result_position"),
            str(value.get("provider_id") or candidate.get("provider_id") or ""),
        )
        unique.setdefault(key, value)
    return list(unique.values())


def _resolve_observation(
    observation: Mapping[str, Any],
    candidate: Mapping[str, Any],
    evidence_by_id: Mapping[str, Mapping[str, Any]],
    evidence_index_path: Path,
) -> ResolvedObservation:
    evidence = observation.get("provider_evidence")
    if not isinstance(evidence, Mapping):
        raise ValueError("provider_evidence is missing")
    if evidence.get("status") != PROVIDER_EVIDENCE_ARCHIVED:
        raise ValueError("provider_evidence is not archived")
    page_id = str(evidence.get("page_evidence_id") or "")
    page = evidence_by_id.get(page_id)
    if page is None:
        raise ValueError(f"page evidence {page_id!r} is absent from the index")
    request = page.get("request")
    response = page.get("response")
    context = page.get("retrieval_context")
    if not all(isinstance(value, Mapping) for value in (request, response, context)):
        raise ValueError(f"page evidence {page_id!r} has invalid structure")
    assert isinstance(request, Mapping)
    assert isinstance(response, Mapping)
    assert isinstance(context, Mapping)

    comparisons = (
        ("request_sha256", request.get("request_sha256")),
        ("redacted_request_url", request.get("redacted_url")),
        ("response_sha256", response.get("response_sha256")),
        ("response_uri", response.get("artifact_uri")),
        ("response_media_type", response.get("media_type")),
        ("retrieved_at", response.get("retrieved_at")),
        ("page_or_cursor", context.get("page_or_cursor")),
        ("result_count", response.get("result_count")),
    )
    for field, expected in comparisons:
        if evidence.get(field) != expected:
            raise ValueError(f"provider evidence {field} does not match page")

    position = evidence.get("result_position")
    if not isinstance(position, int) or position < 1:
        raise ValueError("provider result_position is invalid")
    artifact_uri = str(response.get("artifact_uri") or "")
    artifact_path = (evidence_index_path.parent / artifact_uri).resolve()
    content = artifact_path.read_bytes()
    raw_page = json_object_from_response_bytes(
        content,
        str(response.get("content_encoding") or "") or None,
        f"Provider page {page_id}",
    )
    results = raw_page.get("results")
    if not isinstance(results, list) or position > len(results):
        raise ValueError("provider result_position is outside the archived page")
    raw_record = results[position - 1]
    if not isinstance(raw_record, Mapping):
        raise ValueError("archived provider result is not an object")
    raw_hash = sha256_mapping(raw_record)
    if evidence.get("raw_record_sha256") != raw_hash:
        raise ValueError("provider raw item hash does not match archived bytes")
    if evidence.get("raw_record_json_pointer") != f"/results/{position - 1}":
        raise ValueError("provider raw item JSON pointer is incorrect")
    provider_item_id = str(
        observation.get("provider_id")
        or candidate.get("provider_id")
        or raw_record.get("id")
        or ""
    ).strip()
    if not provider_item_id or provider_item_id != str(raw_record.get("id") or ""):
        raise ValueError("provider item identity does not match archived result")
    provider = str(
        observation.get("provider")
        or candidate.get("provider")
        or page.get("provider")
        or ""
    ).casefold()
    if not provider or provider != str(page.get("provider") or "").casefold():
        raise ValueError("provider name does not match archived page")
    return ResolvedObservation(
        provider=provider,
        provider_item_id=provider_item_id,
        evidence=dict(evidence),
        page_record=page,
        raw_record=dict(raw_record),
        artifact_path=artifact_path,
    )


def _endpoint(redacted_url: str) -> str:
    parsed = urlsplit(redacted_url)
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))


def _as_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"expected integer value, got {value!r}") from exc


def _provider_timestamp(value: Any) -> str | None:
    candidate = str(value or "").strip()
    if not candidate:
        return None
    return _utc_timestamp(candidate, assume_utc=True)


def _identifier(scheme: str, value: str, uri: str | None) -> dict[str, Any]:
    return {"scheme": scheme, "value": value, "uri": uri}


def _identifiers(
    candidate: Mapping[str, Any],
    observations: Sequence[ResolvedObservation],
) -> list[dict[str, Any]]:
    identifiers: dict[tuple[str, str], dict[str, Any]] = {}
    doi = normalize_doi(candidate.get("doi"))
    if doi:
        identifiers[("doi", doi.casefold())] = _identifier(
            "doi", doi, f"https://doi.org/{doi}"
        )
    for observation in observations:
        value = observation.provider_item_id
        uri = value if value.startswith(("http://", "https://")) else None
        identifiers[(observation.provider, value.casefold())] = _identifier(
            observation.provider,
            value,
            uri,
        )
    return [identifiers[key] for key in sorted(identifiers)]


def _reference_identifiers(raw_record: Mapping[str, Any]) -> list[dict[str, Any]]:
    values = raw_record.get("referenced_works")
    if not isinstance(values, list):
        return []
    identifiers: dict[str, dict[str, Any]] = {}
    for value in values:
        cleaned = str(value or "").strip()
        if cleaned:
            identifiers.setdefault(
                cleaned.casefold(),
                _identifier(
                    "openalex",
                    cleaned,
                    cleaned if cleaned.startswith(("http://", "https://")) else None,
                ),
            )
    return [identifiers[key] for key in sorted(identifiers)]


def _contributors(
    candidate: Mapping[str, Any],
    raw_record: Mapping[str, Any],
) -> list[dict[str, Any]]:
    authorships = raw_record.get("authorships")
    contributors: list[dict[str, Any]] = []
    if isinstance(authorships, list):
        for position, authorship in enumerate(authorships):
            if not isinstance(authorship, Mapping):
                continue
            author = authorship.get("author")
            if not isinstance(author, Mapping):
                continue
            name = str(author.get("display_name") or "").strip()
            if not name:
                continue
            author_identifiers: list[dict[str, Any]] = []
            orcid = str(author.get("orcid") or "").strip()
            if orcid:
                value = orcid.rsplit("/", maxsplit=1)[-1]
                author_identifiers.append(_identifier("orcid", value, orcid))
            contributors.append(
                {
                    "name": name,
                    "role": "author",
                    "position": position,
                    "identifiers": author_identifiers,
                }
            )
    if contributors:
        return contributors
    authors = str(candidate.get("authors") or "").strip()
    return [
        {
            "name": name.strip(),
            "role": "author",
            "position": position,
            "identifiers": [],
        }
        for position, name in enumerate(authors.split(";"))
        if name.strip()
    ]


def _exact_partial_date(value: Any) -> PartialDate | None:
    candidate = str(value or "").strip()
    if not candidate:
        return None
    try:
        date.fromisoformat(candidate)
    except ValueError:
        return None
    if len(candidate) != 10:
        return None
    return PartialDate(
        value=candidate,
        precision=PartialDatePrecision.DAY,
        certainty=PartialDateCertainty.EXACT,
    )


def _partial_date_payload(value: PartialDate | None) -> dict[str, Any] | None:
    if value is None:
        return None
    return {
        "value": value.value,
        "precision": value.precision.value,
        "certainty": value.certainty.value,
    }


def _version_label(raw_record: Mapping[str, Any]) -> str | None:
    for field in ("primary_location", "best_oa_location"):
        location = raw_record.get(field)
        if isinstance(location, Mapping):
            value = str(location.get("version") or "").strip()
            if value:
                return value
    value = str(raw_record.get("version") or "").strip()
    return value or None


def _publisher(raw_record: Mapping[str, Any]) -> str | None:
    location = raw_record.get("primary_location")
    if not isinstance(location, Mapping):
        return None
    source = location.get("source")
    if not isinstance(source, Mapping):
        return None
    value = str(source.get("host_organization_name") or "").strip()
    return value or None


def _parse_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    normalized = str(value or "").strip().casefold()
    if normalized in {"true", "yes", "1"}:
        return True
    if normalized in {"false", "no", "0"}:
        return False
    return None


def _location_kind(value: Any, uri: str) -> str:
    normalized = str(value or "").strip().casefold()
    if normalized in {"landing_page", "pdf", "html", "xml", "repository", "data"}:
        return normalized
    path = urlsplit(uri).path.casefold()
    if path.endswith(".pdf") or "/pdf" in path:
        return "pdf"
    return "landing_page"


def _candidate_access_locations(
    candidate: Mapping[str, Any],
    paper: Mapping[str, str],
    *,
    source_version_id: str,
    provider_record_id: str,
    provider_observed_at: str,
    snapshot_id: str,
    created_at: str,
    producing_run_id: str,
    candidate_provenance: Mapping[str, Any],
    papers_provenance: Mapping[str, Any],
) -> list[dict[str, Any]]:
    locations: dict[str, dict[str, Any]] = {}
    raw_locations = candidate.get("full_text_locations")
    if isinstance(raw_locations, list):
        for item in raw_locations:
            if not isinstance(item, Mapping):
                continue
            uri = str(item.get("url") or "").strip()
            if not uri:
                continue
            locations.setdefault(
                uri,
                {
                    "uri": uri,
                    "kind": _location_kind(item.get("kind"), uri),
                    "observed_at": provider_observed_at,
                    "status": "unknown",
                    "method": "provider_api",
                    "media_type": (
                        "application/pdf"
                        if _location_kind(item.get("kind"), uri) == "pdf"
                        else None
                    ),
                    "license": str(item.get("license") or "").strip() or None,
                    "is_open_access": _parse_bool(item.get("is_open_access")),
                    "provider_record_id": provider_record_id,
                    "source": str(item.get("source") or "provider_metadata"),
                    "provenance": candidate_provenance,
                },
            )
    candidate_uri = str(candidate.get("url") or "").strip()
    if candidate_uri:
        locations.setdefault(
            candidate_uri,
            {
                "uri": candidate_uri,
                "kind": "landing_page",
                "observed_at": provider_observed_at,
                "status": "unknown",
                "method": "provider_api",
                "media_type": None,
                "license": None,
                "is_open_access": None,
                "provider_record_id": provider_record_id,
                "source": "candidate_primary_url",
                "provenance": candidate_provenance,
            },
        )

    verified_uri = str(paper.get("full_text_url") or "").strip()
    verification_status = str(
        paper.get("full_text_availability_status") or ""
    ).strip()
    if verified_uri:
        checked_at = str(paper.get("full_text_url_checked_at") or "").strip()
        observed_at = (
            _utc_timestamp(checked_at)
            if checked_at
            else provider_observed_at
        )
        status = "available" if verification_status == "verified" else "unknown"
        existing = locations.get(verified_uri, {})
        locations[verified_uri] = {
            "uri": verified_uri,
            "kind": _location_kind(
                paper.get("full_text_url_kind") or existing.get("kind"),
                verified_uri,
            ),
            "observed_at": observed_at,
            "status": status,
            "method": "public_http" if verification_status == "verified" else "provider_api",
            "media_type": (
                str(paper.get("full_text_url_content_type") or "").strip()
                or existing.get("media_type")
                or None
            ),
            "license": (
                str(paper.get("full_text_license") or "").strip()
                or existing.get("license")
                or None
            ),
            "is_open_access": (
                _parse_bool(paper.get("full_text_is_open_access"))
                if paper.get("full_text_is_open_access") not in (None, "")
                else existing.get("is_open_access")
            ),
            "provider_record_id": existing.get("provider_record_id"),
            "source": str(
                paper.get("full_text_availability_source")
                or existing.get("source")
                or "full_text_availability"
            ),
            "provenance": papers_provenance,
        }

    payloads: list[dict[str, Any]] = []
    for uri in sorted(locations):
        location = locations[uri]
        linked_provider_id = location.get("provider_record_id")
        source_ids = [linked_provider_id] if linked_provider_id else []
        payload = _base_payload(
            "access_location",
            snapshot_id=snapshot_id,
            created_at=created_at,
            producing_run_id=producing_run_id,
            provenance=[location["provenance"]],
            parent_record_ids=[source_version_id],
            source_record_ids=source_ids,
            extensions={
                MATERIALIZATION_EXTENSION: {
                    "observation_source": location["source"],
                    "verification_status": verification_status or "not_checked",
                }
            },
        )
        payload.update(
            {
                "source_version_id": source_version_id,
                "provider_record_id": linked_provider_id,
                "uri": uri,
                "uri_sha256": _sha256_bytes(uri.encode("utf-8")),
                "location_kind": location["kind"],
                "access_method": location["method"],
                "observed_at": location["observed_at"],
                "access_status": location["status"],
                "media_type": location["media_type"],
                "license": location["license"],
                "is_open_access": location["is_open_access"],
                "http_status": None,
                "redirect_uri": None,
                "failure_reason": None,
            }
        )
        _refresh_id(payload)
        payloads.append(payload)
    return payloads


def _planned_query_ids(plan: Mapping[str, Any]) -> tuple[str, ...]:
    groups = plan.get("query_groups")
    identifiers: set[str] = set()
    if isinstance(groups, list):
        for group in groups:
            if not isinstance(group, Mapping):
                continue
            queries = group.get("queries")
            if not isinstance(queries, list):
                continue
            for query in queries:
                if not isinstance(query, Mapping):
                    continue
                query_id = str(query.get("query_id") or "").strip()
                if query_id:
                    identifiers.add(query_id)
    if identifiers:
        return tuple(sorted(identifiers))
    search_queries = plan.get("search_queries")
    if isinstance(search_queries, list):
        return tuple(
            f"legacy_query_{index}"
            for index, query in enumerate(search_queries, start=1)
            if query
        )
    return ()


def _coverage(
    plan: Mapping[str, Any],
    specification: CorpusSpecification,
    evidence_records: Sequence[Mapping[str, Any]],
    prepared: Sequence[Mapping[str, Any]],
    access_payloads: Sequence[Mapping[str, Any]],
    *,
    as_of: str,
) -> tuple[str, dict[str, Any], tuple[str, ...], tuple[str, ...]]:
    planned_ids = set(_planned_query_ids(plan))
    executed_ids: set[str] = set()
    executed_logical_ids: set[str] = set()
    providers: set[str] = set()
    tiers: set[int] = set()
    page_count = 0
    result_count = 0
    for page in evidence_records:
        providers.add(str(page.get("provider") or "").casefold())
        context = page.get("retrieval_context")
        response = page.get("response")
        if isinstance(context, Mapping):
            query_id = str(context.get("query_id") or "").strip()
            logical_id = str(context.get("logical_query_id") or query_id).strip()
            if query_id:
                executed_ids.add(query_id)
            if logical_id:
                executed_logical_ids.add(logical_id)
            tier = context.get("query_tier")
            if isinstance(tier, int):
                tiers.add(tier)
        if isinstance(response, Mapping):
            page_count += 1
            count = response.get("result_count")
            if isinstance(count, int):
                result_count += count

    actual_work_kinds = sorted(
        {
            str(item["source_type_assessment"].work_kind.value)
            for item in prepared
        }
    )
    actual_languages = sorted(
        {
            str(item["language"])
            for item in prepared
            if str(item.get("language") or "")
        }
    )
    missing_queries = sorted(planned_ids - executed_logical_ids)
    missing_providers = sorted(set(specification.providers) - providers)
    fully_executed = bool(planned_ids) and not missing_queries
    status = (
        "adequate_for_rule"
        if fully_executed and not missing_providers
        else "partial"
    )
    verified_access = sum(
        1 for item in access_payloads if item.get("access_status") == "available"
    )
    open_access = sum(
        1 for item in access_payloads if item.get("is_open_access") is True
    )
    dimensions = {
        "providers": {
            "declared": list(specification.providers),
            "observed": sorted(providers),
            "missing": missing_providers,
        },
        "source_types": {
            "allowed": list(specification.allowed_source_types),
            "included": actual_work_kinds,
        },
        "date_window": {
            "publication_start": specification.publication_start,
            "publication_end": specification.publication_end,
            "as_of_inclusive": as_of,
            "availability_rule": specification.availability_date_rule,
        },
        "languages": {
            "allowed": list(specification.allowed_languages),
            "include_unknown": specification.include_unknown_language,
            "included": actual_languages,
        },
        "query_variants": {
            "planned_logical_query_ids": sorted(planned_ids),
            "executed_query_ids": sorted(executed_ids),
            "executed_logical_query_ids": sorted(executed_logical_ids),
            "missing_logical_query_ids": missing_queries,
            "successful_page_count": page_count,
            "provider_result_count_before_selection": result_count,
        },
        "synonym_coverage": {
            "assessment": (
                "declared logical query variants all observed"
                if fully_executed
                else "only executed query variants are evidenced"
            )
        },
        "adjacent_literature": {
            "executed_non_primary_tiers": sorted(tier for tier in tiers if tier > 0),
            "assessment": (
                "adjacent or relaxed retrieval observed"
                if any(tier > 0 for tier in tiers)
                else "no non-primary retrieval tier observed"
            ),
        },
        "retrieval_failures": {
            "successful_pages_archived": page_count,
            "failed_http_attempts_archived": False,
            "assessment": "Phase 2.2 archives successful response bodies only",
        },
        "inaccessible_material": {
            "access_locations": len(access_payloads),
            "verified_available": verified_access,
            "open_access_claims": open_access,
        },
        "deduplication": {
            "selected_candidate_rows": len(prepared),
            "work_identity_basis_order": list(specification.identity_basis_order),
            "source": "deduped candidate artifact plus strict work/version identity",
        },
    }
    limitations = {
        "Coverage describes observed provider pages, not global literature completeness.",
        "Failed HTTP attempts without successful response bodies are not archived in Phase 2.2.",
        "Public availability uses an exact provider-asserted publication date "
        "for the identified version.",
    }
    if missing_queries:
        limitations.add(
            "The target was reached or retrieval ended before every planned "
            "logical query was observed."
        )
    if missing_providers:
        limitations.add("Not every provider declared by the corpus specification was observed.")
    if verified_access == 0:
        limitations.add("No access location was independently verified as available.")
    return status, dimensions, tuple(sorted(limitations)), tuple(sorted(providers))


def _plan_window(plan: Mapping[str, Any]) -> tuple[str | None, str | None]:
    constraints = plan.get("corpus_constraints")
    if not isinstance(constraints, Mapping):
        return None, None
    window = constraints.get("publication_window")
    if not isinstance(window, Mapping):
        return None, None
    return (
        str(window.get("start") or "").strip() or None,
        str(window.get("end") or "").strip() or None,
    )


def _scope(
    contract: Mapping[str, Any],
    specification: CorpusSpecification,
) -> dict[str, Any]:
    research_topic = contract.get("research_topic")
    research_map = research_topic if isinstance(research_topic, Mapping) else {}
    scope = contract.get("scope")
    scope_map = scope if isinstance(scope, Mapping) else {}
    include = scope_map.get("include_criteria")
    exclude = scope_map.get("exclude_criteria")
    include_values = include if isinstance(include, list) else []
    exclude_values = exclude if isinstance(exclude, list) else []
    research_question = str(
        research_map.get("description") or research_map.get("title") or ""
    ).strip()
    return {
        "research_question": research_question,
        "providers": list(specification.providers),
        "source_types": list(specification.allowed_source_types),
        "languages": list(specification.allowed_languages),
        "publication_start": specification.publication_start,
        "publication_end": specification.publication_end,
        "inclusion_policy_sha256": _canonical_sha256(include_values),
        "exclusion_policy_sha256": _canonical_sha256(exclude_values),
    }


def _provider_record_payload(
    observation: ResolvedObservation,
    *,
    snapshot_id: str,
    created_at: str,
    producing_run_id: str,
    artifact_root: Path,
) -> dict[str, Any]:
    page = observation.page_record
    request = page["request"]
    context = page["retrieval_context"]
    response = page["response"]
    assert isinstance(request, Mapping)
    assert isinstance(context, Mapping)
    assert isinstance(response, Mapping)
    retrieved_at = _utc_timestamp(str(response.get("retrieved_at") or ""))
    provider_updated_at = _provider_timestamp(
        observation.raw_record.get("updated_date")
        or observation.raw_record.get("updated_at")
    )
    if (
        provider_updated_at is not None
        and _utc_datetime(provider_updated_at) > _utc_datetime(retrieved_at)
    ):
        raise ValueError("provider update timestamp follows its retrieval observation")
    artifact_reference = _artifact_reference(observation.artifact_path, artifact_root)
    response_sha256 = str(response.get("response_sha256") or "")
    payload = _base_payload(
        "provider_record",
        snapshot_id=snapshot_id,
        created_at=created_at,
        producing_run_id=producing_run_id,
        provenance=[
            _provenance(
                artifact_reference,
                response_sha256,
                "observed_in_provider_response_page",
            )
        ],
        policy_versions={"provider_evidence": PROVIDER_EVIDENCE_SCHEMA_VERSION},
        extensions={
            PROVIDER_EXTENSION: {
                "page_evidence_id": page["page_evidence_id"],
                "response_sha256": response_sha256,
                "response_byte_count": response.get("byte_count"),
                "raw_record_sha256": observation.evidence["raw_record_sha256"],
                "raw_record_json_pointer": observation.evidence[
                    "raw_record_json_pointer"
                ],
                "result_position": observation.evidence["result_position"],
                "result_count": observation.evidence["result_count"],
            }
        },
    )
    redacted_url = str(request.get("redacted_url") or "")
    provider_item_url = (
        observation.provider_item_id
        if observation.provider_item_id.startswith(("http://", "https://"))
        else None
    )
    payload.update(
        {
            "provider_name": observation.provider,
            "provider_version": None,
            "endpoint": _endpoint(redacted_url),
            "provider_item_id": observation.provider_item_id,
            "provider_item_url": provider_item_url,
            "query_id": str(context.get("query_id") or ""),
            "request_sha256": str(request.get("request_sha256") or ""),
            "redacted_request_url": redacted_url,
            "query_tier": _as_int(context.get("query_tier")),
            "page_or_cursor": str(context.get("page_or_cursor") or "") or None,
            "provider_rank": _as_int(observation.evidence.get("result_position")),
            "retrieved_at": retrieved_at,
            "provider_updated_at": provider_updated_at,
            "retrieval_status": "succeeded",
            "raw_record_media_type": str(response.get("media_type") or "application/json"),
            # The exact response page is the verifiable raw artifact. The item
            # occurrence and its canonical hash live in the provider extension.
            "raw_record_sha256": response_sha256,
            "raw_record_uri": artifact_reference,
            "license": None,
            "error_code": None,
            "error_message": None,
        }
    )
    _refresh_id(payload)
    return payload


def _prepare_candidates(
    candidates: Sequence[Mapping[str, Any]],
    papers: Sequence[Mapping[str, str]],
    evidence_records: Sequence[Mapping[str, Any]],
    evidence_index_path: Path,
    specification: CorpusSpecification,
    *,
    as_of: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    issues: list[dict[str, Any]] = []
    candidates_by_key: dict[tuple[str, str], Mapping[str, Any]] = {}
    duplicate_candidate_keys: set[tuple[str, str]] = set()
    for candidate in candidates:
        key = _candidate_key(candidate)
        if key in candidates_by_key:
            duplicate_candidate_keys.add(key)
        candidates_by_key[key] = candidate
    for key in sorted(duplicate_candidate_keys):
        issues.append(
            _issue(
                "duplicate_candidate_identity",
                f"Deduped candidate artifact contains duplicate key {key!r}.",
            )
        )

    paper_keys: set[tuple[str, str]] = set()
    selected: list[tuple[Mapping[str, Any], Mapping[str, str]]] = []
    for paper in papers:
        key = _candidate_key(paper)
        if key in paper_keys:
            issues.append(
                _issue(
                    "duplicate_included_paper",
                    f"Included papers CSV repeats candidate key {key!r}.",
                    paper_id=paper.get("paper_id"),
                )
            )
            continue
        paper_keys.add(key)
        candidate = candidates_by_key.get(key)
        if candidate is None:
            issues.append(
                _issue(
                    "included_candidate_missing",
                    f"Included paper does not resolve to a deduped candidate: {key!r}.",
                    paper_id=paper.get("paper_id"),
                )
            )
            continue
        selected.append((candidate, paper))
    if not papers:
        issues.append(
            _issue("empty_included_corpus", "No included paper rows are available.")
        )

    primary_errors = candidate_evidence_errors(
        [dict(candidate) for candidate, _ in selected],
        [dict(record) for record in evidence_records],
        require_archived=True,
    )
    issues.extend(
        _issue("candidate_provider_evidence_invalid", message)
        for message in primary_errors
    )

    evidence_by_id = {
        str(record.get("page_evidence_id") or ""): record
        for record in evidence_records
    }
    prepared: list[dict[str, Any]] = []
    seen_version_keys: set[str] = set()
    for candidate, paper in selected:
        label = str(
            paper.get("paper_id")
            or candidate.get("provider_id")
            or candidate.get("title")
            or "candidate"
        )
        resolved_observations: list[ResolvedObservation] = []
        for observation in _observations(candidate):
            try:
                resolved_observations.append(
                    _resolve_observation(
                        observation,
                        candidate,
                        evidence_by_id,
                        evidence_index_path,
                    )
                )
            except (OSError, ValueError) as exc:
                issues.append(
                    _issue(
                        "provider_observation_invalid",
                        f"{label}: {exc}",
                        paper_id=paper.get("paper_id"),
                    )
                )
        if not resolved_observations:
            continue
        raw_record = resolved_observations[0].raw_record
        combined = {**raw_record, **candidate}
        work_identity = assess_work_identity(combined)
        source_type = classify_source_type(combined)
        version = assess_source_version(combined, work_identity)
        provider = str(candidate.get("provider") or "").casefold()
        language = str(candidate.get("language") or raw_record.get("language") or "").casefold()

        if work_identity.identity_status is not IdentityStatus.RESOLVED:
            issues.append(
                _issue(
                    "work_identity_unresolved",
                    f"{label}: work identity is {work_identity.identity_status.value}.",
                    reasons=list(work_identity.review_reasons),
                )
            )
        if work_identity.identity_key is None or work_identity.identity_basis is None:
            issues.append(
                _issue("work_identity_missing", f"{label}: work identity has no key.")
            )
        if source_type.status == CLASSIFICATION_NEEDS_REVIEW:
            issues.append(
                _issue(
                    "source_type_unresolved",
                    f"{label}: source type requires review.",
                    reasons=list(source_type.review_reasons),
                )
            )
        if source_type.work_kind.value not in specification.allowed_source_types:
            issues.append(
                _issue(
                    "source_type_disallowed",
                    f"{label}: {source_type.work_kind.value!r} is outside corpus policy.",
                )
            )
        if provider not in specification.providers:
            issues.append(
                _issue(
                    "provider_disallowed",
                    f"{label}: provider {provider!r} is outside corpus policy.",
                )
            )
        if (
            specification.allowed_languages
            and language
            and language not in specification.allowed_languages
        ):
            issues.append(
                _issue(
                    "language_disallowed",
                    f"{label}: language {language!r} is outside corpus policy.",
                )
            )
        if not language and not specification.include_unknown_language:
            issues.append(
                _issue(
                    "unknown_language_disallowed",
                    f"{label}: language is unknown and corpus policy excludes it.",
                )
            )
        if version.version_kind.value not in specification.retained_version_kinds:
            issues.append(
                _issue(
                    "version_kind_disallowed",
                    f"{label}: version kind {version.version_kind.value!r} is not retained.",
                )
            )
        if version.version_identity_key is None:
            issues.append(
                _issue(
                    "source_version_identity_missing",
                    f"{label}: source-version identity could not be constructed.",
                )
            )
        elif version.version_identity_key in seen_version_keys:
            issues.append(
                _issue(
                    "duplicate_source_version_identity",
                    f"{label}: selected rows repeat a source-version identity.",
                )
            )
        else:
            seen_version_keys.add(version.version_identity_key)

        publication = _exact_partial_date(
            candidate.get("publication_date") or raw_record.get("publication_date")
        )
        if publication is None:
            issues.append(
                _issue(
                    "publication_date_not_exact",
                    f"{label}: an exact provider publication date is required.",
                )
            )
            availability = None
            temporal = None
        else:
            availability = publication
            temporal = assess_temporal_eligibility(
                availability,
                availability,
                as_of=as_of,
            )
            if temporal.temporal_eligibility is not TemporalEligibility.ELIGIBLE:
                issues.append(
                    _issue(
                        "snapshot_cutoff_violation",
                        f"{label}: version is not defensibly available at cutoff {as_of}.",
                        reasons=list(temporal.reasons),
                    )
                )
        if publication is not None:
            published = publication.value
            if specification.publication_start and published < specification.publication_start:
                issues.append(
                    _issue(
                        "publication_window_violation",
                        f"{label}: publication precedes the corpus window.",
                    )
                )
            if specification.publication_end and published > specification.publication_end:
                issues.append(
                    _issue(
                        "publication_window_violation",
                        f"{label}: publication follows the corpus window.",
                    )
                )
        for field, expected in (
            ("corpus_publication_window_start", specification.publication_start),
            ("corpus_publication_window_end", specification.publication_end),
        ):
            actual = candidate.get(field)
            if expected is not None and actual != expected:
                issues.append(
                    _issue(
                        "candidate_window_mismatch",
                        f"{label}: {field}={actual!r}, expected {expected!r}.",
                    )
                )

        prepared.append(
            {
                "candidate": candidate,
                "paper": paper,
                "raw_record": raw_record,
                "observations": resolved_observations,
                "work_identity": work_identity,
                "source_type_assessment": source_type,
                "version_assessment": version,
                "publication": publication,
                "availability": availability,
                "temporal": temporal,
                "language": language or None,
            }
        )
    return prepared, issues


def materialize(
    *,
    candidates_path: Path,
    papers_path: Path,
    provider_evidence_index_path: Path,
    provider_response_pages_dir: Path,
    plan_path: Path,
    topic_contract_path: Path,
    producing_run_id: str,
    artifact_root: Path,
    frozen_at: str | None = None,
) -> SnapshotBuild:
    """Build a complete frozen record set or raise before any output write."""
    root = artifact_root.resolve()
    inputs = {
        "deduped_candidates_jsonl": candidates_path,
        "papers_csv": papers_path,
        "provider_evidence_index_jsonl": provider_evidence_index_path,
        "collection_plan_json": plan_path,
        "topic_contract_yaml": topic_contract_path,
    }
    input_hashes = {name: _sha256_file(path) for name, path in inputs.items()}
    input_references = {
        name: _artifact_reference(path, root) for name, path in inputs.items()
    }
    provider_verification = verify_provider_evidence(
        provider_evidence_index_path,
        provider_response_pages_dir,
    )
    issues = [
        _issue("provider_evidence_integrity_error", message)
        for message in provider_verification.errors
    ]
    evidence_records = read_provider_evidence_index(provider_evidence_index_path)
    if not evidence_records:
        issues.append(
            _issue(
                "provider_evidence_empty",
                "Provider evidence index contains no successful response pages.",
            )
        )
    retrieval_times: list[str] = []
    for index, page in enumerate(evidence_records, start=1):
        response = page.get("response")
        if not isinstance(response, Mapping):
            issues.append(
                _issue(
                    "provider_evidence_structure_invalid",
                    f"Provider page {index} has no response object.",
                )
            )
            continue
        try:
            retrieval_times.append(
                _utc_timestamp(str(response.get("retrieved_at") or ""))
            )
        except ValueError as exc:
            issues.append(
                _issue(
                    "provider_retrieval_timestamp_invalid",
                    f"Provider page {index}: {exc}",
                )
            )
    if not retrieval_times:
        issues.append(
            _issue(
                "provider_retrieval_time_missing",
                "No valid provider retrieval timestamp is available.",
            )
        )

    contract = load_topic_contract(topic_contract_path)
    specification = corpus_specification_from_contract(contract)
    plan = read_json_object(plan_path)
    plan_start, plan_end = _plan_window(plan)
    if (plan_start, plan_end) != (
        specification.publication_start,
        specification.publication_end,
    ):
        issues.append(
            _issue(
                "plan_contract_window_mismatch",
                "Resolved plan publication window differs from the topic contract.",
                plan_window=[plan_start, plan_end],
                contract_window=[
                    specification.publication_start,
                    specification.publication_end,
                ],
            )
        )
    retrieval_started_at = (
        min(retrieval_times, key=_utc_datetime) if retrieval_times else _now_utc()
    )
    as_of = resolve_as_of(specification, retrieval_started_at)
    candidates = _read_jsonl(candidates_path)
    papers = _read_csv(papers_path)
    prepared, candidate_issues = _prepare_candidates(
        candidates,
        papers,
        evidence_records,
        provider_evidence_index_path,
        specification,
        as_of=as_of,
    )
    issues.extend(candidate_issues)
    if len(prepared) != len(papers):
        issues.append(
            _issue(
                "selected_materialization_count_mismatch",
                "Not every included paper reached the record-materialization boundary.",
                included_papers=len(papers),
                prepared_candidates=len(prepared),
            )
        )
    if issues:
        raise SnapshotFreezeError(issues)

    freeze_timestamp = _utc_timestamp(frozen_at) if frozen_at else _now_utc()
    input_candidate_provenance = _provenance(
        input_references["deduped_candidates_jsonl"],
        input_hashes["deduped_candidates_jsonl"],
        "materialized_from_candidate",
    )
    input_papers_provenance = _provenance(
        input_references["papers_csv"],
        input_hashes["papers_csv"],
        "selected_by_collection_screening",
    )
    placeholder_snapshot = _placeholder_id("corpus_snapshot")

    provider_payloads: dict[str, dict[str, Any]] = {}
    prepared_provider_ids: dict[int, list[str]] = {}
    for prepared_index, item in enumerate(prepared):
        provider_ids: list[str] = []
        for observation in item["observations"]:
            payload = _provider_record_payload(
                observation,
                snapshot_id=placeholder_snapshot,
                created_at=freeze_timestamp,
                producing_run_id=producing_run_id,
                artifact_root=root,
            )
            record_id = str(payload["record_id"])
            existing = provider_payloads.get(record_id)
            if existing is not None and canonical_json(existing) != canonical_json(payload):
                raise SnapshotFreezeError(
                    [
                        _issue(
                            "provider_record_identity_conflict",
                            f"Provider record {record_id} has competing payloads.",
                        )
                    ]
                )
            provider_payloads.setdefault(record_id, payload)
            provider_ids.append(record_id)
        prepared_provider_ids[prepared_index] = sorted(set(provider_ids))

    work_payloads: dict[str, dict[str, Any]] = {}
    work_id_by_identity: dict[str, str] = {}
    for item in prepared:
        identity: WorkIdentityAssessment = item["work_identity"]
        source_type: SourceTypeAssessment = item["source_type_assessment"]
        assert identity.identity_key is not None
        assert identity.identity_basis is not None
        candidate = item["candidate"]
        observations = item["observations"]
        title = str(candidate.get("title") or item["raw_record"].get("display_name") or "").strip()
        warnings = [
            _validation_warning(
                reason,
                f"Work identity assessment: {reason}.",
                "identity_status",
            )
            for reason in identity.review_reasons
        ]
        warnings.extend(
            _validation_warning(
                reason,
                f"Source-type assessment: {reason}.",
                "work_kind",
            )
            for reason in source_type.review_reasons
        )
        payload = _base_payload(
            "scholarly_work",
            snapshot_id=placeholder_snapshot,
            created_at=freeze_timestamp,
            producing_run_id=producing_run_id,
            provenance=[input_candidate_provenance],
            warnings=warnings,
            extensions={
                MATERIALIZATION_EXTENSION: {
                    "identity_evidence_json": canonical_json(identity.evidence),
                    "source_type_status": source_type.status,
                    "source_type_evidence_json": canonical_json(
                        source_type.evidence
                    ),
                }
            },
        )
        payload.update(
            {
                "preferred_title": title,
                "alternate_titles": [],
                "work_kind": source_type.work_kind.value,
                "identifiers": _identifiers(candidate, observations),
                "identity_basis": identity.identity_basis.value,
                "identity_key": identity.identity_key,
                "identity_status": identity.identity_status.value,
            }
        )
        _refresh_id(payload)
        existing_id = work_id_by_identity.get(identity.identity_key)
        if existing_id is not None:
            existing = work_payloads[existing_id]
            if existing["work_kind"] != payload["work_kind"]:
                raise SnapshotFreezeError(
                    [
                        _issue(
                            "competing_work_classification",
                            f"Work identity {identity.identity_key!r} has competing kinds.",
                        )
                    ]
                )
            alternate = set(existing["alternate_titles"])
            if title != existing["preferred_title"]:
                alternate.add(title)
            existing["alternate_titles"] = sorted(alternate)
            # Alternate titles are not identity fields, so the work ID remains valid.
            continue
        work_id = str(payload["record_id"])
        work_id_by_identity[identity.identity_key] = work_id
        work_payloads[work_id] = payload

    source_payloads: list[dict[str, Any]] = []
    access_payloads: list[dict[str, Any]] = []
    for prepared_index, item in enumerate(prepared):
        candidate = item["candidate"]
        paper = item["paper"]
        raw_record = item["raw_record"]
        identity: WorkIdentityAssessment = item["work_identity"]
        version: SourceVersionAssessment = item["version_assessment"]
        source_type: SourceTypeAssessment = item["source_type_assessment"]
        publication: PartialDate = item["publication"]
        availability: PartialDate = item["availability"]
        temporal = item["temporal"]
        assert identity.identity_key is not None
        assert temporal is not None
        work_id = work_id_by_identity[identity.identity_key]
        provider_ids = prepared_provider_ids[prepared_index]
        warnings = [
            _validation_warning(
                reason,
                f"Source-version assessment: {reason}.",
                "version_kind",
            )
            for reason in version.review_reasons
        ]
        if version.explicit_lineage_references:
            warnings.append(
                _validation_warning(
                    "unresolved_external_version_lineage",
                    "Explicit provider lineage references are preserved in the "
                    "extension but do not resolve to selected source-version "
                    "records.",
                    "previous_source_version_ids",
                )
            )
        payload = _base_payload(
            "source_version",
            snapshot_id=placeholder_snapshot,
            created_at=freeze_timestamp,
            producing_run_id=producing_run_id,
            provenance=[input_candidate_provenance],
            parent_record_ids=[work_id],
            source_record_ids=provider_ids,
            warnings=warnings,
            extensions={
                MATERIALIZATION_EXTENSION: {
                    "version_identity_key": version.version_identity_key,
                    "version_identity_status": version.identity_status.value,
                    "version_evidence_json": canonical_json(version.evidence),
                    "explicit_lineage_references_json": canonical_json(
                        version.explicit_lineage_references
                    ),
                    "availability_basis": (
                        "provider_asserted_publication_date_for_identified_"
                        "version_v1"
                    ),
                    "temporal_reasons_json": canonical_json(temporal.reasons),
                    "paper_id": str(paper.get("paper_id") or ""),
                }
            },
        )
        identifiers = _identifiers(candidate, item["observations"])
        payload.update(
            {
                "work_id": work_id,
                "version_kind": version.version_kind.value,
                "version_label": _version_label(raw_record),
                "version_number": str(raw_record.get("version_number") or "").strip() or None,
                "version_identifiers": identifiers,
                "title": str(
                    candidate.get("title") or raw_record.get("display_name") or ""
                ).strip(),
                "abstract": str(candidate.get("abstract") or "").strip() or None,
                "contributors": _contributors(candidate, raw_record),
                "venue": str(candidate.get("venue") or "").strip() or None,
                "publisher": _publisher(raw_record),
                "language": item["language"],
                "source_type": source_type.source_type,
                "study_design_entity_ids": [],
                "publication_date": _partial_date_payload(publication),
                "availability_earliest": _partial_date_payload(availability),
                "availability_latest": _partial_date_payload(availability),
                "availability_date_rule": specification.availability_date_rule,
                "availability_status": temporal.availability_status.value,
                "temporal_eligibility": temporal.temporal_eligibility.value,
                "lifecycle_status": version.lifecycle_status.value,
                "previous_source_version_ids": [],
                "provider_record_ids": provider_ids,
                "reference_identifiers": _reference_identifiers(raw_record),
            }
        )
        source_version_id = _refresh_id(payload)
        source_payloads.append(payload)
        first_provider = provider_payloads[provider_ids[0]]
        provider_observed_at = str(first_provider["retrieved_at"])
        access_payloads.extend(
            _candidate_access_locations(
                candidate,
                paper,
                source_version_id=source_version_id,
                provider_record_id=provider_ids[0],
                provider_observed_at=provider_observed_at,
                snapshot_id=placeholder_snapshot,
                created_at=freeze_timestamp,
                producing_run_id=producing_run_id,
                candidate_provenance=input_candidate_provenance,
                papers_provenance=input_papers_provenance,
            )
        )

    retrieval_completed_candidates = list(retrieval_times)
    retrieval_completed_candidates.extend(
        str(payload["observed_at"]) for payload in access_payloads
    )
    retrieval_completed_at = max(
        retrieval_completed_candidates,
        key=_utc_datetime,
    )
    if _utc_datetime(freeze_timestamp) < _utc_datetime(retrieval_completed_at):
        raise SnapshotFreezeError(
            [
                _issue(
                    "freeze_timestamp_precedes_retrieval",
                    "Frozen timestamp precedes a provider or access observation.",
                )
            ]
        )

    coverage_status, coverage_dimensions, limitations, searched_sources = _coverage(
        plan,
        specification,
        evidence_records,
        prepared,
        access_payloads,
        as_of=as_of,
    )
    resolved_plan_projection = {
        "plan": plan,
        "corpus_specification": specification.semantic_mapping(),
        "resolved_as_of": as_of,
        "provider_evidence_index_sha256": input_hashes[
            "provider_evidence_index_jsonl"
        ],
        "deduped_candidates_sha256": input_hashes["deduped_candidates_jsonl"],
        "included_papers_sha256": input_hashes["papers_csv"],
    }
    resolved_plan_sha256 = _canonical_sha256(resolved_plan_projection)
    scope = _scope(contract, specification)
    topic_title = str(contract["research_topic"]["title"]).strip()
    topic_version_value = contract.get("schema_version") or contract.get("version")
    topic_version = str(topic_version_value).strip() if topic_version_value else None
    snapshot_payload = _base_payload(
        "corpus_snapshot",
        snapshot_id=placeholder_snapshot,
        created_at=freeze_timestamp,
        producing_run_id=producing_run_id,
        provenance=[
            _provenance(
                input_references["collection_plan_json"],
                input_hashes["collection_plan_json"],
                "frozen_from_collection_plan",
            ),
            _provenance(
                input_references["topic_contract_yaml"],
                input_hashes["topic_contract_yaml"],
                "scoped_by_topic_contract",
            ),
            _provenance(
                input_references["provider_evidence_index_jsonl"],
                input_hashes["provider_evidence_index_jsonl"],
                "verified_against_provider_evidence_index",
            ),
            input_papers_provenance,
        ],
        extensions={
            MATERIALIZATION_EXTENSION: {
                "resolved_plan_projection_sha256": resolved_plan_sha256,
                "provider_evidence_schema_version": PROVIDER_EVIDENCE_SCHEMA_VERSION,
                "provider_page_count": provider_verification.record_count,
                "provider_archive_file_count": provider_verification.archive_file_count,
                "provider_response_bytes": provider_verification.total_response_bytes,
                "included_paper_count": len(papers),
                "access_location_count": len(access_payloads),
            }
        },
    )
    source_ids = sorted(str(payload["record_id"]) for payload in source_payloads)
    provider_ids = sorted(provider_payloads)
    snapshot_payload.update(
        {
            "name": f"{topic_title} corpus snapshot",
            "description": (
                "Frozen provider-evidenced corpus materialized from included "
                "collection candidates under the declared open-world scope."
            ),
            "snapshot_status": "frozen",
            "as_of": as_of,
            "availability_date_rule": specification.availability_date_rule,
            "topic_contract_ref": {
                "topic_id": str(contract.get("topic_id") or "").strip(),
                "sha256": input_hashes["topic_contract_yaml"],
                "path": input_references["topic_contract_yaml"],
                "version": topic_version,
            },
            "scope": scope,
            "negative_null_policy": specification.negative_null_result_policy,
            "collection_plan_sha256": input_hashes["collection_plan_json"],
            "resolved_plan_sha256": resolved_plan_sha256,
            "retrieval_started_at": retrieval_started_at,
            "retrieval_completed_at": retrieval_completed_at,
            "source_version_ids": source_ids,
            "provider_record_ids": provider_ids,
            "coverage": {
                "status": coverage_status,
                "rule_id": "observed-provider-execution-coverage-v1",
                "searched_sources": list(searched_sources),
                # The v1 record decoder accepts scalar JsonValue dimensions.
                # Keep the full structured form in the integrity report while
                # preserving it losslessly here as canonical JSON strings.
                "dimensions": {
                    key: canonical_json(value)
                    for key, value in coverage_dimensions.items()
                },
                "limitations": list(limitations),
            },
            "frozen_at": freeze_timestamp,
        }
    )
    snapshot_id = _refresh_id(snapshot_payload)
    snapshot_payload["corpus_snapshot_id"] = snapshot_id

    all_payloads = [
        snapshot_payload,
        *sorted(work_payloads.values(), key=lambda item: str(item["record_id"])),
        *sorted(source_payloads, key=lambda item: str(item["record_id"])),
        *sorted(provider_payloads.values(), key=lambda item: str(item["record_id"])),
        *sorted(access_payloads, key=lambda item: str(item["record_id"])),
    ]
    for payload in all_payloads[1:]:
        payload["corpus_snapshot_id"] = snapshot_id
    records = tuple(record_from_dict(payload) for payload in all_payloads)
    counts: dict[str, int] = {}
    for record in records:
        counts[record.RECORD_TYPE] = counts.get(record.RECORD_TYPE, 0) + 1
    return SnapshotBuild(
        records=records,
        snapshot_id=snapshot_id,
        record_counts=dict(sorted(counts.items())),
        coverage_status=coverage_status,
        coverage_dimensions=coverage_dimensions,
        limitations=limitations,
        input_hashes=dict(input_hashes),
        provider_evidence_summary={
            "schema_version": PROVIDER_EVIDENCE_SCHEMA_VERSION,
            "valid": provider_verification.valid,
            "record_count": provider_verification.record_count,
            "archive_file_count": provider_verification.archive_file_count,
            "total_response_bytes": provider_verification.total_response_bytes,
            "errors": list(provider_verification.errors),
        },
    )


def _failure_report(
    *,
    generated_at: str,
    producing_run_id: str,
    issues: Sequence[Mapping[str, Any]],
    output_path: Path,
) -> dict[str, Any]:
    stale = output_path.exists()
    return {
        "record_type": "corpus_snapshot_integrity_report",
        "schema_version": SNAPSHOT_INTEGRITY_SCHEMA_VERSION,
        "generated_at": generated_at,
        "producing_run_id": producing_run_id,
        "producing_step_id": PRODUCING_STEP_ID,
        "snapshot_status": "failed",
        "freeze_allowed": False,
        "snapshot_id": None,
        "input_integrity": {"valid": False, "issues": [dict(item) for item in issues]},
        "record_integrity": None,
        "output": {
            "records_written": False,
            "path": str(output_path),
            "stale_existing_artifact_preserved": stale,
            "stale_existing_sha256": _sha256_file(output_path) if stale else None,
        },
    }


def run(
    candidates_path: Path,
    papers_path: Path,
    provider_evidence_index_path: Path,
    provider_response_pages_dir: Path,
    plan_path: Path,
    topic_contract_path: Path,
    output_path: Path,
    integrity_report_path: Path,
    producing_run_id: str,
    *,
    artifact_root: Path = Path("."),
    frozen_at: str | None = None,
) -> StepResult:
    """Write a frozen snapshot only after evidence and record integrity pass."""
    generated_at = _utc_timestamp(frozen_at) if frozen_at else _now_utc()
    inputs = {
        "deduped_candidates_jsonl": candidates_path,
        "papers_csv": papers_path,
        "provider_evidence_index_jsonl": provider_evidence_index_path,
        "provider_response_pages_dir": provider_response_pages_dir,
        "collection_plan_json": plan_path,
        "topic_contract_yaml": topic_contract_path,
    }
    try:
        build = materialize(
            candidates_path=candidates_path,
            papers_path=papers_path,
            provider_evidence_index_path=provider_evidence_index_path,
            provider_response_pages_dir=provider_response_pages_dir,
            plan_path=plan_path,
            topic_contract_path=topic_contract_path,
            producing_run_id=producing_run_id,
            artifact_root=artifact_root,
            frozen_at=generated_at,
        )
    except SnapshotFreezeError as exc:
        report = _failure_report(
            generated_at=generated_at,
            producing_run_id=producing_run_id,
            issues=exc.issues,
            output_path=output_path,
        )
        _atomic_write(integrity_report_path, _json_bytes(report))
        return StepResult(
            step_name=STEP.name,
            inputs=inputs,
            outputs={"corpus_snapshot_integrity_json": integrity_report_path},
            error=str(exc),
            metadata={
                "snapshot_status": "failed",
                "freeze_allowed": False,
                "issue_count": len(exc.issues),
            },
        )
    except (OSError, TypeError, ValueError) as exc:
        issues = (
            _issue("materialization_error", str(exc)),
        )
        report = _failure_report(
            generated_at=generated_at,
            producing_run_id=producing_run_id,
            issues=issues,
            output_path=output_path,
        )
        _atomic_write(integrity_report_path, _json_bytes(report))
        return StepResult(
            step_name=STEP.name,
            inputs=inputs,
            outputs={"corpus_snapshot_integrity_json": integrity_report_path},
            error=f"Corpus snapshot materialization failed: {exc}",
            metadata={
                "snapshot_status": "failed",
                "freeze_allowed": False,
                "issue_count": 1,
            },
        )

    serialized = _records_bytes(build.records)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=output_path.parent,
        prefix=f".{output_path.name}.",
        suffix=".candidate",
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(serialized)
            handle.flush()
            os.fsync(handle.fileno())
        record_integrity = validate_record_artifacts(
            [temporary_path],
            artifact_root=artifact_root,
            verify_local_artifacts=True,
        )
        if not record_integrity.is_valid:
            issues = tuple(
                _issue(issue.code, issue.message, record_id=issue.record_id)
                for issue in record_integrity.errors
            )
            report = _failure_report(
                generated_at=generated_at,
                producing_run_id=producing_run_id,
                issues=issues,
                output_path=output_path,
            )
            report["record_integrity"] = record_integrity.to_dict()
            _atomic_write(integrity_report_path, _json_bytes(report))
            return StepResult(
                step_name=STEP.name,
                inputs=inputs,
                outputs={"corpus_snapshot_integrity_json": integrity_report_path},
                error="Corpus snapshot record integrity validation failed.",
                metadata={
                    "snapshot_status": "failed",
                    "freeze_allowed": False,
                    "issue_count": len(issues),
                },
            )
        os.replace(temporary_path, output_path)
    finally:
        if temporary_path.exists():
            temporary_path.unlink()

    output_sha256 = _sha256_bytes(serialized)
    report = {
        "record_type": "corpus_snapshot_integrity_report",
        "schema_version": SNAPSHOT_INTEGRITY_SCHEMA_VERSION,
        "generated_at": generated_at,
        "producing_run_id": producing_run_id,
        "producing_step_id": PRODUCING_STEP_ID,
        "snapshot_status": "frozen",
        "freeze_allowed": True,
        "snapshot_id": build.snapshot_id,
        "input_integrity": {
            "valid": True,
            "sha256": dict(build.input_hashes),
            "provider_evidence": dict(build.provider_evidence_summary),
            "issues": [],
        },
        "materialization": {
            "record_counts": dict(build.record_counts),
            "coverage_status": build.coverage_status,
            "coverage_dimensions": dict(build.coverage_dimensions),
            "limitations": list(build.limitations),
        },
        "record_integrity": record_integrity.to_dict(),
        "output": {
            "records_written": True,
            "path": str(output_path),
            "sha256": output_sha256,
            "byte_count": len(serialized),
        },
    }
    _atomic_write(integrity_report_path, _json_bytes(report))
    return StepResult(
        step_name=STEP.name,
        inputs=inputs,
        outputs={
            "corpus_records_jsonl": output_path,
            "corpus_snapshot_integrity_json": integrity_report_path,
        },
        row_counts={
            "records": len(build.records),
            **{
                f"{record_type}_records": count
                for record_type, count in build.record_counts.items()
            },
        },
        metadata={
            "snapshot_status": "frozen",
            "freeze_allowed": True,
            "snapshot_id": build.snapshot_id,
            "records_sha256": output_sha256,
            "coverage_status": build.coverage_status,
            "integrity_error_count": len(record_integrity.errors),
            "integrity_warning_count": len(record_integrity.warnings),
        },
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Materialize and freeze a strict v1 corpus snapshot."
    )
    parser.add_argument("--candidates", required=True)
    parser.add_argument("--papers", required=True)
    parser.add_argument("--provider-evidence-index", required=True)
    parser.add_argument("--provider-response-pages", required=True)
    parser.add_argument("--plan", required=True)
    parser.add_argument("--topic-contract", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--integrity-report", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--artifact-root", default=".")
    args = parser.parse_args()
    result = run(
        Path(args.candidates),
        Path(args.papers),
        Path(args.provider_evidence_index),
        Path(args.provider_response_pages),
        Path(args.plan),
        Path(args.topic_contract),
        Path(args.output),
        Path(args.integrity_report),
        args.run_id,
        artifact_root=Path(args.artifact_root),
    )
    if result.error:
        raise SystemExit(result.error)
    print(f"Snapshot: {result.metadata['snapshot_id']}")
    print(f"Records: {result.row_counts['records']}")


if __name__ == "__main__":
    main()
