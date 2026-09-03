from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from pathlib import Path
from types import MappingProxyType
from typing import Any

import yaml

from ad_lit_pipeline.core.errors import ValidationError
from ad_lit_pipeline.io.yaml_io import read_yaml_object
from ad_lit_pipeline.validity.models import (
    AssessmentDimension,
    AssessmentDimensionKind,
    ClaimVerificationOutcome,
    GapStatus,
    HumanReviewPolicy,
    MantisInterpretationPolicy,
    OpenWorldPolicy,
    ScientificValidityPolicy,
    StateDefinition,
    TermDefinition,
    TransitionRule,
)


DEFAULT_SCIENTIFIC_VALIDITY_POLICY_PATH = (
    Path(__file__).resolve().parents[2]
    / "configs"
    / "policies"
    / "scientific_validity_v1.yaml"
)

_SEMANTIC_VERSION = re.compile(
    r"^[0-9]+\.[0-9]+\.[0-9]+(?:[-+][0-9A-Za-z.-]+)?$"
)

_TOP_LEVEL_KEYS = {
    "schema_version",
    "policy_id",
    "policy_version",
    "scope",
    "terminology",
    "open_world",
    "claim_verification",
    "gap_lifecycle",
    "coverage",
    "assessment_dimensions",
    "human_review",
    "mantis_interpretation",
}

_REQUIRED_TERMS = {
    "gap_candidate",
    "verified_gap",
    "refuted_gap",
    "resolved_gap",
    "corpus_sparse",
    "as_of",
    "supported",
    "contradicted",
    "insufficient",
    "uncertain",
}

_REQUIRED_TERM_QUALIFIERS = {
    "gap_candidate": {
        "candidate_version",
        "corpus_snapshot_id",
        "corpus_scope",
        "as_of",
        "gap_type",
        "signal_ids",
        "coverage_status",
        "uncertainty_reasons",
    },
    "verified_gap": {
        "candidate_version",
        "corpus_snapshot_id",
        "corpus_scope",
        "as_of",
        "coverage_status",
        "verification_dossier_id",
        "uncertainty_reasons",
    },
    "refuted_gap": {
        "original_candidate_version",
        "original_as_of",
        "refuting_evidence_ids",
        "verification_dossier_id",
    },
    "resolved_gap": {
        "prior_verified_candidate_version",
        "prior_as_of",
        "resolving_evidence_ids",
        "resolution_rule_id",
        "resolution_as_of",
    },
    "corpus_sparse": {
        "corpus_snapshot_id",
        "corpus_scope",
        "as_of",
        "query_or_cell",
        "counted_unit",
        "observed_count",
        "threshold",
        "coverage_status",
    },
    "as_of": {"cutoff_date", "availability_date_rule", "corpus_snapshot_id"},
    "supported": {"claim_id", "source_version_id", "passage_ids", "verifier_id"},
    "contradicted": {
        "claim_id",
        "counterclaim_id",
        "passage_ids",
        "comparability_key",
        "verifier_id",
    },
    "insufficient": {"claim_id", "checked_passage_ids", "insufficiency_reasons"},
    "uncertain": {
        "uncertainty_context",
        "subject_id",
        "uncertainty_reasons",
        "unresolved_checks",
    },
}

_REQUIRED_PROHIBITED_INFERENCES = {
    "gap_candidate": {"global_nonexistence", "expert_acceptance"},
    "verified_gap": {"global_nonexistence", "final_scientific_truth"},
    "refuted_gap": {"underlying_hypothesis_refuted", "final_scientific_truth"},
    "resolved_gap": {"final_scientific_truth", "permanent_resolution"},
    "corpus_sparse": {"globally_unstudied", "scientifically_important"},
    "as_of": {"historical_completeness_without_snapshot"},
    "supported": {"independently_replicated", "final_scientific_truth"},
    "contradicted": {"contradiction_without_comparability"},
    "insufficient": {"global_nonexistence", "claim_false"},
    "uncertain": {"probably_false", "probably_unimportant"},
}

_REQUIRED_QUALIFICATION_PHRASES = {
    "not studied",
    "not been studied",
    "never studied",
    "unstudied",
    "not been investigated",
    "never been investigated",
    "no evidence exists",
    "no studies have",
    "no study has",
    "no studies exist",
    "no research exists",
    "no literature exists",
    "no prior work exists",
    "no published evidence",
    "evidence is absent",
    "no eligible records",
    "no records were found",
}

_REQUIRED_ALWAYS_PROHIBITED_PHRASES = {
    "proven gap",
    "scientifically validated gap",
}

_REQUIRED_ABSENCE_QUALIFIERS = {
    "corpus_snapshot_id",
    "corpus_scope",
    "as_of",
    "searched_sources",
    "coverage_status",
}

_REQUIRED_COVERAGE_STATUSES = {
    "not_assessed",
    "adequate_for_rule",
    "partial",
    "insufficient",
}

_REQUIRED_ASSESSMENT_DIMENSIONS = {
    "screening_confidence",
    "extraction_confidence",
    "verification_confidence",
    "reporting_quality",
    "study_quality",
    "evidence_quality",
    "scientific_confidence",
    "corpus_coverage",
    "gap_uncertainty",
    "novelty",
    "importance",
    "feasibility",
}

_REQUIRED_ASSESSMENT_KINDS = {
    "screening_confidence": AssessmentDimensionKind.CONFIDENCE,
    "extraction_confidence": AssessmentDimensionKind.CONFIDENCE,
    "verification_confidence": AssessmentDimensionKind.CONFIDENCE,
    "reporting_quality": AssessmentDimensionKind.QUALITY,
    "study_quality": AssessmentDimensionKind.QUALITY,
    "evidence_quality": AssessmentDimensionKind.QUALITY,
    "scientific_confidence": AssessmentDimensionKind.CONFIDENCE,
    "corpus_coverage": AssessmentDimensionKind.COVERAGE,
    "gap_uncertainty": AssessmentDimensionKind.UNCERTAINTY,
    "novelty": AssessmentDimensionKind.RANKING,
    "importance": AssessmentDimensionKind.RANKING,
    "feasibility": AssessmentDimensionKind.RANKING,
}

