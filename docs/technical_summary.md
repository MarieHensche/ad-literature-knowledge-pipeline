# Technical Summary

Status: reconciled with the implemented repository on 2026-09-01

This project is a domain-adaptable research-literature pipeline with an
Alzheimer early-detection default contract. It collects or imports papers,
screens them, prepares full text, extracts structured tags, can generate an
evidence-linked literature review, and emits Mantis-ready outputs.

It is not yet a complete scientific gap-discovery system. The strict scientific
record, integrity, gap-ontology, and validity layers are implemented, but the
production paper pipeline does not yet emit those v1 records or run evidence-
graph construction, counterretrieval, gap verification, or three-axis ranking.

## Documentation Sources Of Truth

- [README](../README.md) is the quick-start and operator guide.
- This document describes implemented architecture and workflow boundaries.
- [Pipeline registry](pipeline_registry.md) defines ordering, dependencies, and
  capabilities.
- [Run provenance](run_provenance.md) defines manifests, traces, and resume
  behavior.
- [Continuous integration](continuous_integration.md) defines the offline
  matrix, network guard, security boundary, and stable required check.
- [Scientific validity](scientific_validity.md), [record contracts](record_contracts_v1.md),
  and [schema migration](schema_migration_policy.md) define the durable
  scientific layer that later stages will produce.
- [Topic-structure policy](topic_structure_policy.md) defines portable domain
  vocabulary and structural heuristics.
- [Mantis integration](mantis_integration.md) defines local projections,
  publication, and interpretation boundaries.
- [Living implementation plan](gap_discovery_implementation_plan.md) is the only
  active dependency-ordered roadmap and contains verified phase records.

The retained [bootstrap/refinement plan](topic_contract_bootstrap_refinement_plan.md)
is explicitly superseded and exists only to preserve old links.

## Package Layout

```text
scripts/                 Compatibility wrappers and direct step CLIs
ad_lit_pipeline/cli/     Main and collection orchestration
ad_lit_pipeline/corpus/  Corpus policy, identity, source-type, temporal rules
ad_lit_pipeline/core/    Artifacts, registry, manifests, runner, provenance
ad_lit_pipeline/io/      CSV, JSON, JSONL, YAML, and path helpers
ad_lit_pipeline/knowledge/
                         Preliminary source, excerpt, and finding contracts
ad_lit_pipeline/llm/     Shared LLM clients, schemas, and trace writing
ad_lit_pipeline/mantis/  Versioned projections and publication adapter
ad_lit_pipeline/prompts/ Prompt rendering and Markdown templates
ad_lit_pipeline/providers/
                         Provider interfaces and OpenAlex implementation
ad_lit_pipeline/records/ Strict v1 scientific records and integrity checks
ad_lit_pipeline/steps/   Implemented pipeline behaviors
ad_lit_pipeline/topics/  Topic contracts and portable policy handling
ad_lit_pipeline/validity/
                         Scientific terminology and lifecycle policy
configs/mantis/          Versioned Mantis profile templates
configs/policies/        Validity, gap-ontology, and topic-structure policies
configs/topics/          Topic contracts and generic template
data/raw/                Imported and collected paper artifacts
data/processed/          Tagging, review, knowledge, and legacy Mantis outputs
runs/                    Versioned run manifests and LLM traces
```

Reusable behavior belongs in `ad_lit_pipeline/`. Files in `scripts/` remain
thin compatibility wrappers or direct CLIs.

## Authoritative Pipeline Registry

`ad_lit_pipeline/core/registry.py` contains **43 registered steps** and **10
named pipelines**. Both orchestrated CLIs and the local UI use this registry;
the UI does not maintain a separate order.

