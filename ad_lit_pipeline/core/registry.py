from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from types import MappingProxyType

from ad_lit_pipeline.core.step import StepSpec
from ad_lit_pipeline.steps.collection import (
    backfill_candidates,
    deduplicate,
    export_included,
    fetch_candidates,
    fetch_review_overviews,
    generate_topic_contract,
    plan_search,
    prepare_review_full_text,
    refine_topic_contract,
    select_calibration_papers,
    verify_full_text_availability,
)
from ad_lit_pipeline.steps.export import mantis, mantis_views, publish_mantis
from ad_lit_pipeline.steps.full_text import prepare as prepare_full_text
from ad_lit_pipeline.steps.importers import bibtex, json_metadata, ris
from ad_lit_pipeline.steps.knowledge import (
    export_evidence_excerpts,
    export_sources,
    extract_findings,
)
from ad_lit_pipeline.steps.metadata import normalize
from ad_lit_pipeline.steps.review import (
    assemble_review,
    config as review_config,
    coverage_report,
    edit_sections,
    evidence_map,
    extract_labels,
    filter_papers,
    label_value_review,
    label_values,
    synthesize_sections,
    validate_labels,
)
from ad_lit_pipeline.steps.screening import (
    llm_candidate_screening,
    rule_based_scope,
    title_relevance,
)
from ad_lit_pipeline.steps.tagging import (
    audit,
    calibrate_topic_contract,
    generate_rules,
    normalize_config,
    review_categories,
    tag_papers,
)


KNOWN_STEP_CAPABILITIES = frozenset(
    {
        "human_review",
        "llm",
        "mantis_export",
        "mantis_publish",
        "network",
        "provider_access",
    }
)


@dataclass(frozen=True)
class PipelineSpec:
    """One immutable named pipeline with a validated step order."""

    name: str
    steps: tuple[str, ...]
    description: str = ""

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("PipelineSpec name must be non-empty.")
        object.__setattr__(self, "steps", tuple(self.steps))


@dataclass(frozen=True)
class MainPipelineOptions:
    """Feature switches that determine the main pipeline composition."""

    calibrate_topic_contract: bool = False
    review_tagging_categories: bool = False
    export_knowledge: bool = False
    extract_knowledge_findings: bool = False
    extract_review_labels: bool = False
    generate_review: bool = False
    review_review_label_values: bool = False
    requested_step: str | None = None


@dataclass(frozen=True)
class CollectionPipelineOptions:
    """Feature switches that determine the collection pipeline composition."""

    generate_topic_contract: bool = False
    topic_contract_supplied: bool = True
    contract_bootstrap_only: bool = False
    requested_step: str | None = None


_BASE_STEP_SPECS = (
    backfill_candidates.STEP,
    deduplicate.STEP,
    export_included.STEP,
    fetch_candidates.STEP,
    fetch_review_overviews.STEP,
    generate_topic_contract.STEP,
    plan_search.STEP,
    prepare_review_full_text.STEP,
    refine_topic_contract.STEP,
    select_calibration_papers.STEP,
    verify_full_text_availability.STEP,
    mantis.STEP,
    mantis_views.STEP,
    publish_mantis.STEP,
    prepare_full_text.STEP,
    bibtex.STEP,
    json_metadata.STEP,
    ris.STEP,
    export_evidence_excerpts.STEP,
    export_sources.STEP,
    extract_findings.STEP,
    normalize.STEP,
    assemble_review.STEP,
    review_config.STEP,
    coverage_report.STEP,
    edit_sections.STEP,
    evidence_map.STEP,
    extract_labels.STEP,
    filter_papers.STEP,
    label_value_review.STEP,
    label_values.STEP,
    synthesize_sections.STEP,
    validate_labels.STEP,
    llm_candidate_screening.STEP,
    rule_based_scope.STEP,
    title_relevance.STEP,
    audit.STEP,
    calibrate_topic_contract.STEP,
    generate_rules.STEP,
    normalize_config.STEP,
    review_categories.STEP,
    tag_papers.STEP,
)

