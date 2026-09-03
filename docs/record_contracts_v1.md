# Versioned Scientific Record Contracts v1

Status: implemented; five corpus-boundary records are emitted by collection,
with direct Phase 2.4 document/passage materialization available
Record schema: `1.0.0`
Scientific-validity policy: `1.0.0`
Gap ontology: `1.0.0`

## Purpose And Boundary

`ad_lit_pipeline/records/` defines the durable data boundary for future corpus,
evidence-graph, gap-discovery, ranking, evaluation, and Mantis workflows. The
contracts coexist with `ad_lit_pipeline/knowledge/`, whose current `Source`,
`Finding`, `Gap`, and related records remain preliminary legacy contracts. Step
1.3 did not reinterpret those records or change the legacy Mantis CSV. Phase
2.3 now uses the same contracts to emit `CorpusSnapshot`, `ScholarlyWork`,
`SourceVersion`, `ProviderRecord`, and `AccessLocation` from selected collection
results. Phase 2.4 emits `Document` and `Passage` records through a strict direct
materializer; Phase 2.5 will register that snapshot-native handoff. Later record
types remain contracts until their owning phases produce them.

All v1 records are frozen dataclasses with strict JSON-compatible codecs. JSONL
is the collection format. The schema rejects unknown core fields, requires
explicit optional fields, and permits additions only through controlled
namespaced `extensions`. Loading or writing a record runs record-local semantic
validation by default.

## Common Envelope

Every serialized record has:

- `record_type` and exact `schema_version`;
- a deterministic typed `record_id`;
- `created_at` as RFC3339 UTC;
- the inclusive source `corpus_snapshot_id`;
- `producing_run_id` and `producing_step_id`;
- sorted `parent_record_ids` and `source_record_ids`;
- structured `provenance` entries with kind, relation, reference, and optional
  SHA-256;
- administrative `record_status`: `active`, `superseded`, or `invalid`;
- structured `validation_warnings`;
- applicable `policy_versions`; and
- JSON-object values under namespaced `extensions` keys such as
  `provider.openalex`.

Administrative status never represents a scientific outcome. Claim evidence
uses `supported`, `contradicted`, `insufficient`, or `uncertain`. Gap candidates
use the separate append-only scientific lifecycle. Expert acceptance is a
judgment and is not a gap status.

Credentials, tokens, cookies, passwords, secret-like query parameters, and
signed authentication material are forbidden from provenance, extension, URL,
request, publication, and error fields. Mantis receipts retain a non-secret host
and stable remote identifiers, never authentication data.

## Record Inventory

