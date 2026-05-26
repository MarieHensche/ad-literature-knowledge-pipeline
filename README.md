# Alzheimer Literature Knowledge Pipeline

This repository turns Alzheimer-related literature metadata into structured
knowledge tags and a Mantis-ready CSV.

The current refactor keeps the original `scripts/` entry points as compatibility
wrappers, while the reusable pipeline logic lives in `ad_lit_pipeline/`.

## What It Does

The pipeline supports two workflows:

1. Start with an existing paper collection.
2. Start with a topic description and collect candidate papers automatically.

It can:

- import paper metadata from CSV, BibTeX, JSON, JSONL, or RIS
- plan and run OpenAlex candidate collection from a topic description
- deduplicate candidate papers
- screen papers against a topic contract
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
scripts/run_pipeline.py       Main tagging pipeline CLI
scripts/run_collection.py     Automated collection CLI
ad_lit_pipeline/              Importable pipeline package
configs/topics/               Topic contracts
data/raw/                     Raw paper inputs and collected candidates
data/processed/               Normalized, tagged, audited, and exported outputs
runs/                         Run manifests and LLM traces
```

The default topic contract is:

```text
configs/topics/early_detection_ad.yaml
```

It defines the research topic, scope criteria, rule-based screening terms,
candidate-screening policy, tagging categories, fallback policy, and enabled
providers.

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
candidate papers first:

```bash
TOPIC="$(cat configs/topics/ad_early_detection_test_topic.txt)"

python scripts/run_collection.py run \
  --topic "$TOPIC" \
  --collection ad_early_detection_test \
  --max-results 25 \
  --model gpt-4o-mini \
  --topic-contract configs/topics/early_detection_ad.yaml
```

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

## Development

Run tests with:

```bash
pytest
```

Agent and contributor coding rules live in `AGENT.md`. The short
Codex-discovery bridge is `AGENTS.md`.

For architecture details, see `docs/technical_summary.md`.

## Current Limits

- OpenAlex is the only implemented collection provider.
- `--tagging-config` still works for legacy runs, but `--topic-contract` is the
  preferred source of topic and tagging policy.
- If no papers reach LLM tagging, the Mantis export step fails because it
  requires at least one extraction row.
- `schemas/early_detection_knowledge_schema.yaml` is not generated from the
  topic contract yet, so schema drift is still possible.
