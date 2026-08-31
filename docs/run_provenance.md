# Run Provenance And Manifest Contract

Status: implemented for the current main and collection orchestrators
Manifest schema: `1.0.0`
Run-provenance schema: `1.0.0`
LLM-trace schema: `1.0.0`

## Purpose And Boundary

Every orchestrated run writes enough local, content-addressed context to explain
which code, environment, command, contracts, provider implementation, prompt,
response schema, model, and artifacts produced its outputs. This is an additive
extension of the existing manifest: established run, step, artifact, warning,
error, and trace fields remain present.

The current pipeline does not yet emit canonical `CorpusSnapshot` records.
Manifests therefore record that fact explicitly with `status: not_emitted`, a
null snapshot ID and cutoff, and a reason. They never fabricate a snapshot or
imply temporal reproducibility that the legacy pipeline cannot provide.

This Foundation step does not wire the versioned scientific records into
production, execute migrations, contact Mantis, or make live provider or OpenAI
calls merely to collect provenance.

## Manifest Envelope

`runs/<run_id>/manifest.json` contains:

- `manifest_schema_version`, run identity, pipeline identity, model, status,
  timestamps, and the effective topic-contract file reference;
- the first-attempt `provenance` for compatibility with consumers that need a
  single run-level context;
- append-only `attempts`, each with its own provenance, start/end step indexes,
  timestamps, status, and resume flag;
- append-only step results with the attempt ID that produced them;
- sanitized step metadata, warnings, errors, row counts, trace paths, and hashed
  trace-artifact references;
- input and output path, existence, byte size, and SHA-256; and
- `failed_step` only while a failure or pause remains unresolved.

Manifest writes use a temporary file in the run directory followed by
`os.replace`. Readers therefore see the previous complete manifest or the new
complete manifest, not a partially written JSON document.

## Run Provenance

Each attempt records the following sections.

### Code

- exact Git commit and commit timestamp;
- branch or explicit detached-HEAD state;
- dirty/clean state;
- SHA-256 values for Git status, tracked diff, staged diff, and the aggregate of
  relevant untracked source files; and
- one aggregate source-state hash.

A dirty worktree is allowed because research runs sometimes need to measure
uncommitted experiments. The manifest records the state but does not store raw
diffs, filenames from status output, or source contents. Untracked paths are
hashed before aggregation.

### Environment

- Python implementation and version;
- operating-system and machine identifiers;
- sorted installed distribution names and versions plus an aggregate hash;
- the `requirements.txt` path and hash; and
- the allowlisted OpenAI timeout and retry settings.

The full process environment and `.env` contents are never copied.

### Invocation

- sanitized command arguments;
- sanitized parsed CLI options;
- working directory;
- exact selected step sequence, complete assembled pipeline sequence, and a
  normalized set of resume-compatible effective options; and
- resolved model.

Credential-, token-, password-, cookie-, authorization-, mail-, and email-like
options are redacted. Sensitive URL query values and URL user information are
also redacted. Repository and home-directory prefixes are rendered as `.` and
`$HOME` rather than copied literally.

### Contracts And Providers

- effective or pending topic contract, including its hash and declared identity;
- effective topic-structure policy, including file hash, policy identity/version,
  and formatting-independent semantic hash;
- scientific-validity and gap-ontology policy files and versions;
- durable-record registry and schema version;
- aggregate prompt-template hash;
- response-schema source inventory and hash; and
- configured provider name, implementation availability, path, and hash.

Status fields distinguish inputs the legacy pipeline actually applies from
contracts that are available for future durable records but are not yet applied
or emitted. This prevents the manifest from presenting Step 1.2-1.4 contracts
as current production behavior.

Provider collection steps also record the earliest and latest candidate
retrieval dates and provider update timestamps retained in their result sets.

## LLM Trace Provenance

Every traced call writes the exact system message, rendered prompt, response
schema, raw response, and parsed response. Its versioned metadata file records:

- model and schema name;
- safe effective request parameters such as API type, response format, timeout,
  SDK retry count, and application JSON-decode attempts;
- selected response metadata such as response ID, returned model, service tier,
  creation time, and usage when the provider returns them;
- validation metadata; and
- the path and SHA-256 of every trace artifact.

Traces intentionally contain exact scientific request and response content and
must be handled as research artifacts. API keys and authorization material are
not request parameters and are not written by the shared clients.

Trace files are namespaced by attempt under
`runs/<run_id>/traces/<attempt_id>/`. A duplicate step/call ID in one attempt is
rejected before any existing trace file is changed. Resumed attempts therefore
cannot overwrite prior prompt or response evidence. An explicitly configured
`--trace-dir` is treated as a base directory and receives the same attempt
subdirectory.

## Resume Semantics

Creating a run with an existing run ID is rejected before the manifest is
changed. `--resume --run-id <run_id>` is the only path that opens an existing
run directory.

Resume is rejected before step execution when collection, pipeline, model,
assembled pipeline sequence, effective non-transient options, topic-contract
hash, or effective topic-policy semantic hash is incompatible or unavailable.
It continues the originally selected sequence at the first step without a
successful result. This handles a recorded failure, a pause, and abrupt process
termination before, during, or between steps. An attempt found with status
`running` is closed as `interrupted` before the new attempt is appended. A final
successful or dry-run attempt clears the active failure marker. If the crash
occurred after the final step result but before finalization, resume appends an
empty successful attempt and closes the run. Resume cannot be combined with
`--dry-run`, `--only-step`, or `--from-step`; it always honors the original
selection.

Legacy unversioned manifests remain readable. On their first compatible resume,
their existing steps are retained under a synthetic `attempt-0000-legacy`, and
the new attempt uses the current schema. No old history is silently rewritten.

True snapshot compatibility cannot be enforced until the production pipeline
emits canonical snapshot IDs and cutoffs. That missing capability is explicit in
the manifest and remains scheduled for the Corpus stage.

## Verification

Offline tests cover redaction, dirty/detached Git capture, deterministic hashes,
environment allowlisting, contract/provider boundaries, explicit missing
snapshots, atomic writes, manifest validation, append-only resume history,
run-ID collision rejection, abrupt-interruption recovery, changed pipeline and
option rejection, legacy upgrades, provider dates, CLI integration, attempt
trace isolation, overwrite refusal, and exact LLM trace hashes. No test requires
a provider, OpenAI, or Mantis connection.