_REQUIRED_FORBIDDEN_DERIVATIONS = {
    ("extraction_confidence", "evidence_quality"),
    ("extraction_confidence", "scientific_confidence"),
    ("model_confidence", "scientific_confidence"),
    ("model_confidence", "novelty"),
    ("model_confidence", "importance"),
    ("model_confidence", "feasibility"),
    ("model_confidence", "reporting_quality"),
    ("model_confidence", "study_quality"),
    ("reporting_quality", "study_quality"),
    ("study_quality", "reporting_quality"),
    ("legacy_evidence_strength", "scientific_confidence"),
    ("map_proximity", "scientific_support"),
}

_REQUIRED_HUMAN_REVIEW_TRIGGERS = {
    "verifier_disagreement",
    "material_detail_mismatch",
    "comparability_ambiguous",
    "terminology_or_entity_ambiguous",
    "central_evidence_inaccessible",
    "inadequate_coverage_for_promotion",
    "high_stakes_claim",
    "terminal_state_reopened",
    "expert_judgment_conflict",
    "mantis_or_llm_hypothesis_without_signal",
}

_REQUIRED_UNWAIVABLE_BLOCKERS = {
    "missing_stable_id",
    "missing_provenance",
    "invalid_schema",
    "orphan_reference",
    "missing_corpus_snapshot",
    "missing_as_of",
    "missing_independent_deterministic_signal",
}

_REQUIRED_MANTIS_PROVENANCE_FIELDS = {
    "interpretation_id",
    "space_id",
    "map_id",
    "map_profile_version",
    "map_input_hash",
    "selected_point_ids",
    "actor",
    "prompt_or_action",
    "timestamp",
    "output_text",
}

_SAFE_MISSING_EDGE_MEANING = "Not represented in this corpus snapshot."
_SAFE_UNKNOWN_AVAILABILITY_POLICY = (
    "exclude_from_temporal_claim_and_mark_uncertain"
)

_REQUIRED_TRANSITIONS = {
    (GapStatus.PROPOSED, GapStatus.VERIFICATION_IN_PROGRESS),
    (GapStatus.VERIFICATION_IN_PROGRESS, GapStatus.VERIFIED_OPEN),
    (GapStatus.VERIFICATION_IN_PROGRESS, GapStatus.REFUTED),
    (GapStatus.VERIFICATION_IN_PROGRESS, GapStatus.RESOLVED),
    (GapStatus.VERIFICATION_IN_PROGRESS, GapStatus.UNCERTAIN),
    (GapStatus.VERIFICATION_IN_PROGRESS, GapStatus.TERMINOLOGY_ARTIFACT),
    (GapStatus.VERIFICATION_IN_PROGRESS, GapStatus.DUPLICATE),
    (GapStatus.UNCERTAIN, GapStatus.VERIFICATION_IN_PROGRESS),
    (GapStatus.VERIFIED_OPEN, GapStatus.VERIFICATION_IN_PROGRESS),
    (GapStatus.REFUTED, GapStatus.VERIFICATION_IN_PROGRESS),
    (GapStatus.RESOLVED, GapStatus.VERIFICATION_IN_PROGRESS),
    (GapStatus.TERMINOLOGY_ARTIFACT, GapStatus.VERIFICATION_IN_PROGRESS),
    (GapStatus.DUPLICATE, GapStatus.VERIFICATION_IN_PROGRESS),
}

_REASSESSMENT_SOURCES = {
    GapStatus.UNCERTAIN,
    GapStatus.VERIFIED_OPEN,
    GapStatus.REFUTED,
    GapStatus.RESOLVED,
    GapStatus.TERMINOLOGY_ARTIFACT,
    GapStatus.DUPLICATE,
}


def _invalid(source: str, path: str, message: str) -> ValidationError:
    return ValidationError(f"{source}: {path}: {message}")


