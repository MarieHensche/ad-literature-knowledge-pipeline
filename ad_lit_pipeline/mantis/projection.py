from __future__ import annotations

import csv
import hashlib
import json
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

from ad_lit_pipeline.core.errors import ValidationError
from ad_lit_pipeline.mantis.profiles import (
    DEFAULT_PROFILE_DIRECTORY,
    ProfileContext,
    compile_profile,
    load_profile_template,
)
from ad_lit_pipeline.records import (
    Claim,
    ClaimEvidence,
    CorpusSnapshot,
    Entity,
    GapCandidate,
    GapScore,
    MantisExportProfile,
    RecordEnvelope,
    ScholarlyWork,
    SourceVersion,
    VerificationAttempt,
    canonical_json,
    read_record_jsonl,
    record_to_dict,
    require_record_integrity,
    validate_record_collection,
)
from ad_lit_pipeline.records.models import (
    AdministrativeRecordStatus,
    MantisMultivaluePolicy,
    MantisNullPolicy,
    MantisRecordKind,
    SnapshotStatus,
    SourceLifecycleStatus,
    TemporalEligibility,
    VerificationAttemptStatus,
)
from ad_lit_pipeline.validity.models import ClaimVerificationOutcome, GapStatus


_ALLOWED_CLAIM_OUTCOMES = {
    ClaimVerificationOutcome.SUPPORTED,
    ClaimVerificationOutcome.CONTRADICTED,
}
_ALLOWED_PAPER_LIFECYCLES = {
    SourceLifecycleStatus.ACTIVE,
    SourceLifecycleStatus.CORRECTED,
}


@dataclass(frozen=True)
class ProjectionResult:
    """One in-memory Mantis view and its eligibility audit."""

    profile: MantisExportProfile
    rows: tuple[Mapping[str, Any], ...]
    report: Mapping[str, Any]


@dataclass(frozen=True)
class ExportedView:
    """Paths and counts produced for one materialized Mantis view."""

    record_kind: str
    csv_path: Path
    profile_path: Path
    report_path: Path
    row_count: int


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _active(record: RecordEnvelope) -> bool:
    return record.record_status is AdministrativeRecordStatus.ACTIVE


def _exact_snapshot(records: Sequence[RecordEnvelope]) -> CorpusSnapshot:
    snapshots = [record for record in records if isinstance(record, CorpusSnapshot)]
    if len(snapshots) != 1:
        raise ValidationError(
            "Mantis projection requires exactly one complete CorpusSnapshot; "
            f"found {len(snapshots)}."
        )
    snapshot = snapshots[0]
    if not _active(snapshot) or snapshot.snapshot_status is not SnapshotStatus.FROZEN:
        raise ValidationError("Mantis projection requires an active frozen snapshot.")
    wrong_snapshot = sorted(
        record.record_id
        for record in records
        if record.corpus_snapshot_id != snapshot.record_id
    )
    if wrong_snapshot:
        raise ValidationError(
            "Mantis projection cannot mix snapshots; first mismatched record is "
            f"{wrong_snapshot[0]}."
        )
    return snapshot


def _entity_names(
    entity_ids: Sequence[str], entities: Mapping[str, Entity]
) -> tuple[str, ...]:
    return tuple(
        sorted(
            {
                entities[entity_id].canonical_name
                for entity_id in entity_ids
                if entity_id in entities and _active(entities[entity_id])
            }
        )
    )


