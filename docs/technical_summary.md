# Technical Summary

This project is a refactored research pipeline for converting literature
metadata into structured knowledge tags and a Mantis-ready CSV.

The script entry points remain stable for existing workflows, but the reusable
implementation now lives under `ad_lit_pipeline/`.

## Architecture

```text
scripts/                 Compatibility wrappers and direct step CLIs
ad_lit_pipeline/cli/     Pipeline orchestration CLIs
ad_lit_pipeline/core/    Step specs, artifact paths, manifests, runner helpers
ad_lit_pipeline/io/      CSV, JSON, JSONL, YAML, and path helpers
ad_lit_pipeline/llm/     Shared OpenAI client, schemas, and trace writer
ad_lit_pipeline/prompts/ Prompt rendering and Markdown prompt templates
ad_lit_pipeline/providers/
                         Candidate provider interfaces and OpenAlex provider
ad_lit_pipeline/steps/   Pipeline task implementations
ad_lit_pipeline/topics/  Topic contract loading and validation
configs/topics/          Topic contracts
data/raw/                Raw inputs and collection artifacts
data/processed/          Main pipeline outputs
runs/                    Run manifests and LLM traces
```

The two orchestrated pipelines are declared in `ad_lit_pipeline/core/registry.py`.

## Main Pipeline

Entry point:

```bash
python scripts/run_pipeline.py run ...
```

Package CLI:

```text
ad_lit_pipeline/cli/run_pipeline.py
```

Steps:

| Step | Module | Output |
| --- | --- | --- |
| `normalize_metadata` | `ad_lit_pipeline/steps/metadata/normalize.py` | `data/processed/<collection>_papers_normalized.csv` |
| `screen_scope` | `ad_lit_pipeline/steps/screening/rule_based_scope.py` | `data/processed/<collection>_scope_screened.csv` |
| `prepare_full_text` | `ad_lit_pipeline/steps/full_text/prepare.py` | `data/processed/<collection>_scope_screened_full_text.csv`, `data/processed/<collection>_full_text_manifest.csv` |
| `calibrate_topic_contract` | `ad_lit_pipeline/steps/tagging/calibrate_topic_contract.py` | `data/collection_plans/<collection>_topic_contract.yaml` |
| `normalize_tagging_config` | `ad_lit_pipeline/steps/tagging/normalize_config.py` | `data/processed/<collection>_tagging_config_normalized.json` |
| `generate_tagging_rules` | `ad_lit_pipeline/steps/tagging/generate_rules.py` | `data/processed/<collection>_tagging_rules.json` |
| `tag_papers` | `ad_lit_pipeline/steps/tagging/tag_papers.py` | `data/processed/<collection>_extraction_filled.csv` |
| `audit_extraction` | `ad_lit_pipeline/steps/tagging/audit.py` | `data/processed/<collection>_extraction_audit.csv` |
| `export_mantis` | `ad_lit_pipeline/steps/export/mantis.py` | `data/processed/<collection>_mantis_ready.csv` |

Supported `--papers` formats are `.csv`, `.bib`, `.bibtex`, `.json`, `.jsonl`,
and `.ris`. Non-CSV formats are imported to the canonical paper CSV before
normalization.

The `prepare_full_text` step resolves and extracts full text for included papers
before LLM tagging. It uses local full-text paths when present, then tries open
full-text locations from provider metadata, Unpaywall, Europe PMC, and CORE when
configured. Extracted text is cached outside the project via
`--full-text-cache-dir` or `AD_LIT_FULL_TEXT_CACHE`; the project stores only a
manifest and text-path metadata. `calibrate_topic_contract` uses a selected
set of included primary-paper full texts to refine the review-derived tagging
ontology before rules are generated. `tag_papers` reads the extracted text and
sends a bounded, knowledge-focused evidence view to the LLM.

## Collection Pipeline

Entry point:

```bash
python scripts/run_collection.py run ...
```

Package CLI:

```text
ad_lit_pipeline/cli/run_collection.py
```

Steps:

