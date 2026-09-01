from __future__ import annotations

import gzip
import hashlib
import json
import os
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from ad_lit_pipeline.records.ids import canonical_json


PROVIDER_EVIDENCE_SCHEMA_VERSION = "1.0.0"
PROVIDER_RESPONSE_PAGE_RECORD_TYPE = "provider_response_page"
PROVIDER_EVIDENCE_ARCHIVED = "archived"
PROVIDER_EVIDENCE_UNAVAILABLE = "unavailable"

_SENSITIVE_QUERY_KEYS = frozenset(
    {
        "access_token",
        "api-key",
        "api_key",
        "authorization",
        "cookie",
        "credential",
        "email",
        "key",
        "mailto",
        "password",
        "secret",
        "signature",
        "token",
    }
)
_RECORD_FIELDS = frozenset(
    {
        "record_type",
        "schema_version",
        "page_evidence_id",
        "provider",
        "request",
        "retrieval_context",
        "response",
    }
)


class CapturedJSONResponse(dict[str, Any]):
    """JSON object with the exact successful HTTP response observation."""

    def __init__(
        self,
        payload: Mapping[str, Any],
        *,
        raw_bytes: bytes,
        retrieved_at: str,
        response_url: str,
        status_code: int,
        media_type: str,
        content_encoding: str | None,
    ) -> None:
        super().__init__(payload)
        self.raw_bytes = raw_bytes
        self.retrieved_at = retrieved_at
        self.response_url = response_url
        self.status_code = status_code
        self.media_type = media_type
        self.content_encoding = content_encoding


@dataclass(frozen=True)
class ProviderEvidenceVerification:
    """Result of verifying an evidence index and every referenced page."""

    record_count: int
    archive_file_count: int
    total_response_bytes: int
    errors: tuple[str, ...]

    @property
    def valid(self) -> bool:
        return not self.errors


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_mapping(value: Mapping[str, Any]) -> str:
    return sha256_bytes(canonical_json(value).encode("utf-8"))


def canonical_redacted_request_url(url: str) -> str:
    """Return a stable URL with credentials and private contact data removed."""
    parsed = urlsplit(url)
    hostname = (parsed.hostname or "").casefold()
    if not hostname:
        raise ValueError("Provider request URL must include a hostname.")
    port = f":{parsed.port}" if parsed.port is not None else ""
    netloc = f"{hostname}{port}"
    query = sorted(
        (
            key,
            value,
        )
        for key, value in parse_qsl(parsed.query, keep_blank_values=True)
        if key.casefold() not in _SENSITIVE_QUERY_KEYS
    )
    return urlunsplit(
        (
            parsed.scheme.casefold(),
            netloc,
            parsed.path or "/",
            urlencode(query, doseq=True),
            "",
        )
    )


