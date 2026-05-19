# Alzheimer Literature Knowledge Pipeline

This repository builds a structured knowledge-extraction pipeline for computational Alzheimer’s disease literature.

The project is based on Manolis Kellis’s guidance to separate:

- **Knowledge**: what a paper learns or claims scientifically/clinically
- **Know-how**: how the paper produces that result methodologically

This repository currently focuses only on the **knowledge layer**.

## Current Pilot

The first pilot ontology is:

**Early detection of Alzheimer’s disease, MCI, dementia, or dementia-related cognitive impairment**

The goal is to turn a collection of research papers into structured, Mantis-processable data that can be visualized as a knowledge landscape.

## Pipeline Goal

Input:

- canonical paper metadata CSV
- topic scope definition
- knowledge schema
- optional full text / PDF text path

Output:

- normalized paper table
- scope-screened paper table
- extraction template for manual/assisted knowledge review
- audited extraction table
- Mantis-ready CSV

For now, the pipeline starts from a canonical CSV. Later, Zotero exports, Semantic Scholar/OpenAlex APIs, or digital-library searches can be added as importer steps before this CSV input.

## Pipeline Steps

1. Define topic scope
2. Define knowledge schema
3. Validate schema
4. Ingest canonical paper CSV
5. Normalize metadata
6. Screen papers against the topic scope
7. Create extraction table
8. Fill/review knowledge extraction
9. Audit extraction quality
10. Export Mantis-ready output

## Conceptual Flow

canonical paper CSV
→ metadata normalization
→ scope screening
→ extraction template
→ manual/assisted knowledge extraction
→ extraction audit
→ Mantis-ready CSV


## Quick Start

Create and activate a virtual environment:
```text
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

Validate the schema: 
```text
python scripts/validate_schema.py
```

Run the prepare stage:
```text
python scripts/run_pipeline.py prepare \
  --input data/raw/example_papers.csv \
  --collection example
```

This creates:
```text
data/processed/example_papers_normalized.csv
data/processed/example_scope_screened.csv
data/processed/ex
```

Fill/review the extraction table, then save the filled file as:
```text
data/processed/example_extraction_filled.csv
```

Run finalize:
```text
python scripts/run_pipeline.py finalize --collection example
```

This creates: 
```text
data/processed/example_extraction_audit.csv
data/processed/example_mantis_ready.csv
```

Generated example outputs are ignored by git.

## Current status

The pipeline skeleton is working end-to-end on the example collection.

Current capabilities:

- schema validation
- metadata normalization
- scope screening
- extraction-template creation
- manual/assisted knowledge extraction workflow
- extraction audit
- Mantis-ready export
- managed prepare/finalize pipeline runner

## Notes

The current implementation is intentionally small and testable. The next major step is to test the pipeline on a small real set of early-detection papers, then improve the schema and extraction fields based on what breaks or feels scientifically weak.
