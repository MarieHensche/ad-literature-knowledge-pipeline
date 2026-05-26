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
| `normalize_tagging_config` | `ad_lit_pipeline/steps/tagging/normalize_config.py` | `data/processed/<collection>_tagging_config_normalized.json` |
| `generate_tagging_rules` | `ad_lit_pipeline/steps/tagging/generate_rules.py` | `data/processed/<collection>_tagging_rules.json` |
| `tag_papers` | `ad_lit_pipeline/steps/tagging/tag_papers.py` | `data/processed/<collection>_extraction_filled.csv` |
| `audit_extraction` | `ad_lit_pipeline/steps/tagging/audit.py` | `data/processed/<collection>_extraction_audit.csv` |
| `export_mantis` | `ad_lit_pipeline/steps/export/mantis.py` | `data/processed/<collection>_mantis_ready.csv` |

Supported `--papers` formats are `.csv`, `.bib`, `.bibtex`, `.json`, `.jsonl`,
and `.ris`. Non-CSV formats are imported to the canonical paper CSV before
normalization.

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
| `plan_search` | `ad_lit_pipeline/steps/collection/plan_search.py` | `data/collection_plans/<collection>_plan.json` |
| `fetch_candidates` | `ad_lit_pipeline/steps/collection/fetch_candidates.py` | `data/raw/<collection>_openalex_candidates.jsonl` |
| `deduplicate_candidates` | `ad_lit_pipeline/steps/collection/deduplicate.py` | `data/raw/<collection>_openalex_candidates_deduped.jsonl` |
| `screen_candidates` | `ad_lit_pipeline/steps/screening/llm_candidate_screening.py` | `data/raw/<collection>_candidate_screening.csv` |
| `export_included_candidates` | `ad_lit_pipeline/steps/collection/export_included.py` | `data/raw/<collection>_papers.csv` |

The planner can describe multiple provider types, but the current fetch layer
implements only OpenAlex. Unsupported provider selections fail before any network
fetch.

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
| `scripts/normalize_tagging_config.py` | `ad_lit_pipeline/steps/tagging/normalize_config.py` |
| `scripts/generate_tagging_rules.py` | `ad_lit_pipeline/steps/tagging/generate_rules.py` |
| `scripts/tag_papers_with_llm.py` | `ad_lit_pipeline/steps/tagging/tag_papers.py` |
| `scripts/audit_extraction.py` | `ad_lit_pipeline/steps/tagging/audit.py` |
| `scripts/export_mantis_ready.py` | `ad_lit_pipeline/steps/export/mantis.py` |
| `scripts/plan_library_search.py` | `ad_lit_pipeline/steps/collection/plan_search.py` |
| `scripts/fetch_openalex_candidates.py` | `ad_lit_pipeline/steps/collection/fetch_candidates.py` and `ad_lit_pipeline/providers/openalex.py` |
| `scripts/deduplicate_candidates.py` | `ad_lit_pipeline/steps/collection/deduplicate.py` |
| `scripts/screen_candidates_with_llm.py` | `ad_lit_pipeline/steps/screening/llm_candidate_screening.py` |
| `scripts/export_screened_candidates_to_csv.py` | `ad_lit_pipeline/steps/collection/export_included.py` |

## Topic Contract

Topic contracts in `configs/topics/` are the source of truth for each pipeline
run. Each orchestrated run must pass an explicit `--topic-contract`. A contract
includes:

- research topic title and description
- include, exclude, and boundary scope criteria
- rule-based include and exclude terms
- candidate-screening policy
- tagging fallback policy
- allowed category values
- enabled collection providers

Every contract must include the generic categories `main_topic_category` and
`research_target`. The Mantis export uses these fields to populate its core
`categoric` column without depending on any specific research topic.

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
