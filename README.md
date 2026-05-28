# Literature Knowledge Pipeline

This repository turns research literature metadata into structured knowledge
tags and a Mantis-ready CSV.

The current refactor keeps the original `scripts/` entry points as compatibility
wrappers, while the reusable pipeline logic lives in `ad_lit_pipeline/`.

## What It Does

The pipeline supports two workflows:

1. Start with an existing paper collection.
2. Start with a research question, generate a topic contract, and collect
   candidate papers automatically.

It can:

- import paper metadata from CSV, BibTeX, JSON, JSONL, or RIS
- draft a topic contract from a plain research question
- plan and run OpenAlex candidate collection from multiple search-query variants
- deduplicate candidate papers
- screen papers against a topic contract with a recall-oriented candidate pass
- generate ontology tagging rules
- tag included papers with an LLM
- audit extracted tags
- export a Mantis-ready CSV

## Setup

Create and activate a local environment:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Configure OpenAI credentials for LLM steps:

```bash
cp .env.example .env
```

Then edit `.env`:

```text
OPENAI_API_KEY=...
OPENAI_MODEL=gpt-4o-mini
```

Non-LLM commands, `explain`, and `--dry-run` do not require an API key.

## Main Files

```text
scripts/run_pipeline.py             Main tagging pipeline CLI
scripts/run_collection.py           Automated collection CLI
scripts/generate_topic_contract.py  Topic-contract draft generator
scripts/fetch_review_overviews.py   Review/overview seed fetcher
scripts/refine_topic_contract.py    Review-seeded contract refiner
ad_lit_pipeline/                    Importable pipeline package
configs/topics/                     Topic contracts and the generic template
data/collection_plans/              Search plans and generated topic contracts
data/raw/                           Raw paper inputs and collected candidates
data/processed/                     Normalized, tagged, audited, and exported outputs
runs/                               Run manifests and LLM traces
```

Example topic contracts live under:

```text
configs/topics/
```

Topic contracts define the research topic, scope criteria, rule-based screening
terms, candidate-screening policy, tagging categories, fallback policy, enabled
providers, and optional seed search queries. Each contract must include the
generic categories `main_topic_category` and `research_target`; the Mantis
export uses them to populate its core `categoric` field.

For a new research direction, start from a plain research question and generate
a draft contract. The generator uses:

```text
configs/topics/topic_contract_template.yaml
```

The generated YAML is meant to be inspected and edited before collection
continues. This is the review point for tightening scope, adding topic-specific
tagging categories, changing candidate-screening policy, or improving search
queries.

## Input Format

The main pipeline accepts `.csv`, `.bib`, `.bibtex`, `.json`, `.jsonl`, and
`.ris` files through `--papers`.

Canonical CSV inputs should contain one row per paper. Required columns are:

```text
paper_id
title
year
doi
abstract
```

Recommended optional columns are:

```text
authors
venue
url
source
full_text_path
notes
```

When non-CSV input is provided, the pipeline imports it into the canonical CSV
shape before normalization.

## Run Existing Papers

Use this when you already have paper metadata:

```bash
python scripts/run_pipeline.py run \
  --papers data/raw/example_papers.csv \
  --topic-contract configs/topics/early_detection_ad.yaml \
  --collection example
```

The final export is written to:

```text
data/processed/example_mantis_ready.csv
```

The audit file is written to:

```text
data/processed/example_extraction_audit.csv
```

## Run Automated Collection

Use this when you have a topic description and want the pipeline to collect
candidate papers first. If `--topic-contract` is omitted, the collection
workflow generates a draft contract, fetches a small set of OpenAlex
review/overview seed papers, refines the contract's knowledge tagging
categories from those seeds, and then plans the search:

```bash
TOPIC="How does climate change affect human health?"

python scripts/run_collection.py run \
  --topic "$TOPIC" \
  --collection climate_health \
  --model gpt-4o-mini \
  --max-review-overviews 5
```

The generated and refined contract is written to:

```text
data/collection_plans/climate_health_topic_contract.yaml
```

The review/overview seed artifact is written to:

```text
data/raw/climate_health_review_overviews.jsonl
```

