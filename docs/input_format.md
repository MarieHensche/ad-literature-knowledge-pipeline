# Input Format

## Purpose

The pipeline starts from a canonical paper metadata CSV.

Different sources can be converted into this format before entering the pipeline:

- manual CSV
- Zotero export
- Semantic Scholar / OpenAlex / other APIs
- digital library export

For now, the pipeline directly accepts this canonical CSV. Source-specific importers can be added later.

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