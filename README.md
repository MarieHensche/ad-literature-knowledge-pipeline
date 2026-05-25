# Alzheimer Literature Knowledge Pipeline

This repository contains a small, script-based pipeline for turning Alzheimer disease literature metadata into structured, Mantis-ready knowledge tags.

The project currently focuses on the **knowledge layer**: what a paper claims, detects, distinguishes, or identifies scientifically or clinically. It does not yet model the **know-how layer**, such as model architecture, preprocessing, feature engineering, training workflow, or evaluation procedure.

## Current Scope

The active pilot scope is:

> Early detection of Alzheimer's disease, mild cognitive impairment, dementia, or dementia-related cognitive impairment in computational literature.

Included papers are expected to use computational or data-driven methods for detection, diagnosis, screening, classification, stage distinction, or conversion-related early detection. The current ontology captures the clinical target, early-detection subtype, population structure, comparison structure, evidence modality, signal type, dataset source type, extraction basis, confidence, and review status.

See [docs/early_detection_scope.md](docs/early_detection_scope.md) for the inclusion and exclusion rules.


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

Add your OpenAI key:

```text
OPENAI_API_KEY=your_key_here
OPENAI_MODEL=gpt-4o-mini
```


# Workflow 1: Pipeline With Paper Input

Use this workflow when you already have papers.

The main pipeline expects a **canonical CSV**.

## Canonical CSV Format

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

Example:

```text
data/raw/example_papers.csv
```

Run the main pipeline:

```bash
python scripts/run_pipeline.py run \
  --papers data/raw/example_papers.csv \
  --tagging-config configs/early_detection_tagging_config.yaml \
  --collection example
```

Final output:

```text
data/processed/example_mantis_ready.csv
```

Audit output:

```text
data/processed/example_extraction_audit.csv
```

## Paper Input Option A: BibTeX

Convert BibTeX to canonical CSV:

```bash
python scripts/import_bibtex.py \
  --input data/raw/example_papers.bib \
  --output data/raw/example_papers_from_bib.csv
```

Run the pipeline:

```bash
python scripts/run_pipeline.py run \
  --papers data/raw/example_papers_from_bib.csv \
  --tagging-config configs/early_detection_tagging_config.yaml \
  --collection example_bib
```

Final output:


```text
data/processed/example_bib_mantis_ready.csv
```

## Paper Input Option B: JSON / JSONL Metadata

Convert JSONL to canonical CSV:

```bash
python scripts/import_json_metadata.py \
  --input data/raw/example_papers.jsonl \
  --output data/raw/example_papers_from_json.csv
```

Check the generated CSV:

```bash
head -5 data/raw/example_papers_from_json.csv
```

Run the pipeline:

```bash
python scripts/run_pipeline.py run \
  --papers data/raw/example_papers_from_json.csv \
  --tagging-config configs/early_detection_tagging_config.yaml \
  --collection example_json
```

Final output:

```text
data/processed/example_json_mantis_ready.csv
```

## Paper Input Option C: RIS

Convert RIS to canonical CSV:

```bash
python scripts/import_ris.py \
  --input data/raw/example_papers.ris \
  --output data/raw/example_papers_from_ris.csv
```

Check the generated CSV:

```bash
head -5 data/raw/example_papers_from_ris.csv
```

Run the pipeline:

```bash
python scripts/run_pipeline.py run \
  --papers data/raw/example_papers_from_ris.csv \
  --tagging-config configs/early_detection_tagging_config.yaml \
  --collection example_ris
```

Final output:

```text
data/processed/example_ris_mantis_ready.csv
```

# Workflow 2: Pipeline Without Paper Input

Use this workflow when you do **not** already have a paper collection.

You provide:

1. A topic description text file
2. A tagging config YAML file

The system then collects papers automatically.

Current automated collection implementation:

```text
topic description
-> AI search planner
-> provider-specific fetcher
-> deduplication
-> AI relevance screening
-> canonical CSV export
-> existing knowledge pipeline
-> Mantis-ready CSV
```

Important note:

```text
The AI planner can recommend different providers.
Currently, only the OpenAlex fetcher is implemented.
```

So the current automated workflow works when the planner selects OpenAlex.

## Input File 1: Topic Description

Recommended location:

```text
configs/topics/ad_early_detection_test_topic.txt
```

Example content:

```text
Computational papers about early detection of Alzheimer's disease, mild cognitive impairment, dementia, or dementia-related cognitive impairment from the years 2018 to 2024.

Focus on papers that use machine learning, deep learning, statistical modeling, digital biomarkers, neuroimaging, speech or language analysis, cognitive testing, sensor data, eye tracking, or multimodal computational methods for detection, diagnosis, screening, classification, or prediction.

Exclude papers mainly about treatment, drug discovery, care support, disease biology or mechanism discovery without detection, general clinical guidelines, or unrelated neurological diseases.
```

If you have the file somewhere on your Mac, copy it into the project:

```bash
mkdir -p configs/topics

cp "/FULL/PATH/FROM/FINDER/your_topic_file.txt" \
  configs/topics/ad_early_detection_test_topic.txt
```

## Input File 2: Tagging Config YAML

Recommended location:

```text
configs/ad_early_detection_test_tagging_config.yaml
```

Example structure:

```yaml
research_topic:
  title: Computational early detection of Alzheimer's disease and related cognitive impairment
  description: >
    Computational and data-driven papers about early detection, diagnosis,
    screening, classification, or prediction of Alzheimer's disease, mild cognitive
    impairment, dementia, or dementia-related cognitive impairment.

categories:
  primary_clinical_target:
    values:
      - ad
      - mci
      - dementia
      - cognitive_impairment
      - mixed_or_unclear
      - unclear

  early_detection_subtype:
    values:
      - early_ad_detection
      - mci_detection
      - mci_ad_detection
      - dementia_screening
      - conversion_or_deterioration_detection
      - preclinical_or_prodromal_detection
      - mixed_or_unclear
         - unclear

  computational_method_family:
    values:
      - machine_learning
      - deep_learning
      - statistical_modeling
      - signal_processing
      - natural_language_processing
      - computer_vision
      - digital_biomarker_modeling
      - multimodal_fusion
      - unclear

  evidence_modality_family:
    values:
      - neuroimaging
      - speech_language
      - cognitive_assessment
      - clinical_tabular
      - sensor_behavior
      - eye_tracking
      - genetics_or_omics
      - fluid_biomarker
      - multimodal
      - unclear

  dataset_source_type:
    values:
      - public_named_dataset
      - private_or_local_clinical_dataset
      - challenge_dataset
      - simulated_or_synthetic
      - not_reported
      - unclear

  extraction_basis:
    values:
      - title_only
      - abstract
      - abstract_and_metadata
      - full_text
      - unclear



  knowledge_confidence:
    values:
      - high
      - medium
      - low
      - very_low
      - conflict

  review_status:
    required: true
    values:
      - ai_tagged
      - human_reviewed
      - needs_decision
      - full_text_needed
      - excluded_from_scope
```

If you have the YAML file somewhere on your Mac, copy it into the project:

```bash
cp "/FULL/PATH/FROM/FINDER/your_tagging_config.yaml" \
  configs/ad_early_detection_test_tagging_config.yaml
```

## Step 1: Run Automated Collection

Load the topic text:

```bash
TOPIC="$(cat configs/topics/ad_early_detection_test_topic.txt)"
```

Run collection:

```bash
python scripts/run_collection.py run \
  --topic "$TOPIC" \
  --collection ad_early_detection_test \
  --max-results 25 \
  --model gpt-4o-mini
```


This creates:

```text
data/collection_plans/ad_early_detection_test_plan.json
data/raw/ad_early_detection_test_openalex_candidates.jsonl
data/raw/ad_early_detection_test_openalex_candidates_deduped.jsonl
data/raw/ad_early_detection_test_candidate_screening.csv
data/raw/ad_early_detection_test_papers.csv
```

The most important file is:

```text
data/raw/ad_early_detection_test_papers.csv
```

That is the canonical CSV created from automatically collected papers.

Check it:

```bash
head -5 data/raw/ad_early_detection_test_papers.csv
wc -l data/raw/ad_early_detection_test_papers.csv
```

## Step 2: Run Main Knowledge Pipeline

Run the normal pipeline on the collected paper CSV:

```bash
python scripts/run_pipeline.py run \
  --papers data/raw/ad_early_detection_test_papers.csv \
  --tagging-config configs/ad_early_detection_test_tagging_config.yaml \
  --collection ad_early_detection_test
```

Final Mantis-ready output:

```text
data/processed/ad_early_detection_test_mantis_ready.csv
```

Audit output:

```text
data/processed/ad_early_detection_test_extraction_audit.csv
```

# Important Generated Files

These files are generated outputs and usually should **not** be committed:

```text
data/raw/*_openalex_candidates.jsonl
data/raw/*_openalex_candidates_deduped.jsonl
data/raw/*_candidate_screening.csv
data/raw/*_papers.csv
data/raw/*_from_bib.csv
data/raw/*_from_json.csv
data/raw/*_from_ris.csv
data/processed/*
```

Reusable files that can be committed:

```text
scripts/*.py
configs/*.yaml
configs/topics/*.txt
data/raw/example_papers.csv
data/raw/example_papers.bib
data/raw/example_papers.jsonl
data/raw/example_papers.ris
```

# Common Commands


Check git status:

```bash
git status
```

Commit reusable config/input files:

```bash
git add configs/topics/ad_early_detection_test_topic.txt \
  configs/ad_early_detection_test_tagging_config.yaml

git commit -m "Add early detection test inputs"
git push
```

Clean generated collection files for a collection:

```bash
rm -f data/collection_plans/ad_early_detection_test_plan.json
rm -f data/raw/ad_early_detection_test_openalex_candidates.jsonl
rm -f data/raw/ad_early_detection_test_openalex_candidates_deduped.jsonl
rm -f data/raw/ad_early_detection_test_candidate_screening.csv
rm -f data/raw/ad_early_detection_test_papers.csv
rm -f data/processed/ad_early_detection_test_*
```

# Current Limitations

- Automated paper collection currently has only one implemented provider adapter: OpenAlex.
- The AI planner may recommend Semantic Scholar, Europe PMC, or Crossref, but those fetchers are not implemented yet.
- Candidate screening uses abstracts and metadata only.
- Ambiguous candidates are excluded during automated collection.
- The existing keyword-based `screen_scope.py` still runs inside the main pipeline, so collected papers may be screened twice.
- Tagging rules are regenerated for each collection run, even when the tagging config has not changed.
