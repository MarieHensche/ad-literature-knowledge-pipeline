from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest

from ad_lit_pipeline.core.errors import ValidationError
from ad_lit_pipeline.io.yaml_io import read_yaml_object
from ad_lit_pipeline.validity import (
    DEFAULT_SCIENTIFIC_VALIDITY_POLICY_PATH,
    AssessmentDimensionKind,
    ClaimVerificationOutcome,
    GapStatus,
    gap_transition_rule,
    is_gap_transition_allowed,
    load_scientific_validity_policy,
    mandatory_human_review_reasons,
    parse_scientific_validity_policy,
    scientific_validity_policy_to_dict,
    validate_gap_language,
    validate_gap_transition,
)


EXPECTED_TERMS = {
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

EXPECTED_GAP_STATUSES = (
    "proposed",
    "verification_in_progress",
    "verified_open",
    "refuted",
    "resolved",
    "uncertain",
    "terminology_artifact",
    "duplicate",
)

EXPECTED_CLAIM_OUTCOMES = (
    "supported",
    "contradicted",
    "insufficient",
    "uncertain",
)

EXPECTED_TRANSITIONS = (
    ("proposed", "verification_in_progress"),
    ("verification_in_progress", "verified_open"),
    ("verification_in_progress", "refuted"),
    ("verification_in_progress", "resolved"),
    ("verification_in_progress", "uncertain"),
    ("verification_in_progress", "terminology_artifact"),
    ("verification_in_progress", "duplicate"),
    ("uncertain", "verification_in_progress"),
    ("verified_open", "verification_in_progress"),
    ("refuted", "verification_in_progress"),
    ("resolved", "verification_in_progress"),
    ("terminology_artifact", "verification_in_progress"),
    ("duplicate", "verification_in_progress"),
)

EXPECTED_QUALIFICATION_REQUIRED_PHRASES = {
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

EXPECTED_ASSESSMENT_DIMENSIONS = {
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

EXPECTED_FORBIDDEN_DERIVATIONS = {
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

EXPECTED_REVIEW_TRIGGERS = (
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
)

EXPECTED_UNWAIVABLE_BLOCKERS = {
    "missing_stable_id",
    "missing_provenance",
    "invalid_schema",
    "orphan_reference",
    "missing_corpus_snapshot",
    "missing_as_of",
    "missing_independent_deterministic_signal",
}


@pytest.fixture
def policy():
    return load_scientific_validity_policy()


def policy_payload() -> dict[str, object]:
    return deepcopy(read_yaml_object(DEFAULT_SCIENTIFIC_VALIDITY_POLICY_PATH))


def absence_qualifiers() -> dict[str, object]:
    return {
        "corpus_snapshot_id": "snapshot_1",
        "corpus_scope": "Declared primary-study corpus",
        "as_of": "2026-08-26",
        "searched_sources": ["openalex"],
        "coverage_status": "adequate_for_rule",
    }


def test_default_policy_loads_as_cross_domain_versioned_policy(policy) -> None:
    assert DEFAULT_SCIENTIFIC_VALIDITY_POLICY_PATH == (
        Path(__file__).resolve().parents[1]
        / "configs"
        / "policies"
        / "scientific_validity_v1.yaml"
    )
    assert policy.schema_version == "1.0.0"
    assert policy.policy_id == "scientific_validity"
    assert policy.policy_version == "1.0.0"
    assert policy.scope == "cross_domain"


def test_policy_freezes_exact_terminology_and_controlled_states(policy) -> None:
    assert set(policy.terminology) == EXPECTED_TERMS
    assert tuple(status.value for status in policy.gap_statuses) == (
        EXPECTED_GAP_STATUSES
    )
    assert tuple(outcome.value for outcome in policy.claim_outcomes) == (
        EXPECTED_CLAIM_OUTCOMES
    )
    assert policy.initial_gap_status is GapStatus.PROPOSED
    assert policy.state_history_is_append_only is True
    assert policy.human_judgment_is_gap_status is False
    assert "accepted" not in EXPECTED_GAP_STATUSES
    assert "rejected" not in EXPECTED_GAP_STATUSES
    assert "needs_human_review" not in EXPECTED_CLAIM_OUTCOMES


def test_gap_terms_encode_scope_time_and_distinct_terminal_meanings(policy) -> None:
    candidate = policy.terminology["gap_candidate"]
    verified = policy.terminology["verified_gap"]
    refuted = policy.terminology["refuted_gap"]
    resolved = policy.terminology["resolved_gap"]
    sparse = policy.terminology["corpus_sparse"]
    as_of = policy.terminology["as_of"]

    assert {"corpus_snapshot_id", "corpus_scope", "as_of"}.issubset(
        candidate.required_qualifiers
    )
    assert {"verification_dossier_id", "coverage_status", "as_of"}.issubset(
        verified.required_qualifiers
    )
    assert "original_as_of" in refuted.required_qualifiers
    assert "resolution_as_of" in resolved.required_qualifiers
    assert refuted.definition != resolved.definition
    assert "original" in refuted.definition.casefold()
    assert "later" in resolved.definition.casefold()
    assert {
        "corpus_snapshot_id",
        "query_or_cell",
        "observed_count",
        "threshold",
        "coverage_status",
    }.issubset(sparse.required_qualifiers)
    assert {"cutoff_date", "availability_date_rule", "corpus_snapshot_id"} == set(
        as_of.required_qualifiers
    )
    assert "inclusive" in as_of.definition.casefold()


def test_claim_outcomes_keep_evidence_checks_scientifically_bounded(policy) -> None:
    assert policy.claim_outcomes_are_mutually_exclusive is True
    assert policy.comparability_required_for_contradiction is True
    assert policy.support_is_scientific_truth is False
    assert "passage_ids" in policy.terminology["supported"].required_qualifiers
    assert "comparability_key" in (
        policy.terminology["contradicted"].required_qualifiers
    )
    assert "global_nonexistence" in (
        policy.terminology["insufficient"].prohibited_inferences
    )
    assert set(policy.terminology["uncertain"].required_qualifiers) == {
        "uncertainty_context",
        "subject_id",
        "uncertainty_reasons",
        "unresolved_checks",
    }


def test_claim_outcomes_and_human_review_are_orthogonal(policy) -> None:
    assert ClaimVerificationOutcome.UNCERTAIN in policy.claim_outcomes
    assert "needs_human_review" not in {
        outcome.value for outcome in policy.claim_outcomes
    }
    assert "verifier_disagreement" in policy.human_review.mandatory_triggers
    assert "high_stakes_claim" in policy.human_review.mandatory_triggers


def test_open_world_policy_never_turns_absence_signals_into_global_facts(
    policy,
) -> None:
    assert policy.open_world.missing_representation_is_global_absence is False
    assert policy.open_world.zero_results_are_global_absence is False
    assert policy.open_world.adequate_coverage_is_global_completeness is False
    assert (
        policy.open_world.historical_reconstruction_without_snapshot_is_certain
        is False
    )
    assert policy.adequate_coverage_is_global_completeness is False
    assert policy.missing_edge_meaning == "Not represented in this corpus snapshot."
    assert policy.unknown_availability_policy == (
        "exclude_from_temporal_claim_and_mark_uncertain"
    )
    assert set(policy.open_world.qualification_required_phrases) == (
        EXPECTED_QUALIFICATION_REQUIRED_PHRASES
    )
    assert set(policy.open_world.always_prohibited_phrases) == {
        "proven gap",
        "scientifically validated gap",
    }
    assert set(policy.open_world.required_absence_qualifiers) == {
        "corpus_snapshot_id",
        "corpus_scope",
        "as_of",
        "searched_sources",
        "coverage_status",
    }


@pytest.mark.parametrize(
    "text",
    [
        "This question has not studied any population.",
        "This population has not been studied.",
        "This population was never studied.",
        "The combination is unstudied.",
        "This outcome has not been investigated.",
        "This outcome has never been investigated.",
        "No evidence exists for this method.",
        "No studies have evaluated this comparison.",
        "No study has evaluated this comparison.",
        "No studies exist for this intervention.",
        "No research exists on this transfer.",
        "No literature exists for this population.",
        "No prior work exists on this pairing.",
        "There is no published evidence for this method.",
        "Evidence is absent for this outcome.",
        "No eligible records met the criteria.",
        "No records were found for this query.",
        "NO   STUDIES   HAVE compared these methods.",
    ],
)
def test_common_absence_language_cannot_bypass_qualification(
    policy,
    text: str,
) -> None:
    with pytest.raises(ValidationError, match="requires qualified corpus context"):
        validate_gap_language(policy, text)


@pytest.mark.parametrize(
    "text",
    [
        "This population was not studied in the declared snapshot.",
        "The combination is unstudied in the declared snapshot.",
        "No evidence exists in the declared snapshot.",
    ],
)
def test_absence_language_is_allowed_only_with_complete_qualifiers(
    policy,
    text: str,
) -> None:
    validate_gap_language(policy, text, qualifiers=absence_qualifiers())

    incomplete = absence_qualifiers()
    del incomplete["as_of"]
    with pytest.raises(ValidationError, match=r"missing \['as_of'\]"):
        validate_gap_language(policy, text, qualifiers=incomplete)


@pytest.mark.parametrize(
    ("field", "invalid_value"),
    [
        ("corpus_snapshot_id", ["snapshot_1"]),
        ("corpus_scope", ""),
        ("as_of", 20260826),
        ("as_of", False),
        ("searched_sources", "openalex"),
        ("searched_sources", []),
        ("searched_sources", ["openalex", ""]),
        ("coverage_status", "complete"),
    ],
)
def test_absence_qualifiers_require_safe_types_and_coverage_literals(
    policy,
    field: str,
    invalid_value: object,
) -> None:
    qualifiers = absence_qualifiers()
    qualifiers[field] = invalid_value

    with pytest.raises(
        ValidationError,
        match=rf"invalid \['{field}'\]",
    ):
        validate_gap_language(
            policy,
            "No studies exist for this question.",
            qualifiers=qualifiers,
        )


def test_every_controlled_coverage_status_is_a_valid_explicit_qualifier(
    policy,
) -> None:
    assert set(policy.coverage_statuses) == {
        "not_assessed",
        "adequate_for_rule",
        "partial",
        "insufficient",
    }
    for coverage_status in policy.coverage_statuses:
        qualifiers = absence_qualifiers()
        qualifiers["coverage_status"] = coverage_status
        validate_gap_language(
            policy,
            "No eligible records met the declared criteria.",
            qualifiers=qualifiers,
        )

@pytest.mark.parametrize(
    "text",
    [
        "This is a proven gap.",
        "This is a scientifically validated gap.",
    ],
)
def test_absolute_gap_language_is_always_prohibited(
    policy,
    text: str,
) -> None:
    with pytest.raises(ValidationError, match="always-prohibited phrase"):
        validate_gap_language(policy, text, qualifiers=absence_qualifiers())


def test_typed_assessment_dimensions_cannot_collapse(policy) -> None:
    assert policy.assessment_dimensions_must_remain_separate is True
    assert {
        dimension_id: dimension.kind
        for dimension_id, dimension in policy.assessment_dimensions.items()
    } == EXPECTED_ASSESSMENT_DIMENSIONS
    assert set(policy.forbidden_assessment_derivations) == (
        EXPECTED_FORBIDDEN_DERIVATIONS
    )
    assert policy.assessment_dimensions["extraction_confidence"].definition != (
        policy.assessment_dimensions["evidence_quality"].definition
    )
    assert policy.assessment_dimensions["reporting_quality"].definition != (
        policy.assessment_dimensions["study_quality"].definition
    )
    assert policy.assessment_dimensions["novelty"].definition != (
        policy.assessment_dimensions["importance"].definition
    )
    assert policy.assessment_dimensions["importance"].definition != (
        policy.assessment_dimensions["feasibility"].definition
    )
def test_policy_declares_only_the_exact_allowed_transition_graph(policy) -> None:
    actual = tuple(
        (transition.source.value, transition.target.value)
        for transition in policy.transitions
    )
    assert actual == EXPECTED_TRANSITIONS

    for source, target in EXPECTED_TRANSITIONS:
        assert is_gap_transition_allowed(policy, source, target) is True
        rule = gap_transition_rule(policy, source, target)
        assert rule is not None
        assert rule.source.value == source
        assert rule.target.value == target


def test_terminal_candidate_version_states_are_exact_and_immutable(policy) -> None:
    terminal_statuses = {
        GapStatus.VERIFIED_OPEN,
        GapStatus.REFUTED,
        GapStatus.RESOLVED,
        GapStatus.UNCERTAIN,
        GapStatus.TERMINOLOGY_ARTIFACT,
        GapStatus.DUPLICATE,
    }

    assert {
        status
        for status, state in policy.gap_statuses.items()
        if state.terminal_for_candidate_version
    } == terminal_statuses
    assert policy.gap_statuses[GapStatus.PROPOSED].terminal_for_candidate_version is (
        False
    )
    assert policy.gap_statuses[
        GapStatus.VERIFICATION_IN_PROGRESS
    ].terminal_for_candidate_version is False
    assert all(
        transition.requires_new_candidate_version
        for transition in policy.transitions
        if transition.source in terminal_statuses
    )


@pytest.mark.parametrize(
    ("source", "target"),
    [
        ("proposed", "verified_open"),
        ("proposed", "resolved"),
        ("uncertain", "verified_open"),
        ("refuted", "verified_open"),
        ("resolved", "verified_open"),
        ("terminology_artifact", "verified_open"),
        ("duplicate", "verified_open"),
    ],
)
def test_policy_forbids_scientific_status_shortcuts(
    policy,
    source: str,
    target: str,
) -> None:
    assert is_gap_transition_allowed(policy, source, target) is False
    with pytest.raises(ValidationError, match="Gap transition is not allowed"):
        validate_gap_transition(policy, source, target)


def test_verified_promotion_requires_every_declared_scientific_check(policy) -> None:
    rule = gap_transition_rule(
        policy,
        GapStatus.VERIFICATION_IN_PROGRESS,
        GapStatus.VERIFIED_OPEN,
    )
    assert rule is not None
    assert rule.required_checks == policy.verified_open_required_checks
    assert {
        "supporting_claims_verified",
        "counterevidence_verified",
        "counterretrieval_complete",
        "synonym_and_indexing_check_complete",
        "adjacent_literature_check_complete",
        "coverage_adequate_for_rule",
    }.issubset(rule.required_checks)

    missing_counterretrieval = set(rule.required_checks) - {
        "counterretrieval_complete"
    }
    with pytest.raises(ValidationError, match="counterretrieval_complete"):
        validate_gap_transition(
            policy,
            GapStatus.VERIFICATION_IN_PROGRESS,
            GapStatus.VERIFIED_OPEN,
            completed_checks=missing_counterretrieval,
        )

    assert validate_gap_transition(
        policy,
        GapStatus.VERIFICATION_IN_PROGRESS,
        GapStatus.VERIFIED_OPEN,
        completed_checks=rule.required_checks,
    ) is rule


@pytest.mark.parametrize(
    "source",
    [
        "uncertain",
        "verified_open",
        "refuted",
        "resolved",
        "terminology_artifact",
        "duplicate",
    ],
)
def test_reassessment_requires_a_new_candidate_version(policy, source: str) -> None:
    rule = gap_transition_rule(policy, source, "verification_in_progress")
    assert rule is not None
    assert rule.requires_new_candidate_version is True

    with pytest.raises(ValidationError, match="requires a new candidate version"):
        validate_gap_transition(
            policy,
            source,
            "verification_in_progress",
            completed_checks=rule.required_checks,
        )

    assert validate_gap_transition(
        policy,
        source,
        "verification_in_progress",
        completed_checks=rule.required_checks,
        new_candidate_version=True,
    ) is rule


@pytest.mark.parametrize(
    ("source", "expected_checks"),
    [
        (
            "terminology_artifact",
            {"artifact_correction_recorded", "candidate_lineage_recorded"},
        ),
        (
            "duplicate",
            {"deduplication_correction_recorded", "candidate_lineage_recorded"},
        ),
    ],
)
def test_artifact_and_duplicate_corrections_are_versioned_and_auditable(
    policy,
    source: str,
    expected_checks: set[str],
) -> None:
    rule = gap_transition_rule(policy, source, "verification_in_progress")

    assert rule is not None
    assert rule.requires_new_candidate_version is True
    assert set(rule.required_checks) == expected_checks


def test_unknown_gap_states_fail_closed(policy) -> None:
    with pytest.raises(ValidationError, match="unknown status 'accepted'"):
        is_gap_transition_allowed(policy, "accepted", "verified_open")
    with pytest.raises(ValidationError, match="unknown status 'accepted'"):
        validate_gap_transition(policy, "proposed", "accepted")


def test_invalid_transition_checks_raise_validation_error_not_type_error(
    policy,
) -> None:
    with pytest.raises(ValidationError, match="contains an invalid id"):
        validate_gap_transition(
            policy,
            GapStatus.PROPOSED,
            GapStatus.VERIFICATION_IN_PROGRESS,
            completed_checks=[["unhashable"]],
        )


def test_human_review_triggers_are_mandatory_ordered_and_deduplicated(
    policy,
) -> None:
    assert policy.human_review.mandatory_triggers == EXPECTED_REVIEW_TRIGGERS
    assert set(policy.human_review.cannot_be_waived_by_review) == (
        EXPECTED_UNWAIVABLE_BLOCKERS
    )

    reasons = mandatory_human_review_reasons(
        policy,
        [
            "high_stakes_claim",
            "verifier_disagreement",
            "high_stakes_claim",
            "central_evidence_inaccessible",
        ],
    )
    assert reasons == (
        "verifier_disagreement",
        "central_evidence_inaccessible",
        "high_stakes_claim",
    )
    assert mandatory_human_review_reasons(policy, []) == ()

    with pytest.raises(ValidationError, match="Unknown mandatory human-review"):
        mandatory_human_review_reasons(policy, ["model_is_confident"])


def test_mantis_interpretation_is_a_hypothesis_not_evidence(policy) -> None:
    mantis = policy.mantis_interpretation

    assert mantis.is_evidence is False
    assert mantis.may_create_gap_candidate is False
    assert (
        mantis.resulting_gap_status_after_independent_signal
        is GapStatus.PROPOSED
    )
    assert mantis.may_set_verified_status is False
    assert mantis.requires_independent_deterministic_signal is True
    assert mantis.requires_standard_counterretrieval_and_verification is True
    assert {
        "interpretation_id",
        "space_id",
        "map_id",
        "map_input_hash",
        "selected_point_ids",
        "actor",
        "prompt_or_action",
        "timestamp",
    }.issubset(mantis.required_provenance_fields)


def test_policy_is_domain_portable_and_contains_no_ad_specific_vocabulary(
    policy,
) -> None:
    policy_text = DEFAULT_SCIENTIFIC_VALIDITY_POLICY_PATH.read_text(
        encoding="utf-8"
    ).casefold()
    for domain_term in (
        "alzheimer",
        "amyloid",
        "dementia",
        "mild cognitive impairment",
    ):
        assert domain_term not in policy_text

    for topic_id in ("early_detection_ad", "ai_in_education"):
        validate_gap_language(
            policy,
            f"A scoped research question for {topic_id} remains uncertain.",
        )
        assert is_gap_transition_allowed(
            policy,
            GapStatus.PROPOSED,
            GapStatus.VERIFICATION_IN_PROGRESS,
        )


def test_parser_rejects_missing_required_policy_section_with_source_context() -> None:
    payload = policy_payload()
    del payload["open_world"]

    with pytest.raises(
        ValidationError,
        match=r"test policy: policy: missing \['open_world'\]",
    ):
        parse_scientific_validity_policy(payload, source="test policy")


def test_parser_rejects_unknown_status_and_direct_verified_shortcut() -> None:
    unknown = policy_payload()
    unknown["gap_lifecycle"]["transitions"][0]["to"] = "accepted"

    with pytest.raises(ValidationError, match="unknown status 'accepted'"):
        parse_scientific_validity_policy(unknown, source="unknown status policy")

    shortcut = policy_payload()
    shortcut["gap_lifecycle"]["transitions"].append(
        {
            "from": "proposed",
            "to": "verified_open",
            "required_checks": ["model_confident"],
            "requires_new_candidate_version": False,
        }
    )
    with pytest.raises(
        ValidationError,
        match="direct proposed-to-verified_open promotion is prohibited",
    ):
        parse_scientific_validity_policy(shortcut, source="shortcut policy")


def test_parser_rejects_assessment_collapse_and_open_world_overclaim() -> None:
    assessments = policy_payload()
    assessments["assessment_dimensions"]["must_remain_separate"] = False

    with pytest.raises(
        ValidationError,
        match=r"assessment_dimensions\.must_remain_separate: must be true",
    ):
        parse_scientific_validity_policy(assessments, source="assessment policy")

    open_world = policy_payload()
    open_world["open_world"]["zero_results_are_global_absence"] = True

    with pytest.raises(
        ValidationError,
        match=r"zero_results_are_global_absence: must be false",
    ):
        parse_scientific_validity_policy(open_world, source="open-world policy")


def test_parser_rejects_wrong_assessment_dimension_kind() -> None:
    payload = policy_payload()
    payload["assessment_dimensions"]["dimensions"]["reporting_quality"][
        "kind"
    ] = "confidence"

    with pytest.raises(
        ValidationError,
        match=r"reporting_quality\.kind: must be 'quality'",
    ):
        parse_scientific_validity_policy(payload, source="typed assessment policy")


@pytest.mark.parametrize(
    ("field", "unsafe_value"),
    [
        ("missing_edge_meaning", "The relationship does not exist."),
        ("unknown_availability_policy", "assume_available_at_publication"),
    ],
)
def test_parser_rejects_unsafe_coverage_literals(
    field: str,
    unsafe_value: str,
) -> None:
    payload = policy_payload()
    payload["coverage"][field] = unsafe_value

    with pytest.raises(
        ValidationError,
        match=rf"coverage\.{field}: must be",
    ):
        parse_scientific_validity_policy(payload, source="unsafe coverage policy")


@pytest.mark.parametrize(
    "qualifier",
    ["uncertainty_context", "subject_id"],
)
def test_parser_requires_uncertainty_context_and_subject(qualifier: str) -> None:
    payload = policy_payload()
    payload["terminology"]["uncertain"]["required_qualifiers"].remove(qualifier)

    with pytest.raises(
        ValidationError,
        match=rf"terminology\.uncertain\.required_qualifiers.*{qualifier}",
    ):
        parse_scientific_validity_policy(payload, source="ambiguous uncertainty policy")


def test_parser_requires_mantis_input_hash_and_independent_signal_blocker() -> None:
    missing_hash = policy_payload()
    missing_hash["mantis_interpretation"]["required_provenance_fields"].remove(
        "map_input_hash"
    )

    with pytest.raises(
        ValidationError,
        match=r"mantis_interpretation\.required_provenance_fields.*map_input_hash",
    ):
        parse_scientific_validity_policy(missing_hash, source="untraceable Mantis policy")

    waivable_signal = policy_payload()
    waivable_signal["human_review"]["cannot_be_waived_by_review"].remove(
        "missing_independent_deterministic_signal"
    )

    with pytest.raises(
        ValidationError,
        match=r"cannot_be_waived_by_review.*missing_independent_deterministic_signal",
    ):
        parse_scientific_validity_policy(waivable_signal, source="waivable signal policy")


def test_parser_rejects_mantis_interpretation_as_candidate_or_verified_gap() -> None:
    creates_candidate = policy_payload()
    creates_candidate["mantis_interpretation"]["may_create_gap_candidate"] = True

    with pytest.raises(
        ValidationError,
        match=r"may_create_gap_candidate: must be false",
    ):
        parse_scientific_validity_policy(
            creates_candidate,
            source="Mantis candidate policy",
        )

    verified = policy_payload()
    verified["mantis_interpretation"][
        "resulting_gap_status_after_independent_signal"
    ] = "verified_open"

    with pytest.raises(
        ValidationError,
        match=r"resulting_gap_status_after_independent_signal: must be 'proposed'",
    ):
        parse_scientific_validity_policy(verified, source="Mantis verified policy")


@pytest.mark.parametrize(
    ("field", "required_value"),
    [
        ("qualification_required_phrases", "not studied"),
        ("always_prohibited_phrases", "proven gap"),
        ("required_absence_qualifiers", "as_of"),
    ],
)
def test_parser_requires_safety_critical_open_world_members(
    field: str,
    required_value: str,
) -> None:
    payload = policy_payload()
    payload["open_world"][field].remove(required_value)

    with pytest.raises(
        ValidationError,
        match=rf"open_world\.{field}: missing required values.*{required_value}",
    ):
        parse_scientific_validity_policy(payload, source="unsafe policy")


def test_parser_enforces_terminal_state_and_append_only_invariants() -> None:
    mutable_terminal = policy_payload()
    mutable_terminal["gap_lifecycle"]["statuses"]["verified_open"][
        "terminal_for_candidate_version"
    ] = False

    with pytest.raises(
        ValidationError,
        match=r"verified_open\.terminal_for_candidate_version: must be true",
    ):
        parse_scientific_validity_policy(
            mutable_terminal,
            source="mutable terminal policy",
        )

    rewrite_history = policy_payload()
    rewrite_history["gap_lifecycle"]["state_history_is_append_only"] = False

    with pytest.raises(
        ValidationError,
        match=r"state_history_is_append_only: must be true",
    ):
        parse_scientific_validity_policy(
            rewrite_history,
            source="rewrite history policy",
        )


def test_loader_wraps_non_object_yaml_with_artifact_path(
    tmp_path: Path,
) -> None:
    path = tmp_path / "invalid_policy.yaml"
    path.write_text("- not\n- an\n- object\n", encoding="utf-8")

    with pytest.raises(ValidationError, match=str(path)):
        load_scientific_validity_policy(path)


def test_normalized_policy_dict_round_trips_through_parser(policy) -> None:
    normalized = scientific_validity_policy_to_dict(policy)

    json.dumps(normalized)
    reparsed = parse_scientific_validity_policy(
        normalized,
        source="serialized scientific-validity policy",
    )

    assert scientific_validity_policy_to_dict(reparsed) == normalized


def test_validity_package_exports_public_policy_api() -> None:
    import ad_lit_pipeline.validity as validity

    expected = {
        "AssessmentDimension",
        "AssessmentDimensionKind",
        "ClaimVerificationOutcome",
        "DEFAULT_SCIENTIFIC_VALIDITY_POLICY_PATH",
        "GapStatus",
        "gap_transition_rule",
        "is_gap_transition_allowed",
        "load_scientific_validity_policy",
        "mandatory_human_review_reasons",
        "parse_scientific_validity_policy",
        "scientific_validity_policy_to_dict",
        "validate_gap_language",
        "validate_gap_transition",
    }

    assert expected.issubset(validity.__all__)