| Step | Module | Output |
| --- | --- | --- |
| `generate_topic_contract` | `ad_lit_pipeline/steps/collection/generate_topic_contract.py` | `data/collection_plans/<collection>_topic_contract.yaml` |
| `fetch_review_overviews` | `ad_lit_pipeline/steps/collection/fetch_review_overviews.py` | `data/raw/<collection>_review_overviews.jsonl` |
| `prepare_review_full_text` | `ad_lit_pipeline/steps/collection/prepare_review_full_text.py` | `data/raw/<collection>_review_overviews_full_text.jsonl`, `data/raw/<collection>_review_full_text_manifest.csv` |
| `refine_topic_contract` | `ad_lit_pipeline/steps/collection/refine_topic_contract.py` | `data/collection_plans/<collection>_topic_contract.yaml` |
| `plan_search` | `ad_lit_pipeline/steps/collection/plan_search.py` | `data/collection_plans/<collection>_plan.json` |
| `fetch_candidates` | `ad_lit_pipeline/steps/collection/fetch_candidates.py` | `data/raw/<collection>_openalex_candidates.jsonl` |
| `deduplicate_candidates` | `ad_lit_pipeline/steps/collection/deduplicate.py` | `data/raw/<collection>_openalex_candidates_deduped.jsonl` |
| `screen_title_relevance` | `ad_lit_pipeline/steps/screening/title_relevance.py` | `data/raw/<collection>_candidate_screening.csv` |
| `export_included_candidates` | `ad_lit_pipeline/steps/collection/export_included.py` | `data/raw/<collection>_papers.csv` |

When no topic contract is supplied, collection first generates a draft contract,
fetches a larger review/overview candidate pool, resolves available full text
for that pool, selects the best review seeds only from candidates with readable
extracted text, refines the contract's knowledge categories from those selected
review full texts, and then continues into search planning. The planner can
describe multiple provider types, but the current fetch layer implements only
OpenAlex. Unsupported provider selections fail before any network fetch.

Passing `--contract-bootstrap-only` runs only the contract-bootstrap steps and
stops before search planning, so a user can review the generated contract before
candidate collection.

`prepare_review_full_text` reuses the same full-text extraction helpers as the
main paper-tagging pipeline. It adapts OpenAlex review metadata, DOI landing
pages, Unpaywall, Europe PMC, and CORE locations into cached text files for the
review candidate pool. `refine_topic_contract` then filters to reviews with a
readable `full_text_text_path`, selects the configured number of best matching
reviews, and sends only bounded `full_text_evidence` from those selected texts
to the LLM. Reviews without extracted full text are excluded from tag ontology
generation; if no review full text is available, refinement fails instead of
building tags from abstracts or metadata.

When a reviewed topic contract is supplied, `--topic` is optional. Collection
steps derive the planner and candidate-screening topic text from the contract's
`research_topic` fields.

Generated topic contracts include `topic_structure`, which defines one
non-replaceable title anchor, main topic components with broad equivalent terms,
and secondary replacement terms for non-anchor components. Collection fetches a
scaled raw-candidate budget for the requested `--max-results` (currently four
times the target count, with a floor of 30 and cap of 5000), screens up to that
many candidate titles against this structure, and exports selected papers in
tier order: anchor plus all main topics first, then anchor plus secondary
substitutions.

## Script-To-Module Map

The original script names are kept as wrappers or direct CLIs:

| Script | Package module |
| --- | --- |
| `scripts/run_pipeline.py` | `ad_lit_pipeline/cli/run_pipeline.py` |
| `scripts/run_collection.py` | `ad_lit_pipeline/cli/run_collection.py` |
| `scripts/import_bibtex.py` | `ad_lit_pipeline/steps/importers/bibtex.py` |
| `scripts/import_json_metadata.py` | `ad_lit_pipeline/steps/importers/json_metadata.py` |
| `scripts/import_ris.py` | `ad_lit_pipeline/steps/importers/ris.py` |
| `scripts/normalize_metadata.py` | `ad_lit_pipeline/steps/metadata/normalize.py` |
| `scripts/screen_scope.py` | `ad_lit_pipeline/steps/screening/rule_based_scope.py` |
| `scripts/calibrate_topic_contract.py` | `ad_lit_pipeline/steps/tagging/calibrate_topic_contract.py` |
| `scripts/normalize_tagging_config.py` | `ad_lit_pipeline/steps/tagging/normalize_config.py` |
| `scripts/generate_tagging_rules.py` | `ad_lit_pipeline/steps/tagging/generate_rules.py` |
| `scripts/tag_papers_with_llm.py` | `ad_lit_pipeline/steps/tagging/tag_papers.py` |
| `scripts/audit_extraction.py` | `ad_lit_pipeline/steps/tagging/audit.py` |
| `scripts/export_mantis_ready.py` | `ad_lit_pipeline/steps/export/mantis.py` |
| `scripts/generate_topic_contract.py` | `ad_lit_pipeline/steps/collection/generate_topic_contract.py` |
| `scripts/fetch_review_overviews.py` | `ad_lit_pipeline/steps/collection/fetch_review_overviews.py` |
| `scripts/prepare_review_full_text.py` | `ad_lit_pipeline/steps/collection/prepare_review_full_text.py` |
| `scripts/refine_topic_contract.py` | `ad_lit_pipeline/steps/collection/refine_topic_contract.py` |
| `scripts/plan_library_search.py` | `ad_lit_pipeline/steps/collection/plan_search.py` |
| `scripts/fetch_openalex_candidates.py` | `ad_lit_pipeline/steps/collection/fetch_candidates.py` and `ad_lit_pipeline/providers/openalex.py` |
| `scripts/deduplicate_candidates.py` | `ad_lit_pipeline/steps/collection/deduplicate.py` |
| `scripts/screen_title_relevance.py` | `ad_lit_pipeline/steps/screening/title_relevance.py` |
| `scripts/screen_candidates_with_llm.py` | `ad_lit_pipeline/steps/screening/llm_candidate_screening.py` |
| `scripts/export_screened_candidates_to_csv.py` | `ad_lit_pipeline/steps/collection/export_included.py` |

