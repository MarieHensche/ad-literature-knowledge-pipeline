# Early Detection Scope

## Purpose

This scope defines the first narrow pipeline pilot:

**Early detection of Alzheimer's disease, MCI, dementia, or dementia-related cognitive impairment in computational literature.**

The pipeline should turn papers in this scope into structured **knowledge** data. It should not extract the know-how / trajectory workflow yet.

## Include

Include papers that use computational or data-driven methods for at least one of:

- detecting Alzheimer's disease or dementia
- detecting MCI or cognitive impairment
- distinguishing AD, MCI, dementia, or controls
- identifying early, prodromal, or preclinical AD
- predicting or detecting MCI-to-AD conversion when framed as early detection
- screening dementia-related impairment from clinical, behavioral, imaging, omics, sensor, speech, retinal, EEG, or multimodal evidence

## Exclude Or Route Elsewhere

Exclude from this ontology if the main contribution is:

- drug discovery or treatment response
- care support without a detection or screening task
- disease mechanism discovery without a diagnostic / early-detection task
- subtype discovery without an early-detection framing
- later-stage prognosis only
- non-computational clinical reporting
- review/background paper only

## Boundary Rule

If a paper says "early diagnosis" but only performs AD-vs-control classification, keep it in scope but tag the comparison structure accurately. Do not assume it is truly preclinical or prodromal unless the paper's population supports that.

## Current Pipeline Question

For each included paper:

> What early disease state, impairment, or signal is being identified, and from what kind of evidence?