If you want a human review gate before candidate collection, run only the
contract-bootstrap pipeline, review the YAML, then run collection with the
reviewed contract:

```bash
python scripts/run_collection.py run \
  --topic "$TOPIC" \
  --collection climate_health \
  --model gpt-4o-mini \
  --max-review-overviews 5 \
  --contract-bootstrap-only

python scripts/run_collection.py run \
  --collection climate_health \
  --max-results 50 \
  --model gpt-4o-mini \
  --topic-contract data/collection_plans/climate_health_topic_contract.yaml
```

If you already have a reviewed contract, run collection directly:

```bash
python scripts/run_collection.py run \
  --collection ad_early_detection_test \
  --max-results 25 \
  --model gpt-4o-mini \
  --topic-contract configs/topics/early_detection_ad.yaml
```

The search plan can include multiple executable `search_queries`. OpenAlex is
called once per query variant, spreading the `--max-results` budget across
queries. Candidate artifacts preserve the query, query index, query rank, query
reason, and provider URL so screening decisions can be debugged later.

This writes a canonical paper CSV:

```text
data/raw/ad_early_detection_test_papers.csv
```

Then run the main tagging pipeline:

```bash
python scripts/run_pipeline.py run \
  --papers data/raw/ad_early_detection_test_papers.csv \
  --topic-contract configs/topics/early_detection_ad.yaml \
  --collection ad_early_detection_test
```

## Inspect Or Resume Runs

List pipeline steps and conventional output paths:

```bash
python scripts/run_pipeline.py explain --collection example
python scripts/run_collection.py explain --collection example
```

Preview selected steps without executing them:

```bash
python scripts/run_pipeline.py run \
  --papers data/raw/example_papers.csv \
  --topic-contract configs/topics/early_detection_ad.yaml \
  --collection example \
  --only-step normalize_metadata \
  --dry-run
```

Run one step or resume from a step:

```bash
python scripts/run_pipeline.py run \
  --papers data/raw/example_papers.csv \
  --topic-contract configs/topics/early_detection_ad.yaml \
  --collection example \
  --only-step normalize_metadata

python scripts/run_pipeline.py run \
  --papers data/raw/example_papers.csv \
  --topic-contract configs/topics/early_detection_ad.yaml \
  --collection example \
  --from-step tag_papers
```

Resume a failed run from its manifest:

```bash
python scripts/run_pipeline.py run \
  --papers data/raw/example_papers.csv \
  --topic-contract configs/topics/early_detection_ad.yaml \
  --collection example \
  --run-id 20260525T120000Z-example \
  --resume
```

Each run writes:

```text
runs/<run_id>/manifest.json
runs/<run_id>/traces/
```

The manifest records step inputs, outputs, row counts, warnings, errors, and
trace paths. LLM traces include rendered prompts, response schemas, raw
responses, parsed JSON, and metadata.

Collection manifests include the generated or supplied topic contract path,
search plan path, fetched candidate counts, query counts, screening counts, and
trace paths for contract generation, search planning, and candidate screening.

## Local UI

Run the local web console:

```bash
.venv/bin/python scripts/run_ui.py
```

Then open:

```text
http://127.0.0.1:8765
```

The UI is a separate wrapper over the existing CLIs. It can generate and edit
topic contracts, start automated collection runs, start tagging runs from an
input file, tail run logs, and inspect run manifests without changing pipeline
step behavior.

## Development

Run tests with:

```bash
.venv/bin/python -m pytest
```

Agent and contributor coding rules live in `AGENTS.md`.

For architecture details, see `docs/technical_summary.md`.

## Current Limits

- OpenAlex is the only implemented collection provider.
- The main tagging pipeline requires `--topic-contract`. The collection
  pipeline can either receive `--topic-contract` or create and refine one
  automatically from review/overview seed papers when no contract is supplied.
- `--tagging-config` is kept for direct legacy config normalization only.
- If no papers reach LLM tagging, the Mantis export step fails because it
  requires at least one extraction row.
- Legacy schema files are not generated from topic contracts yet, so schema
  drift is still possible.