# Dependencies are ordering constraints when both steps occur in one assembled
# run. A dependency may be absent because --only-step and --from-step are valid
# ways to consume compatible artifacts produced by an earlier run.
_STEP_DEPENDENCIES: dict[str, tuple[str, ...]] = {
    "normalize_metadata": (),
    "screen_scope": ("normalize_metadata",),
    "prepare_full_text": ("screen_scope",),
    "calibrate_topic_contract": (
        "prepare_full_text",
        "prepare_calibration_full_text",
    ),
    "review_tagging_categories": ("prepare_full_text",),
    "normalize_tagging_config": ("prepare_full_text",),
    "generate_tagging_rules": ("normalize_tagging_config",),
    "tag_papers": (
        "prepare_full_text",
        "normalize_review_config",
        "generate_tagging_rules",
    ),
    "audit_extraction": ("tag_papers",),
    "export_mantis": ("audit_extraction",),
    "export_mantis_views": (),
    "publish_mantis_views": ("export_mantis_views",),
    "export_knowledge_sources": ("prepare_full_text",),
    "export_knowledge_evidence_excerpts": ("prepare_full_text",),
    "extract_knowledge_findings": (
        "export_knowledge_sources",
        "export_knowledge_evidence_excerpts",
    ),
    "filter_review_papers": ("prepare_full_text",),
    "normalize_review_config": (),
    "extract_review_labels": (
        "filter_review_papers",
        "normalize_review_config",
    ),
    "normalize_review_label_values": (
        "tag_papers",
        "extract_review_labels",
        "normalize_review_config",
    ),
    "review_review_label_values": ("normalize_review_label_values",),
    "validate_review_labels": ("normalize_review_label_values",),
    "build_review_coverage_report": ("validate_review_labels",),
    "build_review_evidence_map": ("build_review_coverage_report",),
    "synthesize_review_sections": ("build_review_evidence_map",),
    "edit_review_sections": ("synthesize_review_sections",),
    "assemble_literature_review": ("edit_review_sections",),
    "generate_topic_contract": (),
    "fetch_review_overviews": ("generate_topic_contract",),
    "prepare_review_full_text": ("fetch_review_overviews",),
    "refine_topic_contract": ("prepare_review_full_text",),
    "plan_search": ("refine_topic_contract",),
    "fetch_candidates": ("plan_search",),
    "deduplicate_candidates": ("fetch_candidates",),
    "screen_candidates": ("deduplicate_candidates",),
    "screen_title_relevance": ("deduplicate_candidates",),
    "verify_full_text_availability": (
        "deduplicate_candidates",
        "screen_title_relevance",
    ),
    "backfill_candidates": (
        "plan_search",
        "verify_full_text_availability",
    ),
    "select_calibration_papers": ("screen_title_relevance",),
    "prepare_calibration_full_text": ("select_calibration_papers",),
    "export_included_candidates": ("backfill_candidates",),
    "import_bibtex": (),
    "import_json_metadata": (),
    "import_ris": (),
}

_STEP_CAPABILITIES: dict[str, frozenset[str]] = {
    "backfill_candidates": frozenset({"provider_access", "network"}),
    "fetch_candidates": frozenset({"provider_access", "network"}),
    "fetch_review_overviews": frozenset({"provider_access", "network"}),
    "prepare_review_full_text": frozenset({"network"}),
    "verify_full_text_availability": frozenset({"network"}),
    "prepare_full_text": frozenset({"network"}),
    "prepare_calibration_full_text": frozenset({"network"}),
    "review_tagging_categories": frozenset({"human_review"}),
    "review_review_label_values": frozenset({"human_review"}),
    "build_review_coverage_report": frozenset({"human_review"}),
    "export_mantis": frozenset({"mantis_export"}),
    "export_mantis_views": frozenset({"mantis_export"}),
    "publish_mantis_views": frozenset({"mantis_publish", "network"}),
}

_PREPARE_CALIBRATION_FULL_TEXT = StepSpec(
    name="prepare_calibration_full_text",
    inputs=["calibration_papers_csv"],
    outputs=[
        "calibration_papers_full_text_csv",
        "calibration_full_text_manifest_csv",
    ],
    uses_llm=False,
    description=(
        "Prepare full text for the optional collection-time calibration set."
    ),
)


def _effective_step_spec(spec: StepSpec) -> StepSpec:
    capabilities = set(_STEP_CAPABILITIES.get(spec.name, frozenset()))
    if spec.uses_llm:
        capabilities.update({"llm", "network"})
    return replace(
        spec,
        dependencies=_STEP_DEPENDENCIES.get(spec.name, ()),
        capabilities=frozenset(capabilities),
    )


