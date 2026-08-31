# Gap-Discovery System: Living Implementation Plan

Status: active planning document  
Last reviewed: 2026-08-31
Review cadence: review at the start and end of every implementation phase, and
whenever a schema, provider, scientific-validity rule, or pipeline order changes.

This is the canonical plan for extending the existing literature knowledge
pipeline into a domain-adaptable, provenance-preserving, scientifically
defensible gap-discovery system. Its required terminal delivery artifacts are
versioned Mantis projections of the paper, verified-claim, and verified-gap
landscapes. Update progress in this file rather than creating disconnected
plans.

## How To Use This Plan

- Keep the five major stages stable unless the overall product direction changes.
- Change checklist markers only after the corresponding exit gate passes.
- Record important scope decisions and deviations in the decision log at the end.
- Do not call a gap scientifically validated merely because its software step is
  implemented.
- Treat Mantis as a required downstream exploration and delivery consumer, not
  as the scientific source of truth. Preserve the current CSV/download/import
  route while adding explicit export profiles, contract tests, and an optional
  authenticated publisher.
- Assess every durable schema change for its Mantis projection and version that
  projection whenever its contract changes.

Status markers:

- `[ ]` not started
- `[~]` in progress
- `[x]` completed and verified
- `[!]` blocked, with an explanation in the decision log

## Five Major Stages

1. **Foundation**
2. **Corpus**
3. **Evidence**
4. **Discovery**
5. **Validation**

Mantis delivery crosses these stages and is not a sixth scientific stage. The
canonical evidence, verification, and judgment records remain local,
versioned, and independently auditable.

## Stage 1: Foundation — First Ten Sub-Steps

- [x] 1. Freeze the clean Git baseline, a fresh non-network test result, a new
  small copyright-safe synthetic corpus independent of historical demo
  artifacts, and expected outputs including the current Mantis CSV.
- [x] 2. Define precise scientific terminology, especially `gap candidate`,
  `corpus-sparse`, `as of`, `supported`, `refuted`, and `uncertain`.
- [x] 3. Define versioned contracts for every durable corpus, evidence, graph,
  gap, scoring, judgment, Mantis export-profile, Mantis interpretation, and
  Mantis publication-receipt record.
- [x] 4. Add cross-artifact referential validation and a documented schema
  migration policy.
- [x] 5. Extend run provenance with code, environment, command, prompt, schema,
  model, contract, provider, and snapshot information.
- [x] 6. Make pipeline assembly and step dependencies a single source of truth
  shared by the CLI and UI.
- [x] 7. Preserve compatibility for collection, tagging, review, and the legacy
  Mantis CSV through regression tests; add explicit versioned Mantis paper,
  verified-claim, and verified-gap profiles plus a feature-gated publication
  adapter.
- [x] 8. Move domain-specific research vocabulary and heuristics from Python into
  topic contracts or portable policy files.
- [x] 9. Reconcile documentation and retire stale scaffolding that contradicts
  the implemented system.
- [x] 10. Add continuous integration and require the baseline and new contract
  tests to pass before later stages proceed.

Stage 1 is complete only when its exit gates in the roadmap pass. Completing the
ten tasks syntactically is not sufficient.

### Step 1.1 Completion Record

- Baseline source: detached clean code commit `dd1fbc3`; the approved living-plan
  edit was the only pre-existing working-tree change.
- Pre-Step result: 295 tests passed in 5.07 seconds with no network access.
- Fixture: eight copyright-safe fictional records under
  `tests/fixtures/synthetic_baseline/v1/`, independent of historical demo data.
- Frozen boundary: canonical paper input, post-tagging extraction input, and the
  current five-row Mantis CSV with file hashes and case expectations.
- Regression coverage: stable IDs and ordering, exact fields, scope filtering,
  claim trimming, title fallback, missing metadata, multivalue preservation,
  current metadata loss, and repeat-run determinism.
- Post-Step result: 297 tests passed in 4.12 seconds with no network access.
- Machine-readable record:
  `tests/fixtures/synthetic_baseline/v1/manifest.json`.

This completes only Step 1.1. The exporter defects recorded in the manifest are
intentionally unchanged and belong to later Foundation work.

### Step 1.2 Completion Record

- Normative policy:
  `configs/policies/scientific_validity_v1.yaml`, version `1.0.0`, with a
  `cross_domain` scope and semantic validation in
  `ad_lit_pipeline/validity/`.
- Defined terms: gap candidate, verified-open gap, refuted gap, resolved gap,
  corpus-sparse, inclusive `as_of`, supported, contradicted, insufficient, and
  reason-coded uncertain.
- Claim outcomes: `supported`, `contradicted`, `insufficient`, and `uncertain`.
  Mandatory human review is orthogonal to those outcomes.
- Gap lifecycle: append-only state history from `proposed` through
  `verification_in_progress`; no direct verified promotion; terminal candidate
  versions, including corrected artifact or duplicate decisions, can be
  reassessed only through a new candidate version with recorded lineage.
- Open-world rule: missing representation, zero results, graph absence, or
  adequate-for-rule coverage never imply global absence or completeness.
  Unqualified absence language is rejected, and required corpus/snapshot/cutoff
  qualifiers are machine checked.
- Scientific boundary: extraction and verification confidence, reporting and
  study quality, explained evidence quality, scientific confidence, coverage,
  uncertainty, novelty, importance, and feasibility remain separately typed.
  Human acceptance is not a gap state.
- Mantis boundary: map geometry and interpretations are not evidence; a Mantis
  interpretation remains a pre-candidate with no gap status. Only an independent
  deterministic signal can create a `proposed` candidate, which then passes the
  standard counter-retrieval and verification gates.
- Behavior preservation: no existing pipeline step, durable knowledge schema,
  CLI, or legacy Mantis CSV contract changed in Step 1.2. Those records begin in
  Step 1.3.
- Verification: 79 focused policy tests pass; the complete offline suite passes
  376 tests in 5.13 seconds.
- Human-readable reference: `docs/scientific_validity.md`.

This completes only Step 1.2. Step 1.3 must make future durable records carry
the applicable schema and policy versions; it must not retrofit these meanings
onto the current preliminary `Gap` or legacy `evidence_strength` fields.

### Step 1.3 Completion Record

- Record schema: `1.0.0` in `ad_lit_pipeline/records/`, implemented as strict,
  frozen Python dataclasses with exact JSON and streaming JSONL codecs.
- Complete inventory: 20 registered record types covering corpus snapshots,
  works and source versions, provider/access/document/passage provenance,
  entities, claims and claim evidence, graph relationships, gap signals and
  candidates, verification attempts, scores, judgments, outcomes, and the three
  Mantis contract records.
- Common envelope: deterministic typed ID, UTC creation time, snapshot, run and
  step, parent/source references, structured provenance, administrative status,
  structured warnings, explicit policy versions, and controlled namespaced
  extensions. Credentials and secret-like request material are rejected.
- Stable identity: Unicode-NFC canonical JSON, exact schema/version registry,
  typed SHA-256 prefixes, registered identity projections, and ID recomputation
  during validation. Administrative metadata, warnings, and extensions do not
  silently change scientific identity.
- Temporal semantics: RFC3339 UTC instants canonicalize to `Z`; `as_of` is an
  inclusive full date; partial dates retain precision and certainty; unknown
  source availability cannot be assumed temporally eligible.
- Operational ontology: `configs/policies/gap_ontology_v1.yaml` defines 12
  portable gap classes with deterministic generating signal types, minimum
  support, refuting and resolving evidence, coverage assumptions, open-world
  limitations, and human annotation questions. Mantis, LLM, model-intuition,
  and map-interpretation outputs are prohibited as generating signals.
- Scientific enforcement: exact claim-outcome requirements, typed relationship
  evidence, append-only gap transitions, versioned reassessment, independent
  signal requirements, novelty/importance/feasibility separation, explicit
  composite-score rules, coverage dimensions, and mandatory review triggers.
- Mantis enforcement: versioned ordered field/type profiles, required Title and
  Semantic fields, gated Connection output, immutable publication receipts, and
  interpretations that remain `is_evidence: false` and cannot create candidates
  without an independent deterministic signal.
- Fixture: one coherent, copyright-safe record of every type plus a manifest at
  `tests/fixtures/record_contracts/v1/`. Invalid regressions cover strictness,
  stale IDs, time, evidence, lifecycle, score, secret, and Mantis failures.
- Deliberate Step 1.4 boundary: local validators check typed-reference syntax and
  within-record facts only. Cross-record existence, ownership, snapshot closure,
  lineage continuity/cycles, corpus-wide chronology, artifact hashes, exact
  passage occurrence, uniqueness, and migrations remain unimplemented.
- Behavior preservation: the new layer coexists with preliminary
  `ad_lit_pipeline/knowledge/` records. No production step, CLI, current output,
  or legacy Mantis CSV was changed.
- Verification: 210 focused record/ID/ontology/validity tests pass; the complete
  offline suite passes 507 tests in 5.34 seconds; `git diff --check` is clean.
- Human-readable reference: `docs/record_contracts_v1.md`.

This completes only Step 1.3. Step 1.4 must validate collections and migrations
without weakening the strict record-local or scientific-validity rules.

### Step 1.4 Completion Record

- Integrity API: `ad_lit_pipeline/records/integrity.py` validates complete
  in-memory collections or multiple JSONL artifacts as one reference domain and
  returns stable, machine-readable errors and warnings with record, field,
  artifact, and line context. Strict callers retain the complete report through
  `RecordIntegrityError`.
- Referential enforcement: orphan IDs, invalid local types, duplicate IDs,
  competing payloads, snapshot membership omissions, wrong target types, and
  unauthorized cross-snapshot references are hard errors. Cross-snapshot links
  are limited to explicit version, canonical-entity, candidate reassessment,
  judgment replacement, prospective outcome/correction, and Mantis receipt/retry
  lineage.
- Provenance and ownership: collection checks cover work/version/provider/access/
  document/passage chains, exact claim-evidence source ownership, required parent
  and source records, gap candidate/attempt reciprocity, score status, Mantis
  interpretation/signal/candidate reciprocity, and profile/receipt/map identity.
- Temporal and lineage integrity: source availability is evaluated against the
  inclusive snapshot cutoff; snapshot retrieval, document extraction, evidence,
  graph assertion, gap reassessment, Mantis retry/publication/interpretation,
  judgment replacement, and prospective outcome ordering are checked. Parent,
  entity, claim, source-version, gap, judgment, outcome, and Mantis retry cycles
  are rejected.
