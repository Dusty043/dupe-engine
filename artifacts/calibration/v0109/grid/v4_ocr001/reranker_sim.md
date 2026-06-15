# v0.10.9 Reranker Offline Simulation

Source: `/srv/apps/dupe-engine/dupe-engine-repo/artifacts/calibration/v0108/v4_candidate_summary.csv`

## Parameters

- action: **demote**
- min_confidence (default threshold): **0.88**
- ocr_penalty: 0.01
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

- Recommended threshold: **0.78**
- Action: **demote**
- TP actioned: 0/49 (0.0%)
- KN actioned: 0/0 (0.0%)
- Estimated review rows removed: 502

## Threshold Sweep

| Threshold | TP total | TP actioned | TP action% | KN total | KN actioned | KN action% | Partial actioned | Unlabeled actioned | Est. removed |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 0.76 | 49 | 0 | 0.0% | 0 | 0 | 0.0% | 0 | 369 | 369 |
| 0.78 ◀ | 49 | 0 | 0.0% | 0 | 0 | 0.0% | 0 | 502 | 502 |
| 0.80 | 49 | 1 | 2.0% | 0 | 0 | 0.0% | 0 | 625 | 626 |
| 0.82 | 49 | 3 | 6.1% | 0 | 0 | 0.0% | 0 | 775 | 778 |
| 0.84 | 49 | 7 | 14.3% | 0 | 0 | 0.0% | 0 | 917 | 924 |
| 0.86 | 49 | 12 | 24.5% | 0 | 0 | 0.0% | 0 | 1087 | 1099 |
| 0.88 | 49 | 19 | 38.8% | 0 | 0 | 0.0% | 2 | 1285 | 1306 |
| 0.90 | 49 | 25 | 51.0% | 0 | 0 | 0.0% | 4 | 1445 | 1474 |
| 0.92 | 49 | 39 | 79.6% | 0 | 0 | 0.0% | 5 | 1620 | 1664 |
| 0.94 | 49 | 42 | 85.7% | 0 | 0 | 0.0% | 9 | 1778 | 1829 |

## Drop Semantics Summary

Under **drop** semantics, actioned rows are removed from the returned match list.

At threshold **0.78**:
- TPs dropped: 0 / 49 (0.0%)
- KNs dropped: 0 / 0 (0.0%)
- Partial dropped: 0
- Unlabeled dropped: 502

### Demote Semantics Warning

Demotion lowers confidence to 0.49 and routes matches to calibration-only visibility.
Under **demote** semantics, actioned rows **remain in artifacts** but leave the normal review queue.

**IMPORTANT**: If the evaluator (`truth_eval`) still counts calibration-only / demoted rows
as hits at threshold=0.0, `expected_negative_hit_count` may not improve under demote semantics.

The row-level impact shown above reflects review-visible impact only.

To guarantee a reduction in `expected_negative_hit_count`, use **drop** semantics instead.

---
*Schema: `dupe_engine_reranker_sim_v0_10_9`*
