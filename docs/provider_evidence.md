# Immutable Provider Evidence

Status: Phase 2.2 implemented and verified on 2026-09-01  
Evidence schema: `1.0.0`

## Purpose And Boundary

Provider metadata copied into a candidate row is not enough to reconstruct a
search. The provider may later update the item, the original page order is
lost, and a sanitized query URL alone cannot prove which response produced the
candidate.

The OpenAlex transport therefore captures the exact successful HTTP
response-body bytes before JSON interpretation. The evidence layer archives
those retained bytes before candidate conversion and writes a separate, atomic
JSONL index that connects them to a canonical non-secret request, retrieval
context, result order, and candidate position.

This is the input evidence for the production `ProviderRecord` bridge in Phase
2.3. It is not itself a v1 `ProviderRecord`, `ScholarlyWork`, `SourceVersion`, or
`CorpusSnapshot`, and archiving a provider page does not make a work eligible
for a corpus.

## Artifacts

New collection runs use provider-neutral candidate names:

```text
data/raw/<collection>_provider_candidates.jsonl
data/raw/<collection>_provider_candidates_deduped.jsonl
```

Final-candidate retrieval uses:

```text
data/raw/<collection>_provider_evidence_index.jsonl
data/raw/<collection>_provider_response_pages/
```

Review/overview seeds that influence generated topic contracts are isolated in:

```text
data/raw/<collection>_review_provider_evidence_index.jsonl
data/raw/<collection>_review_provider_response_pages/
```

The raw page directories and indexes are generated and ignored by Git. The run
manifest records the index path/hash and step-level page, file, and byte counts.
The content-addressed directory is an evidence store, not a source-code
fixture. Copyright-safe test pages live only in temporary test directories.

Historical `<collection>_openalex_candidates*.jsonl` files remain readable for
resume, `--from-step`, `--only-step`, and main-pipeline handoff when the new
provider-neutral path is absent. They are never relabelled as archived:
missing page evidence receives an explicit `unavailable` compatibility marker.

## Request Identity And Secret Boundary

The request projection contains:

- uppercase HTTP method;
- lowercase scheme and hostname;
- normalized path;
- sorted non-secret query parameters; and
- only allowlisted `Accept` and `User-Agent` headers.

Credentials, API keys, tokens, signatures, cookies, embedded credentials,
`mailto`, and email parameters are removed before the URL or request hash is
written. They are not replaced with hashable secret-dependent values. Thus two
scientifically identical requests made with different credentials have the
same canonical request projection.

The actual network request may contain an OpenAlex API key or polite-pool
email, but neither appears in candidates, evidence indexes, manifests, or
errors. Exact response-body bytes are not altered; OpenAlex responses do not
echo the request credentials.

## Page Record

Each `provider_response_page` index entry records:

- evidence schema and deterministic page-observation ID;
- provider name;
- canonical request projection and SHA-256;
- query, logical-query, group, tier, iteration, retrieval phase, backfill round,
  page/cursor, and requested page size;
- HTTP status, final sanitized URL, retrieval time, media type, and content
  encoding;
- exact response-body byte count, SHA-256, and relative artifact URI;
- result count, provider IDs, and canonical raw-item hashes in their exact
  provider order; and
- the earliest and latest provider item-update values observed on that page.

The raw artifact path is derived from provider and response SHA-256. Existing
content is reused only if its bytes still match the address. A conflicting file
causes a hard failure; no archive file is silently overwritten. Both raw page
and index writes are atomic.

## Candidate Link

Every newly fetched OpenAlex candidate carries `provider_evidence` with:

- archived/unavailable status;
- page evidence ID;
- request and response hashes;
- response URI and media type;
- page/cursor and page retrieval time;
- one-based result position and page result count;
- canonical raw-item SHA-256; and
- the JSON pointer to the item within the archived response page.

The candidate retrieval timestamp is the page observation time, not a second
independently generated timestamp. Deduplication retains the representative
link and also carries page evidence inside duplicate-observation provenance.
The compatibility paper CSV exposes additive flat evidence fields plus the full
canonical evidence JSON.

## Verification

`verify_provider_evidence(...)` detects:

- malformed or duplicate page records;
- request-hash or page-ID changes;
- non-canonical or credential-bearing request URLs;
- missing files and path escapes;
- non-content-addressed artifact paths;
- byte-hash or size changes;
- invalid JSON or unsupported response encoding;
- changed result counts or order; and
- provider-update summary changes.

Candidate-link validation additionally proves that the page exists, the
recorded position resolves to the candidate provider ID, the raw-item hash
matches both the candidate's raw record and the archived page item, and every
copied request/response fact matches the page index.

Initial fetch, review-seed fetch, and backfill all run verification before
returning success. Backfill validates the existing archive before issuing new
requests and appends new page observations atomically. A tampered archive stops
the step rather than allowing new outputs to legitimize it.

## Deliberate Phase Boundary

Phase 2.2 does not:

- infer work or source-version identity from provider page membership;
- turn a page into an immutable corpus snapshot;
- claim OpenAlex search completeness;
- archive failed HTTP attempts without a successful response body;
- emit v1 `ProviderRecord` objects; or
- fetch remote documents or produce passages.

Phase 2.3 now verifies these page/index links again, extracts the exact provider
item observation, emits production provider/work/version/access records, and
freezes a snapshot only after collection-wide integrity succeeds. See the
[corpus snapshot contract](corpus_snapshot.md). Failed HTTP attempts and
document/passages remain outside this evidence boundary.
