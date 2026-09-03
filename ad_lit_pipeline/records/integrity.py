from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from enum import Enum
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlsplit

from ad_lit_pipeline.core.errors import ValidationError
from ad_lit_pipeline.records import models as m
from ad_lit_pipeline.records.ids import canonical_json, record_type_from_id
from ad_lit_pipeline.records.serialization import record_from_dict, record_to_dict
from ad_lit_pipeline.records.validation import validate_record


SUPPORTED_TEXT_STRUCTURE_SCHEMA_VERSIONS = frozenset({"1.0.0"})


class IntegritySeverity(str, Enum):
    ERROR = "error"
    WARNING = "warning"


@dataclass(frozen=True, kw_only=True)
class IntegrityIssue:
    severity: IntegritySeverity
    code: str
    message: str
    record_id: str | None
    record_type: str | None
    field_path: str | None
    artifact_path: str | None
    line_number: int | None


@dataclass(frozen=True, kw_only=True)
class IntegrityReport:
    records_checked: int
    record_artifacts_checked: int
    local_files_verified: int
    issues: tuple[IntegrityIssue, ...]

    @property
    def errors(self) -> tuple[IntegrityIssue, ...]:
        return tuple(
            issue
            for issue in self.issues
            if issue.severity is IntegritySeverity.ERROR
        )

    @property
    def warnings(self) -> tuple[IntegrityIssue, ...]:
        return tuple(
            issue
            for issue in self.issues
            if issue.severity is IntegritySeverity.WARNING
        )

    @property
    def is_valid(self) -> bool:
        return not self.errors

    def to_dict(self) -> dict[str, Any]:
        return {
            "records_checked": self.records_checked,
            "record_artifacts_checked": self.record_artifacts_checked,
            "local_files_verified": self.local_files_verified,
            "is_valid": self.is_valid,
            "error_count": len(self.errors),
            "warning_count": len(self.warnings),
            "issues": [
                {
                    "severity": issue.severity.value,
                    "code": issue.code,
                    "message": issue.message,
                    "record_id": issue.record_id,
                    "record_type": issue.record_type,
                    "field_path": issue.field_path,
                    "artifact_path": issue.artifact_path,
                    "line_number": issue.line_number,
                }
                for issue in self.issues
            ],
        }


class RecordIntegrityError(ValidationError):
    """Raised by strict helpers while retaining the structured report."""

    def __init__(self, report: IntegrityReport) -> None:
        self.report = report
        first = report.errors[0] if report.errors else None
        detail = first.message if first is not None else "unknown integrity error"
        super().__init__(
            f"Record collection failed integrity validation with "
            f"{len(report.errors)} error(s): {detail}"
        )


@dataclass(frozen=True, kw_only=True)
class RecordOccurrence:
    record: m.RecordEnvelope
    artifact_path: str | None = None
    line_number: int | None = None


@dataclass(frozen=True)
class _Reference:
    target_id: str
    expected_type: str
    field_path: str
    allow_cross_snapshot: bool = False


def _issue_sort_key(issue: IntegrityIssue) -> tuple[Any, ...]:
    severity_order = 0 if issue.severity is IntegritySeverity.ERROR else 1
    return (
        severity_order,
        issue.artifact_path or "",
        issue.line_number or 0,
        issue.record_type or "",
        issue.record_id or "",
        issue.field_path or "",
        issue.code,
        issue.message,
    )


class _IssueCollector:
    def __init__(self) -> None:
        self.issues: list[IntegrityIssue] = []

    def add(
        self,
        severity: IntegritySeverity,
        code: str,
        message: str,
        *,
        occurrence: RecordOccurrence | None = None,
        field_path: str | None = None,
        artifact_path: str | None = None,
        line_number: int | None = None,
    ) -> None:
        record = occurrence.record if occurrence is not None else None
        self.issues.append(
            IntegrityIssue(
                severity=severity,
                code=code,
                message=message,
                record_id=record.record_id if record is not None else None,
                record_type=record.RECORD_TYPE if record is not None else None,
                field_path=field_path,
                artifact_path=(
                    occurrence.artifact_path
                    if occurrence is not None
                    else artifact_path
                ),
                line_number=(
                    occurrence.line_number
                    if occurrence is not None
                    else line_number
                ),
            )
        )

    def error(
        self,
        code: str,
        message: str,
        *,
        occurrence: RecordOccurrence | None = None,
        field_path: str | None = None,
        artifact_path: str | None = None,
        line_number: int | None = None,
    ) -> None:
        self.add(
            IntegritySeverity.ERROR,
            code,
            message,
            occurrence=occurrence,
            field_path=field_path,
            artifact_path=artifact_path,
            line_number=line_number,
        )

    def warning(
        self,
        code: str,
        message: str,
        *,
        occurrence: RecordOccurrence | None = None,
        field_path: str | None = None,
    ) -> None:
        self.add(
            IntegritySeverity.WARNING,
            code,
            message,
            occurrence=occurrence,
            field_path=field_path,
        )


def _refs(
    values: Sequence[str],
    expected_type: str,
    field_path: str,
    *,
    allow_cross_snapshot: bool = False,
) -> list[_Reference]:
    return [
        _Reference(
            target_id=value,
            expected_type=expected_type,
            field_path=f"{field_path}[{index}]",
            allow_cross_snapshot=allow_cross_snapshot,
        )
        for index, value in enumerate(values)
    ]


def _generic_refs(
    values: Sequence[str],
    field_path: str,
    *,
    allow_cross_targets: frozenset[str] = frozenset(),
) -> list[_Reference]:
    return [
        _Reference(
            target_id=value,
            expected_type=record_type_from_id(value),
            field_path=f"{field_path}[{index}]",
            allow_cross_snapshot=value in allow_cross_targets,
        )
        for index, value in enumerate(values)
    ]