| Record | ID prefix | Scientific role and important local invariant |
| --- | --- | --- |
| `CorpusSnapshot` | `snap_` | Frozen corpus scope and inclusive cutoff; records policy hashes, retrieval interval, members, coverage, and negative/null-result policy. A frozen snapshot requires completion and freeze timestamps. |
| `ScholarlyWork` | `work_` | Intellectual-work identity, distinct from versions and provider observations. Identifier-based identities require an identifier; weak identities remain explicit. |
| `SourceVersion` | `srcv_` | Exact preprint, version of record, protocol, registry, dataset, correction, or retraction version. Unknown availability cannot be silently declared eligible. |
| `ProviderRecord` | `prov_` | Immutable retrieval observation with provider item, query, request/raw hashes, rank, timestamps, license, and sanitized failure. Success requires a raw hash and location. |
| `AccessLocation` | `access_` | Timestamped access observation for one source version. The URI hash is recomputed and failure-like states require a reason. |
| `Document` | `doc_` | Exact stored byte snapshot with role, media type, hash, size, access source, license, and quarantine state. Encrypted content cannot be treated as usable stored text. |
| `Passage` | `passage_` | Canonical document-order text unit with text/representation hashes and exact locator coordinates. When the Phase 2.4 text/structure extension is present, integrity validation checks exact occurrence and page-coordinate agreement. |
| `Entity` | `entity_` | Typed method, population, outcome, intervention, dataset, design, setting, or other entity with aliases and ontology identifiers. Ambiguity and merges stay explicit. |
| `Claim` | `claim_` | Source-attributed, synthesized, or human claim with typed entity roles and comparability context. It carries extraction state, not scientific truth or evidence quality. |
| `ClaimEvidence` | `clev_` | Exact passage spans and material-element checks for one mutually exclusive claim outcome. Contradiction requires a comparable counterclaim; support requires spans without material mismatch. |
| `Relationship` | `rel_` | Typed evidence-graph edge. Scientific edges require verified claim evidence; `supports` and `contradicts` are Claim-to-Claim and contradiction requires comparability. |
| `GapSignal` | `signal_` | Reproducible rule output tied to a v1 operational gap class, inputs, trace hash, evidence, scope, cutoff, coverage, and uncertainty. `deterministic` must be true. |
| `GapCandidate` | `gap_` | Versioned, scoped hypothesis created only from one or more independent signals. State history is append-only and checked against validity-policy transitions. |
| `VerificationAttempt` | `verify_` | Counterretrieval and adversarial-check dossier with structured checks, support, counterevidence, coverage, uncertainty, and reasoned result. Completion and result semantics must agree. |
| `GapScore` | `score_` | Separate novelty, importance, and feasibility dimensions with their own evidence, scales, rationales, assessor, uncertainty, and calibration reference. Optional composites stay explicit. |
| `ExpertJudgment` | `judgment_` | Protocol-bound accept, reject, already-known, duplicate, or cannot-assess event with blinding, timing, rationale, and presented artifacts. It never mutates gap state. |
| `OutcomeEvent` | `outcome_` | Append-only prospective outcome such as funding, study start, registration, dataset, publication, replication, or use, with source references and cautious causal attribution. |
| `MantisExportProfile` | `mprofile_` | Versioned ordered projection with exact source contract, Title/Semantic/Categoric/Numeric/Date/Links/Connection types, null and multivalue policies, semantic construction, and compatibility version. |
| `MantisInterpretation` | `minterp_` | Immutable record of map input, selected stable point IDs, actor, prompt/action, time, and output. It is never evidence and cannot create a candidate without an independent signal. |
| `MantisPublicationReceipt` | `mreceipt_` | Immutable publication attempt with profile/source hashes, tool version, non-secret host, space/map IDs, idempotency key, timing, status, retry lineage, and sanitized error. |

## Deterministic IDs

`record_id` is `<typed-prefix>_<64 lowercase SHA-256 characters>`. The hash
input contains the exact record type, schema version, and the record's registered
identity projection. Canonical JSON sorts object keys, uses compact separators,
normalizes all strings to Unicode NFC, preserves array order, and rejects
non-finite numbers, non-string object keys, unsupported values, and keys that
collide after normalization.

Identity projections are explicit in `ad_lit_pipeline/records/registry.py`.
They exclude administrative creation metadata, run/step IDs, warnings,
extensions, and mutable explanatory prose unless that prose is part of the
scientific identity. Examples include work identity basis/key, document content
hash, passage representation/coordinates/text hash, candidate lineage/version,
and Mantis input/profile/selection identity. A valid-looking prefix is not
enough: validators recompute the ID from the registered projection.

## Time Semantics

Instants use RFC3339 UTC. Both `Z` and `+00:00` are accepted on input and
serialize canonically as `Z`; naive and non-UTC timestamps are rejected.
Scientific `as_of` values are full `YYYY-MM-DD` dates and are inclusive.
Publication and availability dates use explicit precision and certainty.

`as_of`, `created_at`, `retrieved_at`, provider update time, study completion,
and publication time are different facts. An unknown source-availability date
produces unknown temporal eligibility rather than assumed inclusion. The
collection validator checks declared eligibility against the inclusive snapshot
cutoff and rejects impossible dependency, lineage, retry, and correction order.

## Operational Gap Ontology

`configs/policies/gap_ontology_v1.yaml` defines exactly 12 portable v1 classes:

- explicit author-stated;
- corpus-sparse;
- missing typed graph relation;
- contradictory evidence;
- underrepresented population;
- method transfer;
- outdated evidence;
- missing direct comparison;
- poorly connected evidence region;
- weak evidence base;
- dataset reuse or validation; and
- unlinked protocol or trial result.

Every definition declares allowed deterministic signal types, minimum support,
refuting evidence, resolution evidence, coverage assumptions, open-world
limitations, and human annotation questions. The ontology loader rejects label-
only classes and signal types based on Mantis, LLM, model intuition, or map
interpretation.

A `GapSignal` may retain a Mantis-interpretation lineage reference, but its rule,
inputs, result, trace, and independent corpus/evidence references must remain
reproducible. A `GapCandidate` begins only after such a signal exists. It then
passes the normal synonym/indexing, adjacent-literature, duplicate,
counterretrieval, support, counterevidence, coverage, and uncertainty gates.