| Pipeline ID | Purpose | Public activation |
| --- | --- | --- |
| `main` | Default import, screen, tag, audit, legacy Mantis CSV | `scripts/run_pipeline.py run` |
| `main_with_calibration` | Main pipeline with primary-paper contract calibration | `--calibrate-topic-contract` |
| `review` | Optional evidence-linked literature review | `--generate-review` or focused review options |
| `knowledge_exports` | Preliminary source and excerpt JSONL | `--export-knowledge` |
| `knowledge_findings` | Preliminary source, excerpt, and finding JSONL | `--extract-knowledge-findings` |
| `collection` | Search and select papers from a supplied contract | `scripts/run_collection.py run --topic-contract ...` |
| `collection_calibration` | Retained compatibility specification | Not assembled by the current public collection workflow |
| `contract_bootstrap` | Generate and review-refine a contract | `--contract-bootstrap-only` |
| `collection_with_contract` | Bootstrap a contract, then collect papers | Omit `--topic-contract` |
| `mantis_delivery` | Strict v1 record projections and gated publication | Direct versioned Mantis CLIs |

Dependencies are conditional ordering rules. They may be absent during a valid
`--only-step` or `--from-step` run that consumes compatible existing artifacts.
The runner still verifies that every selected step has an implementation before
execution.

`prepare_calibration_full_text` is the only compatibility spec constructed in
the registry rather than exposed as a module-level `STEP`; its bound collection
runtime delegates to the shared full-text implementation. The obsolete review
scaffold was removed because it duplicated implemented review steps and was
never registered.

## Main Tagging Workflow

Entry point:

```bash
python scripts/run_pipeline.py run \
  --papers data/raw/example_papers.csv \
  --topic-contract configs/topics/early_detection_ad.yaml \
  --collection example
```

Supported paper inputs are `.csv`, `.bib`, `.bibtex`, `.json`, `.jsonl`, and
`.ris`. Non-CSV inputs are imported to the canonical paper CSV before
normalization.

The default `main` pipeline is:

| Step | Primary output |
| --- | --- |
| `normalize_metadata` | `<collection>_papers_normalized.csv` |
| `screen_scope` | `<collection>_scope_screened.csv` |
| `prepare_full_text` | Full-text CSV and manifest |
| `normalize_tagging_config` | Normalized tagging configuration |
| `generate_tagging_rules` | Tagging rules JSON |
| `tag_papers` | `<collection>_extraction_filled.csv` |
| `audit_extraction` | Extraction audit CSV |
| `export_mantis` | Legacy `<collection>_mantis_ready.csv` |

These artifacts are written under `data/processed/` except for imported raw
inputs. The legacy Mantis exporter is intentionally compatibility-preserving;
its frozen limitations are recorded by the Step 1.1 fixture.

Optional main-workflow switches are:

| Option | Effect |
| --- | --- |
| `--calibrate-topic-contract` | Refine tagging categories from selected included primary-paper full texts before rule generation |
| `--review-tagging-categories` | Pause for human editing and approval of category IDs and values |
| `--export-knowledge` | Insert preliminary source and evidence-excerpt exports after full-text preparation |
| `--extract-knowledge-findings` | Insert both preliminary exports and LLM finding extraction |
| `--extract-review-labels` | Produce the first portion of the review-only branch |
| `--generate-review` | Run the complete literature-review branch |
| `--review-review-label-values` | Pause for human approval of auto-discovered review values |

`--review-tagging-categories` and `--review-review-label-values` record a paused
run. After editing the generated YAML and setting `status: approved`, resume the
same run or continue from the paused step.

## Automated Collection Workflow

Entry point with an existing contract:

```bash
python scripts/run_collection.py run \
  --collection example \
  --topic-contract configs/topics/early_detection_ad.yaml \
  --max-results 50
```

The `collection` pipeline runs:

```text
plan_search
-> fetch_candidates
-> deduplicate_candidates
-> screen_title_relevance
-> verify_full_text_availability
-> backfill_candidates
-> export_included_candidates
```

OpenAlex is the only implemented candidate provider. The planner receives only
providers enabled by the topic contract, and unsupported providers fail before
network access. Candidate records preserve provider identity, exact publication
date, executed query/group/tier/rank, redacted provider URL, retrieval
timestamps, duplicate observations, selected raw-record fields, canonical
observation/raw hashes, raw JSONL location/hash, and screening provenance.
Exact inclusive publication windows are applied to provider requests, checked
again on returned candidates, carried into the canonical CSV, and enforced
again during scope screening. Tiered query groups stop when the requested
unique-candidate target is reached; additional planned query text is not
evidence that every query ran or that corpus coverage is adequate.

