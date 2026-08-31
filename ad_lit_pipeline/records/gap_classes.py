from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any

import yaml

from ad_lit_pipeline.core.errors import ValidationError
from ad_lit_pipeline.io.yaml_io import read_yaml_object


DEFAULT_GAP_ONTOLOGY_PATH = (
    Path(__file__).resolve().parents[2]
    / "configs"
    / "policies"
    / "gap_ontology_v1.yaml"
)

REQUIRED_GAP_CLASS_IDS = frozenset(
    {
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
    }
)

_TOP_LEVEL_KEYS = {
    "schema_version",
    "ontology_id",
    "ontology_version",
    "scope",
    "classes",
}
_CLASS_KEYS = {
    "class_id",
    "label",
    "definition",
    "allowed_signal_types",
    "minimum_support",
    "refuting_evidence",
    "resolution_evidence",
    "coverage_assumptions",
    "open_world_limitations",
    "human_annotation_questions",
}
_SEMANTIC_VERSION = re.compile(
    r"^[0-9]+\.[0-9]+\.[0-9]+(?:[-+][0-9A-Za-z.-]+)?$"
)
_IDENTIFIER = re.compile(r"^[a-z][a-z0-9_]*$")
_NONDETERMINISTIC_SIGNAL_MARKERS = (
    "llm",
    "mantis",
    "model_intuition",
    "map_interpretation",
)


@dataclass(frozen=True)
class GapClassDefinition:
    """Operational definition of one portable scientific-gap class."""

    class_id: str
    label: str
    definition: str
    allowed_signal_types: tuple[str, ...]
    minimum_support: tuple[str, ...]
    refuting_evidence: tuple[str, ...]
    resolution_evidence: tuple[str, ...]
    coverage_assumptions: tuple[str, ...]
    open_world_limitations: tuple[str, ...]
    human_annotation_questions: tuple[str, ...]


@dataclass(frozen=True)
class GapOntology:
    """Immutable, versioned collection of operational gap classes."""

    schema_version: str
    ontology_id: str
    ontology_version: str
    scope: str
    classes: Mapping[str, GapClassDefinition]


def _invalid(source: str, path: str, message: str) -> ValidationError:
    return ValidationError(f"{source}: {path}: {message}")


