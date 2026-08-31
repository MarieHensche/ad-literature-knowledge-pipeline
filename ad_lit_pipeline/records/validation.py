from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping, Sequence
from datetime import date, datetime, timezone
from functools import lru_cache
from typing import Any
from urllib.parse import parse_qsl, urlsplit

from ad_lit_pipeline.core.errors import ValidationError
from ad_lit_pipeline.records import models as m
from ad_lit_pipeline.records.gap_classes import (
    GapOntology,
    load_gap_ontology,
)
from ad_lit_pipeline.records.ids import (
    canonical_json,
    make_record_id,
    validate_record_id,
)
from ad_lit_pipeline.records.registry import SCHEMA_VERSION, get_record_spec
from ad_lit_pipeline.validity import (
    ClaimVerificationOutcome,
    GapStatus,
    load_scientific_validity_policy,
    mandatory_human_review_reasons,
    validate_gap_language,
    validate_gap_transition,
)


SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
SEMVER_PATTERN = re.compile(
    r"^[0-9]+\.[0-9]+\.[0-9]+(?:[-+][0-9A-Za-z.-]+)?$"
)
DATE_PATTERN = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")
EXTENSION_NAMESPACE_PATTERN = re.compile(
    r"^[a-z][a-z0-9_-]*(?:[.:][a-z][a-z0-9_-]*)+$"
)
SECRET_KEY_PATTERN = re.compile(
    r"(?:^|[_-])(api[_-]?key|authorization|cookie|credential|password|secret|"
    r"signature|token)(?:$|[_-])",
    re.IGNORECASE,
)
SECRET_ASSIGNMENT_PATTERN = re.compile(
    r"(?:api[_-]?key|authorization|cookie|credential|password|secret|token)"
    r"\s*[:=]\s*\S+",
    re.IGNORECASE,
)
MAX_PASSAGE_CHARACTERS = 8_000

SCIENTIFIC_RECORD_TYPES = frozenset(
    {
        "claim_evidence",
        "relationship",
        "gap_signal",
        "gap_candidate",
        "verification_attempt",
        "gap_score",
        "expert_judgment",
        "outcome_event",
        "mantis_interpretation",
    }
)
GAP_ONTOLOGY_RECORD_TYPES = frozenset(
    {
        "gap_signal",
        "gap_candidate",
        "verification_attempt",
        "gap_score",
    }
)


def _fail(record_type: str, field: str, message: str) -> None:
    raise ValidationError(f"{record_type}.{field}: {message}")