def _build_step_catalog() -> Mapping[str, StepSpec]:
    specs = (*_BASE_STEP_SPECS, _PREPARE_CALIBRATION_FULL_TEXT)
    source_names = {spec.name for spec in specs}
    dependency_names = set(_STEP_DEPENDENCIES)
    if source_names != dependency_names:
        missing = sorted(source_names - dependency_names)
        extra = sorted(dependency_names - source_names)
        raise ValueError(
            "Step dependency declarations do not match registered steps: "
            f"missing={missing}, extra={extra}."
        )
    unknown_capability_steps = sorted(set(_STEP_CAPABILITIES) - source_names)
    if unknown_capability_steps:
        raise ValueError(
            "Capability declarations reference unknown steps: "
            f"{', '.join(unknown_capability_steps)}."
        )
    catalog: dict[str, StepSpec] = {}
    for source_spec in specs:
        spec = _effective_step_spec(source_spec)
        if spec.name in catalog:
            raise ValueError(f"Duplicate registered step: {spec.name}")
        catalog[spec.name] = spec
    return MappingProxyType(dict(sorted(catalog.items())))


STEP_CATALOG = _build_step_catalog()


def step_spec(step_name: str) -> StepSpec:
    """Return the authoritative spec for one registered step."""
    try:
        return STEP_CATALOG[step_name]
    except KeyError as error:
        raise ValueError(f"Unknown registered step: {step_name}") from error


def validate_step_catalog(catalog: Mapping[str, StepSpec] = STEP_CATALOG) -> None:
    """Validate names, dependencies, capabilities, and dependency cycles."""
    for name, spec in catalog.items():
        if name != spec.name:
            raise ValueError(
                f"Step catalog key {name!r} does not match spec name {spec.name!r}."
            )
        unknown_dependencies = sorted(set(spec.dependencies) - set(catalog))
        if unknown_dependencies:
            raise ValueError(
                f"Step {name!r} has unknown dependencies: "
                f"{', '.join(unknown_dependencies)}."
            )
        unknown_capabilities = sorted(spec.capabilities - KNOWN_STEP_CAPABILITIES)
        if unknown_capabilities:
            raise ValueError(
                f"Step {name!r} has unknown capabilities: "
                f"{', '.join(unknown_capabilities)}."
            )
        if spec.uses_llm and "llm" not in spec.capabilities:
            raise ValueError(f"LLM step {name!r} must declare the llm capability.")

    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(name: str) -> None:
        if name in visiting:
            raise ValueError(f"Step dependency cycle detected at {name!r}.")
        if name in visited:
            return
        visiting.add(name)
        for dependency in catalog[name].dependencies:
            visit(dependency)
        visiting.remove(name)
        visited.add(name)

    for name in catalog:
        visit(name)


def validate_pipeline_steps(
    steps: Sequence[str],
    *,
    pipeline_name: str = "pipeline",
    catalog: Mapping[str, StepSpec] = STEP_CATALOG,
) -> tuple[str, ...]:
    """Validate registered, unique steps and their conditional order."""
    ordered = tuple(steps)
    unknown = [name for name in ordered if name not in catalog]
    if unknown:
        raise ValueError(
            f"Pipeline {pipeline_name!r} has unknown steps: {', '.join(unknown)}."
        )
    duplicates = sorted({name for name in ordered if ordered.count(name) > 1})
    if duplicates:
        raise ValueError(
            f"Pipeline {pipeline_name!r} has duplicate steps: "
            f"{', '.join(duplicates)}."
        )
    positions = {name: index for index, name in enumerate(ordered)}
    for name in ordered:
        for dependency in catalog[name].dependencies:
            if dependency in positions and positions[dependency] > positions[name]:
                raise ValueError(
                    f"Pipeline {pipeline_name!r} orders step {name!r} before "
                    f"dependency {dependency!r}."
                )
    return ordered


def _pipeline(name: str, steps: Sequence[str], description: str) -> PipelineSpec:
    return PipelineSpec(
        name=name,
        steps=validate_pipeline_steps(steps, pipeline_name=name),
        description=description,
    )


MAIN_PIPELINE_SPEC = _pipeline(
    "main",
    (
        "normalize_metadata",
        "screen_scope",
        "prepare_full_text",
        "normalize_tagging_config",
        "generate_tagging_rules",
        "tag_papers",
        "audit_extraction",
        "export_mantis",
    ),
    "Normalize, screen, tag, audit, and export papers for Mantis.",
)

MAIN_PIPELINE_WITH_CALIBRATION_SPEC = _pipeline(
    "main_with_calibration",
    (
        "normalize_metadata",
        "screen_scope",
        "prepare_full_text",
        "calibrate_topic_contract",
        "normalize_tagging_config",
        "generate_tagging_rules",
        "tag_papers",
        "audit_extraction",
        "export_mantis",
    ),
    "Main pipeline with legacy topic-contract calibration.",
)

