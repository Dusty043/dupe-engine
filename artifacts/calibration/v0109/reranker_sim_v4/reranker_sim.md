# v0.10.9 Reranker Offline Simulation

Source: `/Users/oreo/code-work/dupe check/dupe-engine-v0108/artifacts/calibration/v0108/v4_candidate_summary.csv`

## Parameters

- action: **demote**
- min_confidence (default threshold): **0.88**
- ocr_penalty: 0.05
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
- TP actioned: 7/49 (14.3%)
- KN actioned: 0/0 (0.0%)
- Estimated review rows removed: 881

## Threshold Sweep

| Threshold | TP total | TP actioned | TP action% | KN total | KN actioned | KN action% | Partial actioned | Unlabeled actioned | Est. removed |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 0.80 ◀ | 49 | 7 | 14.3% | 0 | 0 | 0.0% | 0 | 874 | 881 |
| 0.82 | 49 | 12 | 24.5% | 0 | 0 | 0.0% | 0 | 999 | 1011 |
| 0.84 | 49 | 21 | 42.9% | 0 | 0 | 0.0% | 2 | 1110 | 1133 |
| 0.86 | 49 | 24 | 49.0% | 0 | 0 | 0.0% | 7 | 1219 | 1250 |
| 0.88 | 49 | 31 | 63.3% | 0 | 0 | 0.0% | 8 | 1351 | 1390 |
| 0.90 | 49 | 33 | 67.3% | 0 | 0 | 0.0% | 9 | 1482 | 1524 |
| 0.92 | 49 | 40 | 81.6% | 0 | 0 | 0.0% | 9 | 1643 | 1692 |
| 0.94 | 49 | 43 | 87.8% | 0 | 0 | 0.0% | 9 | 1785 | 1837 |

## Drop Semantics Summary

Under **drop** semantics, actioned rows are removed from the returned match list.

At threshold **0.8**:
- TPs dropped: 7 / 49 (14.3%)
- KNs dropped: 0 / 0 (0.0%)
- Partial dropped: 0
- Unlabeled dropped: 874

### Demote Semantics Warning

Demotion lowers confidence to 0.49 and routes matches to calibration-only visibility.
Under **demote** semantics, actioned rows **remain in artifacts** but leave the normal review queue.

**IMPORTANT**: If the evaluator (`truth_eval`) still counts calibration-only / demoted rows
as hits at threshold=0.0, `expected_negative_hit_count` may not improve under demote semantics.

The row-level impact shown above reflects review-visible impact only.

To guarantee a reduction in `expected_negative_hit_count`, use **drop** semantics instead.

## Actioned TP Examples (would be affected at recommended threshold)

| a_document | a_page | b_document | b_page | confidence | precision_score | a_ocr | b_ocr | a_tess | same_doc |
|---|---:|---|---:|---:|---:|---:|---:|---:|---:|
| ere_records/ere_record_014.pdf | 2 | received_records/received_batch_019.pdf | 2 | 0.8776 | 0.7776 | True | True | False | False |
| ere_records/ere_record_024.pdf | 1 | ere_records/ere_record_014.pdf | 2 | 0.8542 | 0.7542 | True | True | False | False |
| ere_records/ere_record_027.pdf | 2 | received_records/received_batch_026.pdf | 3 | 0.8182 | 0.7882 | True | False | False | False |
| received_records/received_batch_001.pdf | 2 | received_records/received_batch_020.pdf | 1 | 0.8128 | 0.7628 | True | False | False | False |
| ere_records/ere_record_005.pdf | 1 | ere_records/ere_record_008.pdf | 2 | 0.8102 | 0.7802 | True | False | False | False |
| ere_records/ere_record_005.pdf | 2 | received_records/received_batch_029.pdf | 2 | 0.8026 | 0.7726 | True | False | False | False |
| ere_records/ere_record_026.pdf | 2 | ere_records/ere_record_022.pdf | 2 | 0.7801 | 0.7501 | True | False | False | False |

---
*Schema: `dupe_engine_reranker_sim_v0_10_9`*