def _mapping(value: Any, source: str, path: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise _invalid(source, path, "expected an object")
    return value


def _required_mapping(
    parent: Mapping[str, Any], key: str, source: str, path: str
) -> Mapping[str, Any]:
    if key not in parent:
        raise _invalid(source, f"{path}.{key}", "is required")
    return _mapping(parent[key], source, f"{path}.{key}")


def _nonempty_string(value: Any, source: str, path: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise _invalid(source, path, "expected a non-empty string")
    return value.strip()


def _required_string(
    parent: Mapping[str, Any], key: str, source: str, path: str
) -> str:
    if key not in parent:
        raise _invalid(source, f"{path}.{key}", "is required")
    return _nonempty_string(parent[key], source, f"{path}.{key}")


def _required_bool(
    parent: Mapping[str, Any], key: str, source: str, path: str
) -> bool:
    if key not in parent:
        raise _invalid(source, f"{path}.{key}", "is required")
    value = parent[key]
    if not isinstance(value, bool):
        raise _invalid(source, f"{path}.{key}", "expected a boolean")
    return value


def _string_tuple(value: Any, source: str, path: str) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise _invalid(source, path, "expected a list")
    result = tuple(
        _nonempty_string(item, source, f"{path}[{index}]")
        for index, item in enumerate(value)
    )
    if not result:
        raise _invalid(source, path, "must not be empty")
    if len(set(result)) != len(result):
        raise _invalid(source, path, "must not contain duplicate values")
    return result


def _required_string_tuple(
    parent: Mapping[str, Any], key: str, source: str, path: str
) -> tuple[str, ...]:
    if key not in parent:
        raise _invalid(source, f"{path}.{key}", "is required")
    return _string_tuple(parent[key], source, f"{path}.{key}")


def _require_exact_keys(
    mapping: Mapping[str, Any], expected: set[str], source: str, path: str
) -> None:
    actual = set(mapping)
    missing = sorted(expected - actual, key=str)
    unexpected = sorted(actual - expected, key=str)
    problems: list[str] = []
    if missing:
        problems.append(f"missing {missing}")
    if unexpected:
        problems.append(f"unexpected {unexpected}")
    if problems:
        raise _invalid(source, path, "; ".join(problems))


def _require_members(
    actual: Iterable[Any], required: set[Any], source: str, path: str
) -> None:
    missing = sorted(required - set(actual), key=str)
    if missing:
        raise _invalid(source, path, f"missing required values {missing}")


def _expect_bool(value: bool, expected: bool, source: str, path: str) -> None:
    if value is not expected:
        raise _invalid(source, path, f"must be {str(expected).lower()}")


def _parse_terminology(
    payload: Mapping[str, Any], source: str
) -> Mapping[str, TermDefinition]:
    terms = _required_mapping(payload, "terminology", source, "policy")
    _require_members(terms, _REQUIRED_TERMS, source, "policy.terminology")
    parsed: dict[str, TermDefinition] = {}
    for term_id, raw_term in terms.items():
        term_path = f"policy.terminology.{term_id}"
        _nonempty_string(term_id, source, term_path)
        term = _mapping(raw_term, source, term_path)
        parsed[term_id] = TermDefinition(
            definition=_required_string(term, "definition", source, term_path),
            required_qualifiers=_required_string_tuple(
                term, "required_qualifiers", source, term_path
            ),
            prohibited_inferences=_required_string_tuple(
                term, "prohibited_inferences", source, term_path
            ),
        )
        required_qualifiers = _REQUIRED_TERM_QUALIFIERS.get(term_id)
        if required_qualifiers is not None:
            _require_members(
                parsed[term_id].required_qualifiers,
                required_qualifiers,
                source,
                f"{term_path}.required_qualifiers",
            )
        prohibited_inferences = _REQUIRED_PROHIBITED_INFERENCES.get(term_id)
        if prohibited_inferences is not None:
            _require_members(
                parsed[term_id].prohibited_inferences,
                prohibited_inferences,
                source,
                f"{term_path}.prohibited_inferences",
            )
    return MappingProxyType(parsed)


def _parse_open_world(
    payload: Mapping[str, Any], source: str
) -> OpenWorldPolicy:
    raw = _required_mapping(payload, "open_world", source, "policy")
    missing_representation = _required_bool(
        raw,
        "missing_representation_is_global_absence",
        source,
        "policy.open_world",
    )
    zero_results = _required_bool(
        raw, "zero_results_are_global_absence", source, "policy.open_world"
    )
    adequate_coverage = _required_bool(
        raw,
        "adequate_coverage_is_global_completeness",
        source,
        "policy.open_world",
    )
    historical_certainty = _required_bool(
        raw,
        "historical_reconstruction_without_snapshot_is_certain",
        source,
        "policy.open_world",
    )
    _expect_bool(
        missing_representation,
        False,
        source,
        "policy.open_world.missing_representation_is_global_absence",
    )
    _expect_bool(
        zero_results,
        False,
        source,
        "policy.open_world.zero_results_are_global_absence",
    )
    _expect_bool(
        adequate_coverage,
        False,
        source,
        "policy.open_world.adequate_coverage_is_global_completeness",
    )
    _expect_bool(
        historical_certainty,
        False,
        source,
        "policy.open_world.historical_reconstruction_without_snapshot_is_certain",
    )
    qualification_required = _required_string_tuple(
        raw, "qualification_required_phrases", source, "policy.open_world"
    )
    always_prohibited = _required_string_tuple(
        raw, "always_prohibited_phrases", source, "policy.open_world"
    )
    absence_qualifiers = _required_string_tuple(
        raw, "required_absence_qualifiers", source, "policy.open_world"
    )
    _require_members(
        qualification_required,
        _REQUIRED_QUALIFICATION_PHRASES,
        source,
        "policy.open_world.qualification_required_phrases",
    )
    _require_members(
        always_prohibited,
        _REQUIRED_ALWAYS_PROHIBITED_PHRASES,
        source,
        "policy.open_world.always_prohibited_phrases",
    )
    _require_members(
        absence_qualifiers,
        _REQUIRED_ABSENCE_QUALIFIERS,
        source,
        "policy.open_world.required_absence_qualifiers",
    )
    if set(qualification_required) & set(always_prohibited):
        raise _invalid(
            source,
            "policy.open_world",
            "a phrase cannot be both qualifiable and always prohibited",
        )
    return OpenWorldPolicy(
        missing_representation_is_global_absence=missing_representation,
        zero_results_are_global_absence=zero_results,
        adequate_coverage_is_global_completeness=adequate_coverage,
        historical_reconstruction_without_snapshot_is_certain=historical_certainty,
        qualification_required_phrases=qualification_required,
        always_prohibited_phrases=always_prohibited,
        required_absence_qualifiers=absence_qualifiers,
        preferred_absence_language=_required_string(
            raw, "preferred_absence_language", source, "policy.open_world"
        ),
    )


def _parse_claim_outcomes(
    payload: Mapping[str, Any], source: str
) -> tuple[
    Mapping[ClaimVerificationOutcome, str],
    bool,
    bool,
    bool,
]:
    raw = _required_mapping(payload, "claim_verification", source, "policy")
    mutually_exclusive = _required_bool(
        raw, "outcomes_are_mutually_exclusive", source, "policy.claim_verification"
    )
    comparability_required = _required_bool(
        raw,
        "comparability_required_for_contradiction",
        source,
        "policy.claim_verification",
    )
    support_is_truth = _required_bool(
        raw, "support_is_scientific_truth", source, "policy.claim_verification"
    )
    _expect_bool(
        mutually_exclusive,
        True,
        source,
        "policy.claim_verification.outcomes_are_mutually_exclusive",
    )
    _expect_bool(
        comparability_required,
        True,
        source,
        "policy.claim_verification.comparability_required_for_contradiction",
    )
    _expect_bool(
        support_is_truth,
        False,
        source,
        "policy.claim_verification.support_is_scientific_truth",
    )

    outcomes = _required_mapping(
        raw, "outcomes", source, "policy.claim_verification"
    )
    expected = {outcome.value for outcome in ClaimVerificationOutcome}
    _require_exact_keys(
        outcomes, expected, source, "policy.claim_verification.outcomes"
    )
    parsed: dict[ClaimVerificationOutcome, str] = {}
    for outcome in ClaimVerificationOutcome:
        outcome_path = f"policy.claim_verification.outcomes.{outcome.value}"
        definition = _mapping(outcomes[outcome.value], source, outcome_path)
        parsed[outcome] = _required_string(
            definition, "definition", source, outcome_path
        )
    return (
        MappingProxyType(parsed),
        mutually_exclusive,
        comparability_required,
        support_is_truth,
    )


def _coerce_gap_status(
    value: GapStatus | str, source: str, path: str
) -> GapStatus:
    if isinstance(value, GapStatus):
        return value
    if not isinstance(value, str):
        raise _invalid(source, path, "expected a gap-status string")
    try:
        return GapStatus(value)
    except ValueError as error:
        allowed = [status.value for status in GapStatus]
        raise _invalid(source, path, f"unknown status {value!r}; expected {allowed}") from error


def _parse_gap_lifecycle(
    payload: Mapping[str, Any], source: str
) -> tuple[
    Mapping[GapStatus, StateDefinition],
    GapStatus,
    bool,
    bool,
    tuple[TransitionRule, ...],
    tuple[str, ...],
    tuple[str, ...],
]:
    raw = _required_mapping(payload, "gap_lifecycle", source, "policy")
    initial_status = _coerce_gap_status(
        _required_string(raw, "initial_status", source, "policy.gap_lifecycle"),
        source,
        "policy.gap_lifecycle.initial_status",
    )
    if initial_status is not GapStatus.PROPOSED:
        raise _invalid(
            source, "policy.gap_lifecycle.initial_status", "must be 'proposed'"
        )
    state_history_is_append_only = _required_bool(
        raw,
        "state_history_is_append_only",
        source,
        "policy.gap_lifecycle",
    )
    human_judgment_is_status = _required_bool(
        raw,
        "human_judgment_is_gap_status",
        source,
        "policy.gap_lifecycle",
    )
    _expect_bool(
        state_history_is_append_only,
        True,
        source,
        "policy.gap_lifecycle.state_history_is_append_only",
    )
    _expect_bool(
        human_judgment_is_status,
        False,
        source,
        "policy.gap_lifecycle.human_judgment_is_gap_status",
    )

    statuses = _required_mapping(raw, "statuses", source, "policy.gap_lifecycle")
    expected_statuses = {status.value for status in GapStatus}
    _require_exact_keys(
        statuses, expected_statuses, source, "policy.gap_lifecycle.statuses"
    )
    parsed_statuses: dict[GapStatus, StateDefinition] = {}
    for status in GapStatus:
        status_path = f"policy.gap_lifecycle.statuses.{status.value}"
        state = _mapping(statuses[status.value], source, status_path)
        parsed_statuses[status] = StateDefinition(
            definition=_required_string(state, "definition", source, status_path),
            terminal_for_candidate_version=_required_bool(
                state, "terminal_for_candidate_version", source, status_path
            ),
        )
    terminal_statuses = {
        GapStatus.VERIFIED_OPEN,
        GapStatus.REFUTED,
        GapStatus.RESOLVED,
        GapStatus.UNCERTAIN,
        GapStatus.TERMINOLOGY_ARTIFACT,
        GapStatus.DUPLICATE,
    }
    for status in GapStatus:
        expected_terminal = status in terminal_statuses
        if parsed_statuses[status].terminal_for_candidate_version is expected_terminal:
            continue
        expected_text = str(expected_terminal).lower()
        raise _invalid(
            source,
            f"policy.gap_lifecycle.statuses.{status.value}.terminal_for_candidate_version",
            f"must be {expected_text}",
        )

    verified_checks = _required_string_tuple(
        raw,
        "verified_open_required_checks",
        source,
        "policy.gap_lifecycle",
    )
    resolution_checks = _required_string_tuple(
        raw, "resolution_required_checks", source, "policy.gap_lifecycle"
    )

    raw_transitions = raw.get("transitions")
    if not isinstance(raw_transitions, list) or not raw_transitions:
        raise _invalid(
            source, "policy.gap_lifecycle.transitions", "expected a non-empty list"
        )
    transitions: list[TransitionRule] = []
    edges: set[tuple[GapStatus, GapStatus]] = set()
    for index, raw_transition in enumerate(raw_transitions):
        transition_path = f"policy.gap_lifecycle.transitions[{index}]"
        transition = _mapping(raw_transition, source, transition_path)
        source_status = _coerce_gap_status(
            _required_string(transition, "from", source, transition_path),
            source,
            f"{transition_path}.from",
        )
        target_status = _coerce_gap_status(
            _required_string(transition, "to", source, transition_path),
            source,
            f"{transition_path}.to",
        )
        edge = (source_status, target_status)
        if source_status is target_status:
            raise _invalid(source, transition_path, "self-transitions are not allowed")
        if edge in edges:
            raise _invalid(source, transition_path, f"duplicate transition {edge}")
        edges.add(edge)
        transitions.append(
            TransitionRule(
                source=source_status,
                target=target_status,
                required_checks=_required_string_tuple(
                    transition, "required_checks", source, transition_path
                ),
                requires_new_candidate_version=_required_bool(
                    transition,
                    "requires_new_candidate_version",
                    source,
                    transition_path,
                ),
            )
        )

    direct_promotion = (GapStatus.PROPOSED, GapStatus.VERIFIED_OPEN)
    if direct_promotion in edges:
        raise _invalid(
            source,
            "policy.gap_lifecycle.transitions",
            "direct proposed-to-verified_open promotion is prohibited",
        )
    if edges != _REQUIRED_TRANSITIONS:
        missing = sorted(_REQUIRED_TRANSITIONS - edges, key=str)
        unexpected = sorted(edges - _REQUIRED_TRANSITIONS, key=str)
        raise _invalid(
            source,
            "policy.gap_lifecycle.transitions",
            f"missing {missing}; unexpected {unexpected}",
        )
    for transition in transitions:
        if transition.source in _REASSESSMENT_SOURCES:
            if transition.target is not GapStatus.VERIFICATION_IN_PROGRESS:
                raise _invalid(
                    source,
                    "policy.gap_lifecycle.transitions",
                    f"{transition.source.value} may only be reassessed through "
                    "verification_in_progress",
                )
            if not transition.requires_new_candidate_version:
                raise _invalid(
                    source,
                    "policy.gap_lifecycle.transitions",
                    f"reassessment from {transition.source.value} must require a new "
                    "candidate version",
                )
        if (
            parsed_statuses[transition.source].terminal_for_candidate_version
            and not transition.requires_new_candidate_version
        ):
            raise _invalid(
                source,
                "policy.gap_lifecycle.transitions",
                f"outgoing transition from terminal candidate-version status "
                f"{transition.source.value} must require a new candidate version",
            )

    edge_to_rule = {
        (transition.source, transition.target): transition
        for transition in transitions
    }
    verified_transition = edge_to_rule[
        (GapStatus.VERIFICATION_IN_PROGRESS, GapStatus.VERIFIED_OPEN)
    ]
    _require_members(
        verified_transition.required_checks,
        set(verified_checks),
        source,
        "policy.gap_lifecycle.transitions[verification_in_progress->verified_open]"
        ".required_checks",
    )
    resolved_transition = edge_to_rule[
        (GapStatus.VERIFICATION_IN_PROGRESS, GapStatus.RESOLVED)
    ]
    _require_members(
        resolved_transition.required_checks,
        set(resolution_checks),
        source,
        "policy.gap_lifecycle.transitions[verification_in_progress->resolved]"
        ".required_checks",
    )
    return (
        MappingProxyType(parsed_statuses),
        initial_status,
        state_history_is_append_only,
        human_judgment_is_status,
        tuple(transitions),
        verified_checks,
        resolution_checks,
    )


def _parse_coverage(
    payload: Mapping[str, Any], source: str
) -> tuple[Mapping[str, str], tuple[str, ...], bool, str, str]:
    raw = _required_mapping(payload, "coverage", source, "policy")
    adequate_is_complete = _required_bool(
        raw,
        "adequate_for_rule_is_global_completeness",
        source,
        "policy.coverage",
    )
    _expect_bool(
        adequate_is_complete,
        False,
        source,
        "policy.coverage.adequate_for_rule_is_global_completeness",
    )
    statuses = _required_mapping(raw, "statuses", source, "policy.coverage")
    _require_exact_keys(
        statuses,
        _REQUIRED_COVERAGE_STATUSES,
        source,
        "policy.coverage.statuses",
    )
    parsed_statuses: dict[str, str] = {}
    for status_id, raw_status in statuses.items():
        status_path = f"policy.coverage.statuses.{status_id}"
        status = _mapping(raw_status, source, status_path)
        parsed_statuses[status_id] = _required_string(
            status, "definition", source, status_path
        )
    missing_edge_meaning = _required_string(
        raw, "missing_edge_meaning", source, "policy.coverage"
    )
    if missing_edge_meaning != _SAFE_MISSING_EDGE_MEANING:
        raise _invalid(
            source,
            "policy.coverage.missing_edge_meaning",
            f"must be {_SAFE_MISSING_EDGE_MEANING!r}",
        )
    unknown_availability_policy = _required_string(
        raw, "unknown_availability_policy", source, "policy.coverage"
    )
    if unknown_availability_policy != _SAFE_UNKNOWN_AVAILABILITY_POLICY:
        raise _invalid(
            source,
            "policy.coverage.unknown_availability_policy",
            f"must be {_SAFE_UNKNOWN_AVAILABILITY_POLICY!r}",
        )
    return (
        MappingProxyType(parsed_statuses),
        _required_string_tuple(raw, "required_dimensions", source, "policy.coverage"),
        adequate_is_complete,
        missing_edge_meaning,
        unknown_availability_policy,
    )


def _parse_assessment_dimensions(
    payload: Mapping[str, Any], source: str
) -> tuple[
    Mapping[str, AssessmentDimension],
    bool,
    tuple[tuple[str, str], ...],
]:
    raw = _required_mapping(payload, "assessment_dimensions", source, "policy")
    must_remain_separate = _required_bool(
        raw,
        "must_remain_separate",
        source,
        "policy.assessment_dimensions",
    )
    _expect_bool(
        must_remain_separate,
        True,
        source,
        "policy.assessment_dimensions.must_remain_separate",
    )
    dimensions = _required_mapping(
        raw, "dimensions", source, "policy.assessment_dimensions"
    )
    _require_members(
        dimensions,
        _REQUIRED_ASSESSMENT_DIMENSIONS,
        source,
        "policy.assessment_dimensions.dimensions",
    )
    parsed_dimensions: dict[str, AssessmentDimension] = {}
    for dimension_id, raw_dimension in dimensions.items():
        dimension_path = f"policy.assessment_dimensions.dimensions.{dimension_id}"
        dimension = _mapping(raw_dimension, source, dimension_path)
        kind_value = _required_string(dimension, "kind", source, dimension_path)
        try:
            kind = AssessmentDimensionKind(kind_value)
        except ValueError as error:
            allowed = [item.value for item in AssessmentDimensionKind]
            raise _invalid(
                source,
                f"{dimension_path}.kind",
                f"unknown assessment kind {kind_value!r}; expected {allowed}",
            ) from error
        expected_kind = _REQUIRED_ASSESSMENT_KINDS.get(dimension_id)
        if expected_kind is not None and kind is not expected_kind:
            raise _invalid(
                source,
                f"{dimension_path}.kind",
                f"must be {expected_kind.value!r}",
            )
        parsed_dimensions[dimension_id] = AssessmentDimension(
            definition=_required_string(dimension, "definition", source, dimension_path),
            kind=kind,
        )

    raw_derivations = raw.get("forbidden_derivations")
    if not isinstance(raw_derivations, list) or not raw_derivations:
        raise _invalid(
            source,
            "policy.assessment_dimensions.forbidden_derivations",
            "expected a non-empty list",
        )
    derivations: list[tuple[str, str]] = []
    for index, raw_derivation in enumerate(raw_derivations):
        derivation_path = (
            f"policy.assessment_dimensions.forbidden_derivations[{index}]"
        )
        derivation = _mapping(raw_derivation, source, derivation_path)
        pair = (
            _required_string(derivation, "from", source, derivation_path),
            _required_string(derivation, "to", source, derivation_path),
        )
        if pair in derivations:
            raise _invalid(source, derivation_path, f"duplicate derivation {pair}")
        derivations.append(pair)
    _require_members(
        derivations,
        _REQUIRED_FORBIDDEN_DERIVATIONS,
        source,
        "policy.assessment_dimensions.forbidden_derivations",
    )
    return (
        MappingProxyType(parsed_dimensions),
        must_remain_separate,
        tuple(derivations),
    )


def _parse_human_review(
    payload: Mapping[str, Any], source: str
) -> HumanReviewPolicy:
    raw = _required_mapping(payload, "human_review", source, "policy")
    triggers = _required_mapping(
        raw, "mandatory_triggers", source, "policy.human_review"
    )
    _require_members(
        triggers,
        _REQUIRED_HUMAN_REVIEW_TRIGGERS,
        source,
        "policy.human_review.mandatory_triggers",
    )
    definitions: dict[str, str] = {}
    for trigger_id, raw_trigger in triggers.items():
        trigger_path = f"policy.human_review.mandatory_triggers.{trigger_id}"
        trigger = _mapping(raw_trigger, source, trigger_path)
        definitions[trigger_id] = _required_string(
            trigger, "definition", source, trigger_path
        )
    blockers = _required_string_tuple(
        raw, "cannot_be_waived_by_review", source, "policy.human_review"
    )
    _require_members(
        blockers,
        _REQUIRED_UNWAIVABLE_BLOCKERS,
        source,
        "policy.human_review.cannot_be_waived_by_review",
    )
    return HumanReviewPolicy(
        mandatory_triggers=tuple(definitions),
        trigger_definitions=MappingProxyType(definitions),
        cannot_be_waived_by_review=blockers,
    )


def _parse_mantis(
    payload: Mapping[str, Any], source: str
) -> MantisInterpretationPolicy:
    raw = _required_mapping(payload, "mantis_interpretation", source, "policy")
    is_evidence = _required_bool(
        raw, "is_evidence", source, "policy.mantis_interpretation"
    )
    may_create_candidate = _required_bool(
        raw, "may_create_gap_candidate", source, "policy.mantis_interpretation"
    )
    resulting_status = _coerce_gap_status(
        _required_string(
            raw,
            "resulting_gap_status_after_independent_signal",
            source,
            "policy.mantis_interpretation",
        ),
        source,
        "policy.mantis_interpretation.resulting_gap_status_after_independent_signal",
    )
    may_set_verified = _required_bool(
        raw, "may_set_verified_status", source, "policy.mantis_interpretation"
    )
    requires_signal = _required_bool(
        raw,
        "requires_independent_deterministic_signal",
        source,
        "policy.mantis_interpretation",
    )
    requires_verification = _required_bool(
        raw,
        "requires_standard_counterretrieval_and_verification",
        source,
        "policy.mantis_interpretation",
    )
    _expect_bool(
        is_evidence,
        False,
        source,
        "policy.mantis_interpretation.is_evidence",
    )
    _expect_bool(
        may_create_candidate,
        False,
        source,
        "policy.mantis_interpretation.may_create_gap_candidate",
    )
    if resulting_status is not GapStatus.PROPOSED:
        raise _invalid(
            source,
            "policy.mantis_interpretation"
            ".resulting_gap_status_after_independent_signal",
            "must be 'proposed'",
        )
    _expect_bool(
        may_set_verified,
        False,
        source,
        "policy.mantis_interpretation.may_set_verified_status",
    )
    _expect_bool(
        requires_signal,
        True,
        source,
        "policy.mantis_interpretation.requires_independent_deterministic_signal",
    )
    _expect_bool(
        requires_verification,
        True,
        source,
        "policy.mantis_interpretation.requires_standard_counterretrieval_and_verification",
    )
    provenance_fields = _required_string_tuple(
        raw,
        "required_provenance_fields",
        source,
        "policy.mantis_interpretation",
    )
    _require_members(
        provenance_fields,
        _REQUIRED_MANTIS_PROVENANCE_FIELDS,
        source,
        "policy.mantis_interpretation.required_provenance_fields",
    )
    return MantisInterpretationPolicy(
        is_evidence=is_evidence,
        may_create_gap_candidate=may_create_candidate,
        resulting_gap_status_after_independent_signal=resulting_status,
        may_set_verified_status=may_set_verified,
        requires_independent_deterministic_signal=requires_signal,
        requires_standard_counterretrieval_and_verification=requires_verification,
        required_provenance_fields=provenance_fields,
    )


def parse_scientific_validity_policy(
    payload: Mapping[str, Any],
    *,
    source: str = "scientific validity policy",
) -> ScientificValidityPolicy:
    """Parse and semantically validate a scientific-validity policy object."""
    root = _mapping(payload, source, "policy")
    _require_exact_keys(root, _TOP_LEVEL_KEYS, source, "policy")
    schema_version = _required_string(root, "schema_version", source, "policy")
    policy_version = _required_string(root, "policy_version", source, "policy")
    for field_name, version in (
        ("schema_version", schema_version),
        ("policy_version", policy_version),
    ):
        if not _SEMANTIC_VERSION.fullmatch(version):
            raise _invalid(
                source,
                f"policy.{field_name}",
                "expected a semantic version such as '1.0.0'",
            )
    if schema_version.split(".", maxsplit=1)[0] != "1":
        raise _invalid(
            source,
            "policy.schema_version",
            f"unsupported schema major version {schema_version!r}",
        )
    policy_id = _required_string(root, "policy_id", source, "policy")
    if policy_id != "scientific_validity":
        raise _invalid(
            source,
            "policy.policy_id",
            "must be 'scientific_validity'",
        )
    scope = _required_string(root, "scope", source, "policy")
    if scope != "cross_domain":
        raise _invalid(source, "policy.scope", "must be 'cross_domain'")

    terminology = _parse_terminology(root, source)
    open_world = _parse_open_world(root, source)
    (
        claim_outcomes,
        outcomes_mutually_exclusive,
        comparability_required,
        support_is_truth,
    ) = _parse_claim_outcomes(root, source)
    (
        statuses,
        initial_status,
        state_history_is_append_only,
        human_judgment_is_status,
        transitions,
        verified_checks,
        resolution_checks,
    ) = _parse_gap_lifecycle(root, source)
    (
        coverage_statuses,
        coverage_dimensions,
        adequate_is_complete,
        missing_edge_meaning,
        unknown_availability_policy,
    ) = _parse_coverage(root, source)
    (
        assessment_dimensions,
        assessments_separate,
        forbidden_derivations,
    ) = _parse_assessment_dimensions(root, source)

    return ScientificValidityPolicy(
        schema_version=schema_version,
        policy_id=policy_id,
        policy_version=policy_version,
        scope=scope,
        terminology=terminology,
        claim_outcomes=claim_outcomes,
        claim_outcomes_are_mutually_exclusive=outcomes_mutually_exclusive,
        comparability_required_for_contradiction=comparability_required,
        support_is_scientific_truth=support_is_truth,
        gap_statuses=statuses,
        initial_gap_status=initial_status,
        state_history_is_append_only=state_history_is_append_only,
        human_judgment_is_gap_status=human_judgment_is_status,
        transitions=transitions,
        verified_open_required_checks=verified_checks,
        resolution_required_checks=resolution_checks,
        coverage_statuses=coverage_statuses,
        coverage_required_dimensions=coverage_dimensions,
        adequate_coverage_is_global_completeness=adequate_is_complete,
        missing_edge_meaning=missing_edge_meaning,
        unknown_availability_policy=unknown_availability_policy,
        assessment_dimensions=assessment_dimensions,
        assessment_dimensions_must_remain_separate=assessments_separate,
        forbidden_assessment_derivations=forbidden_derivations,
        open_world=open_world,
        human_review=_parse_human_review(root, source),
        mantis_interpretation=_parse_mantis(root, source),
    )


def scientific_validity_policy_to_dict(
    policy: ScientificValidityPolicy,
) -> dict[str, Any]:
    """Return a normalized, parseable representation of a validated policy."""
    return {
        "schema_version": policy.schema_version,
        "policy_id": policy.policy_id,
        "policy_version": policy.policy_version,
        "scope": policy.scope,
        "terminology": {
            term_id: {
                "definition": term.definition,
                "required_qualifiers": list(term.required_qualifiers),
                "prohibited_inferences": list(term.prohibited_inferences),
            }
            for term_id, term in policy.terminology.items()
        },
        "open_world": {
            "missing_representation_is_global_absence": (
                policy.open_world.missing_representation_is_global_absence
            ),
            "zero_results_are_global_absence": (
                policy.open_world.zero_results_are_global_absence
            ),
            "adequate_coverage_is_global_completeness": (
                policy.open_world.adequate_coverage_is_global_completeness
            ),
            "historical_reconstruction_without_snapshot_is_certain": (
                policy.open_world.historical_reconstruction_without_snapshot_is_certain
            ),
            "qualification_required_phrases": list(
                policy.open_world.qualification_required_phrases
            ),
            "always_prohibited_phrases": list(
                policy.open_world.always_prohibited_phrases
            ),
            "required_absence_qualifiers": list(
                policy.open_world.required_absence_qualifiers
            ),
            "preferred_absence_language": (
                policy.open_world.preferred_absence_language
            ),
        },
        "claim_verification": {
            "outcomes_are_mutually_exclusive": (
                policy.claim_outcomes_are_mutually_exclusive
            ),
            "comparability_required_for_contradiction": (
                policy.comparability_required_for_contradiction
            ),
            "support_is_scientific_truth": policy.support_is_scientific_truth,
            "outcomes": {
                outcome.value: {"definition": definition}
                for outcome, definition in policy.claim_outcomes.items()
            },
        },
        "gap_lifecycle": {
            "initial_status": policy.initial_gap_status.value,
            "state_history_is_append_only": policy.state_history_is_append_only,
            "human_judgment_is_gap_status": policy.human_judgment_is_gap_status,
            "statuses": {
                status.value: {
                    "definition": state.definition,
                    "terminal_for_candidate_version": (
                        state.terminal_for_candidate_version
                    ),
                }
                for status, state in policy.gap_statuses.items()
            },
            "verified_open_required_checks": list(
                policy.verified_open_required_checks
            ),
            "resolution_required_checks": list(policy.resolution_required_checks),
            "transitions": [
                {
                    "from": transition.source.value,
                    "to": transition.target.value,
                    "required_checks": list(transition.required_checks),
                    "requires_new_candidate_version": (
                        transition.requires_new_candidate_version
                    ),
                }
                for transition in policy.transitions
            ],
        },
        "coverage": {
            "adequate_for_rule_is_global_completeness": (
                policy.adequate_coverage_is_global_completeness
            ),
            "statuses": {
                status_id: {"definition": definition}
                for status_id, definition in policy.coverage_statuses.items()
            },
            "required_dimensions": list(policy.coverage_required_dimensions),
            "missing_edge_meaning": policy.missing_edge_meaning,
            "unknown_availability_policy": policy.unknown_availability_policy,
        },
        "assessment_dimensions": {
            "must_remain_separate": (
                policy.assessment_dimensions_must_remain_separate
            ),
            "dimensions": {
                dimension_id: {
                    "kind": dimension.kind.value,
                    "definition": dimension.definition,
                }
                for dimension_id, dimension in policy.assessment_dimensions.items()
            },
            "forbidden_derivations": [
                {"from": source, "to": target}
                for source, target in policy.forbidden_assessment_derivations
            ],
        },
        "human_review": {
            "mandatory_triggers": {
                trigger_id: {"definition": definition}
                for trigger_id, definition in (
                    policy.human_review.trigger_definitions.items()
                )
            },
            "cannot_be_waived_by_review": list(
                policy.human_review.cannot_be_waived_by_review
            ),
        },
        "mantis_interpretation": {
            "is_evidence": policy.mantis_interpretation.is_evidence,
            "may_create_gap_candidate": (
                policy.mantis_interpretation.may_create_gap_candidate
            ),
            "resulting_gap_status_after_independent_signal": (
                policy.mantis_interpretation
                .resulting_gap_status_after_independent_signal.value
            ),
            "may_set_verified_status": (
                policy.mantis_interpretation.may_set_verified_status
            ),
            "requires_independent_deterministic_signal": (
                policy.mantis_interpretation
                .requires_independent_deterministic_signal
            ),
            "requires_standard_counterretrieval_and_verification": (
                policy.mantis_interpretation
                .requires_standard_counterretrieval_and_verification
            ),
            "required_provenance_fields": list(
                policy.mantis_interpretation.required_provenance_fields
            ),
        },
    }


def load_scientific_validity_policy(
    path: Path = DEFAULT_SCIENTIFIC_VALIDITY_POLICY_PATH,
) -> ScientificValidityPolicy:
    """Load and semantically validate a scientific-validity policy YAML file."""
    resolved_path = Path(path)
    try:
        payload = read_yaml_object(resolved_path)
    except (OSError, ValueError, yaml.YAMLError) as error:
        raise ValidationError(
            f"Could not load scientific-validity policy {resolved_path}: {error}"
        ) from error
    return parse_scientific_validity_policy(payload, source=str(resolved_path))


def gap_transition_rule(
    policy: ScientificValidityPolicy,
    current: GapStatus | str,
    target: GapStatus | str,
) -> TransitionRule | None:
    """Return the declared rule for a known transition, or ``None`` if disallowed."""
    current_status = _coerce_gap_status(current, "gap transition", "current")
    target_status = _coerce_gap_status(target, "gap transition", "target")
    for transition in policy.transitions:
        if transition.source is current_status and transition.target is target_status:
            return transition
    return None


def is_gap_transition_allowed(
    policy: ScientificValidityPolicy,
    current: GapStatus | str,
    target: GapStatus | str,
) -> bool:
    """Return whether the policy declares a transition between two known states."""
    return gap_transition_rule(policy, current, target) is not None


def validate_gap_transition(
    policy: ScientificValidityPolicy,
    current: GapStatus | str,
    target: GapStatus | str,
    *,
    completed_checks: Iterable[str] = (),
    new_candidate_version: bool = False,
) -> TransitionRule:
    """Validate one lifecycle transition and return its governing rule."""
    current_status = _coerce_gap_status(current, "gap transition", "current")
    target_status = _coerce_gap_status(target, "gap transition", "target")
    rule = gap_transition_rule(policy, current_status, target_status)
    if rule is None:
        raise ValidationError(
            "Gap transition is not allowed: "
            f"{current_status.value} -> {target_status.value}"
        )
    if isinstance(completed_checks, (str, bytes)):
        raise ValidationError(
            "Gap transition completed_checks must be an iterable of ids"
        )
    try:
        completed = list(completed_checks)
    except TypeError as error:
        raise ValidationError(
            "Gap transition completed_checks must be an iterable of ids"
        ) from error
    if not all(isinstance(item, str) and item.strip() for item in completed):
        raise ValidationError(
            "Gap transition completed_checks contains an invalid id"
        )
    checked = set(completed)
    missing = [check for check in rule.required_checks if check not in checked]
    if missing:
        raise ValidationError(
            f"Gap transition {current_status.value} -> {target_status.value} "
            f"is missing required checks: {missing}"
        )
    if not isinstance(new_candidate_version, bool):
        raise ValidationError("Gap transition new_candidate_version must be a boolean")
    if rule.requires_new_candidate_version and not new_candidate_version:
        raise ValidationError(
            f"Gap transition {current_status.value} -> {target_status.value} "
            "requires a new candidate version"
        )
    return rule


def _contains_phrase(text: str, phrase: str) -> bool:
    pattern = (
        r"(?<!\w)"
        + re.escape(phrase.casefold()).replace(r"\ ", r"\s+")
        + r"(?!\w)"
    )
    return re.search(pattern, text.casefold()) is not None


def _qualifier_has_value(qualifiers: Mapping[str, Any], key: str) -> bool:
    if key not in qualifiers:
        return False
    value = qualifiers[key]
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, tuple, set, dict)):
        return bool(value)
    return False


