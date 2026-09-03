from __future__ import annotations

from copy import deepcopy
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from ad_lit_pipeline.core.errors import ValidationError
from ad_lit_pipeline.io.yaml_io import read_yaml_object
from ad_lit_pipeline.records.gap_classes import (
    DEFAULT_GAP_ONTOLOGY_PATH,
    REQUIRED_GAP_CLASS_IDS,
    GapClassDefinition,
    gap_ontology_to_dict,
    load_gap_ontology,
    parse_gap_ontology,
)
from ad_lit_pipeline.records.models import GapSignalType


EXPECTED_CLASS_ORDER = (
    "explicit_author_stated",
    "corpus_sparse",
    "missing_graph_relation",
    "contradictory",
    "underrepresented_population",
    "method_transfer",
    "outdated_evidence",
    "missing_direct_comparison",
    "poorly_connected",
    "weak_evidence",
    "dataset_reuse_validation",
    "unlinked_protocol_trial_result",
)

OPERATIONAL_FIELDS = (
    "allowed_signal_types",
    "minimum_support",
    "refuting_evidence",
    "resolution_evidence",
    "coverage_assumptions",
    "open_world_limitations",
    "human_annotation_questions",
)


@pytest.fixture
def ontology():
    return load_gap_ontology()


def ontology_payload() -> dict[str, object]:
    return deepcopy(read_yaml_object(DEFAULT_GAP_ONTOLOGY_PATH))


def first_class(payload: dict[str, object]) -> dict[str, object]:
    classes = payload["classes"]
    assert isinstance(classes, list)
    item = classes[0]
    assert isinstance(item, dict)
    return item


def test_default_ontology_path_and_versioned_cross_domain_identity(ontology) -> None:
    assert DEFAULT_GAP_ONTOLOGY_PATH == (
        Path(__file__).resolve().parents[1]
        / "configs"
        / "policies"
        / "gap_ontology_v1.yaml"
    )
    assert ontology.schema_version == "1.0.0"
    assert ontology.ontology_id == "gap_ontology"
    assert ontology.ontology_version == "1.0.0"
    assert ontology.scope == "cross_domain"


def test_ontology_defines_exactly_the_twelve_operational_v1_classes(
    ontology,
) -> None:
    assert REQUIRED_GAP_CLASS_IDS == frozenset(EXPECTED_CLASS_ORDER)
    assert tuple(ontology.classes) == EXPECTED_CLASS_ORDER
    assert len(ontology.classes) == 12


def test_every_class_has_a_complete_operational_definition(ontology) -> None:
    for class_id, definition in ontology.classes.items():
        assert isinstance(definition, GapClassDefinition)
        assert definition.class_id == class_id
        assert definition.label
        assert len(definition.definition) >= 40
        assert definition.definition.casefold() != definition.label.casefold()
        for field in OPERATIONAL_FIELDS:
            values = getattr(definition, field)
            assert isinstance(values, tuple)
            assert values
            assert len(values) == len(set(values))
        assert all(
            question.endswith("?")
            for question in definition.human_annotation_questions
        )


def test_generating_signal_types_are_rule_like_and_exclude_mantis_or_llm(
    ontology,
) -> None:
    for definition in ontology.classes.values():
        for signal_type in definition.allowed_signal_types:
            assert signal_type == signal_type.casefold()
            assert "mantis" not in signal_type
            assert "llm" not in signal_type
            assert "model_intuition" not in signal_type
            assert "map_interpretation" not in signal_type

    configured = {
        signal_type
        for definition in ontology.classes.values()
        for signal_type in definition.allowed_signal_types
    }
    assert configured == {signal.value for signal in GapSignalType}


def test_high_risk_classes_encode_their_scientific_safeguards(ontology) -> None:
    author = ontology.classes["explicit_author_stated"]
    sparse = ontology.classes["corpus_sparse"]
    contradiction = ontology.classes["contradictory"]
    weak = ontology.classes["weak_evidence"]
    protocol = ontology.classes["unlinked_protocol_trial_result"]

    assert "not proof" in " ".join(author.open_world_limitations).casefold()
    assert "threshold" in " ".join(sparse.minimum_support).casefold()
    assert "comparability" in " ".join(contradiction.minimum_support).casefold()
    assert "extraction confidence" in " ".join(weak.minimum_support).casefold()
    assert "grace period" in " ".join(protocol.minimum_support).casefold()
    assert "null or negative" in " ".join(
        protocol.open_world_limitations
    ).casefold()


