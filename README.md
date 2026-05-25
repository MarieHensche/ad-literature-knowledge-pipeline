# Alzheimer Literature Knowledge Pipeline

This project helps turn Alzheimer-related research literature into structured data that can be used in Mantis.

The pipeline supports two main workflows:

1. Start with an existing paper collection.
2. Start with only a topic description and let the system collect candidate papers automatically.

## What The Pipeline Does

The pipeline can:

- import paper metadata from common formats
- collect papers from a digital library
- remove duplicate papers
- screen papers for relevance
- assign structured knowledge tags
- audit the tagged results
- export a Mantis-ready CSV file

## Main Workflows

### Existing Paper Collection

Use this workflow when you already have papers in a file such as CSV, BibTeX, JSON/JSONL, or RIS.

The input is converted into the pipeline's standard paper table, then processed into a Mantis-ready output file.

### Automated Paper Collection

Use this workflow when you only have a topic description.

The system creates a search plan, collects candidate papers, screens them, converts relevant papers into the standard input format, and then runs the normal tagging pipeline.

## Main Outputs

The most important output is:

```text
*_mantis_ready.csv
```

This file can be used for creating or updating a Mantis map.

The pipeline also produces audit files and intermediate files that help inspect what happened during collection, screening, and tagging.

## Important Files

Main scripts:

```text
scripts/run_pipeline.py      # Run the knowledge-tagging pipeline
scripts/run_collection.py    # Collect papers automatically from a topic description
```

Main config files:

```text
configs/early_detection_tagging_config.yaml
configs/topics/early_detection_ad.yaml
```

Main input/output locations:

```text
data/raw/          # Paper inputs and collected paper CSVs
data/processed/    # Final Mantis-ready CSVs and audit files
```

## Most Important Commands

Set up the environment:

```bash
source .venv/bin/activate
```

Run the pipeline when you already have a paper CSV:

```bash
python scripts/run_pipeline.py run \
  --papers data/raw/example_papers.csv \
  --topic-contract configs/topics/early_detection_ad.yaml \
  --collection example
```

Run automated paper collection from a topic description:

```bash
TOPIC="$(cat configs/topics/ad_early_detection_test_topic.txt)"

python scripts/run_collection.py run \
  --topic "$TOPIC" \
  --collection ad_early_detection_test \
  --max-results 25 \
  --model gpt-4o-mini \
  --topic-contract configs/topics/early_detection_ad.yaml
```

Run the tagging pipeline on automatically collected papers:

```bash
python scripts/run_pipeline.py run \
  --papers data/raw/ad_early_detection_test_papers.csv \
  --topic-contract configs/topics/early_detection_ad.yaml \
  --collection ad_early_detection_test
```

Explain the pipeline, run one step, or resume from a failed step:

```bash
python scripts/run_pipeline.py explain --collection example

python scripts/run_pipeline.py run \
  --papers data/raw/example_papers.csv \
  --topic-contract configs/topics/early_detection_ad.yaml \
  --collection example \
  --only-step normalize_metadata

python scripts/run_pipeline.py run \
  --papers data/raw/example_papers.csv \
  --topic-contract configs/topics/early_detection_ad.yaml \
  --collection example \
  --run-id 20260525T120000Z-example \
  --resume
```

Check the final Mantis-ready output:

```text
data/processed/ad_early_detection_test_mantis_ready.csv
```

## Current Status

The project is a working research pipeline. It is designed to support iterative thesis work, not yet to be a fully polished production system.

Current automated paper collection uses OpenAlex. Other providers can be added later.

## Typical Use

1. Prepare or collect papers.
2. Convert papers into the standard CSV format.
3. Run the tagging pipeline.
4. Inspect the audit output.
5. Use the Mantis-ready CSV.

## Important Notes

- Topic descriptions define what papers should be collected.
- Topic contracts define scope, screening policy, allowed providers, and tagging categories.
- The legacy `--tagging-config` option still works for the main pipeline.
- Each pipeline run writes a manifest under `runs/<run_id>/manifest.json`.
- LLM steps can write prompt/response traces with `--trace-dir`; orchestrated runs default to `runs/<run_id>/traces`.
- Generated files should usually not be committed.
- Reusable scripts, configs, and topic files can be committed.

## Future Improvements

Possible next steps include adding more digital-library providers, improving screening, reducing repeated work across runs, and adding more documentation and tests.
