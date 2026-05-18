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

- Zotero collection export
- paper metadata
- abstracts
- optional full text / PDF text
- topic scope definition
- knowledge schema

Output:

- cleaned paper table
- structured knowledge tags
- main knowledge claim per paper
- evidence text
- review status and confidence
- Mantis-ready CSV
- schema audit and summary reports

## Conceptual Flow

```text
Zotero collection
→ metadata normalization
→ scope filtering
→ full-text availability check
→ knowledge extraction
→ schema validation
→ Mantis-ready table
→ summary / audit outputs