REVIEW_PIPELINE_SPEC = _pipeline(
    "review",
    (
        "normalize_review_config",
        "filter_review_papers",
        "extract_review_labels",
        "normalize_review_label_values",
        "validate_review_labels",
        "build_review_coverage_report",
        "build_review_evidence_map",
        "synthesize_review_sections",
        "edit_review_sections",
        "assemble_literature_review",
    ),
    "Optional evidence-linked literature-review workflow.",
)

KNOWLEDGE_PIPELINE_SPEC = _pipeline(
    "knowledge_exports",
    (
        "export_knowledge_sources",
        "export_knowledge_evidence_excerpts",
    ),
    "Optional preliminary knowledge-record exports.",
)

KNOWLEDGE_FINDINGS_PIPELINE_SPEC = _pipeline(
    "knowledge_findings",
    (*KNOWLEDGE_PIPELINE_SPEC.steps, "extract_knowledge_findings"),
    "Optional preliminary source, evidence, and finding exports.",
)

COLLECTION_PIPELINE_SPEC = _pipeline(
    "collection",
    (
        "plan_search",
        "fetch_candidates",
        "deduplicate_candidates",
        "screen_title_relevance",
        "verify_full_text_availability",
        "backfill_candidates",
        "export_included_candidates",
    ),
    "Plan, collect, screen, backfill, and export candidate papers.",
)

COLLECTION_CALIBRATION_PIPELINE_SPEC = _pipeline(
    "collection_calibration",
    (
        "select_calibration_papers",
        "prepare_calibration_full_text",
        "calibrate_topic_contract",
    ),
    "Optional collection-time primary-paper calibration workflow.",
)

CONTRACT_BOOTSTRAP_PIPELINE_SPEC = _pipeline(
    "contract_bootstrap",
    (
        "generate_topic_contract",
        "fetch_review_overviews",
        "prepare_review_full_text",
        "refine_topic_contract",
    ),
    "Generate and review-refine a topic contract.",
)

COLLECTION_WITH_CONTRACT_PIPELINE_SPEC = _pipeline(
    "collection_with_contract",
    (*CONTRACT_BOOTSTRAP_PIPELINE_SPEC.steps, *COLLECTION_PIPELINE_SPEC.steps),
    "Bootstrap a topic contract and then collect candidate papers.",
)

MANTIS_DELIVERY_PIPELINE_SPEC = _pipeline(
    "mantis_delivery",
    (
        "export_mantis_views",
        "publish_mantis_views",
    ),
    "Optional versioned export and explicitly gated publication to Mantis.",
)

PIPELINE_SPECS: Mapping[str, PipelineSpec] = MappingProxyType(
    {
        spec.name: spec
        for spec in (
            MAIN_PIPELINE_SPEC,
            MAIN_PIPELINE_WITH_CALIBRATION_SPEC,
            REVIEW_PIPELINE_SPEC,
            KNOWLEDGE_PIPELINE_SPEC,
            KNOWLEDGE_FINDINGS_PIPELINE_SPEC,
            COLLECTION_PIPELINE_SPEC,
            COLLECTION_CALIBRATION_PIPELINE_SPEC,
            CONTRACT_BOOTSTRAP_PIPELINE_SPEC,
            COLLECTION_WITH_CONTRACT_PIPELINE_SPEC,
            MANTIS_DELIVERY_PIPELINE_SPEC,
        )
    }
)

# Compatibility views retained for existing imports. Tuples keep registry-owned
# ordering immutable while remaining valid sequences for existing callers.
MAIN_PIPELINE = MAIN_PIPELINE_SPEC.steps
MAIN_PIPELINE_WITH_CALIBRATION = MAIN_PIPELINE_WITH_CALIBRATION_SPEC.steps
REVIEW_PIPELINE = REVIEW_PIPELINE_SPEC.steps
KNOWLEDGE_PIPELINE = KNOWLEDGE_PIPELINE_SPEC.steps
KNOWLEDGE_FINDINGS_PIPELINE = KNOWLEDGE_FINDINGS_PIPELINE_SPEC.steps
COLLECTION_PIPELINE = COLLECTION_PIPELINE_SPEC.steps
COLLECTION_CALIBRATION_PIPELINE = COLLECTION_CALIBRATION_PIPELINE_SPEC.steps
CONTRACT_BOOTSTRAP_PIPELINE = CONTRACT_BOOTSTRAP_PIPELINE_SPEC.steps
COLLECTION_WITH_CONTRACT_PIPELINE = COLLECTION_WITH_CONTRACT_PIPELINE_SPEC.steps
MANTIS_DELIVERY_PIPELINE = MANTIS_DELIVERY_PIPELINE_SPEC.steps


