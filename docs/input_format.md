# Input Format

## Purpose

The pipeline starts from a canonical paper metadata CSV.

Different sources can be converted into this format before entering the pipeline:

- manual CSV
- BibTeX export
- Zotero export as BibTeX
- Semantic Scholar / OpenAlex / other APIs
- digital library export

For now, the main pipeline directly accepts this canonical CSV. The repository
also includes a BibTeX importer that converts `.bib` files into the canonical
CSV before the main pipeline starts.

## Canonical CSV

The canonical input CSV should contain one row per paper.

Recommended columns:

```text
paper_id
title
year
doi
abstract
authors
venue
url
source
full_text_path
notes
```

## BibTeX Input

Use the BibTeX importer when your papers come from Zotero, ACM, DBLP, Google
Scholar, or another source that can export `.bib`.

```bash
python scripts/import_bibtex.py \
  --input data/raw/my_papers.bib \
  --output data/raw/my_papers.csv
```

Then run the main pipeline on the generated CSV:

```bash
python scripts/run_pipeline.py run \
  --papers data/raw/my_papers.csv \
  --tagging-config configs/early_detection_tagging_config.yaml \
  --collection my_papers
```

The importer maps common BibTeX fields as follows:

```text
BibTeX key       -> paper_id
title           -> title
year/date       -> year
doi             -> doi
abstract        -> abstract
author          -> authors
journal/booktitle/conference/publisher -> venue
url/link        -> url
file            -> full_text_path, when a PDF path is present
entry type      -> source
```