def canonical_request_projection(
    method: str,
    url: str,
    headers: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Return the non-secret request facts used for provenance identity."""
    safe_headers = {
        key.casefold(): str(value).strip()
        for key, value in (headers or {}).items()
        if key.casefold() in {"accept", "user-agent"} and str(value).strip()
    }
    return {
        "method": method.upper(),
        "redacted_url": canonical_redacted_request_url(url),
        "headers": dict(sorted(safe_headers.items())),
    }


def unavailable_provider_evidence(reason: str) -> dict[str, Any]:
    """Return the explicit compatibility marker for unarchived observations."""
    return {
        "schema_version": PROVIDER_EVIDENCE_SCHEMA_VERSION,
        "status": PROVIDER_EVIDENCE_UNAVAILABLE,
        "reason": reason,
    }


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


def _json_object_from_bytes(content: bytes, label: str) -> dict[str, Any]:
    try:
        payload = json.loads(content.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{label} must be a UTF-8 JSON object.") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"{label} must be a JSON object.")
    return payload


def json_object_from_response_bytes(
    content: bytes,
    content_encoding: str | None,
    label: str,
) -> dict[str, Any]:
    """Decode a JSON page while preserving the separately archived raw bytes."""
    encoding = str(content_encoding or "").strip().casefold()
    if encoding in {"", "identity"}:
        decoded = content
    elif encoding == "gzip":
        try:
            decoded = gzip.decompress(content)
        except OSError as exc:
            raise ValueError(f"{label} has invalid gzip content.") from exc
    else:
        raise ValueError(
            f"{label} uses unsupported content encoding {content_encoding!r}."
        )
    return _json_object_from_bytes(decoded, label)


def _result_facts(
    payload: Mapping[str, Any],
) -> tuple[list[str], list[str | None], list[str]]:
    results = payload.get("results")
    if not isinstance(results, list):
        return [], [], []
    provider_ids: list[str] = []
    raw_record_sha256s: list[str | None] = []
    updated_values: list[str] = []
    for result in results:
        if not isinstance(result, Mapping):
            provider_ids.append("")
            raw_record_sha256s.append(None)
            continue
        provider_ids.append(str(result.get("id") or ""))
        raw_record_sha256s.append(sha256_mapping(result))
        updated = str(result.get("updated_date") or result.get("updated_at") or "")
        if updated:
            updated_values.append(updated)
    return provider_ids, raw_record_sha256s, sorted(set(updated_values))


def _relative_artifact_uri(path: Path, index_path: Path) -> str:
    return Path(os.path.relpath(path, start=index_path.parent)).as_posix()


def _archive_path(
    archive_root: Path,
    provider: str,
    response_sha256: str,
) -> Path:
    return (
        archive_root
        / provider.casefold()
        / response_sha256[:2]
        / f"{response_sha256}.json"
    )


def _index_bytes(records: list[dict[str, Any]]) -> bytes:
    return b"".join(
        canonical_json(record).encode("utf-8") + b"\n" for record in records
    )


def read_provider_evidence_index(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    records: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(
                    f"Invalid provider evidence JSON at {path}:{line_number}."
                ) from exc
            if not isinstance(record, dict):
                raise ValueError(
                    f"Provider evidence entry must be an object: "
                    f"{path}:{line_number}."
                )
            records.append(record)
    return records


class ProviderEvidenceArchive:
    """Collection-specific immutable page store plus atomic evidence index."""

    def __init__(
        self,
        archive_root: Path,
        index_path: Path,
        *,
        append_existing: bool = False,
    ) -> None:
        self.archive_root = archive_root
        self.index_path = index_path
        self.records = (
            read_provider_evidence_index(index_path) if append_existing else []
        )
        self._record_ids = {
            str(record.get("page_evidence_id") or "") for record in self.records
        }

    def archive_json_page(
        self,
        *,
        provider: str,
        request_url: str,
        request_headers: Mapping[str, str],
        response: CapturedJSONResponse,
        retrieval_context: Mapping[str, Any],
    ) -> dict[str, Any]:
        """Persist one exact response page and return its immutable index entry."""
        request = canonical_request_projection("GET", request_url, request_headers)
        request_sha256 = sha256_mapping(request)
        response_sha256 = sha256_bytes(response.raw_bytes)
        artifact_path = _archive_path(
            self.archive_root,
            provider,
            response_sha256,
        )
        if artifact_path.exists():
            existing_hash = sha256_bytes(artifact_path.read_bytes())
            if existing_hash != response_sha256:
                raise ValueError(
                    f"Provider archive collision at {artifact_path}: "
                    f"expected={response_sha256} actual={existing_hash}."
                )
        else:
            _atomic_write(artifact_path, response.raw_bytes)

        payload = json_object_from_response_bytes(
            response.raw_bytes,
            response.content_encoding,
            f"Provider response {response_sha256}",
        )
        result_ids, result_hashes, updated_values = _result_facts(payload)
        context = {
            "query_id": str(retrieval_context.get("query_id") or ""),
            "logical_query_id": str(
                retrieval_context.get("logical_query_id") or ""
            ),
            "query_group_id": str(
                retrieval_context.get("query_group_id") or ""
            ),
            "query_tier": retrieval_context.get("query_tier"),
            "retrieval_iteration": retrieval_context.get("retrieval_iteration"),
            "retrieval_phase": str(
                retrieval_context.get("retrieval_phase") or ""
            ),
            "page_or_cursor": str(
                retrieval_context.get("page_or_cursor") or ""
            ),
            "per_page": retrieval_context.get("per_page"),
            "backfill_round": retrieval_context.get("backfill_round"),
        }
        identity_projection = {
            "provider": provider.casefold(),
            "request_sha256": request_sha256,
            "response_sha256": response_sha256,
            "retrieved_at": response.retrieved_at,
            "retrieval_context": context,
        }
        page_evidence_id = (
            "provider_page_" + sha256_mapping(identity_projection)
        )
        record = {
            "record_type": PROVIDER_RESPONSE_PAGE_RECORD_TYPE,
            "schema_version": PROVIDER_EVIDENCE_SCHEMA_VERSION,
            "page_evidence_id": page_evidence_id,
            "provider": provider.casefold(),
            "request": {
                **request,
                "request_sha256": request_sha256,
            },
            "retrieval_context": context,
            "response": {
                "status_code": response.status_code,
                "final_redacted_url": canonical_redacted_request_url(
                    response.response_url
                ),
                "retrieved_at": response.retrieved_at,
                "media_type": response.media_type,
                "content_encoding": response.content_encoding,
                "byte_count": len(response.raw_bytes),
                "response_sha256": response_sha256,
                "artifact_uri": _relative_artifact_uri(
                    artifact_path,
                    self.index_path,
                ),
                "result_count": len(result_ids),
                "result_provider_ids": result_ids,
                "result_raw_record_sha256s": result_hashes,
                "provider_updated_at_earliest": (
                    updated_values[0] if updated_values else None
                ),
                "provider_updated_at_latest": (
                    updated_values[-1] if updated_values else None
                ),
            },
        }
        if page_evidence_id not in self._record_ids:
            self.records.append(record)
            self._record_ids.add(page_evidence_id)
        self.flush()
        return record

    def candidate_link(
        self,
        record: Mapping[str, Any],
        *,
        result_position: int,
        raw_record: Mapping[str, Any],
    ) -> dict[str, Any]:
        response = record["response"]
        request = record["request"]
        context = record["retrieval_context"]
        assert isinstance(response, Mapping)
        assert isinstance(request, Mapping)
        assert isinstance(context, Mapping)
        return {
            "schema_version": PROVIDER_EVIDENCE_SCHEMA_VERSION,
            "status": PROVIDER_EVIDENCE_ARCHIVED,
            "page_evidence_id": record["page_evidence_id"],
            "request_sha256": request["request_sha256"],
            "redacted_request_url": request["redacted_url"],
            "response_sha256": response["response_sha256"],
            "response_uri": response["artifact_uri"],
            "response_media_type": response["media_type"],
            "retrieved_at": response["retrieved_at"],
            "page_or_cursor": context["page_or_cursor"],
            "result_position": result_position,
            "result_count": response["result_count"],
            "raw_record_sha256": sha256_mapping(raw_record),
            "raw_record_json_pointer": f"/results/{result_position - 1}",
        }

    def flush(self) -> None:
        _atomic_write(self.index_path, _index_bytes(self.records))


def verify_provider_evidence(
    index_path: Path,
    archive_root: Path,
) -> ProviderEvidenceVerification:
    """Verify index identities, request hashes, content paths, and page bytes."""
    errors: list[str] = []
    try:
        records = read_provider_evidence_index(index_path)
    except ValueError as exc:
        return ProviderEvidenceVerification(0, 0, 0, (str(exc),))
    seen_ids: set[str] = set()
    verified_paths: set[Path] = set()
    total_bytes = 0
    resolved_root = archive_root.resolve()

    for index, record in enumerate(records, start=1):
        label = f"provider evidence record {index}"
        if set(record) != _RECORD_FIELDS:
            errors.append(f"{label}: fields do not match schema 1.0.0.")
            continue
        if record.get("record_type") != PROVIDER_RESPONSE_PAGE_RECORD_TYPE:
            errors.append(f"{label}: unsupported record_type.")
        if record.get("schema_version") != PROVIDER_EVIDENCE_SCHEMA_VERSION:
            errors.append(f"{label}: unsupported schema_version.")
        page_id = str(record.get("page_evidence_id") or "")
        if not page_id or page_id in seen_ids:
            errors.append(f"{label}: missing or duplicate page_evidence_id.")
        seen_ids.add(page_id)

        request = record.get("request")
        context = record.get("retrieval_context")
        response = record.get("response")
        if not isinstance(request, Mapping) or not isinstance(context, Mapping):
            errors.append(f"{label}: request or retrieval_context is invalid.")
            continue
        if not isinstance(response, Mapping):
            errors.append(f"{label}: response is invalid.")
            continue
        request_projection = {
            "method": request.get("method"),
            "redacted_url": request.get("redacted_url"),
            "headers": request.get("headers"),
        }
        if request.get("request_sha256") != sha256_mapping(request_projection):
            errors.append(f"{label}: request_sha256 mismatch.")
        try:
            canonical_url = canonical_redacted_request_url(
                str(request.get("redacted_url") or "")
            )
        except ValueError:
            canonical_url = ""
        if canonical_url != request.get("redacted_url"):
            errors.append(f"{label}: request URL is not canonical and redacted.")

        response_sha256 = str(response.get("response_sha256") or "")
        artifact_uri = str(response.get("artifact_uri") or "")
        candidate_path = (index_path.parent / artifact_uri).resolve()
        if not candidate_path.is_relative_to(resolved_root):
            errors.append(f"{label}: response artifact escapes archive root.")
            continue
        expected_path = _archive_path(
            archive_root,
            str(record.get("provider") or ""),
            response_sha256,
        ).resolve()
        if candidate_path != expected_path:
            errors.append(f"{label}: response artifact is not content-addressed.")
        if not candidate_path.is_file():
            errors.append(f"{label}: response artifact is missing.")
            continue
        content = candidate_path.read_bytes()
        verified_paths.add(candidate_path)
        total_bytes += len(content)
        if sha256_bytes(content) != response_sha256:
            errors.append(f"{label}: response byte hash mismatch.")
        if response.get("byte_count") != len(content):
            errors.append(f"{label}: response byte count mismatch.")
        try:
            payload = json_object_from_response_bytes(
                content,
                str(response.get("content_encoding") or "") or None,
                label,
            )
        except ValueError as exc:
            errors.append(str(exc))
            continue
        result_ids, result_hashes, updated_values = _result_facts(payload)
        if response.get("result_count") != len(result_ids):
            errors.append(f"{label}: result_count mismatch.")
        if response.get("result_provider_ids") != result_ids:
            errors.append(f"{label}: result order mismatch.")
        if response.get("result_raw_record_sha256s") != result_hashes:
            errors.append(f"{label}: result raw-record hash order mismatch.")
        earliest = updated_values[0] if updated_values else None
        latest = updated_values[-1] if updated_values else None
        if response.get("provider_updated_at_earliest") != earliest:
            errors.append(f"{label}: earliest provider update mismatch.")
        if response.get("provider_updated_at_latest") != latest:
            errors.append(f"{label}: latest provider update mismatch.")

        identity_projection = {
            "provider": record.get("provider"),
            "request_sha256": request.get("request_sha256"),
            "response_sha256": response.get("response_sha256"),
            "retrieved_at": response.get("retrieved_at"),
            "retrieval_context": dict(context),
        }
        expected_id = "provider_page_" + sha256_mapping(identity_projection)
        if page_id != expected_id:
            errors.append(f"{label}: page_evidence_id mismatch.")

    return ProviderEvidenceVerification(
        record_count=len(records),
        archive_file_count=len(verified_paths),
        total_response_bytes=total_bytes,
        errors=tuple(errors),
    )


def candidate_evidence_errors(
    candidates: list[dict[str, Any]],
    index_records: list[dict[str, Any]],
    *,
    require_archived: bool,
) -> tuple[str, ...]:
    """Check candidate-to-page links, result positions, and raw item hashes."""
    errors: list[str] = []
    by_id = {
        str(record.get("page_evidence_id") or ""): record
        for record in index_records
    }
    for index, candidate in enumerate(candidates, start=1):
        label = (
            str(candidate.get("provider_id") or "").strip()
            or f"candidate:{index}"
        )
        evidence = candidate.get("provider_evidence")
        if not isinstance(evidence, Mapping):
            errors.append(f"{label}: provider_evidence is missing.")
            continue
        status = evidence.get("status")
        if status != PROVIDER_EVIDENCE_ARCHIVED:
            if require_archived:
                errors.append(f"{label}: provider evidence is not archived.")
            continue
        page_id = str(evidence.get("page_evidence_id") or "")
        page = by_id.get(page_id)
        if page is None:
            errors.append(f"{label}: page_evidence_id is absent from the index.")
            continue
        response = page.get("response")
        request = page.get("request")
        context = page.get("retrieval_context")
        if not all(
            isinstance(value, Mapping)
            for value in (response, request, context)
        ):
            errors.append(f"{label}: indexed page structure is invalid.")
            continue
        assert isinstance(response, Mapping)
        assert isinstance(request, Mapping)
        assert isinstance(context, Mapping)
        for candidate_key, page_value in (
            ("request_sha256", request.get("request_sha256")),
            ("redacted_request_url", request.get("redacted_url")),
            ("response_sha256", response.get("response_sha256")),
            ("response_uri", response.get("artifact_uri")),
            ("response_media_type", response.get("media_type")),
            ("retrieved_at", response.get("retrieved_at")),
            ("page_or_cursor", context.get("page_or_cursor")),
            ("result_count", response.get("result_count")),
        ):
            if evidence.get(candidate_key) != page_value:
                errors.append(f"{label}: {candidate_key} does not match page.")
        position = evidence.get("result_position")
        result_ids = response.get("result_provider_ids")
        result_hashes = response.get("result_raw_record_sha256s")
        if (
            not isinstance(position, int)
            or position < 1
            or not isinstance(result_ids, list)
            or position > len(result_ids)
        ):
            errors.append(f"{label}: result_position is invalid.")
        elif str(candidate.get("provider_id") or "") != result_ids[position - 1]:
            errors.append(f"{label}: result position resolves to another item.")
        raw_record = candidate.get("raw_record")
        if not isinstance(raw_record, Mapping):
            errors.append(f"{label}: raw_record is unavailable for hash check.")
        elif evidence.get("raw_record_sha256") != sha256_mapping(raw_record):
            errors.append(f"{label}: raw_record_sha256 mismatch.")
        if (
            isinstance(position, int)
            and isinstance(result_hashes, list)
            and 1 <= position <= len(result_hashes)
            and evidence.get("raw_record_sha256") != result_hashes[position - 1]
        ):
            errors.append(
                f"{label}: raw record does not match the archived page item."
            )
        expected_pointer = (
            f"/results/{position - 1}" if isinstance(position, int) else None
        )
        if evidence.get("raw_record_json_pointer") != expected_pointer:
            errors.append(f"{label}: raw record JSON pointer mismatch.")
    return tuple(errors)