When no contract is supplied, the preceding bootstrap pipeline is added:

```text
generate_topic_contract
-> fetch_review_overviews
-> prepare_review_full_text
-> refine_topic_contract
```

Refinement uses only topic-relevant review or overview seeds with readable
extracted full text. Seeds without usable text or enough topic evidence are
excluded and counted. If no usable review full text remains, refinement raises
a clear error rather than claiming a review-grounded ontology from metadata or
abstracts.

`--contract-bootstrap-only` stops after refinement so the generated YAML can be
reviewed before collection. A supplied reviewed contract makes `--topic`
optional because the research title and description come from the contract.

The registered `collection_calibration` specification and its
`--max-calibration-papers` compatibility parameter are not inserted into the
current public collection workflow. Primary-paper calibration is available in
the main tagging workflow through `--calibrate-topic-contract`.

## Topic Contracts And Portable Policy

Topic contracts define:

- research title and description;
- include, exclude, and boundary criteria;
- rule-based screening terms;
- title-candidate screening policy;
- main topics, anchor, and secondary replacements;
- tagging categories, values, dependencies, and fallback policy;
- tagging evidence policy (`abstract_or_full_text` or `full_text_required`);
- enabled providers, exact optional publication window, and search queries;
- corpus semantics for cutoff resolution, earliest public availability,
  languages, access, source/version retention, identity, missing dates, and
  explicitly identified negative or null results; and
- optional explicit topic-policy profile selection.

`ad_lit_pipeline/corpus/` owns these provider-neutral Phase 2.1 semantics. The
corpus specification is strict and versioned as `1.0.0`. An omitted
specification resolves to the same compatibility default as a newly generated
contract, so legacy contracts do not acquire different hidden behavior.
Explicit `as_of` dates are inclusive; otherwise the run's UTC collection-start
date is frozen as the cutoff. Temporal eligibility uses the earliest
defensible public-availability date, never silently substitutes publication
date, and routes missing, estimated, or cutoff-straddling dates to review and
exclusion.

Shared classification distinguishes canonical work kinds from provider labels
and records resolved, provisional, or needs-review evidence. Identity order is
DOI, stable provider identifier, then a normalized metadata fingerprint. The
fingerprint is never treated as resolved identity. Source versions, including
preprints, accepted manuscripts, versions of record, corrections, and
retractions, remain distinct and are linked only when explicit evidence exists.
These rules are also included, with a semantic hash, in run provenance.

Generated and refined contracts contain a `topic_policy` reference with the
policy ID, semantic version, semantic SHA-256, and selected profile IDs. The
strict policy in `configs/policies/topic_structure_v1.yaml` is shared by
generation, repair, refinement, validation, prompt rendering, rule screening,
and review-overview filtering. Existing hand-written contracts without the
reference remain supported by the default policy.

The checked-in policy contains Alzheimer and computational-method profiles, but
Python code is domain-generic. A new domain can add a profile, surface forms,
family relations, exclusions, fallbacks, and anchor preference in policy data.

## Evidence-Linked Review Workflow

The complete optional review pipeline is:

```text
normalize_review_config
-> filter_review_papers
-> extract_review_labels
-> normalize_review_label_values
-> [optional review_review_label_values]
-> validate_review_labels
-> build_review_coverage_report
-> build_review_evidence_map
-> synthesize_review_sections
-> edit_review_sections
-> assemble_literature_review
```

It produces review eligibility, label, quality, coverage, evidence-map, section,
Markdown, and LaTeX artifacts under `data/processed/`. Review generation is an
implemented narrative workflow, not the obsolete placeholder that previously
existed in `steps/review/scaffold.py`.

The review evidence map and narrative citations do not silently become strict
v1 `Claim`, `ClaimEvidence`, or graph records. That conversion requires later
scientific-record steps and validation.