- Artifact integrity: local provider, document, text-representation, and Mantis
  artifacts are resolved inside an optional declared root and hashed in streaming
  chunks; size, path escape, missing file, decode, representation hash, evidence
  span, and exact passage-offset mismatches are errors. Remote artifacts are not
  fetched and produce explicit `remote_artifact_not_checked` warnings instead.
- Regression boundary: the v1 fixture now includes a frozen offline integrity
  report. Programmatic adversarial cases cover orphans, collisions, snapshot
  closure, ownership, cross-snapshot rules, span hashes, cutoff eligibility,
  dependency chronology, cycles, local artifact tampering, passage occurrence,
  malformed JSON, report serialization, and strict failure behavior.
- Migration policy: `ad_lit_pipeline/records/migrations.py` provides an
  instance-owned, deterministic explicit-path registry with no implicit
  downgrade or major-version edge. The production registry is deliberately
  empty because `1.0.0` is the only real schema. The documented release gate
  requires a future migration to operate atomically over a closed collection,
  rewrite schema-dependent IDs and every reference, retain immutable source and
  audit artifacts, and pass collection integrity before publication.
- Legacy and Mantis safety: preliminary `ad_lit_pipeline/knowledge/` records are
  not auto-migrated, no live provider/OpenAI/Mantis operation is performed, and
  no production step, CLI, current output, or legacy Mantis CSV changes in this
  Foundation step.
- Verification: 237 focused record/ID/ontology/validity/integrity/migration tests
  pass; the complete offline suite passes 534 tests; `git diff --check` is clean.
- Human-readable references: `docs/record_contracts_v1.md` and
  `docs/schema_migration_policy.md`.

This completes only Step 1.4. Step 1.5 must extend run provenance and may consume
integrity reports, but it must not wire the new records into production or claim
that an empty migration registry performs migrations.

### Step 1.5 Completion Record

- Versioned envelopes: manifest, run-provenance, and LLM-trace schemas are each
  `1.0.0`. Existing run and step fields remain available, while manifest writes
  now use same-directory temporary files and atomic replacement.
- Code state: every attempt records the exact commit and commit time,
  branch/detached state, dirty state, content hashes for Git status and tracked,
  staged, and relevant untracked changes, and an aggregate source-state hash.
  Dirty research runs remain permitted; raw diffs, status filenames, and source
  content are not copied into the manifest.
- Environment and invocation: Python, platform, sorted installed distributions,
  `requirements.txt`, the allowlisted OpenAI runtime settings, selected steps,
  resolved model, working directory, command, and parsed options are recorded.
  `.env` and the general process environment are not copied; credentials,
  contact addresses, sensitive URL components, and local root prefixes are
  redacted or normalized.
- Contract boundary: the effective topic contract, available scientific-validity
  and gap-ontology policies, durable-record schema, prompt-template inventory,
  response-schema sources, and configured provider implementations are hashed.
  Statuses explicitly distinguish contracts applied by the legacy pipeline from
  future contracts that are merely available.
- Provider timing: candidate-fetch, review-overview, and backfill results record
  the earliest/latest retained retrieval dates and provider update timestamps.
- Corpus truthfulness: because the legacy pipeline does not yet emit canonical
  `CorpusSnapshot` records, provenance explicitly records `not_emitted` with a
  null ID/cutoff and reason. No snapshot is fabricated and no unsupported claim
  of temporal reproducibility is made.
- LLM locality: each exact system message, rendered prompt, schema, raw response,
  and parsed response now has a trace hash. Trace metadata also records the
  model, schema name, safe effective request parameters, selected response
  metadata, and validation data.
- Resume integrity: attempts and step results are append-only. Resume retains
  prior history and is rejected when the collection, pipeline, model, or
  recorded topic-contract boundary is incompatible or unavailable. Legacy
  manifests upgrade under an explicit legacy attempt without discarding steps.
- Behavior and safety boundary: no live provider, OpenAI, or Mantis call was
  introduced; no production scientific-record emission, migration execution, or
  snapshot creation was implied; existing CLI step order and legacy Mantis CSV
  behavior remain unchanged.
- Verification: 15 direct provenance/manifest/trace tests and 76 focused
  integration tests pass offline; the complete suite passes 548 tests;
  `git diff --check` is clean.
- Human-readable reference: `docs/run_provenance.md`.

This completes only Step 1.5. Step 1.6 must make pipeline definitions and
dependencies authoritative across the CLI and UI; the Corpus stage must later
replace the explicit missing-snapshot marker with real immutable snapshot IDs
and cutoffs.

### Step 1.6 Completion Record

- Authoritative registry: `ad_lit_pipeline/core/registry.py` now owns one
  immutable catalog of 41 effective step specifications and nine immutable named
  pipeline specifications. Existing module-level `STEP` definitions remain with
  their implementations, and historical pipeline constants remain tuple-based
  compatibility views.
- Dependency model: `StepSpec` now carries dependencies and capabilities.
  Dependencies are conditional ordering constraints: when two related steps are
  scheduled together, the dependency must come first; an isolated `--only-step`
  or suffix `--from-step` may still consume compatible existing artifacts.
- Catalog validation: startup rejects duplicate registrations, undeclared or
  unknown dependencies, unknown capabilities, missing LLM capability, and
  dependency cycles. Pipeline validation rejects unknown, duplicate, and
  reversed steps before execution.
- Runtime boundary: the runner checks that every selected step has a bound
  implementation before executing the first step, preventing late partial-run
  failures caused by an incomplete runtime mapping.
- Shared assembly: typed main and collection option records feed pure assembly
  functions for calibration, human review, knowledge exports/findings,
  literature-review generation, contract bootstrap, and collection. Both CLIs
  translate their existing arguments into these records.
- UI parity: the server's pipeline dropdown/configuration data now comes from
  those same assembly functions and exposes the authoritative dependency and
  capability metadata. The UI still launches the existing CLIs, and no controls
  or feature meanings changed.
- Compatibility: all existing CLI order, optional-step activation, pause,
  artifact, and legacy Mantis CSV behavior is preserved. Mantis remains the
  terminal local export in the main pipeline and is explicitly marked with the
  `mantis_export` capability; authenticated publishing remains later work.
- Stale scaffold boundary: `ad_lit_pipeline/steps/review/scaffold.py` is
  deliberately excluded from the catalog but not deleted. Its superseded
  definitions remain scheduled for explicit reconciliation in Step 1.9.
- Regression coverage: all 128 combinations of the seven main pipeline options,
  every UI-supported review combination, collection modes, optional-step branch
  activation, immutability, invalid dependencies/order, capability declarations,
  and missing runtime functions are tested offline.
- Verification: 72 focused registry/CLI/UI/provenance tests pass; the complete
  offline suite passes 565 tests; `git diff --check` is clean.
- Human-readable reference: `docs/pipeline_registry.md`.

This completes only Step 1.6. Step 1.7 must freeze compatibility across the
existing workflows and introduce explicit versioned Mantis projection adapters
without placing unverified claims or gaps into the verified Mantis views.

### Step 1.7 Completion Record

- Compatibility boundary: the legacy `export_mantis` implementation, default
  main order, collection, tagging, and review workflows remain unchanged. A
  frozen matrix at `tests/fixtures/compatibility/v1/manifest.json` protects the
  parsed legacy CSV contract, 43-step catalog, ten named pipelines, and optional
  two-step Mantis delivery order.
- Profile contracts: strict `paper`, `verified_claim`, and `verified_gap`
  templates under `configs/mantis/` compile to validated, snapshot-bound
  `MantisExportProfile` records at profile/compatibility version `1.0.0`.
  Ordered fields, exact Mantis types, semantic construction, null/multivalue
  policy, point identity, sort order, and exact `mantisai-cli==3.7.0` support are
  explicit. Template hashes are frozen.
- Scientific eligibility: papers require an active, temporally eligible
  snapshot source and active/corrected lifecycle; claims require active
  `supported` or `contradicted` evidence in an eligible source; gaps require
  `verified_open`, a completed decisive verification with no unresolved checks,
  and a matching separate novelty/importance/feasibility score. All other gap
  states and insufficient/uncertain claim evidence are excluded and counted by
  reason.
- Deterministic artifacts: `export_mantis_views` writes one CSV, compiled
  profile, and audit report per view. Reports preserve snapshot/profile/source/
  CSV hashes, field types, eligibility counts, exclusions, and limitations. A
  new copyright-safe verified-open fixture freezes all three CSV hashes without
  altering the Step 1.1 or Step 1.3 fixtures.
- Compatibility limit: Mantis `Connection` is disabled in v1. Stable record IDs
  remain categoric columns until authenticated serializer/UI behavior is proven.
  Paper-level scope is explicitly marked unavailable in record contract v1; the
  corpus snapshot remains authoritative.
- Publication adapter: `publish_mantis_views` is absent from the default
  pipeline and refuses to run without the explicit `--publish` gate. It invokes
  the external pinned CLI with no credential arguments, private visibility, and
  no activation. It uses create/reject semantics and makes no refresh/upsert
  idempotency claim.
- Failure behavior: source CSVs survive every failure. Exact version mismatch,
  empty view, CLI failure, malformed response, or local exception produces a
  validated, sanitized failed `MantisPublicationReceipt`. Optional
  `--require-publication` raises only after durable receipts are written.
- Interpretation boundary: the Step 1.3 `MantisInterpretation` contract remains
  non-evidentiary. Automatic interpretation capture and tested expert writeback
  are not claimed by this step.
- Regression boundary: normal tests use fake command runners and require no
  network, Mantis account, OpenAI call, or provider. No live publication was
  performed; a disposable private-space smoke test remains explicitly opt-in.
- Verification: 37 focused Mantis/registry/legacy tests pass; the complete
  offline suite passes 583 tests in 11.86 seconds; compilation and
  `git diff --check` are clean.
- Human-readable reference: `docs/mantis_integration.md`.

This completes only Step 1.7. Step 1.8 completion is recorded below.

### Step 1.8 Completion Record

- Policy boundary: `configs/policies/topic_structure_v1.yaml` is the strict,
  versioned `topic-structure-policy` `1.0.0`. Its semantic SHA-256 identifies
  the effective policy independently of YAML formatting. Unknown fields,
  missing sections, invalid profile references, malformed terms, and policy
  hash drift fail before collection or LLM work begins.