def _type_specific_references(record: m.RecordEnvelope) -> list[_Reference]:
    references: list[_Reference] = []

    if isinstance(record, m.CorpusSnapshot):
        references.extend(
            _refs(record.source_version_ids, "source_version", "source_version_ids")
        )
        references.extend(
            _refs(
                record.provider_record_ids,
                "provider_record",
                "provider_record_ids",
            )
        )
    elif isinstance(record, m.SourceVersion):
        references.append(_Reference(record.work_id, "scholarly_work", "work_id"))
        references.extend(
            _refs(
                record.study_design_entity_ids,
                "entity",
                "study_design_entity_ids",
            )
        )
        references.extend(
            _refs(
                record.previous_source_version_ids,
                "source_version",
                "previous_source_version_ids",
                allow_cross_snapshot=True,
            )
        )
        references.extend(
            _refs(
                record.provider_record_ids,
                "provider_record",
                "provider_record_ids",
            )
        )
    elif isinstance(record, m.AccessLocation):
        references.append(
            _Reference(record.source_version_id, "source_version", "source_version_id")
        )
        if record.provider_record_id is not None:
            references.append(
                _Reference(
                    record.provider_record_id,
                    "provider_record",
                    "provider_record_id",
                )
            )
    elif isinstance(record, m.Document):
        references.extend(
            (
                _Reference(
                    record.source_version_id,
                    "source_version",
                    "source_version_id",
                ),
                _Reference(
                    record.access_location_id,
                    "access_location",
                    "access_location_id",
                ),
            )
        )
    elif isinstance(record, m.Passage):
        references.extend(
            (
                _Reference(record.document_id, "document", "document_id"),
                _Reference(
                    record.source_version_id,
                    "source_version",
                    "source_version_id",
                ),
            )
        )
    elif isinstance(record, m.Entity):
        if record.canonical_entity_id is not None:
            references.append(
                _Reference(
                    record.canonical_entity_id,
                    "entity",
                    "canonical_entity_id",
                    allow_cross_snapshot=True,
                )
            )
        references.extend(
            _refs(record.source_passage_ids, "passage", "source_passage_ids")
        )
    elif isinstance(record, m.Claim):
        if record.source_version_id is not None:
            references.append(
                _Reference(
                    record.source_version_id,
                    "source_version",
                    "source_version_id",
                )
            )
        references.extend(_refs(record.source_claim_ids, "claim", "source_claim_ids"))
        for field_path in (
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
        ):
            references.extend(
                _refs(getattr(record, field_path), "entity", field_path)
            )
    elif isinstance(record, m.ClaimEvidence):
        references.extend(
            (
                _Reference(record.claim_id, "claim", "claim_id"),
                _Reference(
                    record.source_version_id,
                    "source_version",
                    "source_version_id",
                ),
            )
        )
        references.extend(
            _refs(
                tuple(span.passage_id for span in record.passage_spans),
                "passage",
                "passage_spans",
            )
        )
        references.extend(
            _refs(
                record.checked_passage_ids,
                "passage",
                "checked_passage_ids",
            )
        )
        if record.counterclaim_id is not None:
            references.append(
                _Reference(record.counterclaim_id, "claim", "counterclaim_id")
            )
    elif isinstance(record, m.Relationship):
        references.extend(
            (
                _Reference(
                    record.subject_id,
                    record.subject_type.value,
                    "subject_id",
                ),
                _Reference(
                    record.object_id,
                    record.object_type.value,
                    "object_id",
                ),
            )
        )
        references.extend(
            _refs(
                record.claim_evidence_ids,
                "claim_evidence",
                "claim_evidence_ids",
            )
        )
        references.extend(_refs(record.passage_ids, "passage", "passage_ids"))
    elif isinstance(record, m.GapSignal):
        references.extend(
            _refs(record.supporting_claim_ids, "claim", "supporting_claim_ids")
        )
        references.extend(
            _refs(
                record.supporting_passage_ids,
                "passage",
                "supporting_passage_ids",
            )
        )
        references.extend(
            _refs(record.relationship_ids, "relationship", "relationship_ids")
        )
        references.extend(
            _refs(
                record.checked_source_version_ids,
                "source_version",
                "checked_source_version_ids",
            )
        )
        references.extend(
            _refs(
                record.source_interpretation_ids,
                "mantis_interpretation",
                "source_interpretation_ids",
            )
        )
    elif isinstance(record, m.GapCandidate):
        if record.supersedes_candidate_id is not None:
            references.append(
                _Reference(
                    record.supersedes_candidate_id,
                    "gap_candidate",
                    "supersedes_candidate_id",
                    allow_cross_snapshot=True,
                )
            )
        references.extend(_refs(record.signal_ids, "gap_signal", "signal_ids"))
        references.extend(
            _refs(record.supporting_claim_ids, "claim", "supporting_claim_ids")
        )
        references.extend(
            _refs(
                record.verification_attempt_ids,
                "verification_attempt",
                "verification_attempt_ids",
            )
        )
        for index, transition in enumerate(record.state_history):
            if transition.verification_attempt_id is not None:
                references.append(
                    _Reference(
                        transition.verification_attempt_id,
                        "verification_attempt",
                        f"state_history[{index}].verification_attempt_id",
                    )
                )
        if record.decisive_verification_attempt_id is not None:
            references.append(
                _Reference(
                    record.decisive_verification_attempt_id,
                    "verification_attempt",
                    "decisive_verification_attempt_id",
                )
            )
        if record.canonical_gap_id is not None:
            references.append(
                _Reference(
                    record.canonical_gap_id,
                    "gap_candidate",
                    "canonical_gap_id",
                )
            )
    elif isinstance(record, m.VerificationAttempt):
        references.append(
            _Reference(
                record.gap_candidate_id,
                "gap_candidate",
                "gap_candidate_id",
            )
        )
        for index, check in enumerate(record.checks):
            references.extend(
                _generic_refs(check.evidence_ids, f"checks[{index}].evidence_ids")
            )
        references.extend(
            _refs(
                record.supporting_claim_evidence_ids,
                "claim_evidence",
                "supporting_claim_evidence_ids",
            )
        )
        references.extend(
            _refs(
                record.counterclaim_evidence_ids,
                "claim_evidence",
                "counterclaim_evidence_ids",
            )
        )
        references.extend(
            _refs(
                record.checked_passage_ids,
                "passage",
                "checked_passage_ids",
            )
        )
        references.extend(
            _generic_refs(record.refuting_evidence_ids, "refuting_evidence_ids")
        )
        references.extend(
            _generic_refs(record.resolving_evidence_ids, "resolving_evidence_ids")
        )
        references.extend(
            _refs(
                record.expert_judgment_ids,
                "expert_judgment",
                "expert_judgment_ids",
            )
        )
        if record.canonical_gap_id is not None:
            references.append(
                _Reference(
                    record.canonical_gap_id,
                    "gap_candidate",
                    "canonical_gap_id",
                )
            )
        references.extend(
            _generic_refs(record.artifact_basis_ids, "artifact_basis_ids")
        )
    elif isinstance(record, m.GapScore):
        references.append(
            _Reference(
                record.gap_candidate_id,
                "gap_candidate",
                "gap_candidate_id",
            )
        )
        for field_path in ("novelty", "importance", "feasibility", "composite"):
            score = getattr(record, field_path)
            if score is not None:
                references.extend(
                    _generic_refs(score.evidence_ids, f"{field_path}.evidence_ids")
                )
        references.extend(
            _refs(
                record.expert_judgment_ids,
                "expert_judgment",
                "expert_judgment_ids",
            )
        )
    elif isinstance(record, m.ExpertJudgment):
        references.append(
            _Reference(
                record.gap_candidate_id,
                "gap_candidate",
                "gap_candidate_id",
            )
        )
        references.extend(
            _generic_refs(record.presented_artifact_ids, "presented_artifact_ids")
        )
        if record.mantis_profile_id is not None:
            references.append(
                _Reference(
                    record.mantis_profile_id,
                    "mantis_export_profile",
                    "mantis_profile_id",
                )
            )
        if record.mantis_receipt_id is not None:
            references.append(
                _Reference(
                    record.mantis_receipt_id,
                    "mantis_publication_receipt",
                    "mantis_receipt_id",
                )
            )
        references.extend(
            _generic_refs(record.known_evidence_ids, "known_evidence_ids")
        )
        if record.canonical_gap_id is not None:
            references.append(
                _Reference(
                    record.canonical_gap_id,
                    "gap_candidate",
                    "canonical_gap_id",
                )
            )
        if record.supersedes_judgment_id is not None:
            references.append(
                _Reference(
                    record.supersedes_judgment_id,
                    "expert_judgment",
                    "supersedes_judgment_id",
                    allow_cross_snapshot=True,
                )
            )
    elif isinstance(record, m.OutcomeEvent):
        references.append(
            _Reference(
                record.gap_candidate_id,
                "gap_candidate",
                "gap_candidate_id",
                allow_cross_snapshot=True,
            )
        )
        references.extend(
            _refs(
                record.expert_judgment_ids,
                "expert_judgment",
                "expert_judgment_ids",
                allow_cross_snapshot=True,
            )
        )
        references.extend(
            _generic_refs(
                record.source_reference_ids,
                "source_reference_ids",
                allow_cross_targets=frozenset(record.source_reference_ids),
            )
        )
        if record.corrects_event_id is not None:
            references.append(
                _Reference(
                    record.corrects_event_id,
                    "outcome_event",
                    "corrects_event_id",
                    allow_cross_snapshot=True,
                )
            )
    elif isinstance(record, m.MantisInterpretation):
        references.extend(
            _generic_refs(record.selected_point_ids, "selected_point_ids")
        )
        references.extend(
            _refs(
                record.independent_signal_ids,
                "gap_signal",
                "independent_signal_ids",
            )
        )
        references.extend(
            _refs(
                record.created_candidate_ids,
                "gap_candidate",
                "created_candidate_ids",
            )
        )
        references.append(
            _Reference(
                record.publication_receipt_id,
                "mantis_publication_receipt",
                "publication_receipt_id",
            )
        )
    elif isinstance(record, m.MantisPublicationReceipt):
        references.append(
            _Reference(
                record.export_profile_id,
                "mantis_export_profile",
                "export_profile_id",
                allow_cross_snapshot=True,
            )
        )
        if record.retry_of_receipt_id is not None:
            references.append(
                _Reference(
                    record.retry_of_receipt_id,
                    "mantis_publication_receipt",
                    "retry_of_receipt_id",
                    allow_cross_snapshot=True,
                )
            )

    return references


def _all_references(record: m.RecordEnvelope) -> tuple[_Reference, ...]:
    references = _type_specific_references(record)
    allowed_cross_targets = frozenset(
        reference.target_id
        for reference in references
        if reference.allow_cross_snapshot
    )

    if record.RECORD_TYPE != "corpus_snapshot":
        references.append(
            _Reference(
                record.corpus_snapshot_id,
                "corpus_snapshot",
                "corpus_snapshot_id",
            )
        )
    references.extend(
        _generic_refs(
            record.parent_record_ids,
            "parent_record_ids",
            allow_cross_targets=allowed_cross_targets,
        )
    )
    references.extend(
        _generic_refs(
            record.source_record_ids,
            "source_record_ids",
            allow_cross_targets=allowed_cross_targets,
        )
    )
    for index, provenance in enumerate(record.provenance):
        if provenance.kind is m.ProvenanceKind.RECORD:
            references.append(
                _Reference(
                    provenance.reference,
                    record_type_from_id(provenance.reference),
                    f"provenance[{index}].reference",
                    allow_cross_snapshot=(
                        provenance.reference in allowed_cross_targets
                    ),
                )
            )
    return tuple(references)