def test_ontology_is_domain_portable_and_contains_no_alzheimer_topic_terms() -> None:
    text = DEFAULT_GAP_ONTOLOGY_PATH.read_text(encoding="utf-8").casefold()
    for domain_term in (
        "alzheimer",
        "dementia",
        "amyloid",
        "mild cognitive impairment",
    ):
        assert domain_term not in text


def test_loaded_dataclasses_and_class_mapping_are_immutable(ontology) -> None:
    with pytest.raises(TypeError):
        ontology.classes["another"] = ontology.classes["corpus_sparse"]

    with pytest.raises(FrozenInstanceError):
        ontology.scope = "one_domain"

    with pytest.raises(FrozenInstanceError):
        ontology.classes["corpus_sparse"].label = "Changed"


def test_normalized_serialization_round_trips_without_semantic_loss(
    ontology,
) -> None:
    normalized = gap_ontology_to_dict(ontology)
    reparsed = parse_gap_ontology(normalized, source="round-trip ontology")

    assert gap_ontology_to_dict(reparsed) == normalized
    assert tuple(reparsed.classes) == EXPECTED_CLASS_ORDER


@pytest.mark.parametrize("field", ("schema_version", "ontology_version"))
def test_parser_requires_semantic_versions(field: str) -> None:
    payload = ontology_payload()
    payload[field] = "version-one"

    with pytest.raises(ValidationError, match=rf"ontology\.{field}.*semantic"):
        parse_gap_ontology(payload, source="bad version ontology")


def test_parser_rejects_unsupported_schema_major_version() -> None:
    payload = ontology_payload()
    payload["schema_version"] = "2.0.0"

    with pytest.raises(
        ValidationError,
        match=r"ontology\.schema_version.*unsupported schema major",
    ):
        parse_gap_ontology(payload, source="future ontology")


@pytest.mark.parametrize(
    ("field", "value", "expected"),
    (
        ("ontology_id", "research_gaps", "must be 'gap_ontology'"),
        ("scope", "alzheimer_only", "must be 'cross_domain'"),
    ),
)
def test_parser_freezes_ontology_identity_and_scope(
    field: str, value: str, expected: str
) -> None:
    payload = ontology_payload()
    payload[field] = value

    with pytest.raises(ValidationError, match=expected):
        parse_gap_ontology(payload, source="wrong identity ontology")


@pytest.mark.parametrize("field", OPERATIONAL_FIELDS)
def test_parser_rejects_a_label_only_class_missing_operational_fields(
    field: str,
) -> None:
    payload = ontology_payload()
    first_class(payload).pop(field)

    with pytest.raises(
        ValidationError,
        match=rf"classes\[0\].*missing required fields.*{field}",
    ):
        parse_gap_ontology(payload, source="label-only ontology")


@pytest.mark.parametrize("field", OPERATIONAL_FIELDS)
def test_parser_rejects_empty_operational_fields(field: str) -> None:
    payload = ontology_payload()
    first_class(payload)[field] = []

    with pytest.raises(
        ValidationError,
        match=rf"classes\[0\]\.{field}.*must not be empty",
    ):
        parse_gap_ontology(payload, source="empty operation ontology")


def test_parser_rejects_a_definition_that_only_repeats_the_label() -> None:
    payload = ontology_payload()
    item = first_class(payload)
    item["definition"] = item["label"]

    with pytest.raises(
        ValidationError,
        match=r"classes\[0\]\.definition.*operationally define",
    ):
        parse_gap_ontology(payload, source="label definition ontology")


def test_parser_rejects_duplicate_class_ids_before_set_completeness() -> None:
    payload = ontology_payload()
    classes = payload["classes"]
    assert isinstance(classes, list)
    duplicate = deepcopy(classes[0])
    classes.append(duplicate)

    with pytest.raises(
        ValidationError,
        match=r"classes\[12\]\.class_id.*duplicate class id",
    ):
        parse_gap_ontology(payload, source="duplicate id ontology")


