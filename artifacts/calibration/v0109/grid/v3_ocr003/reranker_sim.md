# v0.10.9 Reranker Offline Simulation

Source: `/srv/apps/dupe-engine/dupe-engine-repo/artifacts/calibration/v0108/v3_candidate_summary.csv`

## Parameters

- action: **demote**
- min_confidence (default threshold): **0.88**
- ocr_penalty: 0.03
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

- Recommended threshold: **0.82**
- Action: **demote**
- TP actioned: 2/33 (6.1%)
- KN actioned: 20/54 (37.0%)
- Estimated review rows removed: 1106

## Threshold Sweep

| Threshold | TP total | TP actioned | TP action% | KN total | KN actioned | KN action% | Partial actioned | Unlabeled actioned | Est. removed |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 0.76 | 33 | 1 | 3.0% | 54 | 7 | 13.0% | 0 | 457 | 465 |
| 0.78 | 33 | 1 | 3.0% | 54 | 11 | 20.4% | 0 | 619 | 631 |
| 0.80 | 33 | 1 | 3.0% | 54 | 15 | 27.8% | 0 | 837 | 853 |
| 0.82 ◀ | 33 | 2 | 6.1% | 54 | 20 | 37.0% | 1 | 1083 | 1106 |
| 0.84 | 33 | 4 | 12.1% | 54 | 27 | 50.0% | 1 | 1350 | 1382 |
| 0.86 | 33 | 4 | 12.1% | 54 | 33 | 61.1% | 1 | 1611 | 1649 |
| 0.88 | 33 | 5 | 15.2% | 54 | 37 | 68.5% | 1 | 1982 | 2025 |
| 0.90 | 33 | 8 | 24.2% | 54 | 47 | 87.0% | 2 | 2417 | 2474 |
| 0.92 | 33 | 11 | 33.3% | 54 | 51 | 94.4% | 2 | 2798 | 2862 |
| 0.94 | 33 | 18 | 54.5% | 54 | 52 | 96.3% | 2 | 3114 | 3186 |

## Drop Semantics Summary

Under **drop** semantics, actioned rows are removed from the returned match list.

At threshold **0.82**:
- TPs dropped: 2 / 33 (6.1%)
- KNs dropped: 20 / 54 (37.0%)
- Partial dropped: 1
- Unlabeled dropped: 1083

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
| source_A_client_upload/intake_batch_002.pdf | 13 | source_F_fax_batch/intake_batch_003.pdf | 6 | 0.7581 | 0.7481 | False | True | True | False |

## Actioned KN Examples (would be affected at recommended threshold)

| a_document | a_page | b_document | b_page | confidence | precision_score | a_ocr | b_ocr | a_tess | same_doc |
|---|---:|---|---:|---:|---:|---:|---:|---:|---:|
| source_A_client_upload/intake_batch_005.pdf | 5 | source_A_client_upload/intake_batch_003.pdf | 14 | 0.8793 | 0.8193 | True | True | False | False |
| source_F_fax_batch/intake_batch_006.pdf | 3 | source_D_legacy_export/intake_batch_003.pdf | 15 | 0.8682 | 0.8082 | True | True | False | False |
| source_B_email_attachment/intake_batch_001.pdf | 11 | source_C_scanned_mail/intake_batch_004.pdf | 12 | 0.8513 | 0.7913 | True | True | False | False |
| source_C_scanned_mail/intake_batch_005.pdf | 2 | source_C_scanned_mail/intake_batch_002.pdf | 12 | 0.8465 | 0.7865 | True | True | False | False |
| source_D_legacy_export/intake_batch_003.pdf | 15 | source_C_scanned_mail/intake_batch_004.pdf | 9 | 0.8451 | 0.7851 | True | True | False | False |
| source_D_legacy_export/intake_batch_004.pdf | 10 | source_D_legacy_export/intake_batch_003.pdf | 15 | 0.8379 | 0.7779 | True | True | False | False |
| source_E_manual_rescan/intake_batch_003.pdf | 10 | source_D_legacy_export/intake_batch_004.pdf | 10 | 0.8312 | 0.7712 | True | True | False | False |
| source_F_fax_batch/intake_batch_006.pdf | 3 | source_E_manual_rescan/intake_batch_004.pdf | 18 | 0.8262 | 0.7662 | True | True | False | False |
| source_F_fax_batch/intake_batch_006.pdf | 3 | source_B_email_attachment/intake_batch_005.pdf | 14 | 0.8244 | 0.8144 | True | False | False | False |
| source_D_legacy_export/intake_batch_002.pdf | 8 | source_D_legacy_export/intake_batch_001.pdf | 2 | 0.8238 | 0.8138 | True | False | False | False |

---
*Schema: `dupe_engine_reranker_sim_v0_10_9`*
