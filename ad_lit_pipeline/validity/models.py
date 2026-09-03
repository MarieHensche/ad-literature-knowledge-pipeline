from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Mapping


class GapStatus(str, Enum):
    PROPOSED = "proposed"
    VERIFICATION_IN_PROGRESS = "verification_in_progress"
    VERIFIED_OPEN = "verified_open"
    REFUTED = "refuted"
    RESOLVED = "resolved"
    UNCERTAIN = "uncertain"
    TERMINOLOGY_ARTIFACT = "terminology_artifact"
    DUPLICATE = "duplicate"


class ClaimVerificationOutcome(str, Enum):
    SUPPORTED = "supported"
    CONTRADICTED = "contradicted"
    INSUFFICIENT = "insufficient"
    UNCERTAIN = "uncertain"


class AssessmentDimensionKind(str, Enum):
    CONFIDENCE = "confidence"
    QUALITY = "quality"
    COVERAGE = "coverage"
    UNCERTAINTY = "uncertainty"
    RANKING = "ranking"


@dataclass(frozen=True)
class TermDefinition:
    definition: str
    required_qualifiers: tuple[str, ...]
    prohibited_inferences: tuple[str, ...]


@dataclass(frozen=True)
class StateDefinition:
    definition: str
    terminal_for_candidate_version: bool = False


@dataclass(frozen=True)
class TransitionRule:
    source: GapStatus
    target: GapStatus
    required_checks: tuple[str, ...]
    requires_new_candidate_version: bool


@dataclass(frozen=True)
class AssessmentDimension:
    definition: str
    kind: AssessmentDimensionKind


@dataclass(frozen=True)
class OpenWorldPolicy:
    missing_representation_is_global_absence: bool
    zero_results_are_global_absence: bool
    adequate_coverage_is_global_completeness: bool
    historical_reconstruction_without_snapshot_is_certain: bool
    qualification_required_phrases: tuple[str, ...]
    always_prohibited_phrases: tuple[str, ...]
    required_absence_qualifiers: tuple[str, ...]
    preferred_absence_language: str


@dataclass(frozen=True)
class HumanReviewPolicy:
    mandatory_triggers: tuple[str, ...]
    trigger_definitions: Mapping[str, str]
    cannot_be_waived_by_review: tuple[str, ...]


@dataclass(frozen=True)
class MantisInterpretationPolicy:
    is_evidence: bool
    may_create_gap_candidate: bool
    resulting_gap_status_after_independent_signal: GapStatus
    may_set_verified_status: bool
    requires_independent_deterministic_signal: bool
    requires_standard_counterretrieval_and_verification: bool
    required_provenance_fields: tuple[str, ...]


@dataclass(frozen=True)
class ScientificValidityPolicy:
    schema_version: str
    policy_id: str
    policy_version: str
    scope: str
    terminology: Mapping[str, TermDefinition]
    claim_outcomes: Mapping[ClaimVerificationOutcome, str]
    claim_outcomes_are_mutually_exclusive: bool
    comparability_required_for_contradiction: bool
    support_is_scientific_truth: bool
    gap_statuses: Mapping[GapStatus, StateDefinition]
    initial_gap_status: GapStatus
    state_history_is_append_only: bool
    human_judgment_is_gap_status: bool
    transitions: tuple[TransitionRule, ...]
    verified_open_required_checks: tuple[str, ...]
    resolution_required_checks: tuple[str, ...]
    coverage_statuses: Mapping[str, str]
    coverage_required_dimensions: tuple[str, ...]
    adequate_coverage_is_global_completeness: bool
    missing_edge_meaning: str
    unknown_availability_policy: str
    assessment_dimensions: Mapping[str, AssessmentDimension]
    assessment_dimensions_must_remain_separate: bool
    forbidden_assessment_derivations: tuple[tuple[str, str], ...]
    open_world: OpenWorldPolicy
    human_review: HumanReviewPolicy
    mantis_interpretation: MantisInterpretationPolicy
