from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable

from ad_lit_pipeline.io.yaml_io import read_yaml_object


DEFAULT_TOPIC_STRUCTURE_POLICY_PATH = (
    Path(__file__).resolve().parents[2]
    / "configs"
    / "policies"
    / "topic_structure_v1.yaml"
)
POLICY_REFERENCE_KEYS = {
    "policy_id",
    "policy_version",
    "policy_sha256",
    "profile_ids",
}
_VERSION_PATTERN = re.compile(r"^\d+\.\d+\.\d+$")
QUALITY_TERM_SET_IDS = {
    "application_component_heads",
    "application_component_qualifiers",
    "application_process_or_property_words",
    "broad_criterion_topic_words",
    "broad_material_family_words",
    "broad_umbrella_topic_structure_terms",
    "broad_umbrella_topic_words",
    "explicit_pair_stopwords",
    "generic_application_topic_words",
    "generic_topic_structure_terms",
    "method_topic_words",
    "replacement_comparator_coverage_words",
    "replacement_comparator_topic_words",
    "replacement_role_words",
    "replacement_target_stopwords",
    "source_anchor_modifiers",
    "source_anchor_stopwords",
    "title_field_component_words",
    "title_or_abstract_exception_topic_words",
}


def normalize_policy_term(value: object) -> str:
    """Normalize policy vocabulary for deterministic matching."""
    return " ".join(str(value or "").casefold().replace("_", " ").split())