def _utc(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _full_date(value: str) -> date:
    return date.fromisoformat(value)


def _partial_date_lower(value: m.PartialDate | None) -> date | None:
    if value is None or value.value is None:
        return None
    raw = value.value
    if value.precision is m.PartialDatePrecision.YEAR:
        raw += "-01-01"
    elif value.precision is m.PartialDatePrecision.MONTH:
        raw += "-01"
    return date.fromisoformat(raw)


def _partial_date_upper(value: m.PartialDate | None) -> date | None:
    if value is None or value.value is None:
        return None
    raw = value.value
    if value.precision is m.PartialDatePrecision.DAY:
        return date.fromisoformat(raw)
    if value.precision is m.PartialDatePrecision.YEAR:
        return date(int(raw), 12, 31)
    year, month = (int(part) for part in raw.split("-"))
    if month == 12:
        return date(year, 12, 31)
    return date.fromordinal(
        date(year, month + 1, 1).toordinal() - 1
    )


def _detect_cycles(
    edges: Mapping[str, Sequence[str]],
    *,
    code: str,
    field_path: str,
    index: Mapping[str, RecordOccurrence],
    collector: _IssueCollector,
) -> None:
    state: dict[str, int] = {}
    stack: list[str] = []
    reported: set[frozenset[str]] = set()

    def visit(node: str) -> None:
        state[node] = 1
        stack.append(node)
        for target in edges.get(node, ()):
            if target not in index:
                continue
            target_state = state.get(target, 0)
            if target_state == 0:
                visit(target)
            elif target_state == 1:
                start = stack.index(target)
                cycle = tuple(stack[start:] + [target])
                key = frozenset(cycle)
                if key not in reported:
                    reported.add(key)
                    collector.error(
                        code,
                        "Cycle detected: " + " -> ".join(cycle),
                        occurrence=index[node],
                        field_path=field_path,
                    )
        stack.pop()
        state[node] = 2

    for node in sorted(edges):
        if state.get(node, 0) == 0:
            visit(node)


def _validate_reference_graph(
    occurrences: Sequence[RecordOccurrence],
    index: Mapping[str, RecordOccurrence],
    collector: _IssueCollector,
) -> None:
    for occurrence in occurrences:
        record = occurrence.record
        for reference in _all_references(record):
            target_occurrence = index.get(reference.target_id)
            if target_occurrence is None:
                collector.error(
                    "orphan_reference",
                    f"Referenced record {reference.target_id!r} does not exist.",
                    occurrence=occurrence,
                    field_path=reference.field_path,
                )
                continue
            target = target_occurrence.record
            if target.RECORD_TYPE != reference.expected_type:
                collector.error(
                    "wrong_reference_type",
                    f"Expected {reference.expected_type!r}, found "
                    f"{target.RECORD_TYPE!r} for {reference.target_id!r}.",
                    occurrence=occurrence,
                    field_path=reference.field_path,
                )
            if (
                target.corpus_snapshot_id != record.corpus_snapshot_id
                and not reference.allow_cross_snapshot
            ):
                collector.error(
                    "unauthorized_cross_snapshot_reference",
                    f"Reference crosses from snapshot "
                    f"{record.corpus_snapshot_id!r} to "
                    f"{target.corpus_snapshot_id!r} without an explicit "
                    "lineage, correction, reassessment, outcome, or retry rule.",
                    occurrence=occurrence,
                    field_path=reference.field_path,
                )


def _index_occurrences(
    occurrences: Sequence[RecordOccurrence],
    collector: _IssueCollector,
) -> dict[str, RecordOccurrence]:
    index: dict[str, RecordOccurrence] = {}
    canonical_payloads: dict[str, str] = {}
    for occurrence in occurrences:
        record = occurrence.record
        try:
            validate_record(record)
        except ValidationError as exc:
            collector.error(
                "invalid_local_record",
                str(exc),
                occurrence=occurrence,
            )
            continue
        payload = canonical_json(record_to_dict(record, validate=False))
        prior = index.get(record.record_id)
        if prior is None:
            index[record.record_id] = occurrence
            canonical_payloads[record.record_id] = payload
            continue
        if canonical_payloads[record.record_id] == payload:
            collector.error(
                "duplicate_record_id",
                f"Record ID {record.record_id!r} occurs more than once.",
                occurrence=occurrence,
                field_path="record_id",
            )
        else:
            collector.error(
                "record_id_payload_conflict",
                f"Record ID {record.record_id!r} has competing payloads.",
                occurrence=occurrence,
                field_path="record_id",
            )
    return index


def _validate_snapshot_closure(
    index: Mapping[str, RecordOccurrence],
    collector: _IssueCollector,
) -> None:
    snapshots = {
        record_id: occurrence
        for record_id, occurrence in index.items()
        if isinstance(occurrence.record, m.CorpusSnapshot)
    }
    for snapshot_id, snapshot_occurrence in snapshots.items():
        snapshot = snapshot_occurrence.record
        assert isinstance(snapshot, m.CorpusSnapshot)
        expected_source_versions = {
            record_id
            for record_id, occurrence in index.items()
            if isinstance(occurrence.record, m.SourceVersion)
            and occurrence.record.corpus_snapshot_id == snapshot_id
        }
        expected_provider_records = {
            record_id
            for record_id, occurrence in index.items()
            if isinstance(occurrence.record, m.ProviderRecord)
            and occurrence.record.corpus_snapshot_id == snapshot_id
        }
        declared_source_versions = set(snapshot.source_version_ids)
        declared_provider_records = set(snapshot.provider_record_ids)
        for missing_id in sorted(expected_source_versions - declared_source_versions):
            collector.error(
                "snapshot_membership_omission",
                f"Snapshot omits source version {missing_id!r} present in the collection.",
                occurrence=snapshot_occurrence,
                field_path="source_version_ids",
            )
        for missing_id in sorted(expected_provider_records - declared_provider_records):
            collector.error(
                "snapshot_membership_omission",
                f"Snapshot omits provider record {missing_id!r} present in the collection.",
                occurrence=snapshot_occurrence,
                field_path="provider_record_ids",
            )


def _target(
    index: Mapping[str, RecordOccurrence],
    record_id: str | None,
    expected_type: type[Any],
) -> Any | None:
    if record_id is None:
        return None
    occurrence = index.get(record_id)
    if occurrence is None or not isinstance(occurrence.record, expected_type):
        return None
    return occurrence.record


def _ownership_error(
    collector: _IssueCollector,
    occurrence: RecordOccurrence,
    field_path: str,
    message: str,
) -> None:
    collector.error(
        "ownership_mismatch",
        message,
        occurrence=occurrence,
        field_path=field_path,
    )


def _validate_ownership(
    occurrences: Sequence[RecordOccurrence],
    index: Mapping[str, RecordOccurrence],
    collector: _IssueCollector,
) -> None:
    for occurrence in occurrences:
        record = occurrence.record
        if record.record_id not in index:
            continue

        if isinstance(record, m.SourceVersion):
            if record.work_id not in record.parent_record_ids:
                _ownership_error(
                    collector,
                    occurrence,
                    "parent_record_ids",
                    "Source version must name its scholarly work as a parent.",
                )
            missing_providers = set(record.provider_record_ids) - set(
                record.source_record_ids
            )
            if missing_providers:
                _ownership_error(
                    collector,
                    occurrence,
                    "source_record_ids",
                    f"Provider records are not represented as sources: "
                    f"{sorted(missing_providers)}.",
                )

        elif isinstance(record, m.AccessLocation):
            if record.source_version_id not in record.parent_record_ids:
                _ownership_error(
                    collector,
                    occurrence,
                    "parent_record_ids",
                    "Access observation must name its source version as a parent.",
                )
            if (
                record.provider_record_id is not None
                and record.provider_record_id not in record.source_record_ids
            ):
                _ownership_error(
                    collector,
                    occurrence,
                    "source_record_ids",
                    "Access observation must name its provider record as a source.",
                )

        elif isinstance(record, m.Document):
            access = _target(index, record.access_location_id, m.AccessLocation)
            if access is not None and access.source_version_id != record.source_version_id:
                _ownership_error(
                    collector,
                    occurrence,
                    "source_version_id",
                    "Document and access location identify different source versions.",
                )
            if record.source_version_id not in record.parent_record_ids:
                _ownership_error(
                    collector,
                    occurrence,
                    "parent_record_ids",
                    "Document must name its source version as a parent.",
                )
            if record.access_location_id not in record.source_record_ids:
                _ownership_error(
                    collector,
                    occurrence,
                    "source_record_ids",
                    "Document must name its access observation as a source.",
                )

        elif isinstance(record, m.Passage):
            document = _target(index, record.document_id, m.Document)
            if document is not None and document.source_version_id != record.source_version_id:
                _ownership_error(
                    collector,
                    occurrence,
                    "source_version_id",
                    "Passage and document identify different source versions.",
                )
            if record.document_id not in record.parent_record_ids:
                _ownership_error(
                    collector,
                    occurrence,
                    "parent_record_ids",
                    "Passage must name its document as a parent.",
                )
            if record.source_version_id not in record.source_record_ids:
                _ownership_error(
                    collector,
                    occurrence,
                    "source_record_ids",
                    "Passage must name its source version as a source.",
                )

        elif isinstance(record, m.Entity):
            missing_passages = set(record.source_passage_ids) - set(
                record.source_record_ids
            )
            if missing_passages:
                _ownership_error(
                    collector,
                    occurrence,
                    "source_record_ids",
                    f"Entity omits source passages {sorted(missing_passages)}.",
                )

        elif isinstance(record, m.Claim):
            if (
                record.source_version_id is not None
                and record.source_version_id not in record.source_record_ids
            ):
                _ownership_error(
                    collector,
                    occurrence,
                    "source_record_ids",
                    "Source-anchored claim must retain its source version.",
                )

        elif isinstance(record, m.ClaimEvidence):
            claim = _target(index, record.claim_id, m.Claim)
            if (
                claim is not None
                and claim.source_version_id is not None
                and claim.source_version_id != record.source_version_id
            ):
                _ownership_error(
                    collector,
                    occurrence,
                    "source_version_id",
                    "Claim evidence and source-asserted claim identify different versions.",
                )
            if record.claim_id not in record.parent_record_ids:
                _ownership_error(
                    collector,
                    occurrence,
                    "parent_record_ids",
                    "Claim evidence must name its claim as a parent.",
                )
            passage_ids = {
                span.passage_id for span in record.passage_spans
            } | set(record.checked_passage_ids)
            missing_sources = passage_ids - set(record.source_record_ids)
            if missing_sources:
                _ownership_error(
                    collector,
                    occurrence,
                    "source_record_ids",
                    f"Claim evidence omits cited passages {sorted(missing_sources)}.",
                )
            for passage_id in sorted(passage_ids):
                passage = _target(index, passage_id, m.Passage)
                if (
                    passage is not None
                    and passage.source_version_id != record.source_version_id
                ):
                    _ownership_error(
                        collector,
                        occurrence,
                        "passage_spans",
                        f"Passage {passage_id!r} belongs to another source version.",
                    )

        elif isinstance(record, m.Relationship):
            missing_evidence = set(record.claim_evidence_ids) - set(
                record.source_record_ids
            )
            if missing_evidence:
                _ownership_error(
                    collector,
                    occurrence,
                    "source_record_ids",
                    f"Relationship omits claim evidence {sorted(missing_evidence)}.",
                )

        elif isinstance(record, m.GapSignal):
            scientific_sources = (
                set(record.supporting_claim_ids)
                | set(record.supporting_passage_ids)
            )
            missing_sources = scientific_sources - set(record.source_record_ids)
            if missing_sources:
                _ownership_error(
                    collector,
                    occurrence,
                    "source_record_ids",
                    f"Gap signal omits scientific sources {sorted(missing_sources)}.",
                )

        elif isinstance(record, m.VerificationAttempt):
            if record.gap_candidate_id not in record.parent_record_ids:
                _ownership_error(
                    collector,
                    occurrence,
                    "parent_record_ids",
                    "Verification attempt must name its candidate as a parent.",
                )

        elif isinstance(record, (m.GapScore, m.ExpertJudgment, m.OutcomeEvent)):
            if record.gap_candidate_id not in record.parent_record_ids:
                _ownership_error(
                    collector,
                    occurrence,
                    "parent_record_ids",
                    "Gap-derived record must name its candidate as a parent.",
                )

        elif isinstance(record, m.MantisPublicationReceipt):
            if record.export_profile_id not in record.parent_record_ids:
                _ownership_error(
                    collector,
                    occurrence,
                    "parent_record_ids",
                    "Publication receipt must name its export profile as a parent.",
                )


def _validate_evidence_spans(
    occurrences: Sequence[RecordOccurrence],
    index: Mapping[str, RecordOccurrence],
    collector: _IssueCollector,
) -> None:
    for occurrence in occurrences:
        record = occurrence.record
        if not isinstance(record, m.ClaimEvidence):
            continue
        for span_index, span in enumerate(record.passage_spans):
            passage = _target(index, span.passage_id, m.Passage)
            if passage is None:
                continue
            field_path = f"passage_spans[{span_index}]"
            if span.end_char > len(passage.text):
                collector.error(
                    "evidence_span_out_of_bounds",
                    f"Span ends at {span.end_char}, but passage length is "
                    f"{len(passage.text)}.",
                    occurrence=occurrence,
                    field_path=field_path,
                )
                continue
            quoted = passage.text[span.start_char : span.end_char]
            actual_hash = hashlib.sha256(quoted.encode("utf-8")).hexdigest()
            if actual_hash != span.quoted_text_sha256:
                collector.error(
                    "evidence_span_hash_mismatch",
                    f"Span hash {actual_hash!r} does not match recorded hash "
                    f"{span.quoted_text_sha256!r}.",
                    occurrence=occurrence,
                    field_path=f"{field_path}.quoted_text_sha256",
                )


def _validate_temporal_eligibility(
    occurrences: Sequence[RecordOccurrence],
    index: Mapping[str, RecordOccurrence],
    collector: _IssueCollector,
) -> None:
    for occurrence in occurrences:
        record = occurrence.record
        snapshot = _target(index, record.corpus_snapshot_id, m.CorpusSnapshot)
        if snapshot is not None:
            cutoff = _full_date(snapshot.as_of)
            dated_field: tuple[str, str] | None = None
            if isinstance(record, m.Relationship):
                dated_field = ("valid_as_of", record.valid_as_of)
            elif isinstance(record, (m.GapSignal, m.GapCandidate)):
                dated_field = ("as_of", record.as_of)
            if dated_field is not None and _full_date(dated_field[1]) > cutoff:
                collector.error(
                    "snapshot_cutoff_mismatch",
                    f"{dated_field[0]} {dated_field[1]!r} is later than snapshot "
                    f"cutoff {snapshot.as_of!r}.",
                    occurrence=occurrence,
                    field_path=dated_field[0],
                )
            if isinstance(record, m.ProviderRecord):
                retrieved = _utc(record.retrieved_at)
                if retrieved < _utc(snapshot.retrieval_started_at):
                    collector.error(
                        "chronology_mismatch",
                        "Provider retrieval precedes snapshot retrieval start.",
                        occurrence=occurrence,
                        field_path="retrieved_at",
                    )
                if (
                    snapshot.retrieval_completed_at is not None
                    and retrieved > _utc(snapshot.retrieval_completed_at)
                ):
                    collector.error(
                        "chronology_mismatch",
                        "Provider retrieval follows snapshot retrieval completion.",
                        occurrence=occurrence,
                        field_path="retrieved_at",
                    )
        if not isinstance(record, m.SourceVersion):
            continue
        if snapshot is None:
            continue
        cutoff = _full_date(snapshot.as_of)
        earliest = _partial_date_lower(record.availability_earliest)
        latest = _partial_date_upper(record.availability_latest)
        if record.temporal_eligibility is m.TemporalEligibility.ELIGIBLE:
            if earliest is None or latest is None or latest > cutoff:
                collector.error(
                    "temporal_eligibility_mismatch",
                    "Eligible source version is not known to be available on or "
                    "before the inclusive snapshot cutoff.",
                    occurrence=occurrence,
                    field_path="temporal_eligibility",
                )
        elif record.temporal_eligibility is m.TemporalEligibility.AFTER_CUTOFF:
            if earliest is None or earliest <= cutoff:
                collector.error(
                    "temporal_eligibility_mismatch",
                    "After-cutoff source version is not known to become available "
                    "after the inclusive snapshot cutoff.",
                    occurrence=occurrence,
                    field_path="temporal_eligibility",
                )


def _validate_dependency_chronology(
    occurrences: Sequence[RecordOccurrence],
    index: Mapping[str, RecordOccurrence],
    collector: _IssueCollector,
) -> None:
    for occurrence in occurrences:
        record = occurrence.record
        if isinstance(record, m.Document):
            access = _target(index, record.access_location_id, m.AccessLocation)
            if access is not None and _utc(record.retrieved_at) < _utc(
                access.observed_at
            ):
                collector.error(
                    "chronology_mismatch",
                    "Document retrieval precedes its access observation.",
                    occurrence=occurrence,
                    field_path="retrieved_at",
                )
        elif isinstance(record, m.Passage):
            document = _target(index, record.document_id, m.Document)
            if document is not None and _utc(record.extracted_at) < _utc(
                document.retrieved_at
            ):
                collector.error(
                    "chronology_mismatch",
                    "Passage extraction precedes document retrieval.",
                    occurrence=occurrence,
                    field_path="extracted_at",
                )
        elif isinstance(record, m.ClaimEvidence):
            passage_ids = {span.passage_id for span in record.passage_spans}
            passage_ids.update(record.checked_passage_ids)
            passage_times = [
                _utc(passage.extracted_at)
                for passage_id in passage_ids
                if (passage := _target(index, passage_id, m.Passage)) is not None
            ]
            if passage_times and _utc(record.verified_at) < max(passage_times):
                collector.error(
                    "chronology_mismatch",
                    "Claim verification precedes cited passage extraction.",
                    occurrence=occurrence,
                    field_path="verified_at",
                )
        elif isinstance(record, m.Relationship):
            evidence_times = [
                _utc(evidence.verified_at)
                for evidence_id in record.claim_evidence_ids
                if (
                    evidence := _target(index, evidence_id, m.ClaimEvidence)
                )
                is not None
            ]
            if evidence_times and _utc(record.asserted_at) < max(evidence_times):
                collector.error(
                    "chronology_mismatch",
                    "Relationship assertion precedes its claim-evidence verification.",
                    occurrence=occurrence,
                    field_path="asserted_at",
                )
        elif isinstance(record, m.ExpertJudgment):
            receipt = _target(
                index,
                record.mantis_receipt_id,
                m.MantisPublicationReceipt,
            )
            if (
                receipt is not None
                and receipt.published_at is not None
                and _utc(record.started_at) < _utc(receipt.published_at)
            ):
                collector.error(
                    "chronology_mismatch",
                    "Mantis-assisted judgment starts before map publication.",
                    occurrence=occurrence,
                    field_path="started_at",
                )
        elif isinstance(record, m.OutcomeEvent):
            candidate = _target(index, record.gap_candidate_id, m.GapCandidate)
            event_upper = _partial_date_upper(
                m.PartialDate(
                    value=record.occurred_on,
                    precision=record.date_precision,
                    certainty=m.PartialDateCertainty.EXACT,
                )
            )
            if (
                candidate is not None
                and event_upper is not None
                and event_upper < _full_date(candidate.as_of)
            ):
                collector.error(
                    "chronology_mismatch",
                    "Prospective outcome predates the candidate's evidence cutoff.",
                    occurrence=occurrence,
                    field_path="occurred_on",
                )


def _validate_source_version_lineage(
    occurrences: Sequence[RecordOccurrence],
    index: Mapping[str, RecordOccurrence],
    collector: _IssueCollector,
) -> None:
    edges: dict[str, tuple[str, ...]] = {}
    for occurrence in occurrences:
        record = occurrence.record
        if not isinstance(record, m.SourceVersion):
            continue
        edges[record.record_id] = record.previous_source_version_ids
        current_date = _partial_date_lower(record.availability_earliest)
        for previous_id in record.previous_source_version_ids:
            previous = _target(index, previous_id, m.SourceVersion)
            if previous is None:
                continue
            if previous.work_id != record.work_id:
                collector.error(
                    "source_version_lineage_mismatch",
                    "Source-version predecessor belongs to another scholarly work.",
                    occurrence=occurrence,
                    field_path="previous_source_version_ids",
                )
            previous_date = _partial_date_lower(previous.availability_earliest)
            if (
                current_date is not None
                and previous_date is not None
                and current_date < previous_date
            ):
                collector.error(
                    "chronology_mismatch",
                    "Source version becomes available before its predecessor.",
                    occurrence=occurrence,
                    field_path="availability_earliest",
                )
    _detect_cycles(
        edges,
        code="source_version_lineage_cycle",
        field_path="previous_source_version_ids",
        index=index,
        collector=collector,
    )


def _validate_gap_lineage(
    occurrences: Sequence[RecordOccurrence],
    index: Mapping[str, RecordOccurrence],
    collector: _IssueCollector,
) -> None:
    supersession_edges: dict[str, tuple[str, ...]] = {}
    canonical_edges: dict[str, tuple[str, ...]] = {}
    for occurrence in occurrences:
        record = occurrence.record
        if not isinstance(record, m.GapCandidate):
            continue
        supersession_edges[record.record_id] = (
            (record.supersedes_candidate_id,)
            if record.supersedes_candidate_id is not None
            else ()
        )
        canonical_edges[record.record_id] = (
            (record.canonical_gap_id,)
            if record.canonical_gap_id is not None
            else ()
        )
        predecessor = _target(
            index,
            record.supersedes_candidate_id,
            m.GapCandidate,
        )
        if predecessor is not None:
            if predecessor.gap_lineage_id != record.gap_lineage_id:
                collector.error(
                    "gap_lineage_mismatch",
                    "Superseded candidate has a different gap lineage ID.",
                    occurrence=occurrence,
                    field_path="supersedes_candidate_id",
                )
            if record.candidate_version != predecessor.candidate_version + 1:
                collector.error(
                    "gap_version_gap",
                    "Candidate version must increment its direct predecessor by one.",
                    occurrence=occurrence,
                    field_path="candidate_version",
                )
            if _full_date(record.as_of) < _full_date(predecessor.as_of):
                collector.error(
                    "chronology_mismatch",
                    "Reassessment cutoff precedes its predecessor cutoff.",
                    occurrence=occurrence,
                    field_path="as_of",
                )
            if record.state_history:
                declared_prior = record.state_history[0].from_gap_status
                if declared_prior is not predecessor.gap_status:
                    collector.error(
                        "gap_reassessment_state_mismatch",
                        f"Reassessment declares predecessor state "
                        f"{declared_prior.value!r}, but referenced predecessor is "
                        f"{predecessor.gap_status.value!r}.",
                        occurrence=occurrence,
                        field_path="state_history[0].from_gap_status",
                    )
        canonical = _target(index, record.canonical_gap_id, m.GapCandidate)
        if canonical is not None:
            if canonical.gap_type_id != record.gap_type_id:
                collector.error(
                    "canonical_gap_type_mismatch",
                    "Duplicate candidate and canonical candidate use different gap types.",
                    occurrence=occurrence,
                    field_path="canonical_gap_id",
                )
    _detect_cycles(
        supersession_edges,
        code="gap_supersession_cycle",
        field_path="supersedes_candidate_id",
        index=index,
        collector=collector,
    )
    _detect_cycles(
        canonical_edges,
        code="canonical_gap_cycle",
        field_path="canonical_gap_id",
        index=index,
        collector=collector,
    )


def _validate_gap_dossiers(
    occurrences: Sequence[RecordOccurrence],
    index: Mapping[str, RecordOccurrence],
    collector: _IssueCollector,
) -> None:
    for occurrence in occurrences:
        record = occurrence.record
        if isinstance(record, m.GapCandidate):
            for attempt_id in record.verification_attempt_ids:
                attempt = _target(index, attempt_id, m.VerificationAttempt)
                if attempt is not None and attempt.gap_candidate_id != record.record_id:
                    collector.error(
                        "gap_attempt_mismatch",
                        f"Verification attempt {attempt_id!r} belongs to another candidate.",
                        occurrence=occurrence,
                        field_path="verification_attempt_ids",
                    )
            decisive = _target(
                index,
                record.decisive_verification_attempt_id,
                m.VerificationAttempt,
            )
            if (
                decisive is not None
                and decisive.resulting_gap_status is not record.gap_status
            ):
                collector.error(
                    "decisive_attempt_status_mismatch",
                    "Decisive verification result does not equal candidate status.",
                    occurrence=occurrence,
                    field_path="decisive_verification_attempt_id",
                )
            for transition_index, transition in enumerate(record.state_history):
                attempt = _target(
                    index,
                    transition.verification_attempt_id,
                    m.VerificationAttempt,
                )
                if attempt is None:
                    continue
                if attempt.gap_candidate_id != record.record_id:
                    collector.error(
                        "gap_attempt_mismatch",
                        "State transition references an attempt for another candidate.",
                        occurrence=occurrence,
                        field_path=(
                            f"state_history[{transition_index}]"
                            ".verification_attempt_id"
                        ),
                    )
                if _utc(transition.transitioned_at) < _utc(attempt.started_at):
                    collector.error(
                        "chronology_mismatch",
                        "Gap transition precedes its verification-attempt start.",
                        occurrence=occurrence,
                        field_path=f"state_history[{transition_index}].transitioned_at",
                    )

        elif isinstance(record, m.VerificationAttempt):
            candidate = _target(index, record.gap_candidate_id, m.GapCandidate)
            if (
                candidate is not None
                and record.record_id not in candidate.verification_attempt_ids
            ):
                collector.error(
                    "gap_attempt_reciprocity_mismatch",
                    "Verification attempt is absent from its candidate dossier.",
                    occurrence=occurrence,
                    field_path="gap_candidate_id",
                )

        elif isinstance(record, m.GapScore):
            candidate = _target(index, record.gap_candidate_id, m.GapCandidate)
            if (
                candidate is not None
                and record.candidate_gap_status is not candidate.gap_status
            ):
                collector.error(
                    "gap_score_status_mismatch",
                    "Score captures a different candidate status than the referenced dossier.",
                    occurrence=occurrence,
                    field_path="candidate_gap_status",
                )


def _validate_mantis_lineage(
    occurrences: Sequence[RecordOccurrence],
    index: Mapping[str, RecordOccurrence],
    collector: _IssueCollector,
) -> None:
    retry_edges: dict[str, tuple[str, ...]] = {}
    for occurrence in occurrences:
        record = occurrence.record
        if isinstance(record, m.MantisPublicationReceipt):
            retry_edges[record.record_id] = (
                (record.retry_of_receipt_id,)
                if record.retry_of_receipt_id is not None
                else ()
            )
            profile = _target(
                index,
                record.export_profile_id,
                m.MantisExportProfile,
            )
            if profile is not None:
                mismatches = []
                if record.profile_version != profile.profile_version:
                    mismatches.append("profile_version")
                if record.compatibility_version != profile.compatibility_version:
                    mismatches.append("compatibility_version")
                if record.source_contract != profile.source_contract:
                    mismatches.append("source_contract")
                if record.source_schema_version != profile.source_schema_version:
                    mismatches.append("source_schema_version")
                if mismatches:
                    collector.error(
                        "mantis_profile_receipt_mismatch",
                        f"Receipt differs from its export profile in {mismatches}.",
                        occurrence=occurrence,
                        field_path="export_profile_id",
                    )
            prior = _target(
                index,
                record.retry_of_receipt_id,
                m.MantisPublicationReceipt,
            )
            if prior is not None:
                if record.attempt_number != prior.attempt_number + 1:
                    collector.error(
                        "mantis_retry_attempt_mismatch",
                        "Receipt retry attempt must increment by one.",
                        occurrence=occurrence,
                        field_path="attempt_number",
                    )
                if prior.completed_at is not None and _utc(record.started_at) < _utc(
                    prior.completed_at
                ):
                    collector.error(
                        "chronology_mismatch",
                        "Mantis retry starts before the prior attempt completed.",
                        occurrence=occurrence,
                        field_path="started_at",
                    )

        elif isinstance(record, m.MantisInterpretation):
            receipt = _target(
                index,
                record.publication_receipt_id,
                m.MantisPublicationReceipt,
            )
            if receipt is not None:
                mismatches = []
                if record.map_input_sha256 != receipt.source_sha256:
                    mismatches.append("map_input_sha256")
                if record.map_profile_version != receipt.profile_version:
                    mismatches.append("map_profile_version")
                if record.space_id != receipt.space_id:
                    mismatches.append("space_id")
                if record.map_id != receipt.map_id:
                    mismatches.append("map_id")
                if mismatches:
                    collector.error(
                        "mantis_interpretation_receipt_mismatch",
                        f"Interpretation differs from publication receipt in {mismatches}.",
                        occurrence=occurrence,
                        field_path="publication_receipt_id",
                    )
                if receipt.published_at is not None and _utc(
                    record.interpreted_at
                ) < _utc(receipt.published_at):
                    collector.error(
                        "chronology_mismatch",
                        "Mantis interpretation predates map publication.",
                        occurrence=occurrence,
                        field_path="interpreted_at",
                    )
            for candidate_id in record.created_candidate_ids:
                candidate = _target(index, candidate_id, m.GapCandidate)
                if candidate is None:
                    continue
                if not set(record.independent_signal_ids).intersection(
                    candidate.signal_ids
                ):
                    collector.error(
                        "mantis_candidate_signal_mismatch",
                        "Created candidate does not retain an independent signal "
                        "recorded by the interpretation.",
                        occurrence=occurrence,
                        field_path="created_candidate_ids",
                    )
            for signal_id in record.independent_signal_ids:
                signal = _target(index, signal_id, m.GapSignal)
                if (
                    signal is not None
                    and record.record_id not in signal.source_interpretation_ids
                ):
                    collector.error(
                        "mantis_signal_reciprocity_mismatch",
                        "Independent signal does not retain interpretation lineage.",
                        occurrence=occurrence,
                        field_path="independent_signal_ids",
                    )

    _detect_cycles(
        retry_edges,
        code="mantis_retry_cycle",
        field_path="retry_of_receipt_id",
        index=index,
        collector=collector,
    )


def _validate_other_lineages(
    occurrences: Sequence[RecordOccurrence],
    index: Mapping[str, RecordOccurrence],
    collector: _IssueCollector,
) -> None:
    parent_edges: dict[str, tuple[str, ...]] = {}
    entity_edges: dict[str, tuple[str, ...]] = {}
    claim_edges: dict[str, tuple[str, ...]] = {}
    judgment_edges: dict[str, tuple[str, ...]] = {}
    outcome_edges: dict[str, tuple[str, ...]] = {}

    for occurrence in occurrences:
        record = occurrence.record
        parent_edges[record.record_id] = record.parent_record_ids
        if isinstance(record, m.Entity):
            entity_edges[record.record_id] = (
                (record.canonical_entity_id,)
                if record.canonical_entity_id is not None
                else ()
            )
        elif isinstance(record, m.Claim):
            claim_edges[record.record_id] = record.source_claim_ids
        elif isinstance(record, m.ExpertJudgment):
            judgment_edges[record.record_id] = (
                (record.supersedes_judgment_id,)
                if record.supersedes_judgment_id is not None
                else ()
            )
            prior = _target(
                index,
                record.supersedes_judgment_id,
                m.ExpertJudgment,
            )
            if prior is not None:
                if prior.assignment_id != record.assignment_id:
                    collector.error(
                        "judgment_lineage_mismatch",
                        "Superseded expert judgment has another assignment ID.",
                        occurrence=occurrence,
                        field_path="supersedes_judgment_id",
                    )
                if _utc(record.submitted_at) <= _utc(prior.submitted_at):
                    collector.error(
                        "chronology_mismatch",
                        "Replacement judgment is not later than its predecessor.",
                        occurrence=occurrence,
                        field_path="submitted_at",
                    )
        elif isinstance(record, m.OutcomeEvent):
            outcome_edges[record.record_id] = (
                (record.corrects_event_id,)
                if record.corrects_event_id is not None
                else ()
            )
            prior = _target(index, record.corrects_event_id, m.OutcomeEvent)
            if prior is not None:
                if prior.research_project_id != record.research_project_id:
                    collector.error(
                        "outcome_lineage_mismatch",
                        "Corrected event belongs to another research project.",
                        occurrence=occurrence,
                        field_path="corrects_event_id",
                    )
                current_upper = _partial_date_upper(
                    m.PartialDate(
                        value=record.occurred_on,
                        precision=record.date_precision,
                        certainty=m.PartialDateCertainty.EXACT,
                    )
                )
                prior_lower = _partial_date_lower(
                    m.PartialDate(
                        value=prior.occurred_on,
                        precision=prior.date_precision,
                        certainty=m.PartialDateCertainty.EXACT,
                    )
                )
                if (
                    current_upper is not None
                    and prior_lower is not None
                    and current_upper < prior_lower
                ):
                    collector.error(
                        "chronology_mismatch",
                        "Correcting outcome event predates the corrected event.",
                        occurrence=occurrence,
                        field_path="occurred_on",
                    )

    for edges, code, field_path in (
        (parent_edges, "parent_record_cycle", "parent_record_ids"),
        (entity_edges, "canonical_entity_cycle", "canonical_entity_id"),
        (claim_edges, "claim_synthesis_cycle", "source_claim_ids"),
        (judgment_edges, "judgment_lineage_cycle", "supersedes_judgment_id"),
        (outcome_edges, "outcome_correction_cycle", "corrects_event_id"),
    ):
        _detect_cycles(
            edges,
            code=code,
            field_path=field_path,
            index=index,
            collector=collector,
        )


class _ArtifactVerifier:
    def __init__(
        self,
        collector: _IssueCollector,
        artifact_root: Path | None,
    ) -> None:
        self.collector = collector
        self.artifact_root = (
            artifact_root.resolve() if artifact_root is not None else None
        )
        self.verified_paths: set[Path] = set()
        self.remote_not_checked: set[tuple[str, str]] = set()

    def _path_for_uri(
        self,
        uri: str,
        occurrence: RecordOccurrence,
        field_path: str,
    ) -> Path | None:
        parsed = urlsplit(uri)
        if parsed.scheme in {"http", "https"}:
            key = (occurrence.record.record_id, uri)
            if key not in self.remote_not_checked:
                self.remote_not_checked.add(key)
                self.collector.warning(
                    "remote_artifact_not_checked",
                    f"Remote artifact {uri!r} was not fetched during offline validation.",
                    occurrence=occurrence,
                    field_path=field_path,
                )
            return None
        if parsed.scheme == "file":
            if parsed.netloc not in {"", "localhost"}:
                self.collector.error(
                    "unsupported_local_artifact_uri",
                    f"File URI host {parsed.netloc!r} is not local.",
                    occurrence=occurrence,
                    field_path=field_path,
                )
                return None
            path = Path(unquote(parsed.path))
        elif parsed.scheme == "":
            path = Path(uri)
        else:
            self.collector.warning(
                "artifact_scheme_not_checked",
                f"Artifact scheme {parsed.scheme!r} has no offline verifier.",
                occurrence=occurrence,
                field_path=field_path,
            )
            return None

        if not path.is_absolute():
            if self.artifact_root is None:
                self.collector.warning(
                    "local_artifact_root_missing",
                    f"Relative artifact {uri!r} was not checked without artifact_root.",
                    occurrence=occurrence,
                    field_path=field_path,
                )
                return None
            path = self.artifact_root / path
        resolved = path.resolve()
        if self.artifact_root is not None and not resolved.is_relative_to(
            self.artifact_root
        ):
            self.collector.error(
                "artifact_path_escape",
                f"Artifact {uri!r} resolves outside the declared artifact root.",
                occurrence=occurrence,
                field_path=field_path,
            )
            return None
        if not resolved.exists():
            self.collector.error(
                "local_artifact_missing",
                f"Local artifact {resolved} does not exist.",
                occurrence=occurrence,
                field_path=field_path,
            )
            return None
        if not resolved.is_file():
            self.collector.error(
                "local_artifact_not_file",
                f"Local artifact {resolved} is not a regular file.",
                occurrence=occurrence,
                field_path=field_path,
            )
            return None
        return resolved

    def verify_hash(
        self,
        uri: str,
        expected_sha256: str,
        occurrence: RecordOccurrence,
        field_path: str,
        *,
        expected_size: int | None = None,
    ) -> Path | None:
        path = self._path_for_uri(uri, occurrence, field_path)
        if path is None:
            return None
        digest = hashlib.sha256()
        actual_size = 0
        try:
            with path.open("rb") as handle:
                for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                    digest.update(chunk)
                    actual_size += len(chunk)
        except OSError as exc:
            self.collector.error(
                "local_artifact_read_error",
                f"Could not read local artifact {path}: {exc}.",
                occurrence=occurrence,
                field_path=field_path,
            )
            return None
        self.verified_paths.add(path)
        actual_hash = digest.hexdigest()
        if actual_hash != expected_sha256:
            self.collector.error(
                "local_artifact_hash_mismatch",
                f"Artifact hash {actual_hash!r} does not match recorded hash "
                f"{expected_sha256!r}.",
                occurrence=occurrence,
                field_path=field_path,
            )
        if expected_size is not None and actual_size != expected_size:
            self.collector.error(
                "local_artifact_size_mismatch",
                f"Artifact size {actual_size} does not match recorded size "
                f"{expected_size}.",
                occurrence=occurrence,
                field_path=field_path,
            )
        return path


def _validate_artifacts(
    occurrences: Sequence[RecordOccurrence],
    index: Mapping[str, RecordOccurrence],
    collector: _IssueCollector,
    artifact_root: Path | None,
) -> int:
    verifier = _ArtifactVerifier(collector, artifact_root)
    representation_text: dict[str, str] = {}
    representation_pages: dict[str, tuple[tuple[int, int, int], ...]] = {}

    for occurrence in occurrences:
        record = occurrence.record
        if isinstance(record, m.ProviderRecord):
            if record.raw_record_uri is not None and record.raw_record_sha256 is not None:
                verifier.verify_hash(
                    record.raw_record_uri,
                    record.raw_record_sha256,
                    occurrence,
                    "raw_record_uri",
                )
        elif isinstance(record, m.Document):
            verifier.verify_hash(
                record.artifact_uri,
                record.content_sha256,
                occurrence,
                "artifact_uri",
                expected_size=record.byte_size,
            )
            representation = record.extensions.get("pipeline.text_representation")
            if isinstance(representation, Mapping):
                uri = representation.get("artifact_uri")
                expected_hash = representation.get("sha256")
                encoding = representation.get("encoding", "utf-8")
                if not isinstance(uri, str) or not isinstance(expected_hash, str):
                    collector.error(
                        "invalid_text_representation_extension",
                        "Text representation requires artifact_uri and sha256 strings.",
                        occurrence=occurrence,
                        field_path="extensions.pipeline.text_representation",
                    )
                elif not isinstance(encoding, str):
                    collector.error(
                        "invalid_text_representation_extension",
                        "Text representation encoding must be a string.",
                        occurrence=occurrence,
                        field_path="extensions.pipeline.text_representation.encoding",
                    )
                else:
                    path = verifier.verify_hash(
                        uri,
                        expected_hash,
                        occurrence,
                        "extensions.pipeline.text_representation.artifact_uri",
                    )
                    if path is not None:
                        try:
                            representation_text[record.record_id] = path.read_text(
                                encoding=encoding
                            )
                        except (LookupError, OSError, UnicodeError) as exc:
                            collector.error(
                                "text_representation_decode_error",
                                f"Could not decode text representation: {exc}.",
                                occurrence=occurrence,
                                field_path=(
                                    "extensions.pipeline.text_representation.encoding"
                                ),
                            )
                structure_uri = representation.get("structure_artifact_uri")
                structure_hash = representation.get("structure_sha256")
                structure_version = representation.get("structure_schema_version")
                structure_values = (structure_uri, structure_hash, structure_version)
                if any(value is not None for value in structure_values):
                    if not all(isinstance(value, str) for value in structure_values):
                        collector.error(
                            "invalid_text_structure_extension",
                            "Text structure requires artifact URI, SHA-256, and "
                            "schema-version strings.",
                            occurrence=occurrence,
                            field_path="extensions.pipeline.text_representation",
                        )
                    else:
                        structure_path = verifier.verify_hash(
                            structure_uri,
                            structure_hash,
                            occurrence,
                            (
                                "extensions.pipeline.text_representation."
                                "structure_artifact_uri"
                            ),
                        )
                        if structure_path is not None:
                            try:
                                structure = json.loads(
                                    structure_path.read_text(encoding="utf-8")
                                )
                            except (OSError, UnicodeError, json.JSONDecodeError) as exc:
                                collector.error(
                                    "text_structure_decode_error",
                                    f"Could not decode text structure: {exc}.",
                                    occurrence=occurrence,
                                    field_path=(
                                        "extensions.pipeline.text_representation."
                                        "structure_artifact_uri"
                                    ),
                                )
                            else:
                                text = representation_text.get(record.record_id)
                                spans: list[tuple[int, int, int]] = []
                                structure_valid = isinstance(structure, Mapping)
                                if structure_valid:
                                    structure_valid = (
                                        structure.get("schema_version")
                                        == structure_version
                                        and structure_version
                                        in SUPPORTED_TEXT_STRUCTURE_SCHEMA_VERSIONS
                                        and structure.get("representation_sha256")
                                        == expected_hash
                                        and structure.get("media_type")
                                        == record.media_type
                                        and isinstance(
                                            structure.get("page_spans"), list
                                        )
                                    )
                                previous_page = 0
                                previous_end = 0
                                if structure_valid:
                                    for item in structure["page_spans"]:
                                        if not isinstance(item, Mapping):
                                            structure_valid = False
                                            break
                                        page = item.get("page_number")
                                        start = item.get("start_char")
                                        end = item.get("end_char")
                                        if (
                                            isinstance(page, bool)
                                            or not isinstance(page, int)
                                            or page <= previous_page
                                            or isinstance(start, bool)
                                            or not isinstance(start, int)
                                            or start < previous_end
                                            or isinstance(end, bool)
                                            or not isinstance(end, int)
                                            or end <= start
                                            or (text is not None and end > len(text))
                                        ):
                                            structure_valid = False
                                            break
                                        spans.append((page, start, end))
                                        previous_page = page
                                        previous_end = end
                                if (
                                    structure_valid
                                    and record.media_type == "application/pdf"
                                    and (record.page_count is None or not spans)
                                ):
                                    structure_valid = False
                                if (
                                    structure_valid
                                    and spans
                                    and record.page_count is not None
                                    and spans[-1][0] > record.page_count
                                ):
                                    structure_valid = False
                                if not structure_valid:
                                    collector.error(
                                        "invalid_text_structure",
                                        "Text structure does not match the document "
                                        "representation, media type, or page bounds.",
                                        occurrence=occurrence,
                                        field_path=(
                                            "extensions.pipeline.text_representation."
                                            "structure_artifact_uri"
                                        ),
                                    )
                                else:
                                    representation_pages[record.record_id] = tuple(
                                        spans
                                    )
        elif isinstance(record, m.MantisPublicationReceipt):
            verifier.verify_hash(
                record.source_artifact_reference.reference,
                record.source_sha256,
                occurrence,
                "source_artifact_reference.reference",
            )

    for occurrence in occurrences:
        record = occurrence.record
        if not isinstance(record, m.Passage):
            continue
        text = representation_text.get(record.document_id)
        if text is None:
            collector.warning(
                "passage_representation_not_checked",
                "Exact document occurrence was not checked because no verified "
                "pipeline.text_representation artifact is available.",
                occurrence=occurrence,
                field_path="locator",
            )
            continue
        representation_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
        locator_hash = record.locator["representation_sha256"]
        if representation_hash != locator_hash:
            collector.error(
                "passage_representation_hash_mismatch",
                "Passage locator identifies a different text representation.",
                occurrence=occurrence,
                field_path="locator.representation_sha256",
            )
            continue
        start = record.locator["start_char"]
        end = record.locator["end_char"]
        assert isinstance(start, int) and isinstance(end, int)
        if end > len(text) or text[start:end] != record.text:
            collector.error(
                "passage_occurrence_mismatch",
                "Passage text does not occur at its recorded representation offsets.",
                occurrence=occurrence,
                field_path="locator",
            )
        page_spans = representation_pages.get(record.document_id)
        if page_spans is not None:
            pages = [
                page
                for page, page_start, page_end in page_spans
                if page_start < end and page_end > start
            ]
            expected_page_start = min(pages) if pages else None
            expected_page_end = max(pages) if pages else None
            if (
                record.locator["page_start"] != expected_page_start
                or record.locator["page_end"] != expected_page_end
            ):
                collector.error(
                    "passage_page_locator_mismatch",
                    "Passage page coordinates do not match the verified text "
                    "structure.",
                    occurrence=occurrence,
                    field_path="locator",
                )

    return len(verifier.verified_paths)


def _build_report(
    occurrences: Sequence[RecordOccurrence],
    collector: _IssueCollector,
    *,
    records_checked: int,
    record_artifacts_checked: int,
    artifact_root: Path | None,
    verify_local_artifacts: bool,
) -> IntegrityReport:
    index = _index_occurrences(occurrences, collector)
    indexed_occurrences = tuple(
        occurrence
        for occurrence in occurrences
        if index.get(occurrence.record.record_id) is occurrence
    )
    _validate_reference_graph(indexed_occurrences, index, collector)
    _validate_snapshot_closure(index, collector)
    _validate_ownership(indexed_occurrences, index, collector)
    _validate_evidence_spans(indexed_occurrences, index, collector)
    _validate_temporal_eligibility(indexed_occurrences, index, collector)
    _validate_dependency_chronology(indexed_occurrences, index, collector)
    _validate_source_version_lineage(indexed_occurrences, index, collector)
    _validate_gap_lineage(indexed_occurrences, index, collector)
    _validate_gap_dossiers(indexed_occurrences, index, collector)
    _validate_mantis_lineage(indexed_occurrences, index, collector)
    _validate_other_lineages(indexed_occurrences, index, collector)
    files_verified = 0
    if verify_local_artifacts:
        files_verified = _validate_artifacts(
            indexed_occurrences,
            index,
            collector,
            artifact_root,
        )
    return IntegrityReport(
        records_checked=records_checked,
        record_artifacts_checked=record_artifacts_checked,
        local_files_verified=files_verified,
        issues=tuple(sorted(collector.issues, key=_issue_sort_key)),
    )


def validate_record_collection(
    records: Iterable[m.RecordEnvelope],
    *,
    artifact_root: Path | None = None,
    verify_local_artifacts: bool = True,
) -> IntegrityReport:
    """Validate one complete in-memory record collection.

    Warnings never make the report invalid. Remote artifacts are not fetched;
    when artifact checks are enabled they receive explicit ``not_checked``
    warnings instead.
    """
    collector = _IssueCollector()
    occurrences: list[RecordOccurrence] = []
    checked = 0
    try:
        iterator = iter(records)
    except TypeError as exc:
        raise ValidationError("Record collection must be iterable.") from exc
    for index, record in enumerate(iterator, start=1):
        checked += 1
        if not isinstance(record, m.BaseRecord):
            collector.error(
                "invalid_record_object",
                f"Collection item {index} is not a versioned record.",
            )
            continue
        occurrences.append(RecordOccurrence(record=record))
    return _build_report(
        occurrences,
        collector,
        records_checked=checked,
        record_artifacts_checked=0,
        artifact_root=artifact_root,
        verify_local_artifacts=verify_local_artifacts,
    )


def validate_record_artifacts(
    paths: Iterable[Path],
    *,
    artifact_root: Path | None = None,
    verify_local_artifacts: bool = True,
) -> IntegrityReport:
    """Read one or more JSONL artifacts and validate them as one collection."""
    collector = _IssueCollector()
    occurrences: list[RecordOccurrence] = []
    checked = 0
    artifact_count = 0
    try:
        iterator = iter(paths)
    except TypeError as exc:
        raise ValidationError("Record artifact paths must be iterable.") from exc
    for raw_path in iterator:
        artifact_count += 1
        path = Path(raw_path)
        try:
            handle = path.open(encoding="utf-8")
        except OSError as exc:
            collector.error(
                "record_artifact_read_error",
                f"Could not read record artifact {path}: {exc}.",
                artifact_path=str(path),
            )
            continue
        with handle:
            for line_number, line in enumerate(handle, start=1):
                if not line.strip():
                    continue
                checked += 1
                try:
                    payload = json.loads(line)
                except json.JSONDecodeError as exc:
                    collector.error(
                        "invalid_record_json",
                        f"Invalid JSON: {exc.msg}.",
                        artifact_path=str(path),
                        line_number=line_number,
                    )
                    continue
                try:
                    record = record_from_dict(payload)
                except ValidationError as exc:
                    collector.error(
                        "invalid_local_record",
                        str(exc),
                        artifact_path=str(path),
                        line_number=line_number,
                    )
                    continue
                occurrences.append(
                    RecordOccurrence(
                        record=record,
                        artifact_path=str(path),
                        line_number=line_number,
                    )
                )
    effective_root = artifact_root
    return _build_report(
        occurrences,
        collector,
        records_checked=checked,
        record_artifacts_checked=artifact_count,
        artifact_root=effective_root,
        verify_local_artifacts=verify_local_artifacts,
    )


def require_record_integrity(report: IntegrityReport) -> IntegrityReport:
    """Raise with the complete structured report when integrity errors exist."""
    if not isinstance(report, IntegrityReport):
        raise ValidationError("Expected an IntegrityReport instance.")
    if not report.is_valid:
        raise RecordIntegrityError(report)
    return report


def write_integrity_report(path: Path, report: IntegrityReport) -> None:
    """Write a stable JSON audit report without changing source artifacts."""
    if not isinstance(report, IntegrityReport):
        raise ValidationError("Expected an IntegrityReport instance.")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(report.to_dict(), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