def _paper_rows(
    records: Sequence[RecordEnvelope], snapshot: CorpusSnapshot
) -> tuple[list[dict[str, Any]], Counter[str]]:
    works = {
        record.record_id: record
        for record in records
        if isinstance(record, ScholarlyWork)
    }
    source_versions = sorted(
        (
            record
            for record in records
            if isinstance(record, SourceVersion)
            and record.record_id in snapshot.source_version_ids
        ),
        key=lambda record: record.record_id,
    )
    rows: list[dict[str, Any]] = []
    excluded: Counter[str] = Counter()
    for source in source_versions:
        work = works.get(source.work_id)
        if not _active(source):
            excluded["source_version_not_active"] += 1
        elif source.temporal_eligibility is not TemporalEligibility.ELIGIBLE:
            excluded[f"temporal_{source.temporal_eligibility.value}"] += 1
        elif source.lifecycle_status not in _ALLOWED_PAPER_LIFECYCLES:
            excluded[f"lifecycle_{source.lifecycle_status.value}"] += 1
        elif work is None:
            excluded["missing_scholarly_work"] += 1
        elif not _active(work):
            excluded["scholarly_work_not_active"] += 1
        else:
            identifier_uris = tuple(
                sorted(
                    {
                        identifier.uri
                        for identifier in (*work.identifiers, *source.version_identifiers)
                        if identifier.uri
                    }
                )
            )
            semantic_parts = [source.title.strip()]
            if source.abstract and source.abstract.strip():
                semantic_parts.append(source.abstract.strip())
            rows.append(
                {
                    "point_id": source.record_id,
                    "title": source.title,
                    "semantic": "\n\n".join(semantic_parts),
                    "work_id": work.record_id,
                    "source_version_id": source.record_id,
                    "work_kind": work.work_kind.value,
                    "source_type": source.source_type,
                    "lifecycle_status": source.lifecycle_status.value,
                    "publication_date": (
                        source.publication_date.value
                        if source.publication_date is not None
                        else None
                    ),
                    "availability_date": (
                        source.availability_earliest.value
                        if source.availability_earliest is not None
                        else None
                    ),
                    "venue": source.venue,
                    "identifiers": identifier_uris,
                    "snapshot_id": snapshot.record_id,
                    "snapshot_as_of": snapshot.as_of,
                    "paper_scope": "not_available_per_paper_in_contract_v1",
                }
            )
    return rows, excluded


def _claim_rows(
    records: Sequence[RecordEnvelope], snapshot: CorpusSnapshot
) -> tuple[list[dict[str, Any]], Counter[str]]:
    claims = {
        record.record_id: record for record in records if isinstance(record, Claim)
    }
    sources = {
        record.record_id: record
        for record in records
        if isinstance(record, SourceVersion)
    }
    entities = {
        record.record_id: record for record in records if isinstance(record, Entity)
    }
    all_evidence: dict[str, list[ClaimEvidence]] = defaultdict(list)
    for record in records:
        if isinstance(record, ClaimEvidence):
            all_evidence[record.claim_id].append(record)

    rows: list[dict[str, Any]] = []
    excluded: Counter[str] = Counter()
    for claim_id in sorted(claims):
        claim = claims[claim_id]
        evidence = all_evidence.get(claim_id, [])
        eligible_evidence = sorted(
            (
                item
                for item in evidence
                if _active(item)
                and item.verification_outcome in _ALLOWED_CLAIM_OUTCOMES
            ),
            key=lambda item: item.record_id,
        )
        source = sources.get(claim.source_version_id or "")
        if not _active(claim):
            excluded["claim_not_active"] += 1
        elif claim.source_version_id is None:
            excluded["claim_without_source_version"] += 1
        elif source is None:
            excluded["missing_source_version"] += 1
        elif source.record_id not in snapshot.source_version_ids:
            excluded["source_version_outside_snapshot"] += 1
        elif not _active(source):
            excluded["source_version_not_active"] += 1
        elif source.temporal_eligibility is not TemporalEligibility.ELIGIBLE:
            excluded[f"temporal_{source.temporal_eligibility.value}"] += 1
        elif source.lifecycle_status not in _ALLOWED_PAPER_LIFECYCLES:
            excluded[f"lifecycle_{source.lifecycle_status.value}"] += 1
        elif not eligible_evidence:
            if evidence:
                statuses = sorted(
                    {item.verification_outcome.value for item in evidence}
                )
                excluded[f"unverified_outcomes:{','.join(statuses)}"] += 1
            else:
                excluded["missing_claim_evidence"] += 1
        else:
            passage_ids = tuple(
                sorted(
                    {
                        span.passage_id
                        for item in eligible_evidence
                        for span in item.passage_spans
                    }
                )
            )
            outcomes = tuple(
                sorted({item.verification_outcome.value for item in eligible_evidence})
            )
            rows.append(
                {
                    "point_id": claim.record_id,
                    "title": claim.claim_text,
                    "semantic": claim.claim_text,
                    "verification_outcomes": outcomes,
                    "claim_type": claim.claim_type.value,
                    "direction": claim.direction.value,
                    "source_version_id": source.record_id,
                    "claim_evidence_ids": tuple(
                        item.record_id for item in eligible_evidence
                    ),
                    "passage_ids": passage_ids,
                    "population": _entity_names(
                        claim.population_entity_ids, entities
                    ),
                    "method": _entity_names(claim.method_entity_ids, entities),
                    "outcome": _entity_names(claim.outcome_entity_ids, entities),
                    "verified_at": max(
                        item.verified_at for item in eligible_evidence
                    ),
                    "snapshot_id": snapshot.record_id,
                }
            )
    return rows, excluded


