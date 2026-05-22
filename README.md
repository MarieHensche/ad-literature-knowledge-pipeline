# Alzheimer Literature Knowledge Pipeline

This repository contains a small, script-based pipeline for turning Alzheimer disease literature metadata into structured, Mantis-ready knowledge tags.

The project currently focuses on the **knowledge layer**: what a paper claims, detects, distinguishes, or identifies scientifically or clinically. It does not yet model the **know-how layer**, such as model architecture, preprocessing, feature engineering, training workflow, or evaluation procedure.

## Current Scope

The active pilot scope is:

> Early detection of Alzheimer's disease, mild cognitive impairment, dementia, or dementia-related cognitive impairment in computational literature.

Included papers are expected to use computational or data-driven methods for detection, diagnosis, screening, classification, stage distinction, or conversion-related early detection. The current ontology captures the clinical target, early-detection subtype, population structure, comparison structure, evidence modality, signal type, dataset source type, extraction basis, confidence, and review status.

See [docs/early_detection_scope.md](docs/early_detection_scope.md) for the inclusion and exclusion rules.

## Repository Structure

```text
configs/
  early_detection_tagging_config.yaml   # LLM-facing research topic and tag categories

data/
  raw/
    example_papers.csv                  # Example canonical paper metadata input
  processed/
    example_*                           # Example normalized, tagged, audited, and Mantis-ready outputs

docs/
  early_detection_scope.md              # Current pilot scope
  input_format.md                       # Canonical input CSV format

schemas/
  early_detection_knowledge_schema.yaml # Manual extraction schema for the knowledge layer

scripts/
  import_bibtex.py                      # Convert BibTeX exports to canonical CSV
  run_pipeline.py                       # Full pipeline runner
  normalize_metadata.py                 # Clean and standardize paper metadata
  screen_scope.py                       # Rule-based scope screening
  normalize_tagging_config.py           # Convert YAML tag config to normalized JSON
  generate_tagging_rules.py             # Use OpenAI to create fixed category rules
  tag_papers_with_llm.py                # Use OpenAI to tag included papers
  audit_extraction.py                   # Validate tags against allowed values and rules
  export_mantis_ready.py                # Convert tagged rows to Mantis-ready CSV
  create_extraction_template.py         # Optional manual extraction template generator
  validate_schema.py                    # Validate the YAML knowledge schema
```

## Inputs

The main pipeline starts from a canonical paper metadata CSV with one row per paper.

Required columns:

```text
paper_id
title
year
doi
abstract
```

Recommended optional columns:

```text
authors
venue
url
source
full_text_path
notes
```

BibTeX files can be converted into this canonical CSV before running the main
pipeline. Zotero, Semantic Scholar, OpenAlex, digital-library exports, and
PDF/full-text importers can be added later as additional upstream steps.

See [docs/input_format.md](docs/input_format.md) for the input format.

## Outputs

For a collection named `example`, the full runner writes:

```text
data/processed/example_papers_normalized.csv
data/processed/example_scope_screened.csv
data/processed/example_tagging_config_normalized.json
data/processed/example_tagging_rules.json
data/processed/example_extraction_filled.csv
data/processed/example_extraction_audit.csv
data/processed/example_mantis_ready.csv
```

The final file, `*_mantis_ready.csv`, contains Mantis-oriented `title`, `categoric`, and `semantic` fields plus paper identifiers and all generated knowledge tags.

## Setup

Create and activate a virtual environment:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

Create a local `.env` file from the example and add an OpenAI API key:

```bash
cp .env.example .env
```

The LLM steps use:

```text
OPENAI_API_KEY
OPENAI_MODEL
```

`OPENAI_MODEL` defaults to `gpt-4o-mini` if it is not set.

## Usage

Run the commands below from the repository root, the folder that contains
`scripts/`, `configs/`, `data/`, and `.venv`.

Validate the manual knowledge schema:

```bash
python scripts/validate_schema.py
```