def _mapping(value: Any, source: str, path: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise _invalid(source, path, "expected an object")
    return value


def _exact_keys(
    value: Mapping[str, Any],
    expected: set[str],
    source: str,
    path: str,
) -> None:
    actual = set(value)
    missing = sorted(expected - actual)
    unknown = sorted(actual - expected)
    if missing:
        raise _invalid(source, path, f"missing required fields: {', '.join(missing)}")
    if unknown:
        raise _invalid(source, path, f"unknown fields: {', '.join(unknown)}")


def _nonempty_string(value: Any, source: str, path: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise _invalid(source, path, "expected a non-empty string")
    return value.strip()


def _required_string(
    value: Mapping[str, Any], key: str, source: str, path: str
) -> str:
    if key not in value:
        raise _invalid(source, f"{path}.{key}", "is required")
    return _nonempty_string(value[key], source, f"{path}.{key}")


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
    value: Mapping[str, Any], key: str, source: str, path: str
) -> tuple[str, ...]:
    if key not in value:
        raise _invalid(source, f"{path}.{key}", "is required")
    return _string_tuple(value[key], source, f"{path}.{key}")


def _validate_version(value: str, source: str, path: str) -> None:
    if not _SEMANTIC_VERSION.fullmatch(value):
        raise _invalid(
            source,
            path,
            "expected a semantic version such as '1.0.0'",
        )


def _validate_identifier(value: str, source: str, path: str) -> None:
    if not _IDENTIFIER.fullmatch(value):
        raise _invalid(
            source,
            path,
            "expected a lowercase snake_case identifier",
        )


def _parse_gap_class(
    payload: Mapping[str, Any], source: str, index: int
) -> GapClassDefinition:
    path = f"ontology.classes[{index}]"
    _exact_keys(payload, _CLASS_KEYS, source, path)

    class_id = _required_string(payload, "class_id", source, path)
    _validate_identifier(class_id, source, f"{path}.class_id")
    label = _required_string(payload, "label", source, path)
    definition = _required_string(payload, "definition", source, path)
    if definition.casefold() == label.casefold() or len(definition) < 40:
        raise _invalid(
            source,
            f"{path}.definition",
            "must operationally define the class rather than repeat its label",
        )

    signal_types = _required_string_tuple(
        payload, "allowed_signal_types", source, path
    )
    for signal_index, signal_type in enumerate(signal_types):
        signal_path = f"{path}.allowed_signal_types[{signal_index}]"
        _validate_identifier(signal_type, source, signal_path)
        folded = signal_type.casefold()
        if any(marker in folded for marker in _NONDETERMINISTIC_SIGNAL_MARKERS):
            raise _invalid(
                source,
                signal_path,
                "Mantis or model interpretation cannot be a generating signal",
            )

    minimum_support = _required_string_tuple(
        payload, "minimum_support", source, path
    )
    refuting_evidence = _required_string_tuple(
        payload, "refuting_evidence", source, path
    )
    resolution_evidence = _required_string_tuple(
        payload, "resolution_evidence", source, path
    )
    coverage_assumptions = _required_string_tuple(
        payload, "coverage_assumptions", source, path
    )
    open_world_limitations = _required_string_tuple(
        payload, "open_world_limitations", source, path
    )
    questions = _required_string_tuple(
        payload, "human_annotation_questions", source, path
    )
    for question_index, question in enumerate(questions):
        if not question.endswith("?"):
            raise _invalid(
                source,
                f"{path}.human_annotation_questions[{question_index}]",
                "must be phrased as a question ending in '?'",
            )

    return GapClassDefinition(
        class_id=class_id,
        label=label,
        definition=definition,
        allowed_signal_types=signal_types,
        minimum_support=minimum_support,
        refuting_evidence=refuting_evidence,
        resolution_evidence=resolution_evidence,
        coverage_assumptions=coverage_assumptions,
        open_world_limitations=open_world_limitations,
        human_annotation_questions=questions,
    )


def parse_gap_ontology(
    payload: Mapping[str, Any],
    *,
    source: str = "gap ontology",
) -> GapOntology:
    """Parse and semantically validate one gap-ontology object."""
    root = _mapping(payload, source, "ontology")
    _exact_keys(root, _TOP_LEVEL_KEYS, source, "ontology")

    schema_version = _required_string(root, "schema_version", source, "ontology")
    ontology_version = _required_string(
        root, "ontology_version", source, "ontology"
    )
    _validate_version(schema_version, source, "ontology.schema_version")
    _validate_version(ontology_version, source, "ontology.ontology_version")
    if schema_version.split(".", maxsplit=1)[0] != "1":
        raise _invalid(
            source,
            "ontology.schema_version",
            f"unsupported schema major version {schema_version!r}",
        )

    ontology_id = _required_string(root, "ontology_id", source, "ontology")
    if ontology_id != "gap_ontology":
        raise _invalid(
            source,
            "ontology.ontology_id",
            "must be 'gap_ontology'",
        )
    scope = _required_string(root, "scope", source, "ontology")
    if scope != "cross_domain":
        raise _invalid(source, "ontology.scope", "must be 'cross_domain'")

    raw_classes = root.get("classes")
    if not isinstance(raw_classes, list) or not raw_classes:
        raise _invalid(source, "ontology.classes", "expected a non-empty list")

    parsed: dict[str, GapClassDefinition] = {}
    labels: dict[str, str] = {}
    for index, raw_class in enumerate(raw_classes):
        gap_class = _parse_gap_class(
            _mapping(raw_class, source, f"ontology.classes[{index}]"),
            source,
            index,
        )
        if gap_class.class_id in parsed:
            raise _invalid(
                source,
                f"ontology.classes[{index}].class_id",
                f"duplicate class id {gap_class.class_id!r}",
            )
        folded_label = gap_class.label.casefold()
        if folded_label in labels:
            raise _invalid(
                source,
                f"ontology.classes[{index}].label",
                f"duplicate label also used by {labels[folded_label]!r}",
            )
        parsed[gap_class.class_id] = gap_class
        labels[folded_label] = gap_class.class_id

    actual_ids = set(parsed)
    if actual_ids != REQUIRED_GAP_CLASS_IDS:
        missing = sorted(REQUIRED_GAP_CLASS_IDS - actual_ids)
        unexpected = sorted(actual_ids - REQUIRED_GAP_CLASS_IDS)
        details: list[str] = []
        if missing:
            details.append(f"missing: {', '.join(missing)}")
        if unexpected:
            details.append(f"unexpected: {', '.join(unexpected)}")
        raise _invalid(
            source,
            "ontology.classes",
            "must define the exact v1 class set (" + "; ".join(details) + ")",
        )

    return GapOntology(
        schema_version=schema_version,
        ontology_id=ontology_id,
        ontology_version=ontology_version,
        scope=scope,
        classes=MappingProxyType(parsed),
    )


def gap_ontology_to_dict(ontology: GapOntology) -> dict[str, Any]:
    """Return a normalized, parseable mapping for hashing or serialization."""
    return {
        "schema_version": ontology.schema_version,
        "ontology_id": ontology.ontology_id,
        "ontology_version": ontology.ontology_version,
        "scope": ontology.scope,
        "classes": [
            {
                "class_id": definition.class_id,
                "label": definition.label,
                "definition": definition.definition,
                "allowed_signal_types": list(definition.allowed_signal_types),
                "minimum_support": list(definition.minimum_support),
                "refuting_evidence": list(definition.refuting_evidence),
                "resolution_evidence": list(definition.resolution_evidence),
                "coverage_assumptions": list(definition.coverage_assumptions),
                "open_world_limitations": list(
                    definition.open_world_limitations
                ),
                "human_annotation_questions": list(
                    definition.human_annotation_questions
                ),
            }
            for definition in ontology.classes.values()
        ],
    }


def load_gap_ontology(
    path: Path = DEFAULT_GAP_ONTOLOGY_PATH,
) -> GapOntology:
    """Load and semantically validate a versioned gap ontology YAML file."""
    resolved_path = Path(path)
    try:
        payload = read_yaml_object(resolved_path)
    except (OSError, ValueError, yaml.YAMLError) as error:
        raise ValidationError(
            f"Could not load gap ontology {resolved_path}: {error}"
        ) from error
    return parse_gap_ontology(payload, source=str(resolved_path))
