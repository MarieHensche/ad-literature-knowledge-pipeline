# Gap-Discovery System: Living Implementation Plan

Status: active planning document  
Last reviewed: 2026-08-26  
Review cadence: review at the start and end of every implementation phase, and
whenever a schema, provider, scientific-validity rule, or pipeline order changes.

This is the canonical plan for extending the existing literature knowledge
pipeline into a domain-adaptable, provenance-preserving, scientifically
defensible gap-discovery system. Update progress in this file rather than
creating disconnected plans.

## How To Use This Plan

- Keep the five major stages stable unless the overall product direction changes.
- Change checklist markers only after the corresponding exit gate passes.
- Record important scope decisions and deviations in the decision log at the end.
- Do not call a gap scientifically validated merely because its software step is
  implemented.
- Preserve the existing CLI and Mantis/review workflows while the knowledge layer
  is introduced behind compatible adapters.

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

## Stage 1: Foundation — First Ten Sub-Steps

- [ ] 1. Freeze and document the current passing baseline, representative demo
  corpus, and expected artifacts.
- [ ] 2. Define precise scientific terminology, especially `gap candidate`,
  `corpus-sparse`, `as of`, `supported`, `refuted`, and `uncertain`.
- [ ] 3. Define versioned contracts for every durable corpus, evidence, graph,
  gap, scoring, and judgment record.
- [ ] 4. Add cross-artifact referential validation and a documented schema
  migration policy.
- [ ] 5. Extend run provenance with code, environment, command, prompt, schema,
  model, contract, provider, and snapshot information.
- [ ] 6. Make pipeline assembly and step dependencies a single source of truth
  shared by the CLI and UI.
- [ ] 7. Preserve compatibility for existing collection, tagging, review, and
  Mantis workflows through explicit adapters and regression tests.
- [ ] 8. Move domain-specific research vocabulary and heuristics from Python into
  topic contracts or portable policy files.
- [ ] 9. Reconcile documentation and retire stale scaffolding that contradicts
  the implemented system.
- [ ] 10. Add continuous integration and require the baseline and new contract
  tests to pass before later stages proceed.

Stage 1 is complete only when its exit gates in the roadmap pass. Completing the
ten tasks syntactically is not sufficient.

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

The audit underlying this plan included the working-tree knowledge
implementation under `ad_lit_pipeline/knowledge/` and
`ad_lit_pipeline/steps/knowledge/`. At the time of the audit, the complete test
suite passed with 295 tests.

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
                +-- Topic tagging -> audit -> Mantis export
                +-- Review labels -> evidence map -> literature review
                +-- Optional knowledge export
                        +-- Source records
                        +-- Evidence excerpts
                        +-- Finding records
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

The audited demo evidence map contained 30 labeled papers, with explicit future
work/gaps in 10, key findings in 19, limitations in 15, and direct quotations in
11. These are useful inputs, but no multi-signal gap engine combines them.

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

Audited demo characteristics:

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
   or needs human review.
8. Validate numeric details, sample sizes, direction, and study design.
9. Preserve failed extractions as retry/review records.
10. Run countersearches using normalized entities, aliases, synonyms, acronyms,
    citations, and adjacent literatures.
11. Record every search, result, limitation, and cutoff date.

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

### Extreme Or External Requirements

The UI cannot create expert ground truth. Recruitment, adjudication, governance,
and sustained expert participation are external requirements.

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
- The audited suite passes 295 tests.

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

## Priority 1: Architecture And Reproducibility

- [ ] Add `schema_version` and migrations to durable records.
- [ ] Add corpus snapshot IDs and first-class date/cutoff fields.
- [ ] Extend manifests with git state, environment, command/config, prompt/schema
  hashes, provider dates, and model parameters.
- [ ] Use one central pipeline/dependency registry for CLI and UI.
- [ ] Generate planner provider choices from executable adapters.
- [ ] Rename provider-specific artifact paths before multi-provider collection.
- [ ] Move domain-specific heuristics from Python into contracts/policies.
- [ ] Reconcile or retire obsolete review scaffolding.
- [ ] Document optional knowledge-layer CLI behavior.

## Priority 2: Scalability And Maintainability

- [ ] Stream CSV/JSONL where practical.
- [ ] Add resumable per-source extraction/verification work queues.
- [ ] Reuse LLM clients.
- [ ] Add bounded concurrency, caching, rate handling, and cost accounting.
- [ ] Separate checked-in example artifacts from live generated artifacts.
- [ ] Add CI.

---

# Dependency-Ordered Implementation Roadmap

## Phase 0 — Freeze The Baseline And Scientific Claims

Goal: make later comparisons trustworthy.

Instructions:

1. Preserve the current knowledge implementation in a coherent source change,
   separately from generated demo artifacts.
2. Record the 295-test baseline.
3. Freeze a small representative demo corpus and expected artifacts.
4. Define `gap candidate`, `corpus-sparse`, `as of`, and the difference between
   extraction confidence and scientific confidence.
5. Update README and technical documentation to match implemented behavior.
6. Retire or update stale review scaffolding.
7. Add CI for the non-network test suite.

Exit gate:

- Existing CLI and Mantis behavior remains unchanged.
- All existing tests pass.
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

Exit gate:

- CLI and UI select identical steps for identical options.
- Every downstream result traces to code/config/model/corpus versions.
- Resume cannot combine incompatible snapshots.

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
- The demo does not collapse all evidence into single `body` excerpts.

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
7. Keep Mantis and review adapters backward-compatible.
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
3. Return supported, contradicted, insufficient, or needs review.
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
7. Assign proposed, partially supported, refuted, resolved, artifact, duplicate,
   or uncertain states.
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

# Decision Log

Add entries in reverse chronological order.

| Date | Decision or deviation | Reason | Consequence / follow-up |
| --- | --- | --- | --- |
| 2026-08-26 | Use the portable gap ontology as the primary contribution, temporal provenance as supporting infrastructure, and prospective validation as a later study. | Best fit with the implemented pipeline and achievable scientific novelty. | Complete Foundation, Corpus, and Evidence stages before sophisticated gap ranking. |

