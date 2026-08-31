# Versioned Mantis Integration

Status: Step 1.7 implemented offline; live publication remains opt-in and has
not been exercised against a user account.

## Boundary

Mantis is the terminal exploration and interpretation workspace, not the
scientific source of truth. Versioned records, exact evidence, verification
attempts, coverage, and scores remain authoritative locally. Map position,
clusters, summaries, and agent interpretations do not verify claims or gaps.

The legacy `export_mantis` step remains unchanged in the default tagging
pipeline. The versioned path is a separate optional pipeline:

```text
versioned_records_jsonl
  -> export_mantis_views
  -> deterministic CSV + profile + audit report for each view
  -> publish_mantis_views only with --publish
  -> immutable publication receipts
```

## Three Compatibility-v1 Views

Profiles are strict YAML templates in `configs/mantis/`. Each compiles to a
snapshot-bound `MantisExportProfile`. Template hashes and expected CSV bytes are
frozen by `tests/fixtures/mantis_views/v1/manifest.json`.

| View | Eligibility | Point identity |
| --- | --- | --- |
| Paper | Active snapshot-member source version, temporally eligible, active or corrected lifecycle, active work | `SourceVersion.record_id` |
| Verified claim | Active claim in an eligible snapshot source with at least one active `supported` or `contradicted` `ClaimEvidence` | `Claim.record_id` |
| Verified gap | Active `verified_open` candidate with a completed decisive verification, no unresolved checks, and a matching three-axis score | `GapCandidate.record_id` |

`insufficient` and `uncertain` claim evidence is excluded. Proposed,
verification-in-progress, refuted, resolved, uncertain, terminology-artifact,
and duplicate gap candidates are excluded from the verified-open view. Every
exclusion is counted by reason in the view report.

Compatibility v1 deliberately disables Mantis `Connection` columns. The
current interface retains this type below the main creation UI, so it will only
be enabled after an authenticated round-trip proves serialization and user
interface behavior. Ordinary ID columns preserve relationships without claiming
native Mantis graph semantics.

The paper view records `paper_scope=not_available_per_paper_in_contract_v1`.
The v1 corpus snapshot preserves the authoritative corpus-level scope, but a
durable per-paper inclusion decision does not yet exist. The export reports this
limitation rather than inventing a decision.

## Local Export

Export is offline and deterministic:

```bash
.venv/bin/python scripts/export_mantis_views.py \
  --input runs/<run_id>/versioned_records.jsonl \
  --output-dir runs/<run_id>/mantis \
  --run-id <run_id>
```

For each view this writes:

```text
mantis_<kind>_v1.csv
mantis_<kind>_v1.profile.json
mantis_<kind>_v1.report.json
```

The report records snapshot/profile versions, source/profile/CSV hashes,
ordered columns, Mantis types, eligible rows, exclusions, and known
limitations. CSV output remains available even if later publication fails.

## Optional Publication

The adapter targets exactly `mantisai-cli` 3.7.0. It is an external tool, not a
Python runtime dependency. Install and configure it separately:

```bash
npm install -g mantisai-cli@3.7.0
mantis setup
```

The CLI stores its developer key and active context in its own configuration.
The pipeline never accepts a key argument and never writes one to commands,
receipts, logs, or manifests.

Publish to an existing space:

```bash
.venv/bin/python scripts/publish_mantis_views.py \
  --input-dir runs/<run_id>/mantis \
  --receipts runs/<run_id>/mantis/publication_receipts.jsonl \
  --run-id <run_id> \
  --space-id <space_uuid> \
  --publish
```

Or create a new space with `--space-name` instead of `--space-id`. All three
maps are private and not activated by default. The first successful new-space
publication supplies the space ID for the remaining two maps.

Publication is refused without `--publish`. Before the first remote call, the
batch loads and validates all three profile records and the destination. An
invalid profile or destination is a preflight error: no remote operation and no
partial receipt file is produced because a valid receipt cannot truthfully cite
an invalid profile or destination.

After preflight, every view receives a durable result. The adapter checks the
exact CLI version before uploading and does not call Mantis for an empty or
missing view. Missing/unreadable CSVs, empty views, local request-validation
errors, unexpected runner exceptions, version mismatches, CLI failures, and
malformed CLI responses produce sanitized failed `MantisPublicationReceipt`
records without deleting or rewriting source CSVs. If creation of a new shared
space fails, the remaining views receive `publication_dependency_failed`
receipts and are not sent remotely. `--require-publication` raises only after
all post-preflight receipts have been written.

The adapter uses create plus `duplicate_policy=reject`. It does not claim
idempotent refresh/upsert semantics. Those require a later authenticated
compatibility spike.

## Interpretation And Writeback

The existing `MantisInterpretation` contract can preserve a selected map/profile,
input hash, point IDs, actor, action, timestamp, and text. It enforces
`is_evidence=false`. Step 1.7 does not yet automate interpretation capture or
expert-judgment writeback. A Mantis hypothesis must first yield an independent
deterministic `GapSignal`; only then may the normal proposed-candidate,
counterretrieval, and verification pipeline run.

## Tests And Live Boundary

Normal tests use a fake command runner and require no network, Mantis account,
or API key. They cover exact version gating, typed private commands, successful
and failed receipts, missing inputs, unexpected local failures, complete batch
receipts, preflight atomicity, secret redaction, CSV preservation, eligibility,
output hashes, and legacy compatibility.

No live smoke test was run in Step 1.7. Add one only as an explicitly opt-in
test after access is available; it should create disposable private maps,
inspect returned IDs and field types, and clean up through an approved,
recoverable procedure.

Current primary references:

- [Mantis CLI 3.7 documentation](https://mantis.csail.mit.edu/docs/mantis-cli/)
- [Mantis CLI installation and CSV map creation](https://mantis.csail.mit.edu/docs/mantis-cli/install.html)
- [Mantis CSV/XLSX space creation and field types](https://mantis.csail.mit.edu/docs/start/create-a-space.html)
- [Mantis concepts and the current Connection boundary](https://mantis.csail.mit.edu/docs/start/concepts/spaces-and-maps.html)
