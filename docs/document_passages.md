# Exact Documents And Resolvable Passages

Status: Phase 2.4 implemented; Phase 2.5 orchestration integration pending

- Record schema: `1.0.0`
- Full-text extraction contract: `3.0.0`
- Text-structure schema: `1.0.0`
- Document-materialization policy: `1.0.0`
- Passage-segmentation policy: `1.0.0`

## Purpose And Boundary

Phase 2.4 connects a frozen Phase 2.3 source version to the exact bytes used for
full-text extraction and to bounded text units that future claims can cite. It
does not infer claims, scientific support, or gaps. A passage is a resolvable
location in a normalized representation, not evidence that its text is true.

The materializer is intentionally not in the default registry yet. It has a
direct package CLI and a `StepSpec`, while Phase 2.5 owns the collection-to-main
handoff, artifact names, registry dependencies, resume behavior, UI wiring, and
Mantis paper projection.

## Two-Layer Document Contract

Full-text preparation now preserves two different artifacts:

1. **Exact source bytes** are the downloaded PDF/HTML bytes or the explicitly
   trusted local file bytes. Their SHA-256, byte size, media type, retrieval
   time, encryption state, and page count are recorded.
2. **Normalized text representation** is the UTF-8 text used for deterministic
   passage coordinates. Its SHA-256 is independent of the source-byte hash. A
   content-addressed JSON structure records its normalization rule and any PDF
   page spans.

The distinction is mandatory. Character offsets refer to the normalized text,
never directly to PDF bytes or HTML markup. The `Document` record owns the exact
source artifact and carries a `pipeline.text_representation` extension for the
text and structure artifacts.

Exact source bytes, representations, and structures are first cached outside
the repository by `prepare_full_text`. Materialization verifies them and copies
them to content-addressed paths under:

```text
runs/<run_id>/artifacts/documents/source/
runs/<run_id>/artifacts/documents/representations/
```

The run directory is ignored by Git. Record artifact references are relative to
the declared project artifact root, so offline integrity validation can resolve
them without using the original cache path.

## Full-Text Manifest Contract 3.0.0

The compatibility CSV columns remain available. The manifest adds:

- `full_text_source_artifact_path`
- `full_text_source_sha256`
- `full_text_source_byte_size`
- `full_text_source_media_type`
- `full_text_retrieved_at`
- `full_text_page_count`
- `full_text_encrypted`
- `full_text_structure_path`
- `full_text_structure_sha256`

Remote text cached under an older extraction contract is not treated as an
exact document. It is fetched again so the source bytes can be retained and its
identity rechecked. An explicitly trusted local text path can be adopted as an
exact `text/plain` source. Content-addressed cache entries are hash-checked and
repaired from the source bytes supplied during the same preparation operation.

## Eligibility And Source Ownership

The materializer starts from one integrity-valid, frozen corpus record JSONL.
Each `SourceVersion` resolves to one full-text manifest row through the
`pipeline.corpus_materialization.paper_id` extension created in Phase 2.3.

A stored `Document` is emitted only when:

- the manifest says the text is usable;
- identity is `trusted_local`, `verified_doi`, or `verified_title`;
- exact source, text, and structure files exist and match their hashes;
- source byte size, media type, retrieval time, and extractor identity exist;
- the source is not encrypted; and
- a PDF has independently resolvable page spans and a positive page count.

The materializer reuses the matching snapshot `AccessLocation` when possible.
Otherwise it creates a timestamped access observation with a credential-free
URI. Scientific query parameters are retained; tokens, signatures, API keys,
email/contact parameters, embedded credentials, and URL fragments are removed.
No new access record is kept when document validation fails.

## Deterministic Passage Locators

Passages are emitted in document order. Blank-line paragraphs and recognized
scientific section headings are the primary boundaries; headings separated by
a single newline are also recognized. A unit is split only when it exceeds the
4,000-character policy limit, preferring the last newline or whitespace in the
second half of the window.

Each `Passage` records:

- stable sequence and paragraph indices;
- passage kind and section path;
- exact text and text SHA-256;
- normalized-representation SHA-256;
- inclusive-start/exclusive-end Unicode-code-point offsets;
- page start/end when verified PDF page spans overlap the passage;
- source-version and document IDs; and
- extractor name/version plus segmentation-configuration SHA-256.

The record ID depends on the document, representation, exact offsets, and text
hash. Operational run IDs and timestamps do not change document or passage
identity for unchanged scientific inputs.

## Independent Integrity Validation

`validate_record_artifacts(..., artifact_root=...)` checks:

- exact document source hash and byte size;
- normalized-text artifact hash and decoding;
- structure-artifact hash, supported schema, representation hash, media type,
  ordered page coordinates, and PDF page bounds;
- passage representation hash;
- exact passage occurrence at its stored offsets; and
- page locator agreement with the verified structure.

The materialization output is first written to a temporary file and receives
full v1 record and artifact validation before atomic replacement. A critical
corpus or output-integrity failure writes an atomic failure report and preserves
an older output as explicitly stale. Per-source extraction or identity failures
produce `complete_with_failures`, remain structured in the report, and emit no
invented `Document` or `Passage`.

## Direct Pre-Integration CLI

The Phase 2.4 boundary can be exercised directly before Phase 2.5 registers it:

```bash
.venv/bin/python -m ad_lit_pipeline.steps.full_text.materialize_records \
  --corpus-records data/processed/<collection>_corpus_records.jsonl \
  --full-text-manifest data/processed/<collection>_full_text_manifest.csv \
  --output data/processed/<collection>_corpus_document_records.jsonl \
  --integrity-report data/processed/<collection>_document_passage_integrity.json \
  --run-id <run_id> \
  --artifact-root .
```

This command is a contract and test surface, not the final operator workflow.
Phase 2.5 will make the handoff registry-owned and snapshot-native.

## Known Limits

- Scanned/image-only PDFs need a future OCR extractor; no OCR text is invented.
- A PDF without independently mapped page spans is audited and omitted instead
  of receiving guessed page numbers.
- HTML and plain text use exact character locators but normally have null page
  locators.
- Section recognition is deterministic and portable but not a complete parser
  for publisher-specific layout, tables, figures, references, or nested XML.
- Existing live manifests created under extraction contract `2.0.0` must be
  reprocessed before document materialization.
- Registry, default CLI/UI orchestration, resume handoff, and production Mantis
  paper points remain Phase 2.5 work.