## Claim, Gap, And Score Separation

The contracts preserve the scientific-validity policy's typed boundaries:

- extraction and verification confidence do not become evidence quality;
- reporting quality and study quality remain distinct;
- coverage and gap uncertainty are not confidence scores;
- Mantis map proximity is not scientific support;
- expert acceptance is not scientific state; and
- novelty, importance, and feasibility are three separate scored dimensions.

Gap state history begins at `proposed`. Direct promotion to `verified_open` is
invalid. A terminal candidate version is reassessed only through a new version
with predecessor lineage. Record-local validators check declared transition
order and required check IDs. The collection validator resolves those IDs,
checks candidate/attempt reciprocity and status, and rejects lineage gaps and
cycles.

## Mantis Contract

Mantis is the required downstream interpretation and exploration consumer, not
the scientific source of truth. Profiles must have exactly one `Title` and at
least one ordered `Semantic` field. `Connection` remains gated behind explicit
compatibility verification. Receipts make remote publication observable and
retryable without storing credentials.

An interpretation starts as a pre-candidate or awaits an independent signal.
The `candidate_created` state requires both typed signal IDs and typed candidate
IDs. Even then, the interpretation itself is still `is_evidence: false`. The
canonical local claim, evidence, gap, verification, score, and judgment records
remain authoritative.

The scientific-validity policy's conceptual `interpretation_id` is the common
envelope's typed `record_id` on `MantisInterpretation`; v1 does not duplicate it
under a second field name.

## Record-Local And Collection Validation Boundary

Step 1.3 validates only facts available inside one record:

- exact fields, JSON types, enums, explicit nulls, and policy versions;
- stable-ID syntax and deterministic recomputation;
- timestamp, date, SHA-256, coordinate, numeric, and range syntax;
- sorted/unique local lists and typed reference prefixes;
- record-local conditional and chronological invariants;
- exact claim-outcome, gap-transition, score, and Mantis boundary rules; and
- absence-language, coverage-dimension, and human-review policy declarations.

Record-local success deliberately does not claim to validate:

- whether referenced IDs exist or belong to the same snapshot;
- ownership chains among work, version, provider, access, document, and passage;
- whether evidence passages belong to the claimed source version;
- cross-record endpoint compatibility, membership closure, duplicates, cycles,
  collisions, lineage continuity, or cross-record chronological order;
- whether files exist and match recorded artifact hashes;
- whether passage text occurs at the recorded position in a document; or
- schema migrations and corpus-wide migration validation.

`ad_lit_pipeline.records.integrity` implements the collection boundary. It
rejects orphan and duplicate IDs, competing payloads, wrong or unauthorized
cross-snapshot references, snapshot membership omissions, ownership errors,
evidence-span mismatches, impossible chronology, inconsistent source/gap/
judgment/outcome/Mantis lineage, and cycles. It verifies local artifact hashes
and sizes and, when a verified normalized-text representation is declared under
`extensions.pipeline.text_representation`, exact passage occurrence. Remote
artifacts are never fetched: they produce structured
`remote_artifact_not_checked` warnings. Warnings do not make a report invalid.

Migration execution remains deliberately outside this boundary until a real
target schema exists. The explicit path registry and release requirements are
documented in `docs/schema_migration_policy.md`.

## Python API And Fixtures

The public package exposes strict single-record and JSONL codecs plus structured
collection reports:

```python
from ad_lit_pipeline.records import (
    read_record_jsonl,
    record_from_dict,
    record_to_dict,
    require_record_integrity,
    validate_record_artifacts,
    validate_record_collection,
    write_integrity_report,
    write_record_jsonl,
)
```

`validate_record_collection` accepts already parsed records.
`validate_record_artifacts` reads multiple JSONL files as one integrity domain
and retains file/line context for parse and validation failures.
`require_record_integrity` raises `RecordIntegrityError` while preserving the
complete structured report.

The copyright-safe fixture under `tests/fixtures/record_contracts/v1/` contains
one coherent record of every type, its expected offline integrity report, and a
machine-readable manifest. Invalid cases are constructed from the same
deterministic fixture in `tests/test_record_contracts_v1.py` and
`tests/test_record_integrity.py`, preventing large duplicated artifacts while
covering record-local and collection-wide failure modes.
