# v0.10.9 Semantic Precision Reranker Plan

Status: planned.

## Baseline

v0.10.8 cleared the recall target:

v3:
- TP: 135
- FN: 27
- recall: 0.8333
- expected_negative_hit_count: 72

v4:
- TP: 101
- FN: 15
- recall: 0.8707
- expected_negative_hit_count: 0

## Problem

The widened embedding profile rescues true positives, but on v3 it also admits too many known-negative semantic matches.

Threshold/cap experiments reduced candidate volume but failed the v3 recall floor.

## Decision

Do not continue blind embedding threshold sweeps.

v0.10.9 should add a semantic precision reranker/adjudicator for pure vector recall candidates.

## Candidate scope

Primary target:

- match_type: embedding_similarity_candidate
- candidate_stage: vector_recall
- candidate_category: semantic_recall

## Desired behavior

Pure embedding candidates should not be treated as normal duplicate candidates unless:

1. they have supporting deterministic evidence, or
2. they pass a semantic precision reranker/adjudicator, or
3. they are explicitly kept as low-confidence review-only candidates.

## First implementation step

Build an offline diagnostic script that compares pure embedding true positives against pure embedding known-negative hits from the v0.10.8 widened profile.

The diagnostic should report which features separate rescued duplicates from false positives:

- embedding confidence
- OCR/text source
- best/native/Tesseract/OpenAI word counts
- key-token overlap
- rare-token overlap
- visual/perceptual hash support
- sequence support
- source document families
- review bucket
- candidate category
- deterministic passes

## Success target

Preserve recall >= 0.80 on v3 and v4 while reducing v3 expected_negative_hit_count materially below 72.
