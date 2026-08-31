from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pytest

from ad_lit_pipeline.io.yaml_io import read_yaml_object, write_yaml_object
from ad_lit_pipeline.steps.collection.generate_topic_contract import (
    normalize_topic_structure,
)
from ad_lit_pipeline.topics.contract import (
    generated_topic_structure_quality_issue_records,
    load_topic_contract,
    validate_topic_contract,
)
from ad_lit_pipeline.topics.policy import (
    DEFAULT_TOPIC_STRUCTURE_POLICY_PATH,
    attach_topic_policy_reference,
    load_topic_structure_policy,
    selected_profile_ids,
)


ROOT = Path(__file__).resolve().parents[1]


def test_default_topic_structure_policy_has_stable_identity() -> None:
    first = load_topic_structure_policy()
    second = load_topic_structure_policy()

    assert first.schema_version == "1.0.0"
    assert first.policy_id == "topic_structure"
    assert first.policy_version == "1.0.0"
    assert first.scope == "cross_domain"
    assert len(first.sha256) == 64
    assert first.sha256 == second.sha256
    assert set(first.profiles) == {
        "computational_methods",
        "alzheimer_disease",
    }


def test_topic_structure_policy_rejects_unknown_fields(tmp_path: Path) -> None:
    payload = read_yaml_object(DEFAULT_TOPIC_STRUCTURE_POLICY_PATH)
    payload["unexpected"] = True
    path = tmp_path / "invalid_policy.yaml"
    write_yaml_object(path, payload)

    with pytest.raises(ValueError, match="unknown keys"):
        load_topic_structure_policy(path)


def test_contract_policy_reference_rejects_hash_drift() -> None:
    policy = load_topic_structure_policy()
    contract = load_topic_contract(ROOT / "configs/topics/ai_in_education.yaml")
    attach_topic_policy_reference(contract, policy, ())
    contract["topic_policy"]["policy_sha256"] = "0" * 64

    with pytest.raises(ValueError, match="policy_sha256"):
        validate_topic_contract(contract, policy)


def test_explicit_profile_override_disables_automatic_profiles() -> None:
    policy = load_topic_structure_policy()
    contract = load_topic_contract(ROOT / "configs/topics/early_detection_ad.yaml")
    contract["topic_policy"] = policy.reference(())

    assert selected_profile_ids(
        policy,
        contract,
        "Alzheimer disease computational methods",
    ) == ()


def test_second_domain_profile_requires_only_policy_configuration(
    tmp_path: Path,
) -> None:
    payload = read_yaml_object(DEFAULT_TOPIC_STRUCTURE_POLICY_PATH)
    payload["secondary_groups"]["tension_headache"] = {
        "label": "Tension-type headache",
        "field": "title",
        "terms": ["tension-type headache", "tension headache"],
        "retrieval_terms": ["tension-type headache", "tension headache"],
        "matching_terms": [
            "tension-type headache",
            "tension headache",
            "tension-type headaches",
        ],
        "excluded_terms": ["head pain"],
    }
    payload["profiles"]["migraine"] = {
        "label": "Migraine",
        "kind": "disease",
        "requires_method_topic": False,
        "signal_terms": ["migraine"],
        "family_terms": [
            "migraine",
            "migraine with aura",
            "migraine without aura",
        ],
        "excluded_terms": ["photophobia"],
        "completion_terms": [
            "migraine",
            "migraine with aura",
            "migraine without aura",
            "chronic migraine",
        ],
        "fallback_secondary_group_ids": ["tension_headache"],
        "anchor_over_kinds": ["method"],
        "guidance": [
            "Use the configured migraine family and adjacent headache group."
        ],
    }
    policy_path = tmp_path / "topic_structure_migraine.yaml"
    write_yaml_object(policy_path, payload)
    policy = load_topic_structure_policy(policy_path)

    contract = deepcopy(
        load_topic_contract(ROOT / "configs/topics/ai_in_education.yaml")
    )
    contract["topic_structure"] = {
        "anchor_topic_id": "computational_methods",
        "anchor_reason": "Initial model draft.",
        "main_topics": [
            {
                "topic_id": "computational_methods",
                "label": "Computational methods",
                "field": "title",
                "terms": ["computational methods", "prediction models"],
                "retrieval_terms": ["computational methods", "prediction models"],
                "matching_terms": ["computational methods", "prediction models"],
            },
            {
                "topic_id": "migraine",
                "label": "Migraine",
                "field": "title",
                "terms": ["migraine", "photophobia"],
                "retrieval_terms": ["migraine", "photophobia"],
                "matching_terms": ["migraine", "photophobia"],
            },
        ],
        "secondary_topics": {},
    }

    normalize_topic_structure(contract, policy, ("migraine",))
    attach_topic_policy_reference(contract, policy, ("migraine",))
    validate_topic_contract(contract, policy)

    structure = contract["topic_structure"]
    migraine = structure["main_topics"][1]
    assert structure["anchor_topic_id"] == "migraine"
    assert "photophobia" not in migraine["terms"]
    assert "migraine with aura" in migraine["terms"]
    assert structure["secondary_topics"]["migraine"][0][
        "secondary_topic_id"
    ] == "tension_headache"
    assert contract["topic_policy"] == policy.reference(("migraine",))


def test_custom_quality_rules_drive_validation_and_normalization(
    tmp_path: Path,
) -> None:
    payload = read_yaml_object(DEFAULT_TOPIC_STRUCTURE_POLICY_PATH)
    term_sets = payload["quality_rules"]["term_sets"]
    term_sets["generic_topic_structure_terms"].append("bespoke generic")
    term_sets["broad_umbrella_topic_structure_terms"].append("bespoke generic")
    term_sets["method_topic_words"].append("quantum")
    policy_path = tmp_path / "custom_topic_structure.yaml"
    write_yaml_object(policy_path, payload)
    policy = load_topic_structure_policy(policy_path)

    contract = deepcopy(
        load_topic_contract(ROOT / "configs/topics/ai_in_education.yaml")
    )
    topic = contract["topic_structure"]["main_topics"][0]
    topic["topic_id"] = "quantum_methods"
    topic["label"] = "Quantum methods"
    topic["terms"] = ["quantum methods", "bespoke generic"]
    topic["retrieval_terms"] = ["quantum methods", "bespoke generic"]
    topic["matching_terms"] = ["quantum methods", "bespoke generic"]

    default_codes = {
        issue.code for issue in generated_topic_structure_quality_issue_records(contract)
    }
    custom_codes = {
        issue.code
        for issue in generated_topic_structure_quality_issue_records(
            contract,
            policy=policy,
        )
    }
    assert "generic_topic_term" not in default_codes
    assert "generic_topic_term" in custom_codes

    normalize_topic_structure(contract, policy, ())

    assert "bespoke generic" not in topic["terms"]
    assert "bespoke generic" not in topic["retrieval_terms"]