def test_parser_rejects_case_insensitive_duplicate_labels() -> None:
    payload = ontology_payload()
    classes = payload["classes"]
    assert isinstance(classes, list)
    first = classes[0]
    second = classes[1]
    assert isinstance(first, dict)
    assert isinstance(second, dict)
    second["label"] = str(first["label"]).upper()

    with pytest.raises(
        ValidationError,
        match=r"classes\[1\]\.label.*duplicate label",
    ):
        parse_gap_ontology(payload, source="duplicate label ontology")


def test_parser_requires_the_exact_v1_class_set() -> None:
    payload = ontology_payload()
    classes = payload["classes"]
    assert isinstance(classes, list)
    classes.pop()

    with pytest.raises(
        ValidationError,
        match=r"classes.*exact v1 class set.*unlinked_protocol_trial_result",
    ):
        parse_gap_ontology(payload, source="incomplete ontology")


@pytest.mark.parametrize(
    "invalid_id",
    ("CorpusSparse", "corpus-sparse", "1_corpus_sparse", "corpus sparse"),
)
def test_parser_requires_snake_case_class_ids(invalid_id: str) -> None:
    payload = ontology_payload()
    first_class(payload)["class_id"] = invalid_id

    with pytest.raises(
        ValidationError,
        match=r"classes\[0\]\.class_id.*lowercase snake_case",
    ):
        parse_gap_ontology(payload, source="bad id ontology")


@pytest.mark.parametrize(
    "signal_type",
    (
        "mantis_interpretation",
        "llm_hypothesis",
        "model_intuition_signal",
        "map_interpretation_signal",
    ),
)
def test_parser_rejects_interpretation_as_a_generating_signal(
    signal_type: str,
) -> None:
    payload = ontology_payload()
    first_class(payload)["allowed_signal_types"] = [signal_type]

    with pytest.raises(
        ValidationError,
        match=r"allowed_signal_types\[0\].*cannot be a generating signal",
    ):
        parse_gap_ontology(payload, source="intuition signal ontology")


def test_parser_rejects_duplicate_operational_rules() -> None:
    payload = ontology_payload()
    item = first_class(payload)
    support = item["minimum_support"]
    assert isinstance(support, list)
    support.append(support[0])

    with pytest.raises(
        ValidationError,
        match=r"minimum_support.*duplicate values",
    ):
        parse_gap_ontology(payload, source="duplicate rule ontology")


def test_parser_requires_annotation_questions_to_be_questions() -> None:
    payload = ontology_payload()
    first_class(payload)["human_annotation_questions"] = [
        "Review the source passage."
    ]

    with pytest.raises(
        ValidationError,
        match=r"human_annotation_questions\[0\].*ending in '\?'",
    ):
        parse_gap_ontology(payload, source="statement annotation ontology")


def test_parser_rejects_unknown_top_level_and_class_fields() -> None:
    top_level = ontology_payload()
    top_level["notes"] = "not part of the contract"
    with pytest.raises(ValidationError, match=r"ontology.*unknown fields: notes"):
        parse_gap_ontology(top_level, source="loose ontology")

    class_level = ontology_payload()
    first_class(class_level)["importance"] = "high"
    with pytest.raises(
        ValidationError,
        match=r"classes\[0\].*unknown fields: importance",
    ):
        parse_gap_ontology(class_level, source="scored ontology")


def test_loader_wraps_missing_and_malformed_yaml_with_path_context(
    tmp_path: Path,
) -> None:
    missing = tmp_path / "missing.yaml"
    with pytest.raises(ValidationError, match=r"Could not load gap ontology.*missing"):
        load_gap_ontology(missing)

    malformed = tmp_path / "malformed.yaml"
    malformed.write_text("classes: [unterminated", encoding="utf-8")
    with pytest.raises(
        ValidationError,
        match=r"Could not load gap ontology.*malformed",
    ):
        load_gap_ontology(malformed)
