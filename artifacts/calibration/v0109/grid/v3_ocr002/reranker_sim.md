# v0.10.9 Reranker Offline Simulation

Source: `/srv/apps/dupe-engine/dupe-engine-repo/artifacts/calibration/v0108/v3_candidate_summary.csv`

## Parameters

- action: **demote**
- min_confidence (default threshold): **0.88**
- ocr_penalty: 0.02
- same_doc_bonus: 0.03
- tesseract_bonus: 0.02

## Cohort Overview

- Total rows in candidate_summary.csv: **9344**
- Pure embedding rows (match_type=embedding_similarity_candidate): **3669**
- Non-pure rows (untouched by reranker): **5675**

| Group | Count |
|---|---:|
| TP (truth_label=duplicate) | **33** |
| KN (truth_label=not_duplicate) | **54** |
| Partial overlap | 4 |
| Unlabeled | 3578 |

## Recommendation

- Recommended threshold: **0.84**
- Action: **demote**
- TP actioned: 3/33 (9.1%)
- KN actioned: 20/54 (37.0%)
- Estimated review rows removed: 1251

## Threshold Sweep

| Threshold | TP total | TP actioned | TP action% | KN total | KN actioned | KN action% | Partial actioned | Unlabeled actioned | Est. removed |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 0.76 | 33 | 1 | 3.0% | 54 | 5 | 9.3% | 0 | 384 | 390 |
| 0.78 | 33 | 1 | 3.0% | 54 | 7 | 13.0% | 0 | 537 | 545 |
| 0.80 | 33 | 1 | 3.0% | 54 | 12 | 22.2% | 0 | 726 | 739 |
| 0.82 | 33 | 2 | 6.1% | 54 | 16 | 29.6% | 0 | 960 | 978 |
| 0.84 ◀ | 33 | 3 | 9.1% | 54 | 20 | 37.0% | 1 | 1227 | 1251 |
| 0.86 | 33 | 4 | 12.1% | 54 | 30 | 55.6% | 1 | 1489 | 1524 |
| 0.88 | 33 | 5 | 15.2% | 54 | 35 | 64.8% | 1 | 1808 | 1849 |
| 0.90 | 33 | 7 | 21.2% | 54 | 46 | 85.2% | 1 | 2297 | 2351 |
| 0.92 | 33 | 10 | 30.3% | 54 | 50 | 92.6% | 2 | 2737 | 2799 |
| 0.94 | 33 | 13 | 39.4% | 54 | 52 | 96.3% | 2 | 3098 | 3165 |

## Drop Semantics Summary

Under **drop** semantics, actioned rows are removed from the returned match list.

At threshold **0.84**:
- TPs dropped: 3 / 33 (9.1%)
- KNs dropped: 20 / 54 (37.0%)
- Partial dropped: 1
- Unlabeled dropped: 1227

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
| source_E_manual_rescan/intake_batch_002.pdf | 16 | source_F_fax_batch/intake_batch_003.pdf | 15 | 0.8515 | 0.8315 | False | True | False | False |
| source_B_email_attachment/intake_batch_002.pdf | 1 | source_A_client_upload/intake_batch_001.pdf | 18 | 0.7988 | 0.8188 | False | False | True | False |
| source_A_client_upload/intake_batch_002.pdf | 13 | source_F_fax_batch/intake_batch_003.pdf | 6 | 0.7581 | 0.7581 | False | True | True | False |

## Actioned KN Examples (would be affected at recommended threshold)

| a_document | a_page | b_document | b_page | confidence | precision_score | a_ocr | b_ocr | a_tess | same_doc |
|---|---:|---|---:|---:|---:|---:|---:|---:|---:|
| source_A_client_upload/intake_batch_005.pdf | 5 | source_A_client_upload/intake_batch_003.pdf | 14 | 0.8793 | 0.8393 | True | True | False | False |
| source_F_fax_batch/intake_batch_006.pdf | 3 | source_D_legacy_export/intake_batch_003.pdf | 15 | 0.8682 | 0.8282 | True | True | False | False |
| source_B_email_attachment/intake_batch_001.pdf | 11 | source_C_scanned_mail/intake_batch_004.pdf | 12 | 0.8513 | 0.8113 | True | True | False | False |
| source_C_scanned_mail/intake_batch_005.pdf | 2 | source_C_scanned_mail/intake_batch_002.pdf | 12 | 0.8465 | 0.8065 | True | True | False | False |
| source_D_legacy_export/intake_batch_003.pdf | 15 | source_C_scanned_mail/intake_batch_004.pdf | 9 | 0.8451 | 0.8051 | True | True | False | False |
| source_D_legacy_export/intake_batch_004.pdf | 10 | source_D_legacy_export/intake_batch_003.pdf | 15 | 0.8379 | 0.7979 | True | True | False | False |
| source_E_manual_rescan/intake_batch_003.pdf | 10 | source_D_legacy_export/intake_batch_004.pdf | 10 | 0.8312 | 0.7912 | True | True | False | False |
| source_F_fax_batch/intake_batch_006.pdf | 3 | source_E_manual_rescan/intake_batch_004.pdf | 18 | 0.8262 | 0.7862 | True | True | False | False |
| source_F_fax_batch/intake_batch_006.pdf | 3 | source_B_email_attachment/intake_batch_005.pdf | 14 | 0.8244 | 0.8244 | True | False | False | False |
| source_D_legacy_export/intake_batch_002.pdf | 8 | source_D_legacy_export/intake_batch_001.pdf | 2 | 0.8238 | 0.8238 | True | False | False | False |

---
*Schema: `dupe_engine_reranker_sim_v0_10_9`*