## Preliminary Knowledge Exports

`--export-knowledge` writes:

```text
data/processed/<collection>_sources.jsonl
data/processed/<collection>_evidence_excerpts.jsonl
```

`--extract-knowledge-findings` implies those steps and additionally writes:

```text
data/processed/<collection>_findings.jsonl
```

These artifacts use contracts under `ad_lit_pipeline/knowledge/`. They preserve
useful source and excerpt references, but they predate the strict v1 record
model. They do not establish verified claims, corpus snapshots, graph
relationships, gap candidates, counterretrieval results, or calibrated scores.
They must not be supplied to the versioned Mantis projector as if they were a
complete v1 record collection.

Conventional paths for preliminary relationships, gaps, synthesis claims, and
field summaries exist in the artifact helper, but no current registered
production steps write them.

## Scientific Validity And Versioned Records

`ad_lit_pipeline/validity/` and
`configs/policies/scientific_validity_v1.yaml` define qualified open-world gap
language, evidence outcomes, lifecycle transitions, mandatory human review,
and separation of extraction confidence, scientific confidence, evidence
quality, coverage, uncertainty, novelty, importance, and feasibility.

`ad_lit_pipeline/records/` implements 20 strict v1 record types with immutable
dataclasses, deterministic typed IDs, JSON/JSONL codecs, exact dates, policy
references, lineage, and Mantis record contracts. Collection integrity checks
validate references, snapshot closure, chronology, ownership, artifact hashes,
and passage offsets. The migration registry is deliberately empty because
`1.0.0` is the only implemented schema.

These layers are real and tested, but the current main pipeline does not emit a
complete v1 record collection. Passing record validation demonstrates contract
consistency, not that the current literature corpus has been scientifically
verified.

## Mantis Boundaries

There are two separate Mantis paths:

1. `export_mantis` is the frozen legacy paper/tag CSV at the end of the default
   main pipeline.
2. `export_mantis_views` consumes a complete v1 record JSONL and deterministically
   produces paper, verified-claim, and verified-open-gap CSVs plus compiled
   profiles and audit reports.

The second path is offline. `publish_mantis_views` is a separate explicit action
that refuses to run without `--publish`, targets exactly external
`mantisai-cli==3.7.0`, creates private inactive maps, and writes sanitized
immutable receipts. It has fake-runner tests but has not been exercised against
a user account.

Mantis positions, clusters, summaries, and interpretations are not evidence.
`MantisInterpretation` is a non-evidentiary pre-candidate contract. Automated
interpretation capture and expert writeback do not yet exist; a Mantis-derived
hypothesis must acquire an independent deterministic signal and pass the same
counterretrieval and verification gates as any other candidate.

## Full Text, LLM Calls, And Traces

Full-text preparation prefers configured local paths, then supported open-text
locations including provider metadata, DOI resolution, Unpaywall, Europe PMC,
and CORE when configured. Extracted text is cached outside the repository using
`--full-text-cache-dir` or `AD_LIT_FULL_TEXT_CACHE`; project artifacts retain
manifests and path metadata. Availability locators remain separate from the
resolved extracted document. Remote extraction must match a DOI in front matter
or the compact ordered paper title before it becomes usable tagging evidence.
The manifest records the identity decision, text SHA-256, extraction engine and
version, extraction-contract version, resolved URL/source/license, and any
failure. Text cleanup preserves line and section boundaries for evidence
selection.

Tagging uses an explicit state machine. A row is `tagged` only from a usable
abstract, trusted local text, or identity-verified remote extracted full text;
insufficient rows are
`skipped_insufficient_evidence`, and per-paper model/validation failures are
`failed`. Both non-tagged states preserve the input row and error while clearing
claims and category values. Audit checks state consistency. The legacy Mantis
export accepts only evidence-backed `tagged` rows and fails clearly when none
are eligible.

LLM calls route through `ad_lit_pipeline/llm/client.py`. Prompts live under
`ad_lit_pipeline/prompts/templates/`, response schemas are strict, and parsed
JSON receives semantic validation. Normal tests use fake clients.

