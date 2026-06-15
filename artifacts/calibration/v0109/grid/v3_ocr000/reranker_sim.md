# v0.10.9 Reranker Offline Simulation

Source: `/srv/apps/dupe-engine/dupe-engine-repo/artifacts/calibration/v0108/v3_candidate_summary.csv`

## Parameters

- action: **demote**
- min_confidence (default threshold): **0.88**
- ocr_penalty: 0.0
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

- Recommended threshold: **0.86**
- Action: **demote**
- TP actioned: 3/33 (9.1%)
- KN actioned: 20/54 (37.0%)
- Estimated review rows removed: 1276

## Threshold Sweep

| Threshold | TP total | TP actioned | TP action% | KN total | KN actioned | KN action% | Partial actioned | Unlabeled actioned | Est. removed |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 0.76 | 33 | 0 | 0.0% | 54 | 2 | 3.7% | 0 | 289 | 291 |
| 0.78 | 33 | 1 | 3.0% | 54 | 3 | 5.6% | 0 | 400 | 404 |
| 0.80 | 33 | 1 | 3.0% | 54 | 6 | 11.1% | 0 | 554 | 561 |
| 0.82 | 33 | 2 | 6.1% | 54 | 10 | 18.5% | 0 | 736 | 748 |
| 0.84 | 33 | 2 | 6.1% | 54 | 13 | 24.1% | 0 | 973 | 988 |
| 0.86 ◀ | 33 | 3 | 9.1% | 54 | 20 | 37.0% | 0 | 1253 | 1276 |
| 0.88 | 33 | 4 | 12.1% | 54 | 26 | 48.1% | 1 | 1575 | 1606 |
| 0.90 | 33 | 7 | 21.2% | 54 | 36 | 66.7% | 1 | 2002 | 2046 |
| 0.92 | 33 | 8 | 24.2% | 54 | 49 | 90.7% | 1 | 2463 | 2521 |
| 0.94 | 33 | 12 | 36.4% | 54 | 51 | 94.4% | 1 | 2942 | 3006 |

## Drop Semantics Summary

Under **drop** semantics, actioned rows are removed from the returned match list.

At threshold **0.86**:
- TPs dropped: 3 / 33 (9.1%)
- KNs dropped: 20 / 54 (37.0%)
- Partial dropped: 0
- Unlabeled dropped: 1253

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
| source_E_manual_rescan/intake_batch_002.pdf | 16 | source_F_fax_batch/intake_batch_003.pdf | 15 | 0.8515 | 0.8515 | False | True | False | False |
| source_B_email_attachment/intake_batch_002.pdf | 1 | source_A_client_upload/intake_batch_001.pdf | 18 | 0.7988 | 0.8188 | False | False | True | False |
| source_A_client_upload/intake_batch_002.pdf | 13 | source_F_fax_batch/intake_batch_003.pdf | 6 | 0.7581 | 0.7781 | False | True | True | False |

## Actioned KN Examples (would be affected at recommended threshold)

| a_document | a_page | b_document | b_page | confidence | precision_score | a_ocr | b_ocr | a_tess | same_doc |
|---|---:|---|---:|---:|---:|---:|---:|---:|---:|
| source_B_email_attachment/intake_batch_001.pdf | 11 | source_C_scanned_mail/intake_batch_004.pdf | 12 | 0.8513 | 0.8513 | True | True | False | False |
| source_C_scanned_mail/intake_batch_005.pdf | 2 | source_C_scanned_mail/intake_batch_002.pdf | 12 | 0.8465 | 0.8465 | True | True | False | False |
| source_D_legacy_export/intake_batch_003.pdf | 15 | source_C_scanned_mail/intake_batch_004.pdf | 9 | 0.8451 | 0.8451 | True | True | False | False |
| source_D_legacy_export/intake_batch_004.pdf | 10 | source_D_legacy_export/intake_batch_003.pdf | 15 | 0.8379 | 0.8379 | True | True | False | False |
| source_E_manual_rescan/intake_batch_003.pdf | 10 | source_D_legacy_export/intake_batch_004.pdf | 10 | 0.8312 | 0.8312 | True | True | False | False |
| source_F_fax_batch/intake_batch_006.pdf | 3 | source_E_manual_rescan/intake_batch_004.pdf | 18 | 0.8262 | 0.8262 | True | True | False | False |
| source_F_fax_batch/intake_batch_006.pdf | 3 | source_B_email_attachment/intake_batch_005.pdf | 14 | 0.8244 | 0.8444 | True | False | False | False |
| source_D_legacy_export/intake_batch_002.pdf | 8 | source_D_legacy_export/intake_batch_001.pdf | 2 | 0.8238 | 0.8438 | True | False | False | False |
| source_B_email_attachment/intake_batch_003.pdf | 5 | source_C_scanned_mail/intake_batch_003.pdf | 11 | 0.8080 | 0.8480 | False | False | True | False |
| source_C_scanned_mail/intake_batch_005.pdf | 15 | source_D_legacy_export/intake_batch_003.pdf | 4 | 0.8075 | 0.8075 | True | True | False | False |

---
*Schema: `dupe_engine_reranker_sim_v0_10_9`*
