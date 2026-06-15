# v0.10.9 Reranker Offline Simulation

Source: `/srv/apps/dupe-engine/dupe-engine-repo/artifacts/calibration/v0108/v4_candidate_summary.csv`

## Parameters

- action: **demote**
- min_confidence (default threshold): **0.88**
- ocr_penalty: 0.0
- same_doc_bonus: 0.03
- tesseract_bonus: 0.02

## Cohort Overview

- Total rows in candidate_summary.csv: **8104**
- Pure embedding rows (match_type=embedding_similarity_candidate): **2141**
- Non-pure rows (untouched by reranker): **5963**

| Group | Count |
|---|---:|
| TP (truth_label=duplicate) | **49** |
| KN (truth_label=not_duplicate) | **0** |
| Partial overlap | 12 |
| Unlabeled | 2080 |

## Recommendation

- Recommended threshold: **0.8**
- Action: **demote**
- TP actioned: 0/49 (0.0%)
- KN actioned: 0/0 (0.0%)
- Estimated review rows removed: 561

## Threshold Sweep

| Threshold | TP total | TP actioned | TP action% | KN total | KN actioned | KN action% | Partial actioned | Unlabeled actioned | Est. removed |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 0.76 | 49 | 0 | 0.0% | 0 | 0 | 0.0% | 0 | 310 | 310 |
| 0.78 | 49 | 0 | 0.0% | 0 | 0 | 0.0% | 0 | 453 | 453 |
| 0.80 ◀ | 49 | 0 | 0.0% | 0 | 0 | 0.0% | 0 | 561 | 561 |
| 0.82 | 49 | 2 | 4.1% | 0 | 0 | 0.0% | 0 | 709 | 711 |
| 0.84 | 49 | 6 | 12.2% | 0 | 0 | 0.0% | 0 | 859 | 865 |
| 0.86 | 49 | 7 | 14.3% | 0 | 0 | 0.0% | 0 | 1014 | 1021 |
| 0.88 | 49 | 15 | 30.6% | 0 | 0 | 0.0% | 1 | 1237 | 1253 |
| 0.90 | 49 | 23 | 46.9% | 0 | 0 | 0.0% | 3 | 1414 | 1440 |
| 0.92 | 49 | 33 | 67.3% | 0 | 0 | 0.0% | 5 | 1614 | 1652 |
| 0.94 | 49 | 42 | 85.7% | 0 | 0 | 0.0% | 5 | 1769 | 1816 |

## Drop Semantics Summary

Under **drop** semantics, actioned rows are removed from the returned match list.

At threshold **0.8**:
- TPs dropped: 0 / 49 (0.0%)
- KNs dropped: 0 / 0 (0.0%)
- Partial dropped: 0
- Unlabeled dropped: 561

### Demote Semantics Warning

Demotion lowers confidence to 0.49 and routes matches to calibration-only visibility.
Under **demote** semantics, actioned rows **remain in artifacts** but leave the normal review queue.

**IMPORTANT**: If the evaluator (`truth_eval`) still counts calibration-only / demoted rows
as hits at threshold=0.0, `expected_negative_hit_count` may not improve under demote semantics.

The row-level impact shown above reflects review-visible impact only.

To guarantee a reduction in `expected_negative_hit_count`, use **drop** semantics instead.

---
*Schema: `dupe_engine_reranker_sim_v0_10_9`*