- Portable separation: universal structural guidance and quality rules are
  separate from named concept profiles. Alzheimer and computational-method
  vocabulary, aliases, family relations, exclusions, fallback groups, anchor
  precedence, screening abbreviations, review stopwords, and cross-domain
  quality-term sets now live in policy data rather than Python constants or
  prompt examples.
- Runtime selection: generated contracts deterministically select applicable
  profiles from the research question and generated topics. A contract may
  explicitly set `topic_policy.profile_ids`, including an empty list, to
  override automatic selection. Generic contracts require no named profile.
- Single-source behavior: topic generation, repair, refinement, rule-based
  screening, review-overview filtering, semantic contract validation, and
  prompt rendering consume the same loaded policy. Python implements generic
  matching and structural rules; prompts receive rendered policy guidance
  instead of maintaining a second research vocabulary.
- Provenance: generated and refined topic contracts carry the policy ID,
  semantic version, semantic hash, and selected profile IDs. The same reference
  is returned in step metadata and therefore enters the Step 1.5 run manifest.
  Existing hand-written contracts without a policy reference remain valid for
  backward compatibility and use the checked-in default policy at runtime.
- Transfer proof: an isolated test adds a synthetic migraine profile to a
  temporary policy file and obtains its family completion, exclusions, fallback
  group, anchor precedence, and validated provenance without editing Python or
  prompt templates. An explicit empty-profile test protects genuinely generic
  topics from accidental domain activation.
- Compatibility boundary: no CLI order, provider, record schema, scientific
  validity rule, Mantis profile, projection, publication behavior, or legacy
  Mantis CSV contract changed. Existing Alzheimer topic behavior remains
  covered by the full regression suite.
- Verification: 128 focused topic-policy, prompt, LLM-step, non-LLM-step, and
  CLI tests pass; the complete offline suite passes 588 tests in 8.56 seconds;
  compilation and `git diff --check` are clean. Tests use temporary policies and
  fake LLM clients, with no provider, OpenAI, or Mantis network call.
- Human-readable reference: `docs/topic_structure_policy.md`.

This completes Step 1.8. Step 1.9 must reconcile user-facing documentation and
retire or explicitly quarantine stale scaffolding without changing established
pipeline behavior accidentally.

### Step 1.9 Completion Record

- Documentation hierarchy: `README.md` is the operator quick-start,
  `docs/technical_summary.md` is the implemented architecture and boundary
  reference, focused technical documents own their individual contracts, and
  this living plan remains the only active dependency-ordered roadmap.
- Workflow reconciliation: the operator and technical documentation now cover
  all 43 registered steps and ten named pipelines, the default and optional
  main branches, contract bootstrap, supplied-contract collection, narrative
  review generation, preliminary knowledge exports, strict v1 records, legacy
  Mantis export, and versioned Mantis delivery.
- Scientific boundary: preliminary `Source`, `EvidenceExcerpt`, and `Finding`
  JSONL are explicitly distinguished from strict v1 records. They are not
  verified claims and do not imply a corpus snapshot, evidence graph, gap,
  counterretrieval result, or calibrated ranking. The current main pipeline
  cannot yet feed the versioned Mantis projector directly.
- CLI truthfulness: `--export-knowledge`, `--extract-knowledge-findings`,
  `--generate-review`, both human review gates, artifact paths, and current
  limitations are documented. Help no longer claims that public collection
  runs perform primary-paper calibration: `collection_calibration` and
  `--max-calibration-papers` are retained compatibility surfaces but are not
  assembled by the current collection workflow.
- Scaffold retirement: the unreferenced
  `ad_lit_pipeline/steps/review/scaffold.py` duplicate was removed. Its step
  names now have only their implemented owning modules. No registered step,
  import, CLI, output, or compatibility fixture depended on the deleted file.
- Plan retirement: `docs/topic_contract_bootstrap_refinement_plan.md` keeps its
  stable path but is now a concise, visibly superseded record linking to current
  sources. Its obsolete agent instructions and conflicting fallback behavior
  were removed; Git history retains them for archaeology.
- Drift protection: `tests/test_documentation_contract.py` verifies registry
  counts and all named pipelines, optional public workflow flags and scientific
  boundaries, truthful calibration help, scaffold retirement, superseded-plan
  status, and every local Markdown link in `README.md` and `docs/`.
- Determinism correction: full verification exposed that replacement-target
  extraction iterated a set containing configured word equivalents. Depending
  on Python's hash seed it could report an equivalent instead of the user's
  literal target. Extraction now preserves lexical order; the regression passes
  under ten explicit hash seeds without changing the intended quality rule.
- Compatibility boundary: generated data and historical literature reviews were
  untouched. No pipeline order, default option, provider, prompt, record schema,
  scientific-validity rule, Mantis projection, publication action, or legacy
  Mantis CSV behavior changed. Only inaccurate CLI help text was corrected.
- Verification: five focused documentation-contract tests pass; 102 focused
  documentation/registry/CLI/UI/review tests pass; the documentation, registry,
  CLI, and topic-contract boundary passes 98 tests; the complete offline suite
  passes 594 tests in 8.42 seconds. Compilation and `git diff --check` are clean,
  with no OpenAI, provider, full-text-service, or Mantis network call.

This completes Step 1.9. Step 1.10 must add continuous integration for the
offline suite and make the Foundation contracts required checks before later
stages proceed.

### Step 1.10 Completion Record

- Workflow: `.github/workflows/foundation-ci.yml` runs on every push, pull
  request, and manual dispatch. Concurrency cancels superseded runs for the same
  workflow and reference.
- Matrix: the complete suite is declared on `ubuntu-latest` for Python 3.11 with
  `PYTHONHASHSEED=101` and Python 3.12 with `PYTHONHASHSEED=1201`. Fixed distinct
  seeds make ordering failures reproducible while exercising more than one
  iteration layout.
- Supply-chain boundary: workflow permissions are `contents: read`, checkout
  credentials are not persisted, and official `actions/checkout` 7.0.1 and
  `actions/setup-python` 7.0.0 are pinned to their full release commit hashes.
  The pins were resolved from the official GitHub repositories on 2026-08-28.
- Dependency boundary: CI installs the existing `requirements.txt` plus
  CI-only `pytest>=8,<10`. It adds no runtime dependency, lockfile,
  `pyproject.toml`, packaging workflow, or generated artifact.
- Offline enforcement: the test phase sets `AD_LIT_TEST_OFFLINE=1` and prepends
  `tests/offline/` to `PYTHONPATH`. Its `sitecustomize.py` blocks outbound TCP
  connects in the suite and inherited Python subprocesses while permitting
  Unix-domain sockets. Dependency installation occurs before this guarded test
  phase.
- Required check: `foundation-gate` has a stable name and succeeds only if every
  Python matrix entry succeeds. GitHub branch protection must require that name
  separately after the workflow exists remotely; no repository setting is
  changed by this implementation.
- Contract protection: `tests/test_ci_contract.py` declares checks for triggers,
  permissions, concurrency, matrix versions and seeds, exact action pins,
  credential persistence, install/compile/test commands, absence of secret
  references, and an inherited-process socket-blocking probe.
- Documentation: `docs/continuous_integration.md` is the CI security and
  operating contract. `README.md`, `docs/technical_summary.md`, and `AGENTS.md`
  link the workflow, local equivalents, stable gate, and live-service exclusion.
- Deliberate boundary: live OpenAI, provider, full-text-service, and Mantis
  checks; lint/type gates; release automation; deployment; branch-protection
  mutation; and artifact upload remain outside Step 1.10.
- Local verification: the focused CI/documentation contract passes eight tests.
  The complete guarded suite passes 597 tests on Python 3.11.9 with
  `PYTHONHASHSEED=101` and Python 3.12.2 with `PYTHONHASHSEED=1201`.
  Compilation and `git diff --check` are clean.