def _nonempty(value: Any, record_type: str, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        _fail(record_type, field, "must be a non-empty string")
    if value != value.strip():
        _fail(record_type, field, "must not contain surrounding whitespace")
    return value


def _sha256(value: Any, record_type: str, field: str) -> str:
    value = _nonempty(value, record_type, field)
    if not SHA256_PATTERN.fullmatch(value):
        _fail(record_type, field, "must be a lowercase SHA-256 digest")
    return value


def _semver(value: Any, record_type: str, field: str) -> str:
    value = _nonempty(value, record_type, field)
    if not SEMVER_PATTERN.fullmatch(value):
        _fail(record_type, field, "must be a semantic version")
    return value


def _date(value: Any, record_type: str, field: str) -> date:
    value = _nonempty(value, record_type, field)
    if not DATE_PATTERN.fullmatch(value):
        _fail(record_type, field, "must be an ISO date in YYYY-MM-DD form")
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ValidationError(
            f"{record_type}.{field}: invalid calendar date {value!r}"
        ) from exc


def normalize_utc_timestamp(value: Any, *, context: str) -> str:
    """Validate an RFC3339 UTC timestamp and return canonical ``Z`` form."""
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise ValidationError(f"{context}: must be a non-empty RFC3339 timestamp")
    candidate = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError as exc:
        raise ValidationError(f"{context}: invalid RFC3339 timestamp {value!r}") from exc
    if parsed.tzinfo is None or parsed.utcoffset() != timezone.utc.utcoffset(parsed):
        raise ValidationError(f"{context}: timestamp must use UTC")
    canonical = parsed.astimezone(timezone.utc).isoformat()
    return canonical.replace("+00:00", "Z")


def _timestamp(value: Any, record_type: str, field: str) -> datetime:
    canonical = normalize_utc_timestamp(value, context=f"{record_type}.{field}")
    return datetime.fromisoformat(canonical.replace("Z", "+00:00"))


def _unique_strings(
    values: Sequence[Any],
    record_type: str,
    field: str,
    *,
    nonempty: bool = False,
    sorted_values: bool = False,
) -> tuple[str, ...]:
    if isinstance(values, (str, bytes)) or not isinstance(values, Sequence):
        _fail(record_type, field, "must be an array of strings")
    normalized: list[str] = []
    for index, value in enumerate(values):
        normalized.append(_nonempty(value, record_type, f"{field}[{index}]"))
    if nonempty and not normalized:
        _fail(record_type, field, "must not be empty")
    if len(normalized) != len(set(normalized)):
        _fail(record_type, field, "must not contain duplicates")
    if sorted_values and normalized != sorted(normalized):
        _fail(record_type, field, "must use deterministic sorted order")
    return tuple(normalized)


def _record_ids(
    values: Sequence[Any],
    record_type: str,
    field: str,
    *,
    expected_type: str | None = None,
    nonempty: bool = False,
    sorted_values: bool = False,
) -> tuple[str, ...]:
    ids = _unique_strings(
        values,
        record_type,
        field,
        nonempty=nonempty,
        sorted_values=sorted_values,
    )
    for index, value in enumerate(ids):
        try:
            validate_record_id(value, expected_type)
        except ValidationError as exc:
            raise ValidationError(
                f"{record_type}.{field}[{index}]: {exc}"
            ) from exc
    return ids


def _optional_record_id(
    value: str | None,
    record_type: str,
    field: str,
    expected_type: str,
) -> None:
    if value is None:
        return
    try:
        validate_record_id(value, expected_type)
    except ValidationError as exc:
        raise ValidationError(f"{record_type}.{field}: {exc}") from exc


def _safe_uri(value: str | None, record_type: str, field: str) -> None:
    if value is None:
        return
    _nonempty(value, record_type, field)
    split = urlsplit(value)
    if split.username is not None or split.password is not None:
        _fail(record_type, field, "must not contain embedded credentials")
    for key, _ in parse_qsl(split.query, keep_blank_values=True):
        if SECRET_KEY_PATTERN.search(key):
            _fail(record_type, field, f"contains secret-like query key {key!r}")


def _secret_scan(value: Any, record_type: str, field: str) -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            if SECRET_KEY_PATTERN.search(str(key)):
                _fail(record_type, field, f"contains secret-like key {key!r}")
            _secret_scan(item, record_type, f"{field}.{key}")
    elif isinstance(value, (tuple, list)):
        for index, item in enumerate(value):
            _secret_scan(item, record_type, f"{field}[{index}]")
    elif isinstance(value, str):
        if SECRET_ASSIGNMENT_PATTERN.search(value):
            _fail(record_type, field, "contains credential-like material")
        if "://" in value:
            _safe_uri(value, record_type, field)


def _partial_date(
    value: m.PartialDate | None,
    record_type: str,
    field: str,
) -> date | None:
    if value is None:
        return None
    if value.precision is m.PartialDatePrecision.UNKNOWN:
        if value.value is not None or value.certainty is not m.PartialDateCertainty.UNKNOWN:
            _fail(
                record_type,
                field,
                "unknown precision requires a null value and unknown certainty",
            )
        return None
    if value.value is None:
        _fail(record_type, f"{field}.value", "is required for known precision")
    raw = value.value
    assert raw is not None
    patterns = {
        m.PartialDatePrecision.YEAR: r"^[0-9]{4}$",
        m.PartialDatePrecision.MONTH: r"^[0-9]{4}-[0-9]{2}$",
        m.PartialDatePrecision.DAY: r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$",
    }
    if not re.fullmatch(patterns[value.precision], raw):
        _fail(record_type, f"{field}.value", "does not match its precision")
    padded = raw + ("-01-01" if len(raw) == 4 else "-01" if len(raw) == 7 else "")
    try:
        return date.fromisoformat(padded)
    except ValueError as exc:
        raise ValidationError(
            f"{record_type}.{field}.value: invalid calendar date {raw!r}"
        ) from exc


def _identifiers(
    values: Sequence[m.Identifier],
    record_type: str,
    field: str,
) -> None:
    keys: list[tuple[str, str]] = []
    for index, identifier in enumerate(values):
        scheme = _nonempty(identifier.scheme, record_type, f"{field}[{index}].scheme")
        raw = _nonempty(identifier.value, record_type, f"{field}[{index}].value")
        _safe_uri(identifier.uri, record_type, f"{field}[{index}].uri")
        keys.append((scheme.casefold(), raw.casefold()))
    if len(keys) != len(set(keys)):
        _fail(record_type, field, "must not contain duplicate scheme/value pairs")


@lru_cache(maxsize=1)
def _validity_policy():
    return load_scientific_validity_policy()


@lru_cache(maxsize=1)
def _gap_ontology() -> GapOntology:
    return load_gap_ontology()


def _coverage(
    status: m.CoverageStatus,
    dimensions: Mapping[str, Any],
    record_type: str,
    field: str,
) -> None:
    policy = _validity_policy()
    if status.value not in policy.coverage_statuses:
        _fail(record_type, f"{field}.status", "is not declared by validity policy")
    expected = set(policy.coverage_required_dimensions)
    actual = set(dimensions)
    if actual != expected:
        missing = sorted(expected - actual)
        unknown = sorted(actual - expected)
        _fail(
            record_type,
            f"{field}.dimensions",
            f"must contain exact policy dimensions; missing={missing}, unknown={unknown}",
        )
    _secret_scan(dimensions, record_type, f"{field}.dimensions")


def _coverage_assessment(
    coverage: m.CoverageAssessment,
    record_type: str,
    field: str = "coverage",
) -> None:
    _nonempty(coverage.rule_id, record_type, f"{field}.rule_id")
    _unique_strings(
        coverage.searched_sources,
        record_type,
        f"{field}.searched_sources",
        sorted_values=True,
    )
    _unique_strings(coverage.limitations, record_type, f"{field}.limitations")
    _coverage(coverage.status, coverage.dimensions, record_type, field)


def _assessment(
    assessment: m.Assessment | None,
    record_type: str,
    field: str,
    *,
    expected_dimension: str | None = None,
) -> None:
    if assessment is None:
        return
    policy = _validity_policy()
    if assessment.dimension not in policy.assessment_dimensions:
        _fail(record_type, f"{field}.dimension", "is not a declared dimension")
    if expected_dimension is not None and assessment.dimension != expected_dimension:
        _fail(
            record_type,
            f"{field}.dimension",
            f"must be {expected_dimension!r}",
        )
    if isinstance(assessment.value, float) and not 0.0 <= assessment.value <= 1.0:
        _fail(record_type, f"{field}.value", "numeric confidence must be in [0, 1]")
    _nonempty(assessment.scale, record_type, f"{field}.scale")
    _nonempty(assessment.rationale, record_type, f"{field}.rationale")
    _nonempty(assessment.assessor_id, record_type, f"{field}.assessor_id")


def _human_review_triggers(
    values: Sequence[str], record_type: str, field: str
) -> None:
    triggers = _unique_strings(values, record_type, field)
    try:
        normalized = mandatory_human_review_reasons(_validity_policy(), triggers)
    except ValidationError as exc:
        raise ValidationError(f"{record_type}.{field}: {exc}") from exc
    if tuple(triggers) != normalized:
        _fail(record_type, field, "must follow scientific-validity policy order")


def _identity_value(payload: Mapping[str, Any], path: str) -> Any:
    value: Any = payload
    for part in path.split("."):
        if not isinstance(value, Mapping) or part not in value:
            raise ValidationError(f"Identity field path {path!r} does not exist")
        value = value[part]
    if path.endswith("_at") and value is not None:
        value = normalize_utc_timestamp(value, context=f"identity.{path}")
    return value


def identity_payload(
    record_type: str,
    payload: Mapping[str, Any],
    *,
    schema_version: str = SCHEMA_VERSION,
) -> dict[str, Any]:
    """Extract the registered identity projection from a serialized payload."""
    spec = get_record_spec(record_type, schema_version)
    return {
        path: _identity_value(payload, path)
        for path in spec.identity_field_paths
    }


def make_payload_record_id(
    record_type: str,
    payload: Mapping[str, Any],
    *,
    schema_version: str = SCHEMA_VERSION,
) -> str:
    """Build a typed ID from a record payload's registered identity fields."""
    return make_record_id(
        record_type,
        identity_payload(record_type, payload, schema_version=schema_version),
        schema_version=schema_version,
    )


def _validate_envelope(record: m.RecordEnvelope) -> None:
    record_type = record.RECORD_TYPE
    spec = get_record_spec(record_type, record.schema_version)
    if record.__class__.__name__ != spec.class_name:
        _fail(record_type, "record_type", "does not match the registered model")
    validate_record_id(record.record_id, record_type)
    _timestamp(record.created_at, record_type, "created_at")
    validate_record_id(record.corpus_snapshot_id, "corpus_snapshot")
    if record_type == "corpus_snapshot" and record.corpus_snapshot_id != record.record_id:
        _fail(record_type, "corpus_snapshot_id", "must equal record_id")
    _nonempty(record.producing_run_id, record_type, "producing_run_id")
    _nonempty(record.producing_step_id, record_type, "producing_step_id")
    _record_ids(
        record.parent_record_ids,
        record_type,
        "parent_record_ids",
        sorted_values=True,
    )
    _record_ids(
        record.source_record_ids,
        record_type,
        "source_record_ids",
        sorted_values=True,
    )
    if not record.provenance:
        _fail(record_type, "provenance", "must contain at least one entry")
    for index, entry in enumerate(record.provenance):
        _nonempty(entry.relation, record_type, f"provenance[{index}].relation")
        _nonempty(entry.reference, record_type, f"provenance[{index}].reference")
        if entry.kind is m.ProvenanceKind.RECORD:
            validate_record_id(entry.reference)
        else:
            _safe_uri(entry.reference, record_type, f"provenance[{index}].reference")
        if entry.sha256 is not None:
            _sha256(entry.sha256, record_type, f"provenance[{index}].sha256")
    if record.record_status is m.AdministrativeRecordStatus.INVALID and not record.validation_warnings:
        _fail(record_type, "validation_warnings", "invalid records require a warning")
    warning_keys: list[tuple[str, str | None]] = []
    for index, warning in enumerate(record.validation_warnings):
        code = _nonempty(warning.code, record_type, f"validation_warnings[{index}].code")
        _nonempty(warning.message, record_type, f"validation_warnings[{index}].message")
        warning_keys.append((code, warning.field_path))
    if len(warning_keys) != len(set(warning_keys)):
        _fail(record_type, "validation_warnings", "contains duplicate code/path pairs")

    expected_policy_versions = {"record_contracts": SCHEMA_VERSION}
    if record_type in SCIENTIFIC_RECORD_TYPES:
        expected_policy_versions["scientific_validity"] = "1.0.0"
    if record_type in GAP_ONTOLOGY_RECORD_TYPES:
        expected_policy_versions["gap_ontology"] = "1.0.0"
    for policy_id, expected_version in expected_policy_versions.items():
        if record.policy_versions.get(policy_id) != expected_version:
            _fail(
                record_type,
                "policy_versions",
                f"requires {policy_id}={expected_version!r}",
            )
    for key, version in record.policy_versions.items():
        _nonempty(key, record_type, "policy_versions key")
        _semver(version, record_type, f"policy_versions.{key}")

    core_names = {field.name for field in record.__dataclass_fields__.values()}
    for namespace, value in record.extensions.items():
        if not EXTENSION_NAMESPACE_PATTERN.fullmatch(namespace):
            _fail(
                record_type,
                f"extensions.{namespace}",
                "must be a namespaced key such as 'provider.openalex'",
            )
        if namespace.rsplit(".", maxsplit=1)[-1] in core_names:
            _fail(record_type, f"extensions.{namespace}", "must not shadow a core field")
        if not isinstance(value, Mapping):
            _fail(record_type, f"extensions.{namespace}", "must be an object")
    _secret_scan(record.extensions, record_type, "extensions")

    from ad_lit_pipeline.records.serialization import record_to_dict

    payload = record_to_dict(record, validate=False)
    canonical_json(payload)
    expected_id = make_payload_record_id(
        record_type,
        payload,
        schema_version=record.schema_version,
    )
    if record.record_id != expected_id:
        _fail(
            record_type,
            "record_id",
            f"does not match registered identity projection; expected {expected_id}",
        )


def _validate_corpus_snapshot(record: m.CorpusSnapshot) -> None:
    rt = record.RECORD_TYPE
    _nonempty(record.name, rt, "name")
    _nonempty(record.description, rt, "description")
    _date(record.as_of, rt, "as_of")
    _nonempty(record.availability_date_rule, rt, "availability_date_rule")
    required_topic = {"topic_id", "sha256", "path", "version"}
    if set(record.topic_contract_ref) != required_topic:
        _fail(rt, "topic_contract_ref", f"must contain exact keys {sorted(required_topic)}")
    _nonempty(record.topic_contract_ref["topic_id"], rt, "topic_contract_ref.topic_id")
    _sha256(record.topic_contract_ref["sha256"], rt, "topic_contract_ref.sha256")
    topic_path = record.topic_contract_ref["path"]
    if topic_path is not None:
        _nonempty(topic_path, rt, "topic_contract_ref.path")
    topic_version = record.topic_contract_ref["version"]
    if topic_version is not None:
        _semver(topic_version, rt, "topic_contract_ref.version")
    required_scope = {
        "research_question",
        "providers",
        "source_types",
        "languages",
        "publication_start",
        "publication_end",
        "inclusion_policy_sha256",
        "exclusion_policy_sha256",
    }
    if set(record.scope) != required_scope:
        _fail(rt, "scope", f"must contain exact keys {sorted(required_scope)}")
    _nonempty(record.scope["research_question"], rt, "scope.research_question")
    for key in ("providers", "source_types", "languages"):
        _unique_strings(record.scope[key], rt, f"scope.{key}", sorted_values=True)
    for key in ("publication_start", "publication_end"):
        if record.scope[key] is not None:
            _date(record.scope[key], rt, f"scope.{key}")
    if record.scope["publication_start"] and record.scope["publication_end"]:
        if record.scope["publication_start"] > record.scope["publication_end"]:
            _fail(rt, "scope", "publication_start must not follow publication_end")
    _sha256(record.scope["inclusion_policy_sha256"], rt, "scope.inclusion_policy_sha256")
    _sha256(record.scope["exclusion_policy_sha256"], rt, "scope.exclusion_policy_sha256")
    _sha256(record.collection_plan_sha256, rt, "collection_plan_sha256")
    _sha256(record.resolved_plan_sha256, rt, "resolved_plan_sha256")
    started = _timestamp(record.retrieval_started_at, rt, "retrieval_started_at")
    completed = (
        _timestamp(record.retrieval_completed_at, rt, "retrieval_completed_at")
        if record.retrieval_completed_at is not None
        else None
    )
    if completed is not None and completed < started:
        _fail(rt, "retrieval_completed_at", "must not precede retrieval_started_at")
    _record_ids(
        record.source_version_ids,
        rt,
        "source_version_ids",
        expected_type="source_version",
        sorted_values=True,
    )
    _record_ids(
        record.provider_record_ids,
        rt,
        "provider_record_ids",
        expected_type="provider_record",
        sorted_values=True,
    )
    _coverage_assessment(record.coverage, rt)
    if record.snapshot_status is m.SnapshotStatus.FROZEN:
        if completed is None or record.frozen_at is None:
            _fail(rt, "snapshot_status", "frozen snapshots require completed and frozen timestamps")
        frozen = _timestamp(record.frozen_at, rt, "frozen_at")
        if frozen < completed:
            _fail(rt, "frozen_at", "must not precede retrieval completion")
    elif record.frozen_at is not None:
        _fail(rt, "frozen_at", "is only permitted for a frozen snapshot")
    if record.snapshot_status is m.SnapshotStatus.FAILED and not record.validation_warnings:
        _fail(rt, "validation_warnings", "failed snapshots require a warning")


def _validate_scholarly_work(record: m.ScholarlyWork) -> None:
    rt = record.RECORD_TYPE
    _nonempty(record.preferred_title, rt, "preferred_title")
    _unique_strings(record.alternate_titles, rt, "alternate_titles")
    _identifiers(record.identifiers, rt, "identifiers")
    _nonempty(record.identity_key, rt, "identity_key")
    if record.identity_basis in {
        m.IdentityBasis.GLOBAL_IDENTIFIER,
        m.IdentityBasis.REGISTRY_IDENTIFIER,
    } and not record.identifiers:
        _fail(rt, "identifiers", "identifier-based identity requires an identifier")
    if record.identity_basis is m.IdentityBasis.METADATA_FINGERPRINT:
        _sha256(record.identity_key, rt, "identity_key")
    if record.identity_status in {m.IdentityStatus.AMBIGUOUS, m.IdentityStatus.NEEDS_REVIEW}:
        if not record.validation_warnings:
            _fail(rt, "validation_warnings", "ambiguous identity requires a warning")


def _validate_source_version(record: m.SourceVersion) -> None:
    rt = record.RECORD_TYPE
    validate_record_id(record.work_id, "scholarly_work")
    _identifiers(record.version_identifiers, rt, "version_identifiers")
    _nonempty(record.title, rt, "title")
    for index, contributor in enumerate(record.contributors):
        _nonempty(contributor.name, rt, f"contributors[{index}].name")
        _nonempty(contributor.role, rt, f"contributors[{index}].role")
        if contributor.position is not None and contributor.position < 0:
            _fail(rt, f"contributors[{index}].position", "must be non-negative")
        _identifiers(contributor.identifiers, rt, f"contributors[{index}].identifiers")
    _nonempty(record.source_type, rt, "source_type")
    _record_ids(
        record.study_design_entity_ids,
        rt,
        "study_design_entity_ids",
        expected_type="entity",
        sorted_values=True,
    )
    _partial_date(record.publication_date, rt, "publication_date")
    earliest = _partial_date(record.availability_earliest, rt, "availability_earliest")
    latest = _partial_date(record.availability_latest, rt, "availability_latest")
    _nonempty(record.availability_date_rule, rt, "availability_date_rule")
    if earliest is not None and latest is not None and earliest > latest:
        _fail(rt, "availability_latest", "must not precede availability_earliest")
    if record.availability_status is m.AvailabilityStatus.UNKNOWN:
        if record.availability_earliest is not None or record.availability_latest is not None:
            _fail(rt, "availability_status", "unknown availability requires null bounds")
        if record.temporal_eligibility is not m.TemporalEligibility.UNKNOWN:
            _fail(rt, "temporal_eligibility", "unknown availability cannot be assumed eligible")
    elif earliest is None and latest is None:
        _fail(rt, "availability_status", "known, bounded, or estimated availability requires a date")
    if (
        record.temporal_eligibility is m.TemporalEligibility.ELIGIBLE
        and record.availability_status is not m.AvailabilityStatus.KNOWN
    ):
        _fail(rt, "temporal_eligibility", "eligible requires known availability")
    _record_ids(
        record.previous_source_version_ids,
        rt,
        "previous_source_version_ids",
        expected_type="source_version",
        sorted_values=True,
    )
    _record_ids(
        record.provider_record_ids,
        rt,
        "provider_record_ids",
        expected_type="provider_record",
        sorted_values=True,
    )
    _identifiers(record.reference_identifiers, rt, "reference_identifiers")


def _validate_provider_record(record: m.ProviderRecord) -> None:
    rt = record.RECORD_TYPE
    for field in ("provider_name", "endpoint", "provider_item_id", "query_id", "raw_record_media_type"):
        _nonempty(getattr(record, field), rt, field)
    _safe_uri(record.endpoint, rt, "endpoint")
    _safe_uri(record.provider_item_url, rt, "provider_item_url")
    _sha256(record.request_sha256, rt, "request_sha256")
    _safe_uri(record.redacted_request_url, rt, "redacted_request_url")
    retrieved = _timestamp(record.retrieved_at, rt, "retrieved_at")
    if record.provider_updated_at is not None:
        updated = _timestamp(record.provider_updated_at, rt, "provider_updated_at")
        if updated > retrieved:
            _fail(rt, "provider_updated_at", "cannot be later than retrieval observation")
    for field in ("query_tier", "provider_rank"):
        value = getattr(record, field)
        if value is not None and value < 0:
            _fail(rt, field, "must be non-negative")
    if record.raw_record_sha256 is not None:
        _sha256(record.raw_record_sha256, rt, "raw_record_sha256")
    _safe_uri(record.raw_record_uri, rt, "raw_record_uri")
    if record.retrieval_status is m.ProviderRetrievalStatus.SUCCEEDED:
        if record.raw_record_sha256 is None or record.raw_record_uri is None:
            _fail(rt, "retrieval_status", "succeeded retrieval requires raw hash and URI")
        if record.error_code is not None or record.error_message is not None:
            _fail(rt, "retrieval_status", "succeeded retrieval cannot carry an error")
    if record.retrieval_status is m.ProviderRetrievalStatus.FAILED:
        if not record.error_code or not record.error_message:
            _fail(rt, "retrieval_status", "failed retrieval requires error code and message")


def _validate_access_location(record: m.AccessLocation) -> None:
    rt = record.RECORD_TYPE
    validate_record_id(record.source_version_id, "source_version")
    _optional_record_id(record.provider_record_id, rt, "provider_record_id", "provider_record")
    _safe_uri(record.uri, rt, "uri")
    _sha256(record.uri_sha256, rt, "uri_sha256")
    expected = hashlib.sha256(record.uri.encode("utf-8")).hexdigest()
    if record.uri_sha256 != expected:
        _fail(rt, "uri_sha256", f"does not match uri; expected {expected}")
    _timestamp(record.observed_at, rt, "observed_at")
    _safe_uri(record.redirect_uri, rt, "redirect_uri")
    if record.http_status is not None and not 100 <= record.http_status <= 599:
        _fail(rt, "http_status", "must be in [100, 599]")
    failed = {
        m.AccessStatus.RESTRICTED,
        m.AccessStatus.INACCESSIBLE,
        m.AccessStatus.NOT_FOUND,
        m.AccessStatus.ERROR,
    }
    if record.access_status in failed and not record.failure_reason:
        _fail(rt, "failure_reason", "is required for unsuccessful access")
    if record.access_status is m.AccessStatus.AVAILABLE and record.failure_reason:
        _fail(rt, "failure_reason", "must be null for available access")


def _validate_document(record: m.Document) -> None:
    rt = record.RECORD_TYPE
    validate_record_id(record.source_version_id, "source_version")
    validate_record_id(record.access_location_id, "access_location")
    _nonempty(record.media_type, rt, "media_type")
    _sha256(record.content_sha256, rt, "content_sha256")
    _timestamp(record.retrieved_at, rt, "retrieved_at")
    _safe_uri(record.artifact_uri, rt, "artifact_uri")
    if record.byte_size < 0:
        _fail(rt, "byte_size", "must be non-negative")
    if record.document_status is m.DocumentStatus.STORED and record.byte_size == 0:
        _fail(rt, "byte_size", "stored documents must contain bytes")
    if record.page_count is not None and record.page_count <= 0:
        _fail(rt, "page_count", "must be positive when present")
    if record.encrypted and record.document_status is m.DocumentStatus.STORED:
        _fail(rt, "document_status", "encrypted content must be quarantined or invalid")


def _validate_passage(record: m.Passage) -> None:
    rt = record.RECORD_TYPE
    validate_record_id(record.document_id, "document")
    validate_record_id(record.source_version_id, "source_version")
    if record.sequence_index < 0:
        _fail(rt, "sequence_index", "must be non-negative")
    text = _nonempty(record.text, rt, "text")
    if len(text) > MAX_PASSAGE_CHARACTERS:
        _fail(rt, "text", f"must not exceed {MAX_PASSAGE_CHARACTERS} characters")
    _sha256(record.text_sha256, rt, "text_sha256")
    expected = hashlib.sha256(text.encode("utf-8")).hexdigest()
    if record.text_sha256 != expected:
        _fail(rt, "text_sha256", f"does not match text; expected {expected}")
    _unique_strings(record.section_path, rt, "section_path")
    required_locator = {
        "coordinate_system",
        "representation_sha256",
        "start_char",
        "end_char",
        "page_start",
        "page_end",
        "paragraph_index",
    }
    if set(record.locator) != required_locator:
        _fail(rt, "locator", f"must contain exact keys {sorted(required_locator)}")
    _nonempty(record.locator["coordinate_system"], rt, "locator.coordinate_system")
    _sha256(record.locator["representation_sha256"], rt, "locator.representation_sha256")
    start = record.locator["start_char"]
    end = record.locator["end_char"]
    if isinstance(start, bool) or not isinstance(start, int) or start < 0:
        _fail(rt, "locator.start_char", "must be a non-negative integer")
    if isinstance(end, bool) or not isinstance(end, int) or end <= start:
        _fail(rt, "locator.end_char", "must be an integer greater than start_char")
    page_start = record.locator["page_start"]
    page_end = record.locator["page_end"]
    if page_start is not None and (
        isinstance(page_start, bool)
        or not isinstance(page_start, int)
        or page_start < 1
    ):
        _fail(rt, "locator.page_start", "must be a positive integer or null")
    if page_end is not None and (isinstance(page_end, bool) or not isinstance(page_end, int) or page_end < 1):
        _fail(rt, "locator.page_end", "must be a positive integer or null")
    if page_start is not None and page_end is not None and page_end < page_start:
        _fail(rt, "locator.page_end", "must not precede page_start")
    paragraph = record.locator["paragraph_index"]
    if paragraph is not None and (
        isinstance(paragraph, bool)
        or not isinstance(paragraph, int)
        or paragraph < 0
    ):
        _fail(rt, "locator.paragraph_index", "must be non-negative or null")
    for field in ("extractor_name", "extractor_version"):
        _nonempty(getattr(record, field), rt, field)
    _sha256(record.extraction_config_sha256, rt, "extraction_config_sha256")
    _timestamp(record.extracted_at, rt, "extracted_at")


def _validate_entity(record: m.Entity) -> None:
    rt = record.RECORD_TYPE
    _nonempty(record.canonical_name, rt, "canonical_name")
    _nonempty(record.normalized_name, rt, "normalized_name")
    _unique_strings(record.aliases, rt, "aliases")
    _identifiers(record.ontology_identifiers, rt, "ontology_identifiers")
    _nonempty(record.resolution_method, rt, "resolution_method")
    _optional_record_id(record.canonical_entity_id, rt, "canonical_entity_id", "entity")
    _record_ids(
        record.source_passage_ids,
        rt,
        "source_passage_ids",
        expected_type="passage",
        sorted_values=True,
    )
    _unique_strings(record.topic_ids, rt, "topic_ids", sorted_values=True)
    if record.resolution_status is m.EntityResolutionStatus.MERGED:
        if record.canonical_entity_id is None or record.canonical_entity_id == record.record_id:
            _fail(rt, "canonical_entity_id", "merged entities require a different canonical entity")
    elif record.canonical_entity_id is not None:
        _fail(rt, "canonical_entity_id", "is only valid for merged entities")
    if record.resolution_status is m.EntityResolutionStatus.AMBIGUOUS and not record.validation_warnings:
        _fail(rt, "validation_warnings", "ambiguous entities require a warning")


def _validate_claim(record: m.Claim) -> None:
    rt = record.RECORD_TYPE
    _nonempty(record.claim_text, rt, "claim_text")
    _optional_record_id(record.source_version_id, rt, "source_version_id", "source_version")
    _record_ids(record.source_claim_ids, rt, "source_claim_ids", expected_type="claim", sorted_values=True)
    _unique_strings(record.topic_ids, rt, "topic_ids", sorted_values=True)
    role_fields = (
        "subject_entity_ids",
        "population_entity_ids",
        "intervention_entity_ids",
        "comparator_entity_ids",
        "outcome_entity_ids",
        "measurement_entity_ids",
        "method_entity_ids",
        "dataset_entity_ids",
        "study_design_entity_ids",
        "setting_entity_ids",
    )
    for field in role_fields:
        _record_ids(getattr(record, field), rt, field, expected_type="entity", sorted_values=True)
    if record.claim_origin is m.ClaimOrigin.SOURCE_ASSERTED and record.source_version_id is None:
        _fail(rt, "source_version_id", "source-asserted claims require a source version")
    if record.claim_origin is m.ClaimOrigin.PIPELINE_SYNTHESIS and not record.source_claim_ids:
        _fail(rt, "source_claim_ids", "pipeline synthesis requires source claims")
    if not any(getattr(record, field) for field in role_fields):
        _fail(rt, "subject_entity_ids", "at least one typed entity role is required")
    _secret_scan(record.quantitative_details, rt, "quantitative_details")
    _secret_scan(record.comparability_profile, rt, "comparability_profile")
    _assessment(
        record.extraction_assessment,
        rt,
        "extraction_assessment",
        expected_dimension="extraction_confidence",
    )


def _validate_claim_evidence(record: m.ClaimEvidence) -> None:
    rt = record.RECORD_TYPE
    validate_record_id(record.claim_id, "claim")
    validate_record_id(record.source_version_id, "source_version")
    for index, span in enumerate(record.passage_spans):
        validate_record_id(span.passage_id, "passage")
        if span.start_char < 0 or span.end_char <= span.start_char:
            _fail(rt, f"passage_spans[{index}]", "requires 0 <= start_char < end_char")
        _sha256(span.quoted_text_sha256, rt, f"passage_spans[{index}].quoted_text_sha256")
    _record_ids(
        record.checked_passage_ids,
        rt,
        "checked_passage_ids",
        expected_type="passage",
        sorted_values=True,
    )
    _nonempty(record.verifier_id, rt, "verifier_id")
    _nonempty(record.verification_method, rt, "verification_method")
    _timestamp(record.verified_at, rt, "verified_at")
    _optional_record_id(record.counterclaim_id, rt, "counterclaim_id", "claim")
    _unique_strings(record.insufficiency_reasons, rt, "insufficiency_reasons")
    _unique_strings(record.uncertainty_reasons, rt, "uncertainty_reasons")
    _unique_strings(record.unresolved_checks, rt, "unresolved_checks")
    _human_review_triggers(record.human_review_triggers, rt, "human_review_triggers")
    checks = tuple(record.material_checks.__dict__.values())
    if record.verification_outcome is ClaimVerificationOutcome.SUPPORTED:
        if not record.passage_spans:
            _fail(rt, "passage_spans", "supported outcome requires exact spans")
        invalid_checks = {
            m.MaterialCheckStatus.MISMATCHED,
            m.MaterialCheckStatus.UNCERTAIN,
        }
        if any(check in invalid_checks for check in checks):
            _fail(rt, "material_checks", "supported outcome cannot contain mismatch or uncertainty")
    elif record.verification_outcome is ClaimVerificationOutcome.CONTRADICTED:
        if not record.passage_spans or record.counterclaim_id is None or not record.comparability_key:
            _fail(
                rt,
                "verification_outcome",
                "contradicted requires spans, counterclaim, and comparability key",
            )
    elif record.verification_outcome is ClaimVerificationOutcome.INSUFFICIENT:
        if not record.checked_passage_ids or not record.insufficiency_reasons:
            _fail(rt, "verification_outcome", "insufficient requires checked passages and reasons")
    elif record.verification_outcome is ClaimVerificationOutcome.UNCERTAIN:
        if not record.uncertainty_reasons or not record.unresolved_checks:
            _fail(rt, "verification_outcome", "uncertain requires reasons and unresolved checks")
    _assessment(
        record.verification_assessment,
        rt,
        "verification_assessment",
        expected_dimension="verification_confidence",
    )


def _validate_relationship(record: m.Relationship) -> None:
    rt = record.RECORD_TYPE
    validate_record_id(record.subject_id, record.subject_type.value)
    validate_record_id(record.object_id, record.object_type.value)
    if record.subject_id == record.object_id:
        _fail(rt, "object_id", "self-relationships are not permitted")
    _nonempty(record.basis, rt, "basis")
    _record_ids(
        record.claim_evidence_ids,
        rt,
        "claim_evidence_ids",
        expected_type="claim_evidence",
        sorted_values=True,
    )
    _record_ids(record.passage_ids, rt, "passage_ids", expected_type="passage", sorted_values=True)
    _date(record.valid_as_of, rt, "valid_as_of")
    _timestamp(record.asserted_at, rt, "asserted_at")
    scientific = {
        m.RelationshipPredicate.SUPPORTS,
        m.RelationshipPredicate.CONTRADICTS,
        m.RelationshipPredicate.EXTENDS,
        m.RelationshipPredicate.USES_METHOD,
        m.RelationshipPredicate.STUDIES_POPULATION,
        m.RelationshipPredicate.USES_DATASET,
        m.RelationshipPredicate.MEASURES_OUTCOME,
        m.RelationshipPredicate.TESTS_INTERVENTION,
        m.RelationshipPredicate.HAS_STUDY_DESIGN,
        m.RelationshipPredicate.ADDRESSES_GAP,
    }
    if record.predicate in scientific and not record.claim_evidence_ids:
        _fail(rt, "claim_evidence_ids", "scientific relations require verified evidence")
    if record.predicate in {m.RelationshipPredicate.SUPPORTS, m.RelationshipPredicate.CONTRADICTS}:
        if record.subject_type is not m.RecordType.CLAIM or record.object_type is not m.RecordType.CLAIM:
            _fail(rt, "predicate", "supports/contradicts require Claim -> Claim")
    if record.predicate is m.RelationshipPredicate.CONTRADICTS and not record.comparability_key:
        _fail(rt, "comparability_key", "contradiction requires comparability")


def _gap_language_qualifiers(
    record: m.GapSignal | m.GapCandidate,
) -> dict[str, Any]:
    providers = record.corpus_scope.get("providers", ())
    return {
        "corpus_snapshot_id": record.corpus_snapshot_id,
        "corpus_scope": str(record.corpus_scope.get("description", "declared scope")),
        "as_of": record.as_of,
        "searched_sources": list(providers) if isinstance(providers, (tuple, list)) else [],
        "coverage_status": record.coverage_status.value,
    }


def _validate_gap_signal(record: m.GapSignal) -> None:
    rt = record.RECORD_TYPE
    ontology = _gap_ontology()
    gap_type_ids = _unique_strings(
        record.gap_type_ids,
        rt,
        "gap_type_ids",
        nonempty=True,
        sorted_values=True,
    )
    for gap_type_id in gap_type_ids:
        definition = ontology.classes.get(gap_type_id)
        if definition is None:
            _fail(rt, "gap_type_ids", f"unknown operational class {gap_type_id!r}")
        if record.signal_type.value not in definition.allowed_signal_types:
            _fail(
                rt,
                "signal_type",
                f"{record.signal_type.value!r} is not allowed for {gap_type_id!r}",
            )
    _nonempty(record.rule_id, rt, "rule_id")
    _semver(record.rule_version, rt, "rule_version")
    _nonempty(record.statement, rt, "statement")
    _date(record.as_of, rt, "as_of")
    _nonempty(record.availability_date_rule, rt, "availability_date_rule")
    _nonempty(record.query_or_cell, rt, "query_or_cell")
    if not record.rule_inputs or not record.rule_result:
        _fail(rt, "rule_inputs", "deterministic signals require recorded inputs and result")
    _secret_scan(record.rule_inputs, rt, "rule_inputs")
    _secret_scan(record.rule_result, rt, "rule_result")
    _sha256(record.rule_trace_sha256, rt, "rule_trace_sha256")
    _record_ids(
        record.supporting_claim_ids,
        rt,
        "supporting_claim_ids",
        expected_type="claim",
        sorted_values=True,
    )
    _record_ids(
        record.supporting_passage_ids,
        rt,
        "supporting_passage_ids",
        expected_type="passage",
        sorted_values=True,
    )
    _record_ids(
        record.relationship_ids,
        rt,
        "relationship_ids",
        expected_type="relationship",
        sorted_values=True,
    )
    _record_ids(
        record.checked_source_version_ids,
        rt,
        "checked_source_version_ids",
        expected_type="source_version",
        sorted_values=True,
    )
    _unique_strings(record.retrieval_query_log_ids, rt, "retrieval_query_log_ids", sorted_values=True)
    _coverage(record.coverage_status, record.coverage_dimensions, rt, "coverage")
    _unique_strings(record.uncertainty_reasons, rt, "uncertainty_reasons")
    if record.deterministic is not True:
        _fail(rt, "deterministic", "must be true; interpretations alone are not signals")
    _record_ids(
        record.source_interpretation_ids,
        rt,
        "source_interpretation_ids",
        expected_type="mantis_interpretation",
        sorted_values=True,
    )
    if not (
        record.supporting_claim_ids
        or record.supporting_passage_ids
        or record.relationship_ids
        or record.checked_source_version_ids
    ):
        _fail(rt, "supporting_claim_ids", "requires independent recorded corpus or evidence inputs")
    try:
        validate_gap_language(
            _validity_policy(),
            record.statement,
            qualifiers=_gap_language_qualifiers(record),
        )
    except ValidationError as exc:
        raise ValidationError(f"{rt}.statement: {exc}") from exc


def _validate_gap_state_history(record: m.GapCandidate) -> None:
    rt = record.RECORD_TYPE
    policy = _validity_policy()
    if record.candidate_version == 1:
        current = GapStatus.PROPOSED
    else:
        if not record.state_history:
            _fail(
                rt,
                "state_history",
                "a reassessment version requires its terminal-to-verification transition",
            )
        current = record.state_history[0].from_gap_status
        if not policy.gap_statuses[current].terminal_for_candidate_version:
            _fail(
                rt,
                "state_history[0].from_gap_status",
                "a reassessment must start from a terminal predecessor state",
            )
    previous_time: datetime | None = None
    used_attempts: list[str] = []
    for index, transition in enumerate(record.state_history):
        if transition.from_gap_status is not current:
            _fail(rt, f"state_history[{index}]", f"must start from {current.value!r}")
        transitioned = _timestamp(
            transition.transitioned_at,
            rt,
            f"state_history[{index}].transitioned_at",
        )
        if previous_time is not None and transitioned < previous_time:
            _fail(rt, f"state_history[{index}]", "timestamps must be append-only")
        _nonempty(transition.actor_id, rt, f"state_history[{index}].actor_id")
        _nonempty(transition.reason, rt, f"state_history[{index}].reason")
        checks = _unique_strings(
            transition.completed_check_ids,
            rt,
            f"state_history[{index}].completed_check_ids",
        )
        if transition.verification_attempt_id is not None:
            validate_record_id(transition.verification_attempt_id, "verification_attempt")
            used_attempts.append(transition.verification_attempt_id)
        try:
            validate_gap_transition(
                policy,
                transition.from_gap_status,
                transition.to_gap_status,
                completed_checks=checks,
                new_candidate_version=transition.new_candidate_version,
            )
        except ValidationError as exc:
            raise ValidationError(f"{rt}.state_history[{index}]: {exc}") from exc
        current = transition.to_gap_status
        previous_time = transitioned
    if current is not record.gap_status:
        _fail(rt, "gap_status", f"must equal state-history result {current.value!r}")
    missing_attempts = sorted(set(used_attempts) - set(record.verification_attempt_ids))
    if missing_attempts:
        _fail(rt, "verification_attempt_ids", f"missing state-history attempts {missing_attempts}")


def _validate_gap_candidate(record: m.GapCandidate) -> None:
    rt = record.RECORD_TYPE
    ontology = _gap_ontology()
    _nonempty(record.gap_lineage_id, rt, "gap_lineage_id")
    if record.candidate_version < 1:
        _fail(rt, "candidate_version", "must be at least 1")
    _optional_record_id(record.supersedes_candidate_id, rt, "supersedes_candidate_id", "gap_candidate")
    if record.candidate_version == 1 and record.supersedes_candidate_id is not None:
        _fail(rt, "supersedes_candidate_id", "version 1 cannot supersede a candidate")
    if record.candidate_version > 1 and record.supersedes_candidate_id is None:
        _fail(rt, "supersedes_candidate_id", "later versions must identify their predecessor")
    if record.gap_type_id not in ontology.classes:
        _fail(rt, "gap_type_id", "must be an operational v1 ontology class")
    if record.gap_type_version != ontology.ontology_version:
        _fail(rt, "gap_type_version", f"must be {ontology.ontology_version!r}")
    for field in ("title", "statement", "rationale", "research_question"):
        _nonempty(getattr(record, field), rt, field)
    _date(record.as_of, rt, "as_of")
    _nonempty(record.availability_date_rule, rt, "availability_date_rule")
    _record_ids(
        record.signal_ids,
        rt,
        "signal_ids",
        expected_type="gap_signal",
        nonempty=True,
        sorted_values=True,
    )
    _record_ids(
        record.supporting_claim_ids,
        rt,
        "supporting_claim_ids",
        expected_type="claim",
        sorted_values=True,
    )
    _coverage(record.coverage_status, record.coverage_dimensions, rt, "coverage")
    _unique_strings(record.uncertainty_reasons, rt, "uncertainty_reasons")
    _nonempty(record.resolution_rule_id, rt, "resolution_rule_id")
    _semver(record.resolution_rule_version, rt, "resolution_rule_version")
    _record_ids(
        record.verification_attempt_ids,
        rt,
        "verification_attempt_ids",
        expected_type="verification_attempt",
        sorted_values=True,
    )
    _optional_record_id(
        record.decisive_verification_attempt_id,
        rt,
        "decisive_verification_attempt_id",
        "verification_attempt",
    )
    _human_review_triggers(record.human_review_trigger_ids, rt, "human_review_trigger_ids")
    _optional_record_id(record.canonical_gap_id, rt, "canonical_gap_id", "gap_candidate")
    if record.gap_status is GapStatus.DUPLICATE and record.canonical_gap_id is None:
        _fail(rt, "canonical_gap_id", "duplicate status requires a canonical candidate")
    if record.gap_status not in {GapStatus.PROPOSED, GapStatus.VERIFICATION_IN_PROGRESS}:
        if record.decisive_verification_attempt_id is None:
            _fail(rt, "decisive_verification_attempt_id", "terminal state requires a decisive attempt")
    if (
        record.decisive_verification_attempt_id is not None
        and record.decisive_verification_attempt_id
        not in record.verification_attempt_ids
    ):
        _fail(rt, "decisive_verification_attempt_id", "must be listed in verification_attempt_ids")
    _validate_gap_state_history(record)
    try:
        validate_gap_language(
            _validity_policy(),
            record.statement,
            qualifiers=_gap_language_qualifiers(record),
        )
    except ValidationError as exc:
        raise ValidationError(f"{rt}.statement: {exc}") from exc


def _validate_verification_checks(record: m.VerificationAttempt) -> tuple[str, ...]:
    rt = record.RECORD_TYPE
    check_ids: list[str] = []
    passed: list[str] = []
    for index, check in enumerate(record.checks):
        check_id = _nonempty(check.check_id, rt, f"checks[{index}].check_id")
        check_ids.append(check_id)
        if check.performed_at is not None:
            _timestamp(check.performed_at, rt, f"checks[{index}].performed_at")
        if check.status is m.VerificationCheckStatus.NOT_RUN:
            if check.performed_at is not None or check.verifier_id is not None:
                _fail(rt, f"checks[{index}]", "not-run checks cannot be performed")
        else:
            if check.performed_at is None or not check.verifier_id:
                _fail(rt, f"checks[{index}]", "performed checks require time and verifier")
        _record_ids(check.evidence_ids, rt, f"checks[{index}].evidence_ids", sorted_values=True)
        _nonempty(check.details, rt, f"checks[{index}].details")
        _human_review_triggers(
            check.human_review_trigger_ids,
            rt,
            f"checks[{index}].human_review_trigger_ids",
        )
        if check.status is m.VerificationCheckStatus.PASSED:
            passed.append(check_id)
    if len(check_ids) != len(set(check_ids)):
        _fail(rt, "checks", "check_id values must be unique")
    return tuple(passed)


def _validate_verification_attempt(record: m.VerificationAttempt) -> None:
    rt = record.RECORD_TYPE
    validate_record_id(record.gap_candidate_id, "gap_candidate")
    if record.attempt_number < 1:
        _fail(rt, "attempt_number", "must be at least 1")
    for field in ("protocol_id", "protocol_version"):
        _nonempty(getattr(record, field), rt, field)
    _semver(record.protocol_version, rt, "protocol_version")
    started = _timestamp(record.started_at, rt, "started_at")
    completed = (
        _timestamp(record.completed_at, rt, "completed_at")
        if record.completed_at is not None
        else None
    )
    if completed is not None and completed < started:
        _fail(rt, "completed_at", "must not precede started_at")
    _unique_strings(record.verifier_ids, rt, "verifier_ids", nonempty=True, sorted_values=True)
    passed_checks = _validate_verification_checks(record)
    typed_lists = {
        "supporting_claim_evidence_ids": "claim_evidence",
        "counterclaim_evidence_ids": "claim_evidence",
        "checked_passage_ids": "passage",
        "refuting_evidence_ids": None,
        "resolving_evidence_ids": None,
        "expert_judgment_ids": "expert_judgment",
    }
    for field, expected_type in typed_lists.items():
        _record_ids(getattr(record, field), rt, field, expected_type=expected_type, sorted_values=True)
    _unique_strings(record.counterretrieval_ids, rt, "counterretrieval_ids", sorted_values=True)
    _unique_strings(record.retrieval_query_log_ids, rt, "retrieval_query_log_ids", sorted_values=True)
    _coverage(record.coverage_status, record.coverage_dimensions, rt, "coverage")
    _human_review_triggers(record.human_review_trigger_ids, rt, "human_review_trigger_ids")
    _unique_strings(record.uncertainty_reasons, rt, "uncertainty_reasons")
    _unique_strings(record.unresolved_check_ids, rt, "unresolved_check_ids")
    _nonempty(record.decision_rationale, rt, "decision_rationale")
    _optional_record_id(record.canonical_gap_id, rt, "canonical_gap_id", "gap_candidate")
    if record.attempt_status is m.VerificationAttemptStatus.IN_PROGRESS:
        if completed is not None or record.resulting_gap_status is not None:
            _fail(rt, "attempt_status", "in-progress attempt cannot have a final result")
    elif record.attempt_status is m.VerificationAttemptStatus.COMPLETED:
        if completed is None or record.resulting_gap_status is None:
            _fail(rt, "attempt_status", "completed attempt requires time and result")
    if record.resulting_gap_status is not None:
        try:
            validate_gap_transition(
                _validity_policy(),
                record.from_gap_status,
                record.resulting_gap_status,
                completed_checks=passed_checks,
                new_candidate_version=(
                    record.from_gap_status
                    not in {GapStatus.PROPOSED, GapStatus.VERIFICATION_IN_PROGRESS}
                ),
            )
        except ValidationError as exc:
            raise ValidationError(f"{rt}.resulting_gap_status: {exc}") from exc
    result = record.resulting_gap_status
    if result is GapStatus.VERIFIED_OPEN:
        if record.coverage_status is not m.CoverageStatus.ADEQUATE_FOR_RULE:
            _fail(rt, "coverage_status", "verified-open requires adequate-for-rule coverage")
    elif result is GapStatus.REFUTED and not record.refuting_evidence_ids:
        _fail(rt, "refuting_evidence_ids", "refuted result requires evidence")
    elif result is GapStatus.RESOLVED:
        if not record.resolving_evidence_ids or not record.resolution_rule_id or not record.resolution_as_of:
            _fail(rt, "resolving_evidence_ids", "resolved result requires evidence, rule, and cutoff")
        _date(record.resolution_as_of, rt, "resolution_as_of")
    elif result is GapStatus.UNCERTAIN:
        if not record.uncertainty_reasons or not record.unresolved_check_ids:
            _fail(rt, "uncertainty_reasons", "uncertain result requires reasons and unresolved checks")
    elif result is GapStatus.DUPLICATE and record.canonical_gap_id is None:
        _fail(rt, "canonical_gap_id", "duplicate result requires canonical candidate")
    elif result is GapStatus.TERMINOLOGY_ARTIFACT:
        if not record.artifact_type or not record.artifact_basis_ids:
            _fail(rt, "artifact_type", "artifact result requires type and verified basis")


def _score_dimension(
    score: m.ScoreDimension,
    record_type: str,
    field: str,
    expected_dimension: str,
) -> None:
    if score.dimension != expected_dimension:
        _fail(record_type, f"{field}.dimension", f"must be {expected_dimension!r}")
    if score.scale_max <= score.scale_min:
        _fail(record_type, field, "scale_max must exceed scale_min")
    if not score.scale_min <= score.score <= score.scale_max:
        _fail(record_type, f"{field}.score", "must lie inside its declared scale")
    if score.uncertainty is not None and not 0.0 <= score.uncertainty <= 1.0:
        _fail(record_type, f"{field}.uncertainty", "must be in [0, 1]")
    _nonempty(score.rationale, record_type, f"{field}.rationale")
    _nonempty(score.assessor_id, record_type, f"{field}.assessor_id")
    _record_ids(score.evidence_ids, record_type, f"{field}.evidence_ids", sorted_values=True)


def _validate_gap_score(record: m.GapScore) -> None:
    rt = record.RECORD_TYPE
    validate_record_id(record.gap_candidate_id, "gap_candidate")
    _semver(record.score_version, rt, "score_version")
    _nonempty(record.protocol_id, rt, "protocol_id")
    _semver(record.protocol_version, rt, "protocol_version")
    _score_dimension(record.novelty, rt, "novelty", "novelty")
    _score_dimension(record.importance, rt, "importance", "importance")
    _score_dimension(record.feasibility, rt, "feasibility", "feasibility")
    _record_ids(
        record.expert_judgment_ids,
        rt,
        "expert_judgment_ids",
        expected_type="expert_judgment",
        sorted_values=True,
    )
    if record.calibration_status is m.ScoreCalibrationStatus.CALIBRATED:
        if not record.calibration_dataset_id:
            _fail(rt, "calibration_dataset_id", "calibrated scores require a dataset")
        for field in ("novelty", "importance", "feasibility"):
            if getattr(record, field).calibration_reference_id is None:
                _fail(rt, field, "calibrated dimensions require a calibration reference")
    if record.composite is not None:
        _score_dimension(record.composite, rt, "composite", "composite")
        if not record.composite_rule_id or not record.composite_rule_version:
            _fail(
                rt,
                "composite",
                "requires an explicit composite rule id and version",
            )
        _nonempty(record.composite_rule_id, rt, "composite_rule_id")
        _semver(record.composite_rule_version, rt, "composite_rule_version")
    elif record.composite_rule_id is not None or record.composite_rule_version is not None:
        _fail(
            rt,
            "composite_rule_id",
            "composite rule metadata requires a composite score",
        )


def _validate_expert_judgment(record: m.ExpertJudgment) -> None:
    rt = record.RECORD_TYPE
    for field in (
        "protocol_id",
        "task_id",
        "assignment_id",
        "expert_id",
        "gap_list_version_id",
        "condition_id",
    ):
        _nonempty(getattr(record, field), rt, field)
    _semver(record.protocol_version, rt, "protocol_version")
    validate_record_id(record.gap_candidate_id, "gap_candidate")
    _record_ids(record.presented_artifact_ids, rt, "presented_artifact_ids", sorted_values=True)
    _optional_record_id(record.mantis_profile_id, rt, "mantis_profile_id", "mantis_export_profile")
    if record.mantis_input_sha256 is not None:
        _sha256(record.mantis_input_sha256, rt, "mantis_input_sha256")
    _optional_record_id(record.mantis_receipt_id, rt, "mantis_receipt_id", "mantis_publication_receipt")
    mantis_context = (
        record.mantis_profile_id,
        record.mantis_input_sha256,
        record.mantis_receipt_id,
    )
    if any(mantis_context) and not all(mantis_context):
        _fail(
            rt,
            "mantis_profile_id",
            "Mantis evaluation context requires profile, input hash, and receipt together",
        )
    if record.decision_confidence is not None:
        if not 0.0 <= record.decision_confidence <= 1.0 or not record.confidence_scale_id:
            _fail(rt, "decision_confidence", "requires a [0, 1] value and scale id")
    elif record.confidence_scale_id is not None:
        _fail(rt, "confidence_scale_id", "requires decision_confidence")
    _nonempty(record.rationale, rt, "rationale")
    started = _timestamp(record.started_at, rt, "started_at")
    submitted = _timestamp(record.submitted_at, rt, "submitted_at")
    if submitted < started:
        _fail(rt, "submitted_at", "must not precede started_at")
    if record.duration_seconds < 0:
        _fail(rt, "duration_seconds", "must be non-negative")
    _record_ids(record.known_evidence_ids, rt, "known_evidence_ids", sorted_values=True)
    _optional_record_id(record.canonical_gap_id, rt, "canonical_gap_id", "gap_candidate")
    _optional_record_id(record.supersedes_judgment_id, rt, "supersedes_judgment_id", "expert_judgment")
    if record.decision is m.ExpertDecision.ALREADY_KNOWN and not record.known_evidence_ids:
        _fail(rt, "known_evidence_ids", "already-known judgment requires evidence")
    if record.decision is m.ExpertDecision.DUPLICATE and record.canonical_gap_id is None:
        _fail(rt, "canonical_gap_id", "duplicate judgment requires canonical candidate")


def _validate_outcome_event(record: m.OutcomeEvent) -> None:
    rt = record.RECORD_TYPE
    _nonempty(record.protocol_id, rt, "protocol_id")
    _semver(record.protocol_version, rt, "protocol_version")
    validate_record_id(record.gap_candidate_id, "gap_candidate")
    _record_ids(
        record.expert_judgment_ids,
        rt,
        "expert_judgment_ids",
        expected_type="expert_judgment",
        sorted_values=True,
    )
    _nonempty(record.research_project_id, rt, "research_project_id")
    partial = m.PartialDate(
        value=record.occurred_on,
        precision=record.date_precision,
        certainty=m.PartialDateCertainty.EXACT,
    )
    _partial_date(partial, rt, "occurred_on")
    _record_ids(record.source_reference_ids, rt, "source_reference_ids", nonempty=True, sorted_values=True)
    _nonempty(record.verification_method, rt, "verification_method")
    _optional_record_id(record.corrects_event_id, rt, "corrects_event_id", "outcome_event")
    if record.outcome_status is m.OutcomeStatus.CORRECTED and record.corrects_event_id is None:
        _fail(rt, "corrects_event_id", "corrected outcome requires prior event")
    _nonempty(record.notes, rt, "notes")


def _validate_mantis_export_profile(record: m.MantisExportProfile) -> None:
    rt = record.RECORD_TYPE
    _semver(record.profile_version, rt, "profile_version")
    _semver(record.compatibility_version, rt, "compatibility_version")
    _nonempty(record.source_contract, rt, "source_contract")
    _semver(record.source_schema_version, rt, "source_schema_version")
    _unique_strings(record.eligible_statuses, rt, "eligible_statuses", nonempty=True)
    _nonempty(record.point_id_source_path, rt, "point_id_source_path")
    if not record.fields:
        _fail(rt, "fields", "must declare ordered output fields")
    names: list[str] = []
    title_count = 0
    semantic_count = 0
    semantic_orders: list[int] = []
    has_connection = False
    for index, field in enumerate(record.fields):
        names.append(_nonempty(field.output_name, rt, f"fields[{index}].output_name"))
        _nonempty(field.source_path, rt, f"fields[{index}].source_path")
        if field.mantis_type is m.MantisDataType.TITLE:
            title_count += 1
        if field.mantis_type is m.MantisDataType.SEMANTIC:
            semantic_count += 1
            if field.semantic_order is None or field.semantic_order < 0:
                _fail(rt, f"fields[{index}].semantic_order", "semantic fields require non-negative order")
            semantic_orders.append(field.semantic_order)
        elif field.semantic_order is not None:
            _fail(rt, f"fields[{index}].semantic_order", "is only valid for Semantic fields")
        if field.multivalue_policy is m.MantisMultivaluePolicy.JOIN and field.separator is None:
            _fail(rt, f"fields[{index}].separator", "join policy requires a separator")
        if field.mantis_type is m.MantisDataType.CONNECTION:
            has_connection = True
    if len(names) != len(set(names)):
        _fail(rt, "fields", "output names must be unique")
    if title_count != 1 or semantic_count < 1:
        _fail(rt, "fields", "requires exactly one Title and at least one Semantic field")
    if sorted(semantic_orders) != list(range(len(semantic_orders))):
        _fail(rt, "fields", "Semantic ordering must be contiguous from zero")
    if has_connection and not record.connection_compatibility_verified:
        _fail(
            rt,
            "connection_compatibility_verified",
            "Connection output requires explicit compatibility verification",
        )
    _secret_scan(record.semantic_text, rt, "semantic_text")
    _unique_strings(record.row_sort_paths, rt, "row_sort_paths", nonempty=True)
    _secret_scan(record.csv_policy, rt, "csv_policy")
    _unique_strings(record.supported_tool_versions, rt, "supported_tool_versions", nonempty=True)


def _validate_mantis_interpretation(record: m.MantisInterpretation) -> None:
    rt = record.RECORD_TYPE
    for field in ("space_id", "map_id", "map_profile_version", "actor", "prompt_or_action", "output_text"):
        _nonempty(getattr(record, field), rt, field)
    _semver(record.map_profile_version, rt, "map_profile_version")
    _sha256(record.map_input_sha256, rt, "map_input_sha256")
    _record_ids(record.selected_point_ids, rt, "selected_point_ids", nonempty=True, sorted_values=True)
    _unique_strings(record.selected_remote_point_ids, rt, "selected_remote_point_ids", sorted_values=True)
    _timestamp(record.interpreted_at, rt, "interpreted_at")
    if record.is_evidence is not False:
        _fail(rt, "is_evidence", "Mantis map output is never scientific evidence")
    _record_ids(
        record.independent_signal_ids,
        rt,
        "independent_signal_ids",
        expected_type="gap_signal",
        sorted_values=True,
    )
    _record_ids(
        record.created_candidate_ids,
        rt,
        "created_candidate_ids",
        expected_type="gap_candidate",
        sorted_values=True,
    )
    validate_record_id(record.publication_receipt_id, "mantis_publication_receipt")
    states_requiring_signal = {
        m.InterpretationDownstreamState.INDEPENDENT_SIGNAL_FOUND,
        m.InterpretationDownstreamState.CANDIDATE_CREATED,
    }
    if record.downstream_state in states_requiring_signal and not record.independent_signal_ids:
        _fail(rt, "independent_signal_ids", "downstream state requires an independent deterministic signal")
    if record.downstream_state is m.InterpretationDownstreamState.CANDIDATE_CREATED:
        if not record.created_candidate_ids:
            _fail(rt, "created_candidate_ids", "candidate-created state requires a candidate")
    elif record.created_candidate_ids:
        _fail(rt, "created_candidate_ids", "may only be set after candidate creation")


def _validate_publication_error(
    error: m.PublicationError | None,
    record_type: str,
) -> None:
    if error is None:
        return
    _nonempty(error.code, record_type, "error.code")
    _nonempty(error.message, record_type, "error.message")
    _secret_scan(error.message, record_type, "error.message")


def _validate_mantis_publication_receipt(record: m.MantisPublicationReceipt) -> None:
    rt = record.RECORD_TYPE
    validate_record_id(record.export_profile_id, "mantis_export_profile")
    _semver(record.profile_version, rt, "profile_version")
    _semver(record.compatibility_version, rt, "compatibility_version")
    _nonempty(record.source_contract, rt, "source_contract")
    _semver(record.source_schema_version, rt, "source_schema_version")
    if record.source_artifact_reference.kind is not m.ProvenanceKind.ARTIFACT:
        _fail(rt, "source_artifact_reference.kind", "must be artifact provenance")
    _nonempty(record.source_artifact_reference.reference, rt, "source_artifact_reference.reference")
    if record.source_artifact_reference.sha256 is not None:
        _sha256(record.source_artifact_reference.sha256, rt, "source_artifact_reference.sha256")
    _sha256(record.source_sha256, rt, "source_sha256")
    if record.source_artifact_reference.sha256 != record.source_sha256:
        _fail(rt, "source_sha256", "must match source artifact provenance")
    if record.record_count < 0:
        _fail(rt, "record_count", "must be non-negative")
    for field in ("tool_name", "tool_version", "host", "idempotency_key"):
        _nonempty(getattr(record, field), rt, field)
    if "://" in record.host or "/" in record.host or "@" in record.host:
        _fail(rt, "host", "must be a non-secret hostname, not a URL")
    if record.attempt_number < 1:
        _fail(rt, "attempt_number", "must be at least 1")
    _optional_record_id(record.retry_of_receipt_id, rt, "retry_of_receipt_id", "mantis_publication_receipt")
    if record.attempt_number > 1 and record.retry_of_receipt_id is None:
        _fail(rt, "retry_of_receipt_id", "retry attempts require the previous receipt")
    started = _timestamp(record.started_at, rt, "started_at")
    completed = _timestamp(record.completed_at, rt, "completed_at") if record.completed_at else None
    published = _timestamp(record.published_at, rt, "published_at") if record.published_at else None
    if completed is not None and completed < started:
        _fail(rt, "completed_at", "must not precede started_at")
    if published is not None and published < started:
        _fail(rt, "published_at", "must not precede started_at")
    _safe_uri(record.space_uri, rt, "space_uri")
    _safe_uri(record.map_uri, rt, "map_uri")
    _validate_publication_error(record.error, rt)
    if record.publication_status is m.MantisPublicationStatus.SUCCEEDED:
        required = (completed, published, record.space_id, record.map_id)
        if any(value is None for value in required) or record.error is not None:
            _fail(
                rt,
                "publication_status",
                "success requires completion, publication, space/map ids, and no error",
            )
    elif record.publication_status is m.MantisPublicationStatus.FAILED:
        if completed is None or record.error is None or published is not None:
            _fail(rt, "publication_status", "failure requires completion and error but no publication time")
    elif record.publication_status is m.MantisPublicationStatus.PARTIAL:
        if completed is None or record.error is None:
            _fail(rt, "publication_status", "partial publication requires completion and a sanitized error")


_VALIDATORS = {
    "corpus_snapshot": _validate_corpus_snapshot,
    "scholarly_work": _validate_scholarly_work,
    "source_version": _validate_source_version,
    "provider_record": _validate_provider_record,
    "access_location": _validate_access_location,
    "document": _validate_document,
    "passage": _validate_passage,
    "entity": _validate_entity,
    "claim": _validate_claim,
    "claim_evidence": _validate_claim_evidence,
    "relationship": _validate_relationship,
    "gap_signal": _validate_gap_signal,
    "gap_candidate": _validate_gap_candidate,
    "verification_attempt": _validate_verification_attempt,
    "gap_score": _validate_gap_score,
    "expert_judgment": _validate_expert_judgment,
    "outcome_event": _validate_outcome_event,
    "mantis_export_profile": _validate_mantis_export_profile,
    "mantis_interpretation": _validate_mantis_interpretation,
    "mantis_publication_receipt": _validate_mantis_publication_receipt,
}


def validate_record(record: m.RecordEnvelope) -> None:
    """Validate one record without pretending to resolve cross-record references.

    This checks schema-local semantics, stable-ID recomputation, timestamp and
    hash syntax, and typed reference syntax. Referential existence, ownership,
    lineage across files, and artifact hash verification belong to Step 1.4.
    """
    if not isinstance(record, m.BaseRecord):
        raise ValidationError("Expected a versioned BaseRecord instance.")
    validator = _VALIDATORS.get(record.RECORD_TYPE)
    if validator is None:
        raise ValidationError(f"Unsupported record type {record.RECORD_TYPE!r}.")
    _validate_envelope(record)
    validator(record)
