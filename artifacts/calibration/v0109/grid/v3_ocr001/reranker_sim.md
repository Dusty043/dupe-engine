# v0.10.9 Reranker Offline Simulation

Source: `/srv/apps/dupe-engine/dupe-engine-repo/artifacts/calibration/v0108/v3_candidate_summary.csv`

## Parameters

- action: **demote**
- min_confidence (default threshold): **0.88**
- ocr_penalty: 0.01
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
- TP actioned: 2/33 (6.1%)
- KN actioned: 18/54 (33.3%)
- Estimated review rows removed: 1122

## Threshold Sweep

| Threshold | TP total | TP actioned | TP action% | KN total | KN actioned | KN action% | Partial actioned | Unlabeled actioned | Est. removed |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 0.76 | 33 | 0 | 0.0% | 54 | 3 | 5.6% | 0 | 337 | 340 |
| 0.78 | 33 | 1 | 3.0% | 54 | 5 | 9.3% | 0 | 463 | 469 |
| 0.80 | 33 | 1 | 3.0% | 54 | 9 | 16.7% | 0 | 627 | 637 |
| 0.82 | 33 | 2 | 6.1% | 54 | 13 | 24.1% | 0 | 833 | 848 |
| 0.84 ◀ | 33 | 2 | 6.1% | 54 | 18 | 33.3% | 0 | 1102 | 1122 |
| 0.86 | 33 | 4 | 12.1% | 54 | 25 | 46.3% | 1 | 1379 | 1409 |
| 0.88 | 33 | 4 | 12.1% | 54 | 30 | 55.6% | 1 | 1683 | 1718 |
| 0.90 | 33 | 7 | 21.2% | 54 | 41 | 75.9% | 1 | 2138 | 2187 |
| 0.92 | 33 | 9 | 27.3% | 54 | 50 | 92.6% | 1 | 2626 | 2686 |
| 0.94 | 33 | 12 | 36.4% | 54 | 52 | 96.3% | 2 | 3047 | 3113 |

## Drop Semantics Summary

Under **drop** semantics, actioned rows are removed from the returned match list.

At threshold **0.84**:
- TPs dropped: 2 / 33 (6.1%)
- KNs dropped: 18 / 54 (33.3%)
- Partial dropped: 0
- Unlabeled dropped: 1102

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
| source_B_email_attachment/intake_batch_002.pdf | 1 | source_A_client_upload/intake_batch_001.pdf | 18 | 0.7988 | 0.8188 | False | False | True | False |
| source_A_client_upload/intake_batch_002.pdf | 13 | source_F_fax_batch/intake_batch_003.pdf | 6 | 0.7581 | 0.7681 | False | True | True | False |

## Actioned KN Examples (would be affected at recommended threshold)

| a_document | a_page | b_document | b_page | confidence | precision_score | a_ocr | b_ocr | a_tess | same_doc |
|---|---:|---|---:|---:|---:|---:|---:|---:|---:|
| source_B_email_attachment/intake_batch_001.pdf | 11 | source_C_scanned_mail/intake_batch_004.pdf | 12 | 0.8513 | 0.8313 | True | True | False | False |
| source_C_scanned_mail/intake_batch_005.pdf | 2 | source_C_scanned_mail/intake_batch_002.pdf | 12 | 0.8465 | 0.8265 | True | True | False | False |
| source_D_legacy_export/intake_batch_003.pdf | 15 | source_C_scanned_mail/intake_batch_004.pdf | 9 | 0.8451 | 0.8251 | True | True | False | False |
| source_D_legacy_export/intake_batch_004.pdf | 10 | source_D_legacy_export/intake_batch_003.pdf | 15 | 0.8379 | 0.8179 | True | True | False | False |
| source_E_manual_rescan/intake_batch_003.pdf | 10 | source_D_legacy_export/intake_batch_004.pdf | 10 | 0.8312 | 0.8112 | True | True | False | False |
| source_F_fax_batch/intake_batch_006.pdf | 3 | source_E_manual_rescan/intake_batch_004.pdf | 18 | 0.8262 | 0.8062 | True | True | False | False |
| source_F_fax_batch/intake_batch_006.pdf | 3 | source_B_email_attachment/intake_batch_005.pdf | 14 | 0.8244 | 0.8344 | True | False | False | False |
| source_D_legacy_export/intake_batch_002.pdf | 8 | source_D_legacy_export/intake_batch_001.pdf | 2 | 0.8238 | 0.8338 | True | False | False | False |
| source_C_scanned_mail/intake_batch_005.pdf | 15 | source_D_legacy_export/intake_batch_003.pdf | 4 | 0.8075 | 0.7875 | True | True | False | False |
| source_E_manual_rescan/intake_batch_003.pdf | 10 | source_E_manual_rescan/intake_batch_004.pdf | 18 | 0.8013 | 0.7813 | True | True | False | False |

---
*Schema: `dupe_engine_reranker_sim_v0_10_9`*