def _gap_rows(
    records: Sequence[RecordEnvelope], snapshot: CorpusSnapshot
) -> tuple[list[dict[str, Any]], Counter[str]]:
    attempts = {
        record.record_id: record
        for record in records
        if isinstance(record, VerificationAttempt)
    }
    scores: dict[str, list[GapScore]] = defaultdict(list)
    for record in records:
        if isinstance(record, GapScore) and _active(record):
            scores[record.gap_candidate_id].append(record)

    candidates = sorted(
        (record for record in records if isinstance(record, GapCandidate)),
        key=lambda record: record.record_id,
    )
    rows: list[dict[str, Any]] = []
    excluded: Counter[str] = Counter()
    for candidate in candidates:
        decisive = attempts.get(candidate.decisive_verification_attempt_id or "")
        matching_scores = [
            score
            for score in scores.get(candidate.record_id, [])
            if score.candidate_gap_status is GapStatus.VERIFIED_OPEN
        ]
        if not _active(candidate):
            excluded["gap_candidate_not_active"] += 1
        elif candidate.gap_status is not GapStatus.VERIFIED_OPEN:
            excluded[f"gap_status_{candidate.gap_status.value}"] += 1
        elif decisive is None:
            excluded["missing_decisive_verification"] += 1
        elif not _active(decisive):
            excluded["decisive_verification_not_active"] += 1
        elif decisive.attempt_status is not VerificationAttemptStatus.COMPLETED:
            excluded["decisive_verification_not_completed"] += 1
        elif decisive.resulting_gap_status is not GapStatus.VERIFIED_OPEN:
            excluded["decisive_verification_result_not_open"] += 1
        elif decisive.completed_at is None:
            excluded["decisive_verification_missing_completion"] += 1
        elif decisive.unresolved_check_ids:
            excluded["decisive_verification_has_unresolved_checks"] += 1
        elif not decisive.counterretrieval_ids or not decisive.retrieval_query_log_ids:
            excluded["missing_counterretrieval_provenance"] += 1
        elif not matching_scores:
            excluded["missing_verified_open_gap_score"] += 1
        elif len(matching_scores) > 1:
            excluded["ambiguous_verified_open_gap_scores"] += 1
        else:
            score = matching_scores[0]
            rows.append(
                {
                    "point_id": candidate.record_id,
                    "title": candidate.title,
                    "semantic": "\n\n".join(
                        (
                            candidate.statement,
                            candidate.rationale,
                            candidate.research_question,
                        )
                    ),
                    "gap_type": candidate.gap_type_id,
                    "gap_status": candidate.gap_status.value,
                    "research_question": candidate.research_question,
                    "novelty_score": score.novelty.score,
                    "novelty_scale_min": score.novelty.scale_min,
                    "novelty_scale_max": score.novelty.scale_max,
                    "novelty_uncertainty": score.novelty.uncertainty,
                    "importance_score": score.importance.score,
                    "importance_scale_min": score.importance.scale_min,
                    "importance_scale_max": score.importance.scale_max,
                    "importance_uncertainty": score.importance.uncertainty,
                    "feasibility_score": score.feasibility.score,
                    "feasibility_scale_min": score.feasibility.scale_min,
                    "feasibility_scale_max": score.feasibility.scale_max,
                    "feasibility_uncertainty": score.feasibility.uncertainty,
                    "score_calibration_status": score.calibration_status.value,
                    "coverage_status": candidate.coverage_status.value,
                    "supporting_claim_ids": candidate.supporting_claim_ids,
                    "decisive_verification_attempt_id": decisive.record_id,
                    "verification_completed_at": decisive.completed_at,
                    "counterevidence_ids": tuple(
                        sorted(
                            {
                                *decisive.counterclaim_evidence_ids,
                                *decisive.refuting_evidence_ids,
                            }
                        )
                    ),
                    "counterretrieval_ids": decisive.counterretrieval_ids,
                    "retrieval_query_log_ids": decisive.retrieval_query_log_ids,
                    "uncertainty_reasons": candidate.uncertainty_reasons,
                    "as_of": candidate.as_of,
                    "snapshot_id": snapshot.record_id,
                }
            )
    return rows, excluded


