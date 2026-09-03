from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from ad_lit_pipeline.core.errors import ValidationError
from ad_lit_pipeline.records.ids import (
    RECORD_ID_PREFIXES,
    canonical_json,
    make_record_id,
    record_id_prefix,
    record_type_from_id,
    validate_record_id,
)
from ad_lit_pipeline.records.registry import (
    RECORD_SCHEMA_REGISTRY,
    SCHEMA_VERSION,
    get_record_spec,
    list_record_specs,
)


EXPECTED_PREFIXES = {
    "corpus_snapshot": "snap",
    "scholarly_work": "work",
    "source_version": "srcv",
    "provider_record": "prov",
    "access_location": "access",
    "document": "doc",
    "passage": "passage",
    "entity": "entity",
    "claim": "claim",
    "claim_evidence": "clev",
    "relationship": "rel",
    "gap_signal": "signal",
    "gap_candidate": "gap",
    "verification_attempt": "verify",
    "gap_score": "score",
    "expert_judgment": "judgment",
    "outcome_event": "outcome",
    "mantis_export_profile": "mprofile",
    "mantis_interpretation": "minterp",
    "mantis_publication_receipt": "mreceipt",
}


def test_canonical_json_is_compact_sorted_and_nfc_normalized() -> None:
    decomposed = "e\u0301"

    assert canonical_json(
        {"z": [True, None, 1.5], decomposed: {"name": decomposed}}
    ) == '{"z":[true,null,1.5],"é":{"name":"é"}}'


def test_canonical_json_is_stable_across_mapping_and_sequence_forms() -> None:
    first = {"nested": {"b": 2, "a": 1}, "values": ("x", "y")}
    second = {"values": ["x", "y"], "nested": {"a": 1, "b": 2}}

    assert canonical_json(first) == canonical_json(second)


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_canonical_json_rejects_nonfinite_numbers(value: float) -> None:
    with pytest.raises(ValidationError, match="finite number"):
        canonical_json({"value": value})


@pytest.mark.parametrize("value", [{1: "value"}, {"value": {1, 2}}, object()])
def test_canonical_json_rejects_non_json_values(value: object) -> None:
    with pytest.raises(ValidationError, match="Canonical JSON"):
        canonical_json(value)


def test_canonical_json_rejects_keys_that_collide_after_nfc() -> None:
    with pytest.raises(ValidationError, match="collide after NFC"):
        canonical_json({"é": 1, "e\u0301": 2})


@pytest.mark.parametrize(("record_type", "prefix"), EXPECTED_PREFIXES.items())
def test_all_record_types_have_deterministic_typed_ids(
    record_type: str,
    prefix: str,
) -> None:
    first = make_record_id(
        record_type,
        {"name": "e\u0301", "nested": {"b": 2, "a": 1}},
        schema_version=SCHEMA_VERSION,
    )
    second = make_record_id(
        record_type,
        {"nested": {"a": 1, "b": 2}, "name": "é"},
        schema_version=SCHEMA_VERSION,
    )

    assert record_id_prefix(record_type) == prefix
    assert first == second
    assert first.startswith(f"{prefix}_")
    assert record_type_from_id(first) == record_type
    assert len(first.removeprefix(f"{prefix}_")) == 64
    validate_record_id(first)
    validate_record_id(first, record_type)


def test_record_id_changes_with_schema_version_and_identity() -> None:
    original = make_record_id("claim", {"text": "a"}, schema_version="1.0.0")

    assert original != make_record_id(
        "claim", {"text": "a"}, schema_version="1.1.0"
    )
    assert original != make_record_id(
        "claim", {"text": "b"}, schema_version="1.0.0"
    )


def test_record_id_creation_rejects_bad_inputs() -> None:
    with pytest.raises(ValidationError, match="Unsupported record type"):
        make_record_id("unknown", {"id": 1}, schema_version=SCHEMA_VERSION)
    with pytest.raises(ValidationError, match="schema_version"):
        make_record_id("claim", {"id": 1}, schema_version="")
    with pytest.raises(ValidationError, match="identity must be a JSON object"):
        make_record_id(  # type: ignore[arg-type]
            "claim",
            ["id"],
            schema_version=SCHEMA_VERSION,
        )


@pytest.mark.parametrize(
    "record_id",
    [
        "",
        " claim_" + "a" * 64,
        "claim_" + "A" * 64,
        "claim_abc",
        "unknown_" + "a" * 64,
    ],
)
def test_validate_record_id_rejects_malformed_ids(record_id: str) -> None:
    with pytest.raises(ValidationError, match="Record ID"):
        validate_record_id(record_id)


def test_validate_record_id_rejects_type_prefix_mismatch() -> None:
    record_id = make_record_id(
        "claim",
        {"claim_text": "example"},
        schema_version=SCHEMA_VERSION,
    )

    with pytest.raises(ValidationError, match="not 'gap_candidate'"):
        validate_record_id(record_id, "gap_candidate")


def test_record_prefix_mapping_is_complete_and_immutable() -> None:
    assert dict(RECORD_ID_PREFIXES) == EXPECTED_PREFIXES

    with pytest.raises(TypeError):
        RECORD_ID_PREFIXES["claim"] = "changed"  # type: ignore[index]


def test_registry_is_complete_versioned_and_consistent_with_id_prefixes() -> None:
    specs = list_record_specs()

    assert len(specs) == len(EXPECTED_PREFIXES)
    assert set(RECORD_SCHEMA_REGISTRY) == {
        (record_type, SCHEMA_VERSION) for record_type in EXPECTED_PREFIXES
    }
    assert {spec.record_type for spec in specs} == set(EXPECTED_PREFIXES)
    for spec in specs:
        assert spec.schema_version == SCHEMA_VERSION
        assert spec.id_prefix == EXPECTED_PREFIXES[spec.record_type]
        assert spec.class_name
        assert spec.identity_field_paths
        assert len(spec.identity_field_paths) == len(set(spec.identity_field_paths))
        assert get_record_spec(spec.record_type, SCHEMA_VERSION) is spec


def test_registry_and_specs_are_immutable() -> None:
    spec = get_record_spec("claim", SCHEMA_VERSION)

    with pytest.raises(TypeError):
        RECORD_SCHEMA_REGISTRY[("claim", SCHEMA_VERSION)] = spec  # type: ignore[index]
    with pytest.raises(FrozenInstanceError):
        spec.id_prefix = "changed"  # type: ignore[misc]


def test_registry_rejects_unsupported_record_types_and_versions() -> None:
    with pytest.raises(ValidationError, match="Unsupported record contract"):
        get_record_spec("unknown", SCHEMA_VERSION)
    with pytest.raises(ValidationError, match="Unsupported record contract"):
        get_record_spec("claim", "2.0.0")
    with pytest.raises(ValidationError, match="Unsupported schema version"):
        list_record_specs("2.0.0")