- Hosted verification passed on 2026-08-31. The branch was pushed at `f062f11`,
  then reconciled with `dev061602` in merge commit `ceede85`. Pull request
  [#2](https://github.com/MarieHensche/ad-literature-knowledge-pipeline/pull/2)
  is open against `dev061602` and is mergeable. Its
  [latest pre-completion-record Foundation CI run](https://github.com/MarieHensche/ad-literature-knowledge-pipeline/actions/runs/33373623958)
  passed the Python 3.11 and 3.12 jobs and the stable `foundation-gate`.
- Required-check enforcement: after the owner deliberately made the repository
  public, active repository
  [ruleset 21912442](https://github.com/MarieHensche/ad-literature-knowledge-pipeline/rules/21912442)
  was created for `refs/heads/dev061602`. It requires `foundation-gate` from the
  GitHub Actions integration, requires the branch to be up to date, and has no
  bypass actors. GitHub's branch-rules API confirms that the rule applies to
  `dev061602`.

This completes Step 1.10 and the Foundation stage. Later implementation phases
must retain the stable `foundation-gate` or deliberately record and review any
replacement before changing the required rule.

### Foundation Corrective Hardening Record

The post-implementation audit identified six verification gaps. They were
resolved before the hosted gate and required-check configuration above:

- Run identity is immutable: a pre-existing run directory is rejected unless
  `--resume` is explicit, and the previous manifest remains byte-identical.
- LLM traces are attempt-scoped and a duplicate call ID is rejected before any
  existing trace artifact is changed.
- Resume closes abandoned running attempts as `interrupted`, continues the
  originally selected step suffix after abrupt termination, preserves legacy
  suffix behavior, and rejects changed assembled pipelines, effective options,
  topic contracts, models, or topic-policy semantic hashes. A crash after the
  last recorded step can be finalized safely; resume cannot redefine the
  original selection or clear a failure through a dry run.
- The effective topic-structure policy is now recorded in run provenance and
  all generic quality/normalization helpers consume the supplied policy rather
  than falling back to default module globals.
- Mantis profile/destination validation is an all-or-nothing preflight. After
  preflight, missing inputs, local exceptions, CLI failures, and new-space
  dependency skips all produce durable sanitized receipts for all three views.
- A hermetic orchestrated end-to-end test now runs the complete eight-step main
  pipeline through the real runner, local full-text extraction, fake LLM
  clients, audit, legacy Mantis export, manifests, artifact hashes, and
  attempt-scoped trace hashes.

Corrective verification passes 613 offline tests on Python 3.11.9 with
`PYTHONHASHSEED=101` and Python 3.12.2 with `PYTHONHASHSEED=1201`. Compilation
and `git diff --check` are clean. Hosted Step 1.10 verification now passes on
the pushed branch and pull request, and the required `foundation-gate` rule is
active on `dev061602`.

---

## Executive Assessment

The current repository is a strong foundation worth extending. It is already
more than a generic summarizer: it has domain contracts, deterministic retrieval
and screening, full-text acquisition, provenance-rich raw candidates,
structured LLM calls, human review gates, manifests, audits, and a substantial
literature-review branch.

It is not yet a scientific gap-discovery system. Today it is best described as:

> A domain-configurable literature collection, tagging, and review pipeline with
> an early, partially implemented knowledge layer.

The most defensible direction is to retain the existing pipeline and build a
provenance-first gap-dossier system on top of it. Each gap dossier should show:

- the gap class;
- the corpus and cutoff date under which it was generated;
- supporting and conflicting claims;
- exact source passages;
- the deterministic signals that generated it;
- all countersearches attempted;
- unresolved uncertainty;
- separate novelty, importance, and feasibility scores;
- human judgments and revisions.

The recommended primary research contribution is a portable gap ontology,
strengthened with the temporal provenance needed for a temporal evidence graph.
The software should also prepare a validated human–AI protocol, but proving that
researchers make better decisions is an external, longitudinal research effort.

The initial audit included the knowledge implementation under
`ad_lit_pipeline/knowledge/` and `ad_lit_pipeline/steps/knowledge/`. The new
implementation baseline starts from clean commit `dd1fbc3`. Step 1.1
re-established 295 passing pre-Step tests and 297 passing post-Step tests after
adding two baseline regressions. Historical demo measurements below are
diagnostic observations only, not the Step 1.1 fixture or acceptance baseline.

## Current Implemented System

The current execution structure is approximately:

```text
Research question / topic contract
        |
        +-- Contract generation and review-seeded refinement
        +-- Search planning
        +-- OpenAlex collection
        +-- Deduplication and relevance screening
        +-- Full-text availability and extraction
        +-- Canonical paper CSV
                |
                +-- Topic tagging -> audit
                |       +-- Legacy paper Mantis CSV -> manual import
                +-- Review labels -> evidence map -> literature review
                +-- Optional knowledge export
                        +-- Source records
                        +-- Evidence excerpts
                        +-- Finding records
                        +-- Not currently delivered to Mantis

Future verified knowledge and ranked gap dossiers
        +-- One Mantis space with three versioned projections
                +-- Paper landscape
                +-- Verified-claim landscape
                +-- Verified-gap landscape
                +-- Deterministic CSV fallback
                +-- Optional authenticated map publication
                +-- Controlled interpretation writeback
```

The final vision stages—relationship construction, gap generation,
counterverification/ranking, and prospective validation—do not yet exist as
complete executable pipeline branches.

### Overall Maturity

| Vision component | Current state | Feasibility in this repository |
| --- | --- | --- |
| Corpus construction | Substantial foundation, one discovery provider | Strongly feasible |
| Evidence graph | Schemas and scaffolding only | Feasible, substantial work |
| Multi-signal gap engine | Explicit-gap fragment only | Feasible after graph and evidence fixes |
| Claim-level verification | Nominal links, not claim-level proof | Feasible and high priority |
| Human steering | Good contract/run controls, no gap workspace | Strongly feasible |
| Three-way ranking | Absent | Feasible after verification |
| Prospective validation | Generic run infrastructure only | Software feasible; actual study external |
| Cross-domain benchmark | Absent | Harness feasible; gold data expensive |
| Mantis terminal delivery | Heuristic paper CSV and manual import link only | Strongly feasible through explicit profiles, CSV fallback, and optional publication |

## Mantis As The Required Terminal Consumer

### What Mantis Adds

Mantis is well suited to the final exploration layer: it embeds records into
semantic maps, exposes clusters and categories, preserves links back to context,
and supports CSV/XLSX ingestion, a developer CLI, MCP tools, and a Python SDK.
Those capabilities complement this pipeline, but they do not establish whether
a claim or gap is scientifically valid.

The canonical scientific system of record therefore remains the versioned
JSONL/SQLite artifacts, exact passages, verification attempts, countersearches,
scores, and judgment events. Mantis receives deterministic projections of those
records and provides an interactive research landscape.

### Current Repository State

- `export_mantis` runs at the end of the current tagging branch and produces a
  paper CSV with `title`, `categoric`, `semantic`, `paper_id`, `year`, `doi`, and
  inferred extra fields.
- The default path does not publish a space or map. The UI only downloads the
  legacy file and opens the signed-in Mantis import page.
- Extra fields are inferred from CSV column order, and `categoric` can fall back
  to the first arbitrary non-empty inferred field.
- A separate Step 1.7 path now provides versioned paper, verified-claim, and
  verified-open-gap profiles, deterministic CSVs, audit reports, an external CLI
  adapter, and immutable success/failure receipts. It is not wired into the
  default main pipeline because that pipeline does not yet emit complete v1
  scientific records.
- No live import test, refresh/upsert contract, interpretation capture, expert
  writeback, or automated production record feed exists yet.

The public integration surface was re-audited on 2026-08-27. Official Mantis
documentation describes `mantisai-cli` 3.7, developer-key setup, CSV map
creation, explicit column-type flags, new/existing spaces, visibility, and
activation. Despite an XLSX help reference, its current local parser is CSV.
No stable refresh/upsert behavior has been demonstrated for this pipeline.
Step 1.7 therefore pins exact CLI 3.7.0 as an external tool, uses only CSV
create/reject behavior, and adds no Mantis or `pandas` runtime dependency.

### Required Projection Contracts

Use three separate projections—preferably three maps in one project space—because
papers, verified claims, and verified gap dossiers are different semantic units:

| Projection | One Mantis point represents | Required content |
| --- | --- | --- |
| Paper | One stable scholarly work/version | Stable work/version IDs, title/abstract, snapshot/cutoff, source type, study metadata, topic categories, scope state, and resolvable provenance links |
| Verified claim | One verified claim version | Claim text, exact evidence passage links, population, method, outcome, direction, design, source/version IDs, verifier state, and uncertainty |
| Gap dossier | One deduplicated, counterverified gap candidate version | Gap title and rationale, gap class, status, snapshot/cutoff, support and counterevidence links, countersearch status, coverage, uncertainty, and separate novelty/importance/feasibility scores |

Every profile must explicitly declare record kind, source schema version,
ordered output fields, Mantis data type, null and multivalue policy, semantic
text construction, and compatibility version. Never infer fields from input
column position.

Preferred Mantis type mapping:

| Mantis type | Pipeline use |
| --- | --- |
| `Title` | Human-readable paper, claim, or gap title |
| `Semantic` | Evidence-grounded claim text or gap description/rationale used for embedding |
| `Categoric` | Record kind, gap class, status, domain, study design, population, and controlled tags |
| `Numeric` | Evidence counts, coverage, uncertainty, and the three separate scores |
| `Date` | Publication, snapshot, cutoff, verification, and publication dates |
| `Links` | DOI/source, exact evidence, counterevidence, and local dossier links |
| `Connection` | Optional graph relations only after an authenticated compatibility spike proves the serializer and UI behavior |

### Delivery Strategy

1. Always create deterministic CSV files and a versioned Mantis profile locally.
2. Preserve the legacy paper CSV until compatibility tests permit a deliberate
   migration.
3. Add `publish_mantis` only after export. Keep it authenticated, optional for
   offline/test runs, retryable, and governed by an explicit duplicate/upsert
   policy before calling it idempotent.
4. Prefer a first integration spike through the public Mantis CLI because its
   current implementation uploads CSV with developer-key authentication and
   avoids adding `pandas`. Although its help advertises XLSX, treat CSV as the
   verified boundary. Evaluate the Python SDK later for typed refresh,
   annotations, or writeback.
5. Record profile version, input hash, tool/version, non-secret host, space ID,
   map ID, stable Mantis URIs when available, status, and errors in an immutable
   publication receipt. Never record cookies, developer keys, or other secrets.
6. Mock publication in the normal suite and keep signed-in import/publish and
   round-trip checks explicitly opt-in.
7. Keep structured expert judgments in the local append-only protocol unless a
   tested Mantis writeback adapter can capture the same immutable events.
8. Do not let live Mantis availability block the scientific pipeline; preserve
   validated local outputs and record publication failure visibly.
9. Treat Mantis interpretations as pre-candidate hypotheses. Capture the
   map/profile version, immutable map-input hash, selected point IDs, actor,
   prompt/action, timestamp, and output in a structured `MantisInterpretation`
   record. Create a `proposed` gap candidate only after an independent
   deterministic signal exists, then route it through the normal counterretrieval
   and verification pipeline.

Access to a signed-in developer account is useful for the opt-in live smoke,
completion-state inspection, native Connection testing, interpretation capture,
and writeback. The private repository is not required for the implemented CLI
adapter.

Current primary references for this planning decision:

- [Mantis documentation](https://mantis.csail.mit.edu/docs/)
- [Mantis CLI 3.7](https://mantis.csail.mit.edu/docs/mantis-cli/)
- [CLI installation and CSV map creation](https://mantis.csail.mit.edu/docs/mantis-cli/install.html)
- [Space creation and field types](https://mantis.csail.mit.edu/docs/start/create-a-space.html)

Re-audit the public API and pinned tool version before a live publication smoke
or any refresh, native relation, interpretation, or writeback work.

---

# Vision-By-Vision Audit

## 1. Corpus Construction

### Already Implemented

- Import of CSV, BibTeX, JSON, JSONL, and RIS metadata.
- A canonical paper representation containing title, year, DOI, abstract,
  authors, venue, URL, source, and full-text metadata.
- OpenAlex collection with:
  - exact publication-date filters;
  - year, language, type, abstract, access, and full-text filters;
  - multiple query variants;
  - tiered topic retrieval;
  - pagination, rate-limit retries, backfill, and deduplication;
  - retrieval query, rank, provider URL, retrieval date, topic matches, and raw
    OpenAlex records.
- Raw OpenAlex records retain publication/update dates, type, identifiers,
  locations, versions, retraction status, concepts, references, and citation
  counts.
- Full-text lookup through local files, provider locations, DOI pages,
  Unpaywall, Europe PMC, and CORE.
- Caching of extracted text.
- Topic-specific include/exclude policies and retrieval vocabulary.
- Paper and candidate deduplication.
- Finding enums that permit negative, null, mixed, and inconclusive results.

### Current Limitations

- The raw corpus is richer than the canonical corpus.
- Candidate export narrows records to a small CSV and serializes provider ID,
  retrieval date, query, rank, and screening evidence into a semicolon-delimited
  `notes` field.
- Exact publication date, version, citation provenance, retraction state, and
  provider update dates are discarded downstream.
- Knowledge Source export therefore receives a transformed source label instead
  of the true provider identity and can fall back to DOI as `provider_id`.
- Metadata normalization uses a fixed output column set and can discard useful
  extra columns from user-provided inputs.
- Artifact names remain OpenAlex-specific even though a provider interface exists.
- Date constraints are not first-class corpus fields in the topic template.
- Scholarly work identity is not separated from preprint, manuscript, published
  version, correction, or update identities.
- A `null` finding enum does not mean negative-result repositories or unpublished
  null studies are actually collected.

### Feasible Extensions

- A provenance-preserving canonical corpus model.
- Work-versus-version identities.
- Explicit corpus snapshots and cutoff dates.
- Preprint, trial, protocol, and dataset records.
- Citation and version edges.
- Negative/null findings when reported in accessible sources.
- Additional provider adapters with mocked contract tests.
- Structured licensing, retraction, and access metadata.
- First-class source-type and study-design normalization.
- A Mantis paper projection that retains stable work/version IDs, corpus
  snapshot, cutoff, source type, scope state, and resolvable provenance links.

Recommended provider order:

1. Harden OpenAlex and preserve its full provenance.
2. Add Europe PMC as a discovery provider.
3. Add a clinical-trial registry adapter.
4. Add DOI/dataset enrichment such as Crossref/DataCite-style adapters.
5. Add a preprint-specific source only if coverage analysis justifies it.
6. Add patent discovery last and keep it optional.

### Extreme Or Impossible Guarantees

- A complete global corpus.
- Discovery of confidential, abandoned, or unpublished studies.
- Comprehensive negative-result coverage.
- Access to all paywalled full text.
- Proof that no study exists.
- Reconstruction of an old knowledge state without historical snapshots.
- Uniform patent coverage across jurisdictions, languages, families, and
  licensing regimes.

Patent support is possible, but reliable cross-domain patent normalization and
claim comparison is a very high-effort provider project.

## 2. Evidence Graph

### Already Implemented

Three useful foundations exist:

1. Topic contracts model anchor topics, main topics, secondary replacements,
   retrieval terms, matching terms, scope policies, and tagging categories.
2. The review evidence map extracts and aggregates methodology, study design,
   dataset/sample, findings, limitations, quotations, and explicit future work.
3. Knowledge schemas define Source, EvidenceExcerpt, Finding, Relationship, Gap,
   SynthesisClaim, and FieldSummary records.

Preliminary relationship types include `supports`, `contradicts`, `uses_method`,
`studies_population`, `uses_dataset`, and `measures_outcome`. Artifact paths also
exist for relationships, gaps, synthesis claims, and field summaries.

There is no implemented relationship builder or queryable evidence graph yet.

### Feasible Extensions

Add first-class nodes for:

- scholarly work;
- source version;
- document;
- passage;
- claim;
- method;
- intervention;
- population;
- outcome;
- measurement;
- dataset;
- protocol;
- study design;
- gap candidate.

Add provenance-bearing relations for:

- claim supported by passage;
- claim reported by source version;
- source cites source;
- study uses method;
- study examines population;
- study measures outcome;
- claim supports or contradicts claim;
- gap candidate generated from signal;
- gap candidate refuted or weakened by claim.

Use JSONL as the portable exchange format and SQLite as the initial query and
integrity layer. A graph database is not required for the first version.

Mantis maps and optional `Connection` fields are read-only projections for
exploration. They must not replace canonical nodes, edges, foreign-key checks,
or temporal queries in JSONL/SQLite.

### Extreme Or Impossible Guarantees

- A universal ontology requiring no domain adaptation.
- Fully automatic entity resolution for all terminology and abbreviations.
- Scientifically correct contradiction detection across incompatible designs,
  populations, outcomes, measurements, and interventions.
- Treating a missing graph edge as proof that something was never studied.

The graph must use open-world semantics: a missing edge means not represented
in this corpus snapshot, not globally nonexistent.

## 3. Gap-Generation Engine

### Already Implemented

- Explicit `future_work_or_gap` extraction.
- Paper-reported limitations.
- Methods, study designs, datasets/samples, and key findings.
- Finding types and directions.
- Topic/tag distributions.
- Citation-linked review sections for explicit gaps and future directions.
- Conservative instructions that reject generic calls for more research.

A historical audit artifact—not the Step 1.1 baseline—contained 30 labeled
papers, with explicit future work/gaps in 10, key findings in 19, limitations in
15, and direct quotations in 11. These were useful diagnostics, but no
multi-signal gap engine combines them.

### Feasible Extensions

- Explicit author-stated gaps.
- Sparse or missing entity combinations.
- Contradictory findings.
- Weak evidence concentrations.
- Underrepresented populations.
- Methods used in one context but not transferred to another.
- Stale evidence.
- Clusters without direct comparative studies.
- Poorly connected evidence regions.
- Dataset reuse or validation gaps.
- Protocols/trials without linked results.

Every generator should be deterministic or rule-driven and emit a `GapSignal`.
An LLM may normalize, structure, phrase, or explain a gap, but must not be the
sole reason it exists.

Mantis-facing gap records must have stable IDs and explicit gap type, status,
coverage, and uncertainty fields. Proposed or unverified candidates must never
appear as established gaps merely because they are visible on a map.

### Extreme Or Impossible Guarantees

- Exhaustive gap discovery.
- Automatic knowledge that an empty graph cell is scientifically important.
- Reliable contradiction detection without comparability rules.
- Universal importance inference from graph sparsity.
- Proof of novelty from absence.
- Automatic distinction between unpublished evidence and a genuinely unstudied
  question.

## 4. Claim-Level Retrieval And Verification

### Already Implemented

- Findings link to source and evidence-excerpt IDs.
- Validators reject unknown topic and excerpt IDs.
- Review synthesis accepts only paper IDs included in its evidence packet.
- Search candidates retain query provenance.
- LLM traces retain system prompt, prompt, schema, raw response, parsed output,
  and metadata.
- Run manifests hash step inputs and outputs.

### Current Limitations

- Knowledge excerpts can contain up to 24,000 characters.
- They do not retain page, paragraph, or character offsets.
- Section prioritization can reorder text relative to the source document.
- Direct quotations are validated for shape, not exact source occurrence.
- Review citations prove that a paper ID is allowed, not that every generated
  sentence is entailed by that paper.
- Finding validation proves that an excerpt ID exists, not that it supports the
  claim.
- The same LLM creates a finding and assigns its confidence/evidence strength.

Historical audit characteristics—not current acceptance fixtures:

- 100 Source records;
- 53 sources with evidence excerpts;
- all 53 excerpts classified as `body`;
- mean excerpt length approximately 18,293 characters;
- 43 excerpts longer than 10,000 characters;
- 83 findings, each linked to one large excerpt;
- 76 positive, 6 negative, 1 mixed, no null/inconclusive findings;
- 79 of 83 marked high evidence strength.

This indicates section-detection failure, likely positive-result bias, and
self-evaluation bias. It is not calibrated scientific validation.

### Feasible Extensions

1. Preserve page and document coordinates during PDF/HTML extraction.
2. Store canonical ordered passages separately from retrieved LLM context.
3. Use paragraph-sized or bounded semantic passages.
4. Require exact claim-to-passage spans.
5. Verify quoted text against the document snapshot.
6. Hash documents and passages.
7. Run an independent verifier returning supported, contradicted, insufficient,
   or uncertain, and record mandatory human-review triggers independently.
8. Validate numeric details, sample sizes, direction, and study design.
9. Preserve failed extractions as retry/review records.
10. Run countersearches using normalized entities, aliases, synonyms, acronyms,
    citations, and adjacent literatures.
11. Record every search, result, limitation, and cutoff date.
12. Require every Mantis gap point to link to exact support, counterevidence,
    countersearch status, and verification state.

### Extreme Or Impossible Guarantees

- Guaranteed semantic truth from text alone.
- Verification of claims depending on inaccessible supplements or raw data.
- Guarantee that adjacent or unpublished literature does not address a question.
- Fully automatic methodological-bias and statistical-validity assessment across
  all domains.

## 5. Human-Steerable Interaction

### Already Implemented

- Topic-contract controls for scope, vocabulary, providers, policies, and tags.
- UI creation, loading, editing, and saving of raw topic contracts.
- Collection size, seed count, model, input, run ID, and step controls.
- Human pause gates for tagging categories and review label values.
- Coverage-based review pauses.
- Inspectable manifests, traces, queries, tiers, and screening reasons.

The UI currently exposes collection, paper tagging, and manifests; it has no
knowledge or gap workspace.

### Feasible Extensions

- Structured source and corpus controls.
- Publication and snapshot date fields.
- Source-type selection.
- Vocabulary and alias editing.
- Inclusion-rule preview.
- Gap-type switches and support/coverage thresholds.
- Importance criteria and weights.
- Gap table and graph views.
- Supporting/conflicting passage cards.
- Countersearch history.
- Uncertainty and coverage display.
- Accept, reject, already-known, duplicate, edit, and defer actions.
- Comparison across corpora, contracts, and cutoff dates.
- Blinded evaluation mode.
- Append-only judgment logs with candidate version, user, protocol, timestamp,
  and rationale.
- Published Mantis space/map links and status for semantic landscape
  exploration.

### Extreme Or External Requirements

The UI cannot create expert ground truth. Mantis interactions also do not become
evaluation judgments unless an explicit, tested writeback path records them in
the append-only protocol. Recruitment, adjudication, governance, and sustained
expert participation are external requirements.

## 6. Novelty, Importance, And Feasibility Ranking

### Already Implemented

The code has screening confidence, extraction confidence, LLM-assigned evidence
strength, scope/screening reasons, tag distributions, coverage, and review
quality counts. It has no gap ranking or expert calibration.

### Feasible Extensions

Novelty can use:

- countersearch outcome;
- evidence recency;
- resolving-study quantity and quality;
- terminology-artifact checks;
- corpus coverage;
- temporal cutoff;
- unresolved/refuted state.

Importance can use:

- user-defined theoretical, clinical, practical, or policy criteria;
- affected population or burden;
- decision relevance;
- recurrence across sources;
- expert judgments.

Feasibility can use:

- accessible datasets;
- available methods;
- recruitment constraints;
- sample-size implications;
- ethical/regulatory requirements;
- estimated resource class;
- existing protocol or trial infrastructure.

The three scores must always remain separately visible. A configurable composite
may sort candidates, but must not replace the individual dimensions.
Their Mantis projection must use separate numeric fields; it must not collapse
them into one category, one model-confidence value, or an unexplained composite.

### Extreme Or Invalid Claims

- Objective, domain-independent importance.
- Reliable feasibility without domain and institutional context.
- Calling scores calibrated before expert-label evaluation.
- Treating model confidence as novelty, importance, or evidence quality.

## 7. Prospective Validation

### Already Implemented

Only generic infrastructure is reusable: run IDs, manifests, hashes, human
pauses, the local UI, review decisions, and trace-like artifacts.

### Feasible Software Support

- Frozen gap-list versions.
- Protocol IDs.
- Expert assignment and blinded conditions.
- Accept/reject/already-known/duplicate judgments.
- Decision time, confidence, and rationale.
- Follow-up events for proposals, funding, preregistration, experiments,
  preprints, publications, or abandonment.
- DOI, grant, and protocol links.
- Deidentified exports.
- Predeclared metrics.
- Frozen Mantis profile, source hash, space ID, map ID, and candidate-version
  references in each expert task package.

### External Or Extreme Requirements

- Qualified expert recruitment.
- Ethics/privacy approvals.
- A sufficiently powered controlled study.
- Multi-year funding/publication outcomes.
- Causal proof that the system improved research decisions.

The software can prepare this contribution but cannot establish it on its own.

## 8. Cross-Domain Benchmark

### Already Implemented

- Multiple topic-contract examples demonstrate partial domain adaptability.
- Tests cover importers, providers, screening, prompts, LLM schemas, review
  steps, UI behavior, and the first knowledge records.
- LLM tests use reproducible fake clients.
- Step 1.1 records 295 passing tests before its regression additions and 297
  passing tests afterward on clean code commit `dd1fbc3`.

This is engineering validation, not a scientific benchmark.

### Feasible Extensions

- Corpus snapshot schema.
- Source inclusion labels.
- Gold evidence passages.
- Gold claims and entities.
- Accepted and rejected gap candidates.
- Hard negatives.
- Duplicate clusters.
- Temporal cutoff/future splits.
- Contradictory-literature cases.
- Domain contracts and frozen benchmark runs.
- Baseline systems.
- Deterministic Mantis profile/export compatibility fixtures and an opt-in live
  import/publish smoke check.

Required metrics:

- retrieval recall;
- passage recall;
- claim-support precision;
- unsupported-gap rate;
- duplicate-gap rate;
- gap-type precision/recall;
- domain-transfer performance;
- novelty calibration;
- Brier score and expected calibration error;
- expert agreement;
- median decision time and time saved.

If Mantis-assisted exploration changes what experts see or how they work, treat
it as an explicit benchmark or study condition rather than an invisible UI
detail.

### Extreme Or Expensive Requirements

- Expert-created gold annotations across fields.
- Legally distributable full text.
- Adjudication of scientific disagreement.
- Maintained temporal snapshots.
- Strong hard negatives.
- Blinded expert ratings.
- Real time-saved measurements.

Start with a deep Alzheimer-focused benchmark and add domains only after the
first domain is reliable.

---

# Research Contribution Choice

## A. Portable Gap Ontology — Primary Contribution

This is the best fit. Preliminary gap enums exist, but they need operational
definitions, required evidence, disqualifying counterevidence, open-world
semantics, coverage requirements, uncertainty, temporal state, and expert
annotation rules.

The portable ontology should distinguish at least:

- explicit author-stated gap;
- unstudied or sparsely studied combination;
- contradictory evidence;
- weak evidence;
- poorly connected evidence;
- underrepresented population;
- method-transfer gap;
- dataset/validation gap;
- stale evidence;
- missing direct comparison.

## B. Temporal Provenance-Preserving Graph — Supporting Contribution

The raw data already contains publication, update, version, and retrieval dates,
and manifests hash artifacts. Missing pieces are immutable snapshots, valid-time
and transaction-time fields, version lineage, `as_of` query semantics, complete
code/prompt/config provenance, and graph construction.

This is feasible prospectively. Historical claims must remain qualified when no
historical snapshot exists.

## C. Validated Human–AI Protocol — Prepare Now, Claim Later

Build event logging, blinding, task packages, and evaluation exports early so
real interactions can later form usable study data. The scientific contribution
is incomplete until the controlled expert study actually runs.

---

# Critical Inconsistencies And Renewal Work

## Priority 0: Scientific-Validity Blockers

- [ ] Preserve structured provenance across the canonical handoff instead of
  packing it into `notes`.
- [ ] Replace large pseudo-section excerpts with resolvable, claim-local passages.
- [ ] Exclude or explicitly mark out-of-scope rows in knowledge exports.
- [ ] Add semantic claim support checks, not only valid IDs.
- [ ] Separate finding extraction from evidence/scientific-quality judgment.
- [ ] Implement relationship and gap pipeline steps; current contracts alone are
  not functionality.
- [ ] Use one shared source-type classifier.
- [ ] Unify overlapping review-label and knowledge-finding extraction.
- [x] Prevent proposed or unverified gaps from being presented in Mantis without
  an explicit verification state, coverage, and uncertainty.

## Priority 1: Architecture And Reproducibility

- [ ] Add `schema_version` and migrations to durable records.
- [ ] Add corpus snapshot IDs and first-class date/cutoff fields.
- [x] Extend manifests with git state, environment, command/config, prompt/schema
  hashes, provider dates, and model parameters.
- [x] Use one central pipeline/dependency registry for CLI and UI.
- [ ] Generate planner provider choices from executable adapters.
- [ ] Rename provider-specific artifact paths before multi-provider collection.
- [x] Move domain-specific heuristics from Python into contracts/policies.
- [x] Reconcile or retire obsolete review scaffolding.
- [x] Document optional knowledge-layer CLI behavior.
- [x] Add parallel versioned paper, verified-claim, and gap-dossier export
  profiles; retain the column-order-derived legacy path only for compatibility.
- [x] Add Mantis publication receipts and explicit terminal-step dependencies.
- [ ] Add structured Mantis interpretation records and route hypotheses back
  through counterretrieval and verification.
- [x] Keep Mantis credentials out of commands, manifests, traces, logs, and
  artifacts in the versioned adapter and receipts.

## Priority 2: Scalability And Maintainability

- [ ] Stream CSV/JSONL where practical.
- [ ] Add resumable per-source extraction/verification work queues.
- [ ] Reuse LLM clients.
- [ ] Add bounded concurrency, caching, rate handling, and cost accounting.
- [ ] Separate checked-in example artifacts from live generated artifacts.
- [x] Add CI with local/hosted matrix verification and a required stable gate.
- [x] Add mocked Mantis publisher tests.
- [ ] Add an opt-in live round-trip smoke test and incremental/idempotent
  publication support.

---

# Dependency-Ordered Implementation Roadmap

## Phase 0 — Freeze The Baseline And Scientific Claims

Goal: make later comparisons trustworthy.

Instructions:

1. Record the clean branch, commit SHA, environment, and baseline commands.
2. Run the complete non-network suite and record its fresh result; do not assume
   the historical total of 295.
3. Create a small synthetic, copyright-safe corpus independent of historical
   demo artifacts and freeze its expected current outputs, including the legacy
   Mantis CSV.
4. Add golden and structural assertions for that Mantis CSV before deliberately
   migrating its contract.
5. Define `gap candidate`, `corpus-sparse`, `as of`, and the difference between
   extraction confidence and scientific confidence.
6. Update README and technical documentation to match implemented behavior.
7. Retire or update stale review scaffolding.
8. Add CI for the non-network test suite.

Exit gate:

- The clean baseline SHA and fresh test result are recorded.
- The new synthetic fixture and expected outputs are reproducible and do not
  depend on removed or historical demo artifacts.
- Existing CLI behavior and the current Mantis CSV remain unchanged.
- All existing tests pass, and the Mantis fixture output is deterministic.
- Generated artifacts are not accidentally mixed with source changes.

## Phase 1 — Define Versioned Data And Gap Contracts

Goal: agree on durable records before producing more artifacts.

Implement versioned contracts for:

- `CorpusSnapshot`
- `ScholarlyWork`
- `SourceVersion`
- `ProviderRecord`
- `AccessLocation`
- `Document`
- `Passage`
- `Entity`
- `Claim`
- `ClaimEvidence`
- `Relationship`
- `GapSignal`
- `GapCandidate`
- `VerificationAttempt`
- `GapScore`
- `ExpertJudgment`
- `OutcomeEvent`
- `MantisExportProfile`
- `MantisInterpretation`
- `MantisPublicationReceipt`

Required common fields:

- `schema_version`;
- stable ID;
- creation timestamp;
- source snapshot ID;
- producing run/step ID;
- parent/source references;
- provenance;
- status;
- validation warnings.

`MantisExportProfile` must additionally define record kind, source contract and
schema version, ordered output fields, one explicit Mantis type per retained
column, null/multivalue policy, semantic text construction, and compatibility
version. `MantisPublicationReceipt` must record the source hash, profile/tool
version, non-secret host, space/map identifiers, publication time and status,
and retry/error details without credentials.

`MantisInterpretation` must record the source space/map and profile versions,
immutable map-input hash, selected stable point IDs, actor, prompt or action,
timestamp, generated hypothesis, and downstream verification state. It is never
evidence or a gap candidate by itself.

Define operational rules for every gap class: generating evidence, minimum
support, refuting evidence, coverage assumptions, open-world limitations, and
human annotation questions.

Exit gate:

- All record fixtures validate.
- Cross-artifact validation detects orphan IDs.
- A migration policy is documented.
- No gap type is only a label without an operational definition.

## Phase 2 — Repair Corpus And Provenance Handoffs

Goal: prevent critical metadata loss.

Instructions:

1. Preserve provider, provider ID, exact publication date, type, version, query,
   tier, rank, timestamp, raw-record hash/location, license, access, retraction,
   correction, and citation data.
2. Preserve unknown input columns unless an explicitly narrow output is required.
3. Separate work, version, and provider-record identities.
4. Replace free-form provenance notes with structured records.
5. Add contract fields for publication window, `as_of`, source types, providers,
   languages, access, versions, and negative/null-result policy.
6. Filter knowledge exports by scope or carry explicit scope state.
7. Consolidate source-type classification.
8. Make snapshot artifacts immutable or content-addressed.
9. Require each Mantis projection to retain stable record/work/version IDs,
   snapshot, cutoff, scope/status, and resolvable provenance instead of
   flattening essential context into free-form notes.

Exit gate:

- An OpenAlex candidate traces losslessly into Source/SourceVersion.
- Provider ID, query, publication date, version, and snapshot are structured.
- Unchanged snapshots produce stable identities.

## Phase 3 — Strengthen Reproducibility And Orchestration

Goal: make every result reconstructable.

Instructions:

1. Extend manifests with full code/environment/schema/prompt/command provenance.
2. Save the exact corpus specification and resolved plan.
3. Add a provider query log with requests, cutoffs, hashes, pages, and result IDs.
4. Centralize CLI/UI pipeline construction.
5. Extend `StepSpec` with dependencies and capabilities.
6. Validate dependencies before execution.
7. Add idempotency and compatible-output checks.
8. Keep scripts thin.
9. Make deterministic, profile-driven Mantis CSVs required terminal artifacts.
10. Add an optional authenticated `publish_mantis` step immediately after each
    relevant export; publication failure must preserve the validated local
    artifacts and produce a clear warning/receipt.
11. Record profile/hash/tool/space/map metadata and never credentials.
12. Keep the legacy paper export as a compatibility branch. Run the eventual
    gap publication only after verification, counterretrieval, deduplication,
    and ranking.

Exit gate:

- CLI and UI select identical steps for identical options.
- Every downstream result traces to code/config/model/corpus versions.
- Resume cannot combine incompatible snapshots.
- CLI and UI agree on export and optional publication order, and an offline run
  always ends with usable deterministic Mantis CSV artifacts.

## Phase 4 — Generalize Provider Integration

Goal: add heterogeneous sources safely.

Instructions:

1. Declare provider capabilities for source types, filters, cutoffs, versions,
   citations, raw records, and full-text locations.
2. Generate planner provider options from registered implementations.
3. Refactor OpenAlex through the new mapper first.
4. Add Europe PMC, trials, enrichment, preprints, and patents in that order.
5. Require deterministic IDs, raw records, pagination, rate handling, normalized
   dates/identifiers, and mocked contract tests for each adapter.
6. Extract citation and version lineage.
7. Keep patents outside the initial critical path.

Exit gate:

- Two genuinely different source types pass through the same corpus contract.
- Provider logic remains outside orchestration.
- Unsupported capabilities fail before network calls.

## Phase 5 — Build A Resolvable Document And Passage Layer

Goal: make every evidence item precisely locatable.

Instructions:

1. Preserve document hash and extraction engine/version.
2. Retain PDF page boundaries and HTML headings/paragraphs.
3. Store ordered passages with page, section, paragraph, offsets, text, and hash.
4. Separate document order from relevance-prioritized retrieval.
5. Replace whole-body excerpts with bounded passages.
6. Add quality checks for garbling, missing pages, repeated headers, broken
   sectioning, and suspicious lengths.
7. Quarantine low-quality documents.
8. Add OCR only after measuring need.
9. Enforce licensing and trace-retention rules.

Exit gate:

- Every evidence span resolves to a document snapshot.
- Sampled quotations match the source after documented normalization.
- The new synthetic baseline fixture does not collapse all evidence into single
  `body` excerpts.

## Phase 6 — Unify Entity, Claim, And Review Extraction

Goal: eliminate incompatible parallel extraction.

Instructions:

1. Create canonical method, intervention, population, outcome, measurement,
   dataset, protocol, and study-design entities.
2. Put aliases and vocabulary in topic contracts.
3. Record how each normalized entity was resolved.
4. Structure claims with subject, relation, outcome, direction, population,
   method, measurement, design, context, sample, estimates, and spans.
5. Represent negative, null, mixed, and inconclusive findings explicitly.
6. Generate review labels from canonical entities/claims.
7. Preserve the legacy paper CSV while adding explicit canonical
   claim/evidence-to-Mantis mapping; do not let Mantis-specific shapes become
   canonical scientific records.
8. Preserve the old review path until parity tests pass.

Exit gate:

- One paper is not independently represented by incompatible review/knowledge
  concepts.
- Every claim has passage evidence.
- Existing exports remain available.

## Phase 7 — Add Independent Claim Verification

Goal: establish scientific validity before gap generation.

Instructions:

1. Verify exact spans, IDs, numbers, direction, and source version.
2. Use a verifier separate from extraction.
3. Return supported, contradicted, insufficient, or uncertain; record mandatory
   human-review triggers independently of that outcome.
4. Store verifier rationale and spans.
5. Separate extraction confidence, reporting quality, study quality, and
   verifier outcome.
6. Derive evidence quality from explicit study factors.
7. Preserve failures as records.
8. Add retry queues and human review for disputed/high-impact claims.

Exit gate:

- Unverified claims cannot enter graph gap generation unnoticed.
- Failure rates are measurable.
- Tests cover unsupported, contradictory, and numerically inconsistent claims.

## Phase 8 — Build The Typed Evidence Graph

Goal: create comparable and queryable evidence structures.

Instructions:

1. Write node/edge JSONL and load it into SQLite.
2. Enforce foreign keys and indexes.
3. Generate source, citation, evidence, method, population, dataset, outcome,
   support, contradiction, and extension relations.
4. Define a comparability key for contradiction analysis.
5. Mark relations as asserted, extracted, inferred, or human-reviewed.
6. Add temporal fields and `as_of` graph queries.
7. Keep graph-database export optional.
8. Add an optional Mantis relationship projection only after the native
   `Connection` encoding and target-resolution behavior are confirmed; stable
   IDs and provenance links remain the safe initial representation.

Exit gate:

- No orphan edges.
- Evidence edges link to verified claims and passages.
- Contradiction is not inferred from sentiment/direction alone.

## Phase 9 — Implement Deterministic Gap Signals

Goal: generate inspectable candidates from multiple signals.

Generator order:

1. Explicit author-stated gaps.
2. Weak evidence.
3. Contradictory evidence.
4. Underrepresented population.
5. Missing direct comparison.
6. Method-transfer gap.
7. Stale evidence.
8. Sparse combination/missing edge.
9. Poor connectivity.

Every signal must include type, structured variables, support, assumptions,
coverage, cutoff, claim IDs, uncertainty, and rule version.

Exit gate:

- Every candidate is reproducible without LLM intuition as its sole source.
- Removing support removes the candidate.
- Low-coverage missing edges cannot become strong gap claims.

## Phase 10 — Add Adversarial Counterretrieval

Goal: try to disprove candidates before ranking them.

Instructions:

1. Generate counterqueries from normalized entities and aliases.
2. Search exact, broader, narrower, synonymous, adjacent, citation-linked, trial,
   protocol, dataset, and preprint literatures as enabled.
3. Respect `as_of`.
4. Record queries, results, zero results, failures, and provider limitations.
5. Run counterresults through the same screening/evidence/claim verifier.
6. Test terminology and indexing artifacts.
7. Move candidates through the declared `proposed`,
   `verification_in_progress`, `verified_open`, `refuted`, `resolved`,
   `uncertain`, `terminology_artifact`, or `duplicate` states.
8. Never treat zero results as strong evidence under poor coverage.

Exit gate:

- Every retained candidate has a countersearch dossier.
- Counterevidence changes status.
- Failures and inaccessible sources remain visible.

## Phase 11 — Deduplicate, Synthesize, And Rank Gaps

Goal: prioritize candidates without collapsing scientific dimensions.

Instructions:

1. Cluster equivalent candidates.
2. Preserve source-specific wording.
3. Compute separate novelty, importance, and feasibility components.
4. Show coverage and uncertainty.
5. Explain every component.
6. Put importance criteria in the topic contract.
7. Use a composite only as optional sorting.
8. Delay calibration claims until expert labels exist.
9. Later measure Brier score, expected calibration error, rank correlation, and
   top-k acceptance by type/domain.
10. Emit a versioned gap-dossier Mantis projection with separate gap class,
    verification state, coverage, uncertainty, novelty, importance,
    feasibility, support, counterevidence, countersearch, and provenance fields.
11. Prefer one project space with separate paper, verified-claim, and
    gap-dossier maps; keep all three profiles independently versioned because
    their semantic units differ.

Exit gate:

- All three scores remain visible.
- Model confidence is not silently treated as importance.
- Duplicate rate is measured.

## Phase 12 — Build The Gap Workbench And Annotation Protocol

Goal: make human steering part of the scientific method.

Instructions:

1. Add a Gap Discovery UI section.
2. Build a structured corpus editor.
3. Show snapshot, scope, cutoff, search path, support, counterevidence,
   uncertainty, and scores.
4. Add accept/reject/known/duplicate/edit/defer actions.
5. Require rationale where the protocol needs it.
6. Version human-edited candidates.
7. Add immutable event logging.
8. Support blinding.
9. Export analysis-ready annotations.
10. Compare contracts/cutoffs side by side.
11. Show Mantis publication status and stable space/map links, while retaining a
    downloadable CSV fallback and immutable publication receipt.
12. Do not count Mantis interactions as expert judgments unless tested writeback
    captures the required append-only protocol events.
13. Capture map-grounded interpretations as hypotheses with stable selections
    and route them back through counterretrieval and claim/gap verification.

Exit gate:

- Users can explain each candidate without reading raw LLM traces.
- Judgments link to candidate version and protocol.
- Controls and actions are included in evaluation exports.

## Phase 13 — Create The Benchmark

Goal: evaluate scientific behavior.

Instructions:

1. Start with an Alzheimer-focused benchmark.
2. Annotate inclusion, source type, passage, entity, claim, contradiction, gap,
   duplicate, and hard-negative data.
3. Freeze a temporal cutoff and future holdout.
4. Compare explicit-gap, rules-only, LLM-only, full-pipeline, and expert baselines.
5. Implement all declared metrics.
6. Add domains using contracts, not Python constants.
7. Treat required new domain-specific Python constants as a transfer failure.

Exit gate:

- Benchmark runs are frozen and reproducible.
- Unsupported and duplicate gap rates are reported.
- Domain transfer uses unchanged pipeline code.

## Phase 14 — Prepare And Run Prospective Validation

Goal: support the human–AI research contribution honestly.

Engineering work:

1. Add protocol registration and condition assignment.
2. Freeze lists before expert exposure.
3. Capture time, decisions, rationale, and confidence.
4. Add longitudinal outcome events.
5. Export deidentified analysis tables.
6. Predeclare outcomes and exclusions.

External work:

- expert recruitment;
- study design and power analysis;
- privacy/ethics review;
- follow-up funding;
- long-term outcome tracking.

Do not claim this contribution complete when only software is implemented.

## Phase 15 — Scale After Scientific Correctness

Instructions:

1. Stream JSONL and CSV.
2. Use SQLite indexes and incremental queries.
3. Cache extraction/verification by document, prompt, schema, and model hashes.
4. Add bounded concurrency and retry queues.
5. Add token/cost accounting.
6. Support incremental corpus updates.
7. Recompute only affected graph/gap components.
8. Monitor provider failures, extraction quality, orphan references, and
   verification rates.
9. Define trace retention and sensitive-data policies.
10. Add incremental/idempotent Mantis synchronization, rate handling,
    completion/failure monitoring, and republishing only for affected records.

---

# Recommended First Impressive Release

The first release should implement:

1. Provenance-preserving OpenAlex corpus snapshots.
2. Exact document passages with page/offset provenance.
3. Canonical methods, populations, outcomes, datasets, designs, and claims.
4. Independent claim verification.
5. Five gap classes:
   - explicit author gap;
   - weak evidence;
   - contradictory evidence;
   - underrepresented population;
   - missing comparative study.
6. Counterretrieval with synonyms and citation expansion.
7. Separate novelty, importance, and feasibility scores.
8. A gap-dossier UI with expert accept/reject/already-known judgments.
9. An Alzheimer-focused benchmark.
10. One second-domain demonstration using only a new topic contract.
11. One Mantis project space with independently versioned paper, verified-claim,
    and verified-gap maps, deterministic CSV fallbacks, controlled
    interpretation writeback, and immutable publication receipts.

This release is useful and defensible without attempting exhaustive providers,
patent normalization, a universal ontology, or a completed prospective study.

## Governing Principle

> Preserve the current collection and human-steerable contract system, but make
> provenance, evidence locality, verification, temporal scope, and uncertainty
> first-class before adding sophisticated gap generation.

---

# Regular Review Checklist

At every plan review, answer and record:

- [ ] Does the full regression suite pass?
- [ ] Did any durable schema change without a version/migration?
- [ ] Can every new claim resolve to an exact source passage?
- [ ] Can every new gap resolve to deterministic signals and verified evidence?
- [ ] Was any provider or corpus metadata lost at a handoff?
- [ ] Are `as_of`, corpus coverage, and open-world uncertainty still visible?
- [ ] Are novelty, importance, and feasibility still separate?
- [ ] Did domain logic enter Python that belongs in a topic contract?
- [ ] Do CLI, UI, documentation, and registry describe the same pipeline?
- [ ] Is the project claiming more scientific validation than the evidence permits?
- [ ] Does every terminal paper, verified-claim, and verified-gap artifact have
  a deterministic, versioned Mantis projection?
- [ ] Does each projection match its declared Mantis field/type profile without
  relying on column order?
- [ ] Are input hashes and space/map IDs recorded without credentials?
- [ ] Does the synthetic fixture still import or publish successfully in the
  opt-in live check?
- [ ] Is Mantis presented as an exploration layer rather than scientific
  validation?
- [ ] Is every Mantis-generated interpretation visibly a hypothesis and routed
  through the same counterretrieval and verification gates as other candidates?

# Decision Log

Add entries in reverse chronological order.

| Date | Decision or deviation | Reason | Consequence / follow-up |
| --- | --- | --- | --- |
| 2026-08-31 | Complete Step 1.10 and Foundation after the Python 3.11/3.12 hosted matrix and stable `foundation-gate` passed on the pushed branch and PR, then require that check on `dev061602` through active repository ruleset 21912442 with no bypass actors. | Local-only verification cannot establish that the committed workflow runs correctly on GitHub or prevent later unverified branch updates. | PR #2 is mergeable and green. Later phases must keep the stable gate required or record and review a deliberate replacement. |
| 2026-08-28 | Complete Step 1.9 with one truthful documentation hierarchy, removal of the obsolete review scaffold, a visibly superseded bootstrap plan, explicit preliminary-versus-v1 scientific boundaries, truthful collection-calibration help, local-link and registry documentation tests, and deterministic literal replacement-target extraction. | Contradictory scaffolding and milestone-era documentation could make implemented review steps look unavailable, preliminary knowledge look verified, or compatibility-only calibration look active. Full verification also exposed a hash-seed-dependent equivalent-word choice. | Step 1.10 can add CI against a documented 43-step, ten-pipeline boundary and the complete offline suite. Collection calibration activation, production v1 record emission, and later scientific pipeline behavior remain separate decisions. |
| 2026-08-27 | Complete Step 1.8 with strict topic-structure policy `1.0.0`, semantic policy identity, generic structural code, profile-driven research vocabulary, automatic or explicit profile selection, shared prompt/runtime guidance, and generated-contract provenance. | Domain adaptability is not credible while named research concepts and parallel prompt heuristics remain embedded in Python. A strict external policy makes the boundary reviewable, portable, testable, and reproducible without weakening legacy behavior. | Step 1.9 reconciles documentation and stale scaffolding. Future domains add or version profiles in policy data rather than changing Python; material policy semantics require a new version and hash. |
| 2026-08-27 | Complete Step 1.7 with three compatibility-v1 Mantis profiles, deterministic audited projections, a separate optional delivery pipeline, exact external CLI 3.7.0 gating, private/non-activating create semantics, and immutable sanitized receipts. | Mantis is valuable for semantic interpretation, but only verified scientific units may enter verified views and remote availability must not control the local pipeline. | The default and legacy exporter remain unchanged. Step 1.8 moves topic logic into contracts. A live disposable-space smoke, native Connection, refresh/upsert, interpretation capture, and expert writeback require later explicit authorization and compatibility evidence. |
| 2026-08-27 | Complete Step 1.6 with one immutable 41-step catalog, nine named pipeline specifications, conditional ordering dependencies, capability metadata, shared typed main/collection assembly, CLI/UI parity, and pre-execution implementation checks. | Duplicated branch insertion in the CLI and UI could silently diverge, while strict same-run predecessor requirements would break legitimate artifact-based `--only-step` and `--from-step` workflows. | Step 1.7 can add versioned Mantis projections and adapters against one authoritative order. Artifact compatibility/idempotency remains later work; superseded review scaffolding is excluded but retained until Step 1.9. |
| 2026-08-27 | Complete Step 1.5 with versioned, atomic manifests; sanitized content-addressed code/environment/invocation/contract/provider provenance; hashed exact LLM traces; provider timing; append-only resume attempts; and an explicit missing-snapshot record. | Reconstructability requires effective inputs and history to be recorded without leaking credentials or overstating capabilities the legacy pipeline does not have. | Step 1.6 centralizes pipeline/dependency assembly. The Corpus stage must emit canonical snapshot IDs/cutoffs before resume can enforce snapshot compatibility; production scientific records and Mantis publication remain unwired. |
| 2026-08-27 | Complete Step 1.4 with offline collection-wide referential, ownership, closure, chronology, lineage, artifact, and passage validation plus an explicit but empty migration-path registry and atomic migration policy. | Record-local validity cannot establish that cited records or bytes exist, and inventing a migration without a target schema would create false compatibility. | Step 1.5 may record integrity artifacts in run provenance. Production wiring, a real migration executor, remote artifact fetching, legacy-knowledge conversion, and live Mantis publication remain later explicit steps. |
| 2026-08-27 | Complete Step 1.3 with schema `1.0.0`, 20 strict durable record contracts, 12 operational gap classes, deterministic typed IDs, record-local scientific validation, and explicit Mantis profile/interpretation/receipt boundaries. | Later corpus, evidence, gap, scoring, evaluation, and Mantis stages need one immutable versioned language before they emit artifacts. | Step 1.4 must add cross-artifact integrity and migration policy; no Step 1.3 local success may be represented as proof that referenced records or files exist. |
| 2026-08-27 | Complete Step 1.2 with cross-domain scientific-validity policy `1.0.0`, append-only gap-state history, qualified open-world language, separately typed assessment dimensions, orthogonal claim outcomes and human-review triggers, and Mantis pre-candidate semantics. | Gap statements need enforceable scientific semantics before durable records or generation steps are added. | Step 1.3 records cite schema and policy versions and enforce record-local lineage/evidence declarations; Step 1.4 verifies them across artifacts. No current `Gap`, `evidence_strength`, pipeline, or legacy Mantis meaning is silently upgraded. |
| 2026-08-26 | Use Mantis as a controlled interpretation workspace as well as the final exploration layer, with separate paper, verified-claim, and verified-gap maps in one space. | Map-grounded comparison, clustering, and agent interaction can generate useful hypotheses if they retain selections and provenance. | Add `MantisInterpretation` pre-candidate records; require an independent deterministic signal before creating a `proposed` gap, then apply normal counterretrieval and verification. |
| 2026-08-26 | Complete Step 1.1 at clean code commit `dd1fbc3` with a new eight-record synthetic fixture and frozen legacy Mantis contract. | Later exporter and knowledge-contract changes need a reproducible comparison point independent of historical demo artifacts. | Preserve the fixture and its hashes; 295 pre-Step and 297 post-Step tests pass. |
| 2026-08-26 | Make Mantis a required terminal consumer while keeping deterministic local CSVs and canonical evidence artifacts authoritative; authenticated publication remains feature-gated. | Mantis is a strong semantic exploration and delivery layer, but availability or map generation cannot determine scientific validity. | Add explicit paper, verified-claim, and gap-dossier profiles, publication receipts, mocked publisher tests, and an opt-in live round-trip test. |
| 2026-08-26 | Use a new synthetic, copyright-safe fixture for Step 1.1 instead of historical demo artifacts. | The historical demo test was removed and the new clean baseline must be small, deterministic, and purpose-built for current and Mantis contracts. | Re-measure the clean-HEAD suite and freeze new expected artifacts before feature work. |
| 2026-08-26 | Use the portable gap ontology as the primary contribution, temporal provenance as supporting infrastructure, and prospective validation as a later study. | Best fit with the implemented pipeline and achievable scientific novelty. | Complete Foundation, Corpus, and Evidence stages before sophisticated gap ranking. |
