# Architecture Notes

## Target production shape

```text
Sorter browser / review UI
→ internal backend creates comparison job
→ internal worker runs dupe engine
→ results stored as JSON/CSV/HTML
→ reviewer inspects side-by-side page matches
```

The sorter PC should not need local OCR, embeddings, or LLM runtime support.

## Pipeline

```text
Stage 0: Page processing
- render each PDF page
- extract native text
- optionally OCR thin/scanned pages
- normalize text
- compute hashes

Stage 1: Candidate detectors
- exact image hash
- exact normalized text hash
- perceptual visual hash
- weighted text similarity
- future embedding detector
- future LLM candidate detector

Stage 2: Candidate aggregation
- merge detector outputs for the same pair
- preserve all signals
- compute candidate score
- determine whether adjudication is needed

Stage 3: Adjudicator agent
- receives candidate evidence
- returns final label, confidence, explanation, risk flags
- does not search all pages from scratch

Stage 4: Human review
- side-by-side pages
- candidate sources
- detector signals
- adjudicator reason when available
```

## Design principle

```text
Detection is plural.
Adjudication is singular.
```

Many detectors can nominate or strengthen a candidate pair. One adjudicator agent produces the final review recommendation.

## Why this split matters

This lets us separately evaluate:

- whether the embedding detector finds new candidates,
- whether the LLM candidate detector helps on messy cases,
- whether the adjudicator reduces false positives,
- whether the adjudicator incorrectly downgrades true positives.

It also keeps the system explainable. A final decision should always point back to detector evidence.
