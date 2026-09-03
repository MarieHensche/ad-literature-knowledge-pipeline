# Canonical Corpus Snapshot Materialization

Status: Phase 2.3 implemented
Record schema: `1.0.0`
Materialization policy: `1.0.0`
Owning step: `materialize_corpus_snapshot`

## Purpose And Boundary

The final collection step turns selected compatibility artifacts into the
first production v1 corpus boundary. It emits one canonical JSONL containing:

- `ScholarlyWork` for resolved intellectual-work identities;
- `SourceVersion` for the exact retained versions;
- `ProviderRecord` for exact archived retrieval observations;
- `AccessLocation` for observed access routes; and
- one frozen `CorpusSnapshot` containing the included versions and provider
  records.

This step does not emit `Document` or `Passage`, make the main tagging pipeline
snapshot-native, or publish to Mantis. Those are Phase 2.4 and Phase 2.5
boundaries. The legacy paper CSV and legacy Mantis CSV remain unchanged.

## Inputs And Outputs

The step consumes:

- the deduplicated provider-candidate JSONL;
- the selected paper CSV from `export_included_candidates`;
- the provider-neutral evidence index and content-addressed response pages;
- the resolved collection plan; and
- the effective topic contract and corpus specification.

For collection `<collection>`, it writes:

```text
data/processed/<collection>_corpus_records.jsonl
data/processed/<collection>_corpus_snapshot_integrity.json
```

The records JSONL is canonical and ordered. The integrity report is operational
audit data, not a v1 scientific record. It reports the producing run/step,
snapshot ID, exact input hashes, provider-evidence counts, record counts,
observed coverage, limitations, collection-integrity result, and output hash.

## Evidence Resolution And Materialization

Only rows selected into the paper CSV become snapshot members. Each selected
row must match exactly one deduplicated candidate by DOI or provider identity.
Each retained candidate observation must then resolve through its evidence ID,
request hash, response hash and URI, one-based result position, JSON pointer,
provider item identity, and canonical raw-item hash to the exact archived page
bytes. The materializer never treats copied candidate metadata as a substitute
for those bytes.

The archived provider item and candidate facts are passed through the shared
Phase 2.1 source-type, work-identity, source-version, lifecycle, temporal, and
corpus-retention policies. Provider observations remain distinct from works
and versions. Access records preserve observation state without claiming that
remote content was downloaded or scientifically usable.

## Strict Freeze Gates

The step denies freezing when it finds, among other conditions:

- a missing, malformed, relocated, or hash-mismatched input artifact;
- an absent, ambiguous, or competing selected-candidate identity;
- missing or unverifiable provider page/item evidence;
- request, response, result-order, pointer, item-hash, or provider-ID mismatch;
- unresolved source type, weak work identity, or unresolved version identity;
- a retained source version outside the inclusive cutoff or corpus policy;
- conflicting source-version identities or inconsistent plan/contract windows;
- a freeze timestamp before the completed retrieval interval; or
- any record-local, cross-record, ownership, membership, chronology, or local
  artifact-integrity error from the v1 collection validator.

Input and record validation complete before the destination JSONL is replaced.
On success, the records and then the success report are written atomically. On
failure, only a failure integrity report is written. If a prior records JSONL
exists, it is preserved and explicitly marked as a stale existing artifact in
the report; it must not be mistaken for the failed run's output.

## Determinism And Time

Record IDs use the v1 deterministic identity projections. The snapshot identity
includes the resolved corpus semantics, inclusive `as_of`, plan/contract/input
hashes, actual retrieved observations, and membership. It excludes operational
creation and freeze timestamps. Therefore unchanged scientific inputs produce
the same record and snapshot IDs across repeated runs, while changed selected
rows, provider evidence, policy, plan, contract, cutoff, or coverage change the
snapshot identity.

The JSONL bytes can differ between otherwise identical runs because envelope
timestamps and producing run IDs are intentionally operational provenance. ID
stability must not be confused with byte-for-byte run identity.

## Actual Coverage And Open-World Meaning

Coverage is derived from observed provider-evidence pages, not from every query
listed in the plan. It records planned and observed logical query IDs, missing
planned queries, unplanned observed queries, retrieval phases, providers,
result/page counts, and whether execution was complete, partial, or unplanned.

Even complete execution is open-world retrieval coverage, not proof that no
unindexed, unpublished, synonym-missed, adjacent-domain, or provider-external
literature exists. Those limitations remain explicit snapshot data and must be
carried into later novelty and gap verification.

## Verification

Focused tests cover successful materialization, exact archived-byte resolution,
stable IDs across run/freeze timestamps, page tampering, after-cutoff sources,
competing DOI identities, and preservation of a stale records artifact after a
failed rebuild. Tests use synthetic local provider evidence and never contact a
provider, OpenAI, full-text service, or Mantis.