## Topic Contract

Topic contracts in `configs/topics/` or `data/collection_plans/` are the source
of truth for each pipeline run. Main tagging runs require an explicit
`--topic-contract`; collection runs can generate and refine one automatically
when no contract is supplied. A contract includes:

- research topic title and description
- include, exclude, and boundary scope criteria
- rule-based include and exclude terms
- candidate-screening policy
- tagging fallback policy
- allowed category values
- enabled collection providers

Tagging categories are topic-specific knowledge dimensions. Generated contracts
start from example placeholders, then the review-seeded refinement step replaces
or improves them from extracted review full-text evidence only. New
generated/refined contracts must contain at least six concrete knowledge
categories, reject generic meta-categories, and include a required
single-selection `knowledge_goal` root category whose concrete values form the
complete, mutually exclusive primary study-focus or knowledge-contribution
partition of included papers. The `knowledge_goal` values are inferred from
review full texts, then calibrated against selected primary-paper full texts,
and should use `topic_structure.main_topics` as scaffolding for the main roles
papers play around the topic. Details that apply only under one root value should be
represented as conditional categories with `applies_when`.
Generated values should avoid `unclear`, `not_reported`, `mixed_or_unclear`,
and `other`; missing or inapplicable details should usually be represented by
optional or conditional categories instead. The audit step checks observed
tag distributions after paper tagging: unused values and highly dominant values
are reported, and bad `knowledge_goal` partitions block export so a collapsed
root ontology is not treated as Mantis-ready. The quality checks also warn
about boilerplate labels such as `study_design` and `population_group` that
should be rewritten as topic-specific review-derived dimensions. Category values
do not expand rule-based screening terms.

The legacy `configs/early_detection_tagging_config.yaml` is still supported by
the direct normalization step, but orchestrated runs require `--topic-contract`.

## LLM Calls And Tracing

LLM steps use the shared client in `ad_lit_pipeline/llm/client.py` and schemas
from `ad_lit_pipeline/llm/schemas.py`.

Prompt text lives in:

```text
ad_lit_pipeline/prompts/templates/
```

When a trace directory is provided, or when an orchestrated run uses the default
`runs/<run_id>/traces` directory, each LLM call writes:

```text
*_system.txt
*_prompt.md
*_schema.json
*_raw_response.json
*_parsed.json
*_metadata.json
```

The run manifest records these trace paths.

OpenAI calls are bounded by `OPENAI_TIMEOUT_SECONDS` and
`OPENAI_MAX_RETRIES`. The defaults are 45 seconds and zero SDK retries, so one
slow title-screening or paper-tagging request cannot stall an entire run for many
minutes. These values can be overridden in `.env` or the shell for specific
tests.

## Manifests And Resumability

Each orchestrated run creates:

```text
runs/<run_id>/manifest.json
```

The manifest records:

- run id, collection, pipeline name, model, and topic contract metadata
- step status
- input and output artifact paths, existence, and hashes
- row counts
- warnings
- trace paths
- failed step, when applicable

`--resume --run-id <run_id>` resumes from the failed step recorded in the
manifest. `--only-step`, `--from-step`, and `--dry-run` are implemented by
`ad_lit_pipeline/core/runner.py`.

## Current Limits

- OpenAlex is the only implemented provider in `fetch_candidates`.
- The Mantis export step requires at least one tagged extraction row.
- Legacy schema files remain separate from topic contracts and can drift.
- Generated files under `data/processed/`, `data/raw/`, and `runs/` should be
  reviewed before committing.

## Tests

The test suite covers importers, non-LLM steps, topic-contract loading, prompt
rendering, LLM tracing with fake clients, provider behavior, and CLI runner
behavior.

Run:

```bash
pytest
```