def _source_value(row: Mapping[str, Any], path: str) -> Any:
    value: Any = row
    for part in path.split("."):
        if not isinstance(value, Mapping) or part not in value:
            raise ValidationError(
                f"Mantis projection source path {path!r} is absent."
            )
        value = value[part]
    return value


def _scalar(value: Any) -> str | int | float:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, str | int | float):
        return value
    if isinstance(value, Mapping):
        return canonical_json(value)
    raise ValidationError(f"Unsupported Mantis scalar value: {type(value).__name__}.")


def _format_value(value: Any, field: Any, profile: MantisExportProfile) -> Any:
    empty = value is None or value == "" or value == () or value == []
    if empty:
        if field.required or field.null_policy is MantisNullPolicy.ERROR:
            raise ValidationError(
                f"Required Mantis field {field.output_name!r} is empty."
            )
        if field.null_policy is MantisNullPolicy.SENTINEL:
            return profile.csv_policy.get("null_sentinel", "")
        return ""

    if isinstance(value, Sequence) and not isinstance(value, str | bytes):
        items = list(value)
        policy = field.multivalue_policy
        if policy is MantisMultivaluePolicy.ERROR:
            if len(items) != 1:
                raise ValidationError(
                    f"Mantis field {field.output_name!r} received {len(items)} "
                    "values under the error policy."
                )
            return _scalar(items[0])
        if policy is MantisMultivaluePolicy.FIRST:
            return _scalar(items[0])
        if policy is MantisMultivaluePolicy.JSON:
            return canonical_json(items)
        separator = field.separator or ""
        return separator.join(str(_scalar(item)) for item in items)
    return _scalar(value)


def _apply_profile(
    source_rows: Sequence[Mapping[str, Any]], profile: MantisExportProfile
) -> list[dict[str, Any]]:
    projected: list[dict[str, Any]] = []
    point_ids: set[str] = set()
    for source in source_rows:
        point_id = str(_source_value(source, profile.point_id_source_path))
        if point_id in point_ids:
            raise ValidationError(f"Duplicate Mantis point_id {point_id!r}.")
        point_ids.add(point_id)
        projected.append(
            {
                field.output_name: _format_value(
                    _source_value(source, field.source_path), field, profile
                )
                for field in profile.fields
            }
        )
    return sorted(
        projected,
        key=lambda row: tuple(str(row[path]) for path in profile.row_sort_paths),
    )