Convert a BibTeX export into the canonical CSV format:

```bash
python scripts/import_bibtex.py \
  --input data/raw/example_papers.bib \
  --output data/raw/example_papers_from_bib.csv
```

Run the full current pipeline on the example collection:

```bash
python scripts/run_pipeline.py run \
  --papers data/raw/example_papers.csv \
  --tagging-config configs/early_detection_tagging_config.yaml \
  --collection example
```

Or run it on a CSV created from BibTeX:

```bash
python scripts/run_pipeline.py run \
  --papers data/raw/example_papers_from_bib.csv \
  --tagging-config configs/early_detection_tagging_config.yaml \
  --collection example_bib
```



This performs metadata normalization, rule-based scope screening, tagging-config normalization, LLM generation of fixed tagging rules, LLM paper tagging, extraction audit, and Mantis export.

## Running Individual Steps

Each pipeline step can also be run directly. This is useful while developing or debugging one stage:

```bash
python scripts/normalize_metadata.py \
  --input data/raw/example_papers.csv \
  --output data/processed/example_papers_normalized.csv

python scripts/screen_scope.py \
  --input data/processed/example_papers_normalized.csv \
  --output data/processed/example_scope_screened.csv

python scripts/normalize_tagging_config.py \
  --config configs/early_detection_tagging_config.yaml \
  --output data/processed/example_tagging_config_normalized.json

python scripts/generate_tagging_rules.py \
  --config data/processed/example_tagging_config_normalized.json \
  --output data/processed/example_tagging_rules.json

python scripts/tag_papers_with_llm.py \
  --papers data/processed/example_scope_screened.csv \
  --config data/processed/example_tagging_config_normalized.json \
  --rules data/processed/example_tagging_rules.json \
  --output data/processed/example_extraction_filled.csv

python scripts/audit_extraction.py \
  --input data/processed/example_extraction_filled.csv \
  --config data/processed/example_tagging_config_normalized.json \
  --rules data/processed/example_tagging_rules.json \
  --output data/processed/example_extraction_audit.csv

python scripts/export_mantis_ready.py \
  --input data/processed/example_extraction_filled.csv \
  --output data/processed/example_mantis_ready.csv
```

## Optional Manual Extraction Template

The repository also contains an earlier manual-review path:

```bash
python scripts/create_extraction_template.py \
  --screened data/processed/example_scope_screened.csv \
  --schema schemas/early_detection_knowledge_schema.yaml \
  --output data/processed/example_extraction_template.csv
```

This creates a blank extraction table for papers screened as `include`. It is useful for human review or assisted extraction experiments, but it is not currently called by `scripts/run_pipeline.py`.

## Current Status

The repository is a working pilot rather than a production data system. It can run end to end on the included example data and produce a Mantis-ready CSV.

Current capabilities:

- BibTeX-to-canonical-CSV import
- canonical CSV metadata normalization
- rule-based early-detection scope screening
- YAML-to-JSON tagging configuration normalization
- LLM-generated fixed tagging rules
- LLM tagging of included papers using controlled values
- extraction audit for missing, invalid, or inconsistent tag values
- Mantis-ready CSV export
- optional manual extraction template generation

Important limitations:

- Scope screening is currently keyword-based and should be reviewed before use on a real corpus.
- LLM tagging depends on abstracts and metadata unless richer text is provided upstream.
- The pipeline currently models knowledge tags only, not methodological know-how.
- Example data and example outputs are toy pilot artifacts.
- Direct importers for Zotero, Semantic Scholar, OpenAlex, PDFs, and full text are not implemented yet.

## Development Notes

Generated local outputs under `data/processed/example_*` are ignored by git, although example artifacts are present in this repository for reference. Full text, PDFs, secrets, virtual environments, logs, and temporary files are also ignored.

The next useful development step is to run the pipeline on a small real early-detection paper set, inspect the audit output and Mantis visualization, and refine the ontology values based on actual tagging failures.
