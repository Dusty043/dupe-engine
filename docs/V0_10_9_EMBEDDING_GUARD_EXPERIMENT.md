# v0.10.9 Embedding Guard Experiment

Status: experimental / not promoted.

## Purpose

v0.10.8 cleared the recall target across the v3 and v4 synthetic calibration corpora, but v3 still produced too many known-negative hits under the widened embedding profile.

This branch preserves the v0.10.9 attempt to add an embedding precision guard / cap layer for pure semantic recall candidates.

## Baseline winner: v0.10.8 recall champion

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

## v0.10.9 experiment result

The custom matcher-level embedding guard did not produce a better profile.

Native embedding cap probe:

- TP: 126
- FN: 36
- recall: 0.7778
- expected_negative_hit_count: 50
- candidate rows: 7524
- pure embedding rows: 1849

This reduced candidate volume but failed the v3 recall target.

## Decision

Do not promote this branch to main.

Main should remain the v0.10.8 recall champion.

Next real precision improvement should be a semantic adjudicator / reranker, not more blind embedding threshold/cap tuning.
