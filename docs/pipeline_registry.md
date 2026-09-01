# Pipeline Registry And Dependency Contract

Status: implemented and reconciled for the current CLI and local UI
Authoritative module: `ad_lit_pipeline/core/registry.py`

## Purpose

The registry is the single source of truth for available step metadata, named
pipeline order, optional pipeline assembly, dependencies, and capabilities.
Both orchestrated CLIs and the local UI call the same pure assembly functions.
The UI no longer maintains a separate copy of review-pipeline insertion logic.

The registry preserves the current commands, option meanings, step order, pause
behavior, artifacts, and legacy Mantis export. Versioned Mantis delivery is a
separate optional specification; it does not alter the default main pipeline or
publish without an explicit feature gate.

## Step Catalog

`STEP_CATALOG` is an immutable mapping from step name to the effective
`StepSpec`. It contains 44 registered steps: 43 implemented module-level `STEP`
objects plus `prepare_calibration_full_text`, a compatibility spec whose runtime
delegates to the shared full-text implementation.

Each effective spec contains:

- stable step name;
- symbolic input and output artifacts;
- LLM-use flag and description;
- ordering dependencies; and
- explicit capabilities.

The current capability vocabulary is:

- `llm`;
- `network`;
- `provider_access`;
- `human_review`; and
- `mantis_export`;
- `mantis_publish`.

LLM steps automatically declare both `llm` and `network`. The catalog rejects
duplicate names, missing dependency declarations, dependencies on unknown
steps, unknown capability names, and dependency cycles during import.

Every registered review step now points to its implemented owning module. The
obsolete `ad_lit_pipeline/steps/review/scaffold.py` duplicate was removed in
Step 1.9; it was never registered or imported by a runtime path.

## Dependency Semantics

Dependencies are conditional ordering constraints. If a step and one of its
dependencies are both present in an assembled run, the dependency must occur
first. A dependency may be absent from the selected run because existing
`--only-step` and `--from-step` workflows intentionally consume compatible
artifacts produced earlier or outside that invocation.

Consequently, dependency validation proves structural order; it does not claim
that prerequisite files exist or are compatible. Step input validation remains
the artifact boundary. Strong artifact-compatibility and idempotency checks are
later roadmap work.

Before executing any selected sequence, the runner also verifies that every
selected name has a bound runtime function. This prevents a partially executed
run from failing only when it reaches a missing implementation.

## Named Pipelines

`PIPELINE_SPECS` contains 10 named pipelines:

- `main`;
- `main_with_calibration`;
- `review`;
- `knowledge_exports`;
- `knowledge_findings`;
- `collection`;
- `collection_calibration`;
- `contract_bootstrap`;
- `collection_with_contract`; and
- `mantis_delivery`.

The historical constants such as `MAIN_PIPELINE`, `COLLECTION_PIPELINE`, and
`REVIEW_PIPELINE` remain available as immutable tuple views for compatibility.

## Shared Assembly

`assemble_main_pipeline(MainPipelineOptions(...))` is authoritative for:

- optional legacy topic calibration;
- tagging-category human review;
- preliminary knowledge exports and finding extraction;
- review-label extraction;
- literature-review generation; and
- review-label-value human review.

`assemble_collection_pipeline(CollectionPipelineOptions(...))` is authoritative
for existing-contract collection, generated-contract collection, contract-only
bootstrap, and optional-step branch activation.

The default collection sequence now ends with `materialize_corpus_snapshot`.
That step consumes the selected paper CSV, deduplicated candidate observations,
exact provider-evidence archive, resolved plan, and topic contract. It emits a
strict v1 corpus-record JSONL and a separate freeze/integrity report. The main
tagging pipeline does not consume this snapshot yet; that handoff remains Phase
2.5 work.

`collection_calibration` remains a registered compatibility specification, but
`assemble_collection_pipeline(...)` does not insert it into the current public
collection workflow. The retained `--max-calibration-papers` collection option
therefore does not activate those steps. Primary-paper calibration is available
in the main tagging workflow through `--calibrate-topic-contract`; changing the
collection workflow requires a separate, behavior-changing decision.

The CLIs translate parsed arguments into those option dataclasses. The UI uses
the same functions for dropdown values and command validation, then invokes the
same CLIs as before. `/api/config` also exposes the catalog metadata so future UI
work can render dependencies and capabilities without inventing another model.

## Validation Boundary

Offline regression coverage exercises all 128 combinations of the seven main
feature flags, every UI-supported review combination, all collection modes,
optional-step activation, immutable mappings, unknown and duplicate steps,
reversed dependencies, unknown dependencies, dependency cycles, declared
capabilities, and missing runtime functions.

Provider, OpenAI, and Mantis services are never contacted by these tests. The
Mantis publisher tests use a fake command runner. See
`docs/mantis_integration.md` for the separate live boundary.