def _require_mapping(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a mapping.")
    return value


def _require_exact_keys(
    value: dict[str, Any],
    label: str,
    *,
    required: set[str],
    optional: set[str] | None = None,
) -> None:
    optional = optional or set()
    missing = required - set(value)
    unknown = set(value) - required - optional
    if missing:
        raise ValueError(f"{label} is missing keys: {sorted(missing)}")
    if unknown:
        raise ValueError(f"{label} contains unknown keys: {sorted(unknown)}")


def _require_string(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a non-empty string.")
    return value.strip()


def _require_strings(value: Any, label: str) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise ValueError(f"{label} must be a list.")
    items = tuple(_require_string(item, f"{label} item") for item in value)
    normalized = [normalize_policy_term(item) for item in items]
    if len(set(normalized)) != len(normalized):
        raise ValueError(f"{label} must not contain normalized duplicates.")
    return items


def _normalized_terms(value: Any, label: str) -> frozenset[str]:
    return frozenset(
        normalize_policy_term(item) for item in _require_strings(value, label)
    )


@dataclass(frozen=True)
class SurfaceFormGroup:
    group_id: str
    label: str
    abbreviations: frozenset[str]
    full_forms: frozenset[str]


@dataclass(frozen=True)
class SecondaryTopicGroup:
    group_id: str
    label: str
    field: str
    terms: tuple[str, ...]
    retrieval_terms: tuple[str, ...]
    matching_terms: tuple[str, ...]
    excluded_terms: frozenset[str]

    def as_topic_group(self) -> dict[str, Any]:
        return {
            "secondary_topic_id": self.group_id,
            "label": self.label,
            "field": self.field,
            "terms": list(self.terms),
            "retrieval_terms": list(self.retrieval_terms),
            "matching_terms": list(self.matching_terms),
        }


@dataclass(frozen=True)
class TopicConceptProfile:
    profile_id: str
    label: str
    kind: str
    requires_method_topic: bool
    signal_terms: frozenset[str]
    family_terms: frozenset[str]
    excluded_terms: frozenset[str]
    completion_terms: tuple[str, ...]
    fallback_secondary_group_ids: tuple[str, ...]
    anchor_over_kinds: tuple[str, ...]
    guidance: tuple[str, ...]


@dataclass(frozen=True)
class TopicStructurePolicy:
    schema_version: str
    policy_id: str
    policy_version: str
    scope: str
    sha256: str
    method_internal_subtype_terms: frozenset[str]
    method_topic_bare_domain_terms: frozenset[str]
    generic_secondary_bucket_ids: frozenset[str]
    generic_secondary_terms: frozenset[str]
    review_topic_stopwords: frozenset[str]
    screening_abbreviations: dict[str, tuple[str, ...]]
    topic_word_equivalents: dict[str, tuple[str, ...]]
    main_topic_min_terms: int
    quality_term_sets: dict[str, frozenset[str]]
    surface_form_display: dict[str, str]
    surface_form_groups: tuple[SurfaceFormGroup, ...]
    secondary_groups: dict[str, SecondaryTopicGroup]
    profiles: dict[str, TopicConceptProfile]
    generic_guidance: tuple[str, ...]

    def reference(self, profile_ids: Iterable[str] = ()) -> dict[str, Any]:
        return {
            "policy_id": self.policy_id,
            "policy_version": self.policy_version,
            "policy_sha256": self.sha256,
            "profile_ids": list(profile_ids),
        }


def _load_surface_form_groups(value: Any) -> tuple[SurfaceFormGroup, ...]:
    if not isinstance(value, list):
        raise ValueError("surface_form_groups must be a list.")
    groups = []
    seen = set()
    for index, raw_group in enumerate(value, start=1):
        label = f"surface_form_groups[{index}]"
        group = _require_mapping(raw_group, label)
        _require_exact_keys(
            group,
            label,
            required={"group_id", "label", "abbreviations", "full_forms"},
        )
        group_id = _require_string(group["group_id"], f"{label}.group_id")
        if group_id in seen:
            raise ValueError(f"Duplicate surface-form group: {group_id}")
        seen.add(group_id)
        groups.append(
            SurfaceFormGroup(
                group_id=group_id,
                label=_require_string(group["label"], f"{label}.label"),
                abbreviations=_normalized_terms(
                    group["abbreviations"], f"{label}.abbreviations"
                ),
                full_forms=_normalized_terms(
                    group["full_forms"], f"{label}.full_forms"
                ),
            )
        )
    return tuple(groups)


def _load_secondary_groups(value: Any) -> dict[str, SecondaryTopicGroup]:
    raw_groups = _require_mapping(value, "secondary_groups")
    groups = {}
    for group_id, raw_group in raw_groups.items():
        label = f"secondary_groups.{group_id}"
        group = _require_mapping(raw_group, label)
        _require_exact_keys(
            group,
            label,
            required={
                "label",
                "field",
                "terms",
                "retrieval_terms",
                "matching_terms",
                "excluded_terms",
            },
        )
        normalized_id = _require_string(group_id, "secondary group id")
        field = _require_string(group["field"], f"{label}.field")
        if field not in {"title", "abstract", "title_or_abstract"}:
            raise ValueError(f"{label}.field has unsupported value: {field}")
        groups[normalized_id] = SecondaryTopicGroup(
            group_id=normalized_id,
            label=_require_string(group["label"], f"{label}.label"),
            field=field,
            terms=_require_strings(group["terms"], f"{label}.terms"),
            retrieval_terms=_require_strings(
                group["retrieval_terms"], f"{label}.retrieval_terms"
            ),
            matching_terms=_require_strings(
                group["matching_terms"], f"{label}.matching_terms"
            ),
            excluded_terms=_normalized_terms(
                group["excluded_terms"], f"{label}.excluded_terms"
            ),
        )
    return groups


def _load_profiles(
    value: Any,
    secondary_groups: dict[str, SecondaryTopicGroup],
) -> dict[str, TopicConceptProfile]:
    raw_profiles = _require_mapping(value, "profiles")
    profiles = {}
    for profile_id, raw_profile in raw_profiles.items():
        label = f"profiles.{profile_id}"
        profile = _require_mapping(raw_profile, label)
        _require_exact_keys(
            profile,
            label,
            required={
                "label",
                "kind",
                "requires_method_topic",
                "signal_terms",
                "family_terms",
                "excluded_terms",
                "completion_terms",
                "fallback_secondary_group_ids",
                "anchor_over_kinds",
                "guidance",
            },
        )
        if not isinstance(profile["requires_method_topic"], bool):
            raise ValueError(f"{label}.requires_method_topic must be boolean.")
        fallback_ids = _require_strings(
            profile["fallback_secondary_group_ids"],
            f"{label}.fallback_secondary_group_ids",
        )
        unknown_groups = set(fallback_ids) - set(secondary_groups)
        if unknown_groups:
            raise ValueError(
                f"{label} references unknown secondary groups: "
                f"{sorted(unknown_groups)}"
            )
        normalized_id = _require_string(profile_id, "profile id")
        profiles[normalized_id] = TopicConceptProfile(
            profile_id=normalized_id,
            label=_require_string(profile["label"], f"{label}.label"),
            kind=_require_string(profile["kind"], f"{label}.kind"),
            requires_method_topic=profile["requires_method_topic"],
            signal_terms=_normalized_terms(
                profile["signal_terms"], f"{label}.signal_terms"
            ),
            family_terms=_normalized_terms(
                profile["family_terms"], f"{label}.family_terms"
            ),
            excluded_terms=_normalized_terms(
                profile["excluded_terms"], f"{label}.excluded_terms"
            ),
            completion_terms=_require_strings(
                profile["completion_terms"], f"{label}.completion_terms"
            ),
            fallback_secondary_group_ids=fallback_ids,
            anchor_over_kinds=_require_strings(
                profile["anchor_over_kinds"], f"{label}.anchor_over_kinds"
            ),
            guidance=_require_strings(profile["guidance"], f"{label}.guidance"),
        )
    return profiles


def load_topic_structure_policy(
    path: Path = DEFAULT_TOPIC_STRUCTURE_POLICY_PATH,
) -> TopicStructurePolicy:
    """Load and strictly validate a portable topic-structure policy."""
    raw = read_yaml_object(path)
    _require_exact_keys(
        raw,
        "topic structure policy",
        required={
            "schema_version",
            "policy_id",
            "policy_version",
            "scope",
            "structural_vocabulary",
            "surface_form_display",
            "surface_form_groups",
            "secondary_groups",
            "profiles",
            "generic_guidance",
            "quality_rules",
        },
    )
    schema_version = _require_string(raw["schema_version"], "schema_version")
    policy_version = _require_string(raw["policy_version"], "policy_version")
    if not _VERSION_PATTERN.fullmatch(schema_version):
        raise ValueError("schema_version must use MAJOR.MINOR.PATCH.")
    if not _VERSION_PATTERN.fullmatch(policy_version):
        raise ValueError("policy_version must use MAJOR.MINOR.PATCH.")

    vocabulary = _require_mapping(
        raw["structural_vocabulary"], "structural_vocabulary"
    )
    _require_exact_keys(
        vocabulary,
        "structural_vocabulary",
        required={
            "method_internal_subtype_terms",
            "method_topic_bare_domain_terms",
            "generic_secondary_bucket_ids",
            "generic_secondary_terms",
            "review_topic_stopwords",
            "screening_abbreviations",
            "topic_word_equivalents",
        },
    )
    raw_display = _require_mapping(raw["surface_form_display"], "surface_form_display")
    surface_form_display = {
        normalize_policy_term(key): _require_string(
            value, f"surface_form_display.{key}"
        )
        for key, value in raw_display.items()
    }
    if len(surface_form_display) != len(raw_display):
        raise ValueError("surface_form_display contains normalized duplicate keys.")

    secondary_groups = _load_secondary_groups(raw["secondary_groups"])
    profiles = _load_profiles(raw["profiles"], secondary_groups)
    quality_rules = _require_mapping(raw["quality_rules"], "quality_rules")
    _require_exact_keys(
        quality_rules,
        "quality_rules",
        required={"main_topic_min_terms", "term_sets"},
    )
    main_topic_min_terms = quality_rules["main_topic_min_terms"]
    if not isinstance(main_topic_min_terms, int) or main_topic_min_terms < 1:
        raise ValueError("quality_rules.main_topic_min_terms must be positive.")
    raw_quality_term_sets = _require_mapping(
        quality_rules["term_sets"], "quality_rules.term_sets"
    )
    _require_exact_keys(
        raw_quality_term_sets,
        "quality_rules.term_sets",
        required=QUALITY_TERM_SET_IDS,
    )
    digest = hashlib.sha256(
        json.dumps(
            raw,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
    ).hexdigest()
    return TopicStructurePolicy(
        schema_version=schema_version,
        policy_id=_require_string(raw["policy_id"], "policy_id"),
        policy_version=policy_version,
        scope=_require_string(raw["scope"], "scope"),
        sha256=digest,
        method_internal_subtype_terms=_normalized_terms(
            vocabulary["method_internal_subtype_terms"],
            "structural_vocabulary.method_internal_subtype_terms",
        ),
        method_topic_bare_domain_terms=_normalized_terms(
            vocabulary["method_topic_bare_domain_terms"],
            "structural_vocabulary.method_topic_bare_domain_terms",
        ),
        generic_secondary_bucket_ids=_normalized_terms(
            vocabulary["generic_secondary_bucket_ids"],
            "structural_vocabulary.generic_secondary_bucket_ids",
        ),
        generic_secondary_terms=_normalized_terms(
            vocabulary["generic_secondary_terms"],
            "structural_vocabulary.generic_secondary_terms",
        ),
        review_topic_stopwords=_normalized_terms(
            vocabulary["review_topic_stopwords"],
            "structural_vocabulary.review_topic_stopwords",
        ),
        screening_abbreviations={
            normalize_policy_term(term): tuple(
                normalize_policy_term(value)
                for value in _require_strings(
                    abbreviations,
                    f"structural_vocabulary.screening_abbreviations.{term}",
                )
            )
            for term, abbreviations in _require_mapping(
                vocabulary["screening_abbreviations"],
                "structural_vocabulary.screening_abbreviations",
            ).items()
        },
        topic_word_equivalents={
            normalize_policy_term(term): tuple(
                normalize_policy_term(value)
                for value in _require_strings(
                    equivalents,
                    f"structural_vocabulary.topic_word_equivalents.{term}",
                )
            )
            for term, equivalents in _require_mapping(
                vocabulary["topic_word_equivalents"],
                "structural_vocabulary.topic_word_equivalents",
            ).items()
        },
        main_topic_min_terms=main_topic_min_terms,
        quality_term_sets={
            term_set_id: _normalized_terms(
                values,
                f"quality_rules.term_sets.{term_set_id}",
            )
            for term_set_id, values in raw_quality_term_sets.items()
        },
        surface_form_display=surface_form_display,
        surface_form_groups=_load_surface_form_groups(raw["surface_form_groups"]),
        secondary_groups=secondary_groups,
        profiles=profiles,
        generic_guidance=_require_strings(
            raw["generic_guidance"], "generic_guidance"
        ),
    )


@lru_cache(maxsize=1)
def default_topic_structure_policy() -> TopicStructurePolicy:
    return load_topic_structure_policy()


def _contains_signal(text: str, signal: str) -> bool:
    return text == signal or f" {signal} " in f" {text} "


def profile_matches_values(
    profile: TopicConceptProfile,
    values: Iterable[object],
) -> bool:
    normalized_values = [normalize_policy_term(value) for value in values]
    return any(
        _contains_signal(value, signal)
        for value in normalized_values
        for signal in profile.signal_terms
        if value and signal
    )


def topic_profile(
    policy: TopicStructurePolicy,
    topic_id: str,
    topic: dict[str, Any],
    *,
    is_method: bool,
    allowed_profile_ids: Iterable[str] | None = None,
) -> TopicConceptProfile | None:
    allowed = set(allowed_profile_ids) if allowed_profile_ids is not None else None
    values: list[object] = [topic_id, topic.get("label")]
    for key in ("terms", "retrieval_terms", "matching_terms"):
        terms = topic.get(key)
        if isinstance(terms, list):
            values.extend(terms)
    for profile_id, profile in policy.profiles.items():
        if allowed is not None and profile_id not in allowed:
            continue
        if profile.requires_method_topic and not is_method:
            continue
        if profile_matches_values(profile, values):
            return profile
    return None


def selected_profile_ids(
    policy: TopicStructurePolicy,
    contract: dict[str, Any] | None = None,
    topic_description: str | None = None,
) -> tuple[str, ...]:
    """Resolve explicit profile overrides or auto-select matching profiles."""
    if contract is not None:
        reference = contract.get("topic_policy")
        if isinstance(reference, dict) and "profile_ids" in reference:
            profile_ids = reference.get("profile_ids")
            if not isinstance(profile_ids, list):
                raise ValueError("topic_policy.profile_ids must be a list.")
            unknown = set(profile_ids) - set(policy.profiles)
            if unknown:
                raise ValueError(
                    "topic_policy.profile_ids contains unknown profiles: "
                    f"{sorted(unknown)}"
                )
            return tuple(str(profile_id) for profile_id in profile_ids)

    values: list[object] = [topic_description or ""]
    if contract is not None:
        research_topic = contract.get("research_topic")
        if isinstance(research_topic, dict):
            values.extend(
                [research_topic.get("title"), research_topic.get("description")]
            )
        topic_structure = contract.get("topic_structure")
        if isinstance(topic_structure, dict):
            topics = topic_structure.get("main_topics")
            if isinstance(topics, list):
                for topic in topics:
                    if not isinstance(topic, dict):
                        continue
                    values.extend([topic.get("topic_id"), topic.get("label")])
                    for key in ("terms", "retrieval_terms", "matching_terms"):
                        terms = topic.get(key)
                        if isinstance(terms, list):
                            values.extend(terms)

    return tuple(
        profile_id
        for profile_id, profile in policy.profiles.items()
        if profile_matches_values(profile, values)
    )


def attach_topic_policy_reference(
    contract: dict[str, Any],
    policy: TopicStructurePolicy,
    profile_ids: Iterable[str] | None = None,
) -> tuple[str, ...]:
    resolved = tuple(
        profile_ids
        if profile_ids is not None
        else selected_profile_ids(policy, contract)
    )
    unknown = set(resolved) - set(policy.profiles)
    if unknown:
        raise ValueError(f"Unknown topic policy profiles: {sorted(unknown)}")
    contract["topic_policy"] = policy.reference(resolved)
    return resolved


def validate_topic_policy_reference(
    contract: dict[str, Any],
    policy: TopicStructurePolicy,
) -> None:
    reference = contract.get("topic_policy")
    if reference is None:
        return
    if not isinstance(reference, dict):
        raise ValueError("topic_policy must be a mapping.")
    unknown_keys = set(reference) - POLICY_REFERENCE_KEYS
    missing_keys = POLICY_REFERENCE_KEYS - set(reference)
    if missing_keys or unknown_keys:
        raise ValueError(
            "topic_policy must contain exactly policy_id, policy_version, "
            "policy_sha256, and profile_ids."
        )
    expected = policy.reference(reference.get("profile_ids", []))
    for key in ("policy_id", "policy_version", "policy_sha256"):
        if reference.get(key) != expected[key]:
            raise ValueError(
                f"topic_policy.{key} does not match the loaded policy: "
                f"expected {expected[key]!r}, got {reference.get(key)!r}."
            )
    selected_profile_ids(policy, contract)


def render_topic_policy_guidance(
    policy: TopicStructurePolicy,
    profile_ids: Iterable[str],
) -> str:
    """Render prompt guidance from the same policy used for validation."""
    resolved = tuple(profile_ids)
    lines = [
        f"Policy: {policy.policy_id} {policy.policy_version} ({policy.sha256})",
        "Portable structural rules:",
    ]
    lines.extend(f"- {item}" for item in policy.generic_guidance)
    if resolved:
        lines.append("Selected concept-profile rules:")
    for profile_id in resolved:
        profile = policy.profiles[profile_id]
        lines.append(f"- Profile `{profile.profile_id}` ({profile.label}):")
        lines.extend(f"  - {item}" for item in profile.guidance)
    return "\n".join(lines)


def policy_abbreviations(policy: TopicStructurePolicy) -> frozenset[str]:
    """Return all normalized abbreviations declared by a policy."""
    values = {
        abbreviation
        for group in policy.surface_form_groups
        for abbreviation in group.abbreviations
    }
    for abbreviations in policy.screening_abbreviations.values():
        values.update(abbreviations)
    return frozenset(values)