def _insert_after(
    pipeline: Sequence[str],
    anchor: str,
    additions: Sequence[str],
) -> tuple[str, ...]:
    ordered = list(pipeline)
    if all(name in ordered for name in additions):
        return tuple(ordered)
    index = ordered.index(anchor) + 1
    return tuple((*ordered[:index], *additions, *ordered[index:]))


def _insert_before(
    pipeline: Sequence[str],
    anchor: str,
    additions: Sequence[str],
) -> tuple[str, ...]:
    ordered = list(pipeline)
    if all(name in ordered for name in additions):
        return tuple(ordered)
    index = ordered.index(anchor)
    return tuple((*ordered[:index], *additions, *ordered[index:]))


def _main_with_review_generation(
    pipeline: Sequence[str],
    options: MainPipelineOptions,
) -> tuple[str, ...]:
    requested_step = options.requested_step
    if requested_step == "extract_review_labels":
        return tuple((*pipeline, "filter_review_papers", "extract_review_labels"))

    ordered = tuple(pipeline)
    if "filter_review_papers" not in ordered and "prepare_full_text" in ordered:
        ordered = _insert_after(
            ordered,
            "prepare_full_text",
            ("filter_review_papers",),
        )
    if "normalize_review_config" not in ordered and "tag_papers" in ordered:
        ordered = _insert_before(
            ordered,
            "tag_papers",
            ("normalize_review_config",),
        )
    if options.extract_review_labels and not options.generate_review:
        return ordered

    review_tail: tuple[str, ...] = (
        "normalize_review_label_values",
        "validate_review_labels",
        "build_review_coverage_report",
        "build_review_evidence_map",
        "synthesize_review_sections",
        "edit_review_sections",
        "assemble_literature_review",
    )
    if (
        options.review_review_label_values
        or requested_step == "review_review_label_values"
    ):
        review_tail = _insert_before(
            review_tail,
            "validate_review_labels",
            ("review_review_label_values",),
        )
    return tuple((*ordered, *review_tail))


def assemble_main_pipeline(options: MainPipelineOptions) -> tuple[str, ...]:
    """Build and validate the main pipeline for one set of feature switches."""
    requested_step = options.requested_step
    if options.calibrate_topic_contract or requested_step == "calibrate_topic_contract":
        pipeline = MAIN_PIPELINE_WITH_CALIBRATION
    else:
        pipeline = MAIN_PIPELINE

    if options.review_tagging_categories or requested_step == "review_tagging_categories":
        pipeline = _insert_before(
            pipeline,
            "normalize_tagging_config",
            ("review_tagging_categories",),
        )

    review_steps = {*REVIEW_PIPELINE, "review_review_label_values"}
    if (
        options.generate_review
        or options.extract_review_labels
        or options.review_review_label_values
        or requested_step in review_steps
    ):
        pipeline = _main_with_review_generation(pipeline, options)

    knowledge_requested = (
        options.export_knowledge or requested_step in KNOWLEDGE_PIPELINE
    )
    findings_requested = (
        options.extract_knowledge_findings
        or requested_step == KNOWLEDGE_FINDINGS_PIPELINE[-1]
    )
    if findings_requested:
        pipeline = _insert_after(
            pipeline,
            "prepare_full_text",
            KNOWLEDGE_PIPELINE,
        )
        pipeline = _insert_after(
            pipeline,
            "export_knowledge_evidence_excerpts",
            ("extract_knowledge_findings",),
        )
    elif knowledge_requested:
        pipeline = _insert_after(
            pipeline,
            "prepare_full_text",
            KNOWLEDGE_PIPELINE,
        )

    return validate_pipeline_steps(pipeline, pipeline_name="assembled_main")


def assemble_collection_pipeline(
    options: CollectionPipelineOptions,
) -> tuple[str, ...]:
    """Build and validate the collection pipeline for feature switches."""
    if options.contract_bootstrap_only:
        pipeline = CONTRACT_BOOTSTRAP_PIPELINE
    elif options.generate_topic_contract or not options.topic_contract_supplied:
        pipeline = COLLECTION_WITH_CONTRACT_PIPELINE
    elif options.requested_step in CONTRACT_BOOTSTRAP_PIPELINE:
        pipeline = COLLECTION_WITH_CONTRACT_PIPELINE
    else:
        pipeline = COLLECTION_PIPELINE
    return validate_pipeline_steps(pipeline, pipeline_name="assembled_collection")


validate_step_catalog()