def project_records(
    records: Sequence[RecordEnvelope], profile: MantisExportProfile
) -> ProjectionResult:
    """Validate and project one complete record collection under one profile."""
    materialized = tuple(records)
    require_record_integrity(
        validate_record_collection(materialized, verify_local_artifacts=False)
    )
    snapshot = _exact_snapshot(materialized)
    if profile.corpus_snapshot_id != snapshot.record_id:
        raise ValidationError(
            "Mantis profile snapshot does not match its source collection."
        )
    if profile.record_kind is MantisRecordKind.PAPER:
        source_rows, exclusions = _paper_rows(materialized, snapshot)
    elif profile.record_kind is MantisRecordKind.VERIFIED_CLAIM:
        source_rows, exclusions = _claim_rows(materialized, snapshot)
    else:
        source_rows, exclusions = _gap_rows(materialized, snapshot)
    rows = _apply_profile(source_rows, profile)
    report = {
        "report_schema_version": "1.0.0",
        "record_kind": profile.record_kind.value,
        "profile_id": profile.record_id,
        "profile_version": profile.profile_version,
        "compatibility_version": profile.compatibility_version,
        "corpus_snapshot_id": snapshot.record_id,
        "snapshot_as_of": snapshot.as_of,
        "eligible_row_count": len(rows),
        "excluded_record_count": sum(exclusions.values()),
        "exclusion_reasons": dict(sorted(exclusions.items())),
        "columns": [field.output_name for field in profile.fields],
        "mantis_types": {
            field.output_name: field.mantis_type.value for field in profile.fields
        },
        "connection_fields_enabled": profile.connection_compatibility_verified,
        "limitations": (
            [
                "Per-paper inclusion/exclusion reasons are not durable in "
                "record contract v1; the snapshot scope remains authoritative."
            ]
            if profile.record_kind is MantisRecordKind.PAPER
            else []
        ),
    }
    return ProjectionResult(profile=profile, rows=tuple(rows), report=report)


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _write_csv(
    path: Path, rows: Sequence[Mapping[str, Any]], profile: MantisExportProfile
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = [field.output_name for field in profile.fields]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=fields,
            lineterminator=str(profile.csv_policy.get("line_terminator", "\n")),
        )
        writer.writeheader()
        writer.writerows(rows)


def export_mantis_views(
    records_path: Path,
    output_directory: Path,
    *,
    producing_run_id: str,
    created_at: str,
    profile_directory: Path = DEFAULT_PROFILE_DIRECTORY,
) -> tuple[ExportedView, ...]:
    """Materialize all three audited Mantis views from one record artifact."""
    records = read_record_jsonl(records_path)
    snapshot = _exact_snapshot(records)
    source_sha256 = _file_sha256(records_path)
    outputs: list[ExportedView] = []
    for kind in MantisRecordKind:
        template_path = profile_directory / f"{kind.value}_v1.yaml"
        profile = compile_profile(
            load_profile_template(template_path),
            ProfileContext(
                corpus_snapshot_id=snapshot.record_id,
                producing_run_id=producing_run_id,
                created_at=created_at,
            ),
        )
        result = project_records(records, profile)
        prefix = f"mantis_{kind.value}_v1"
        csv_path = output_directory / f"{prefix}.csv"
        profile_path = output_directory / f"{prefix}.profile.json"
        report_path = output_directory / f"{prefix}.report.json"
        _write_csv(csv_path, result.rows, profile)
        profile_payload = record_to_dict(profile)
        _write_json(profile_path, profile_payload)
        report = {
            **result.report,
            "source_artifact": str(records_path),
            "source_sha256": source_sha256,
            "profile_sha256": _file_sha256(profile_path),
            "csv_sha256": _file_sha256(csv_path),
        }
        _write_json(report_path, report)
        outputs.append(
            ExportedView(
                record_kind=kind.value,
                csv_path=csv_path,
                profile_path=profile_path,
                report_path=report_path,
                row_count=len(result.rows),
            )
        )
    return tuple(outputs)