def _absence_qualifier_issues(
    policy: ScientificValidityPolicy,
    qualifiers: Mapping[str, Any],
) -> tuple[list[str], list[str]]:
    missing: list[str] = []
    invalid: list[str] = []
    string_fields = {"corpus_snapshot_id", "corpus_scope", "as_of"}
    for key in policy.open_world.required_absence_qualifiers:
        if key not in qualifiers:
            missing.append(key)
            continue
        value = qualifiers[key]
        if key in string_fields:
            valid = isinstance(value, str) and bool(value.strip())
        elif key == "searched_sources":
            valid = (
                isinstance(value, list)
                and bool(value)
                and all(isinstance(item, str) and item.strip() for item in value)
            )
        elif key == "coverage_status":
            valid = isinstance(value, str) and value in policy.coverage_statuses
        else:
            valid = _qualifier_has_value(qualifiers, key)
        if not valid:
            invalid.append(key)
    return missing, invalid


def validate_gap_language(
    policy: ScientificValidityPolicy,
    text: str,
    *,
    qualifiers: Mapping[str, Any] | None = None,
) -> None:
    """Reject prohibited or unqualified open-world absence language."""
    if not isinstance(text, str) or not text.strip():
        raise ValidationError("Gap language must be a non-empty string")
    for phrase in policy.open_world.always_prohibited_phrases:
        if _contains_phrase(text, phrase):
            raise ValidationError(
                f"Gap language uses always-prohibited phrase {phrase!r}"
            )
    matched = [
        phrase
        for phrase in policy.open_world.qualification_required_phrases
        if _contains_phrase(text, phrase)
    ]
    if not matched:
        return
    qualifier_values = qualifiers if qualifiers is not None else {}
    if not isinstance(qualifier_values, Mapping):
        raise ValidationError("Gap language qualifiers must be an object")
    missing, invalid = _absence_qualifier_issues(policy, qualifier_values)
    if missing or invalid:
        problems: list[str] = []
        if missing:
            problems.append(f"missing {missing}")
        if invalid:
            problems.append(f"invalid {invalid}")
        raise ValidationError(
            f"Gap language {matched!r} requires qualified corpus context; "
            + "; ".join(problems)
        )


def mandatory_human_review_reasons(
    policy: ScientificValidityPolicy,
    triggers: Iterable[str],
) -> tuple[str, ...]:
    """Validate trigger ids and return mandatory-review reasons in policy order."""
    if isinstance(triggers, (str, bytes)):
        raise ValidationError("Human-review triggers must be an iterable of ids")
    try:
        requested = list(triggers)
    except TypeError as error:
        raise ValidationError(
            "Human-review triggers must be an iterable of ids"
        ) from error
    if not all(isinstance(item, str) and item.strip() for item in requested):
        raise ValidationError("Human-review triggers contain an invalid id")
    unknown = sorted(set(requested) - set(policy.human_review.mandatory_triggers))
    if unknown:
        raise ValidationError(f"Unknown mandatory human-review triggers: {unknown}")
    requested_set = set(requested)
    return tuple(
        trigger
        for trigger in policy.human_review.mandatory_triggers
        if trigger in requested_set
    )