Traced calls write exact system text, prompts, schemas, raw responses, parsed
JSON, and metadata under `runs/<run_id>/traces/<attempt_id>/`. Trace metadata and manifests
record artifact hashes, safe request parameters, returned model metadata, and
usage when available. Duplicate trace IDs cannot overwrite existing artifacts.
Credentials are not stored.

## Manifests, Resume, And UI

Every orchestrated run writes `runs/<run_id>/manifest.json`. Manifest schema
`1.0.0` records sanitized Git state, environment, invocation, selected steps,
contracts, providers, prompts, response schemas, artifacts, traces, warnings,
errors, and append-only attempts. The current missing canonical corpus snapshot
is recorded explicitly rather than fabricated.

An existing run ID is immutable unless `--resume` is explicit.
`--resume --run-id <run_id>` appends a compatible attempt, preserves prior
history, marks abruptly terminated attempts as interrupted, and resumes the
originally selected sequence at its first incomplete step. Changed pipeline
structure, effective options, model, topic contract, or topic-structure policy
is rejected before execution. `--only-step`, `--from-step`, and `--dry-run` use
the shared runner.

The local UI starts with:

```bash
.venv/bin/python scripts/run_ui.py
```

It wraps the existing CLIs, uses the same registry, and can generate or edit
topic contracts, start runs, tail logs, and inspect manifests. It does not add
scientific semantics beyond the underlying steps.

## Current Limitations

- OpenAlex is the only implemented collection provider.
- Clinical-trial registries, datasets, protocols, patents, and dedicated
  negative-result sources are not integrated.
- Canonical corpus snapshots and cutoff-bound production records are not yet
  emitted.
- Work/version identity, source-type, negative/null, and inclusive `as_of`
  semantics are now frozen in provider-neutral Phase 2.1 policy and tested
  helpers, but production work/version records do not yet consume them.
- Immutable content-addressed raw snapshots and complete provider page logs
  remain Phase 2.2 work. Current raw-record and observation hashes improve
  traceability but are not a corpus snapshot.
- Preliminary findings are not verified v1 claims.
- Evidence-graph, gap generation, counterretrieval, verification, scoring, and
  expert-judgment workflows are not production steps yet.
- The main pipeline cannot directly feed the versioned Mantis projector because
  it does not produce a complete v1 record JSONL.
- Live Mantis publication, incremental update behavior, Connection fields,
  interpretation capture, and writeback remain unvalidated or unimplemented.
- Legacy schemas and topic contracts can still drift.
- Generated `data/raw/`, `data/processed/`, and `runs/` artifacts require review
  before committing.

## Verification

The GitHub Actions workflow is configured to run the complete offline suite on
Python 3.11 and 3.12 with different fixed hash seeds. The stable aggregate job
is `foundation-gate`. Dependency installation may use the network; test
execution blocks outbound TCP connections and receives no external-service
secrets. Hosted Python 3.11/3.12 verification passed on 2026-08-31, and the
stable gate is required on `dev061602` through repository ruleset 21912442. See
[continuous integration](continuous_integration.md).

The post-live hardening recorded on 2026-09-01 passes 641 offline tests locally
on Python 3.12.2 under both fixed hash seeds. Implementation commit `7285aec`
is pushed, and hosted Foundation CI run 33512451821 passes Python 3.11, Python
3.12, and the stable `foundation-gate` for these corrections. Phase 2.1 adds 31
focused corpus-semantic tests; the complete offline suite passes 672 tests.

Run focused structural and documentation checks with:

```bash
.venv/bin/python -m pytest -q \
  tests/test_documentation_contract.py \
  tests/test_pipeline_registry.py \
  tests/test_cli_runner.py
```

Run the complete offline suite with:

```bash
.venv/bin/python -m pytest -q
```

Normal tests must not contact OpenAI, providers, full-text services, or Mantis.
Historic per-step test totals and acceptance records live in the
[living implementation plan](gap_discovery_implementation_plan.md), not here,
so this technical description does not preserve stale milestone counts.
