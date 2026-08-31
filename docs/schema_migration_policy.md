# Scientific Record Schema Migration Policy

Status: implemented policy and path registry; no migrations are registered
Current record schema: `1.0.0`
Policy applies to: `ad_lit_pipeline.records` durable JSON/JSONL records

## Purpose

Durable scientific records must remain reproducible after their Python models
change. A schema change is therefore an explicit data transformation, not an
incidental parser fallback. The original artifacts remain immutable, every
transformation is versioned and audited, and the complete migrated collection
must pass both record-local and cross-artifact validation before it can be used.

The current production migration registry is intentionally empty. Schema
`1.0.0` is the only registered contract, so there is no honest target schema to
migrate to. The registry in `ad_lit_pipeline/records/migrations.py` can record
and plan reviewed future edges, but registration alone never executes or
authorizes a migration.

## Versioning Rules

Use stable semantic versions `MAJOR.MINOR.PATCH` for durable record contracts.

- Patch: a correction that does not change accepted serialized data or its
  scientific meaning. Most code-only validation fixes do not require a data
  migration, but the decision must be recorded.
- Minor: a backward-compatible contract addition with an explicit representation
  for old records. Because v1 records reject unknown and missing fields, adding a
  core field normally requires a migration even when its value can be derived.
- Major: a breaking structural, identity, scientific-semantic, or interpretation
  change. A major migration requires explicit review and cannot be registered by
  default.

Never reuse a schema version for changed serialized meaning. Policy, ontology,
prompt, provider, topic-contract, and Mantis-profile versions remain separate
from the record schema version and must not be collapsed into it.

## Required Migration Unit

Migrate a complete closed record collection, not isolated rows. Record IDs hash
the record type, schema version, and registered identity projection. A schema
change can therefore change IDs even when the scientific object is unchanged.
An atomic collection migrator must:

1. Read and validate the immutable source collection under its exact source
   contract.
2. Select one explicit registered path for each record type present.
3. Transform payloads deterministically without network calls, model calls,
   current-time reads, randomness, secrets, or environment-dependent defaults.
4. Recompute every target ID from the target schema's identity projection.
5. Build a complete old-ID to new-ID map before writing target records.
6. Rewrite all typed references, including snapshot membership, snapshot IDs,
   parent/source IDs, record provenance, evidence/graph links, gap dossiers,
   judgments, outcomes, Mantis lineages, and nested evidence IDs.
7. Preserve source facts, provenance, availability/cutoff semantics, original
   precision, and uncertainty unless the reviewed migration explicitly records
   a semantic correction.
8. Validate each target record, then run collection-wide integrity validation.
9. Write into a new versioned destination and publish an audit report only after
   all gates pass.

Partial output is invalid. A failed migration leaves the source untouched and
must not replace a previously valid target.

## Migration Registration

Each edge needs:

- a unique migration ID;
- one supported record type;
- exact source and target versions;
- a concise description of the data and meaning change;
- a deterministic transform callable;
- focused valid, invalid, determinism, and rollback tests; and
- explicit `permits_major_change=True` after major-change review when the major
  version changes.

Edges must move forward. Downgrades, implicit nearest-version selection,
wildcard versions, parser guessing, and silent defaults are prohibited. The
planner chooses the shortest explicit path deterministically and fails when no
path exists. A same-version request is an auditable no-op.

The registry is instance-owned so tests and tools cannot mutate global migration
state. `new_migration_registry()` currently returns an empty production
registry. Add a real production edge only in the same change that introduces
the target schema, collection migrator, audit contract, documentation, and
tests.

## Audit Requirements

A future migration run must record at least:

- source and target artifact paths and SHA-256 hashes;
- source and target record-schema versions;
- ordered migration IDs and their code revision;
- command, configuration, environment, producing run, and producing step;
- source and target record counts by type;
- the old-ID to new-ID map or a content-addressed reference to it;
- unchanged, transformed, rejected, and warning counts;
- target collection-integrity report and policy/ontology versions;
- start/completion timestamps and terminal status; and
- a sanitized error when unsuccessful.

Audit records are append-only. They do not modify the scientific source record
and must not contain credentials.

## Scientific And Mantis Boundaries

A migration may preserve an old assertion; it cannot upgrade its scientific
status merely because the target schema has richer states. Missing evidence
must stay missing, unknown dates remain unknown, and legacy confidence labels
cannot be reinterpreted as support, novelty, importance, or feasibility without
a separately auditable scientific assessment.

The preliminary records under `ad_lit_pipeline/knowledge/` have no automatic
migration into the v1 scientific contracts. Their semantics and provenance are
not sufficient for a lossless conversion. A later import must be an explicit
adapter that emits warnings or quarantines ambiguous fields and then passes the
normal evidence-verification gates.

Mantis projections are derived artifacts. If a source record schema changes,
the corresponding `MantisExportProfile` must declare the new source schema and
receive its own reviewed profile version. Old publication receipts remain
immutable; re-publication creates a new receipt. Map interpretations never
become scientific evidence through migration.

## Release Gate For The First Real Migration

Do not implement or run the first production migration until all of the
following exist in one reviewed change:

- the target record schemas and identity projections;
- registered explicit migration edges;
- an atomic dependency-ordered collection migrator with ID rewriting;
- migration audit and rollback artifacts;
- adversarial fixtures for collisions, missing references, partial failure,
  lineage, chronology, and semantic non-upgrade;
- deterministic repeat-run tests;
- complete local and cross-artifact target validation; and
- an explicit compatibility decision for every affected Mantis profile.
