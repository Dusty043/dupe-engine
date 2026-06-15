# v0.10.9 Reranker Offline Simulation

Source: `/Users/oreo/code-work/dupe check/dupe-engine-v0108/artifacts/calibration/v0108/v3_candidate_summary.csv`

## Parameters

- action: **demote**
- min_confidence (default threshold): **0.88**
- ocr_penalty: 0.05
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

- Recommended threshold: **0.8**
- Action: **demote**
- TP actioned: 1/33 (3.0%)
- KN actioned: 23/54 (42.6%)
- Estimated review rows removed: 1103

## Threshold Sweep

| Threshold | TP total | TP actioned | TP action% | KN total | KN actioned | KN action% | Partial actioned | Unlabeled actioned | Est. removed |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 0.80 ◀ | 33 | 1 | 3.0% | 54 | 23 | 42.6% | 1 | 1078 | 1103 |
| 0.82 | 33 | 4 | 12.1% | 54 | 30 | 55.6% | 1 | 1342 | 1377 |
| 0.84 | 33 | 4 | 12.1% | 54 | 31 | 57.4% | 1 | 1634 | 1670 |
| 0.86 | 33 | 5 | 15.2% | 54 | 37 | 68.5% | 2 | 1905 | 1949 |
| 0.88 | 33 | 7 | 21.2% | 54 | 43 | 79.6% | 2 | 2174 | 2226 |
| 0.90 | 33 | 10 | 30.3% | 54 | 48 | 88.9% | 2 | 2533 | 2593 |
| 0.92 | 33 | 16 | 48.5% | 54 | 51 | 94.4% | 2 | 2853 | 2922 |
| 0.94 | 33 | 19 | 57.6% | 54 | 52 | 96.3% | 2 | 3124 | 3197 |

## Drop Semantics Summary

Under **drop** semantics, actioned rows are removed from the returned match list.

At threshold **0.8**:
- TPs dropped: 1 / 33 (3.0%)
- KNs dropped: 23 / 54 (42.6%)
- Partial dropped: 1
- Unlabeled dropped: 1078

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
| source_A_client_upload/intake_batch_002.pdf | 13 | source_F_fax_batch/intake_batch_003.pdf | 6 | 0.7581 | 0.7281 | False | True | True | False |

## Actioned KN Examples (would be affected at recommended threshold)

| a_document | a_page | b_document | b_page | confidence | precision_score | a_ocr | b_ocr | a_tess | same_doc |
|---|---:|---|---:|---:|---:|---:|---:|---:|---:|
| source_C_scanned_mail/intake_batch_002.pdf | 17 | source_D_legacy_export/intake_batch_003.pdf | 14 | 0.8989 | 0.7989 | True | True | False | False |
| source_D_legacy_export/intake_batch_004.pdf | 12 | source_C_scanned_mail/intake_batch_002.pdf | 2 | 0.8938 | 0.7938 | True | True | False | False |
| source_A_client_upload/intake_batch_003.pdf | 17 | source_C_scanned_mail/intake_batch_005.pdf | 5 | 0.8931 | 0.7931 | True | True | False | False |
| source_A_client_upload/intake_batch_001.pdf | 16 | source_D_legacy_export/intake_batch_001.pdf | 18 | 0.8856 | 0.7856 | True | True | False | False |
| source_A_client_upload/intake_batch_005.pdf | 5 | source_A_client_upload/intake_batch_003.pdf | 14 | 0.8793 | 0.7793 | True | True | False | False |
| source_F_fax_batch/intake_batch_006.pdf | 3 | source_D_legacy_export/intake_batch_003.pdf | 15 | 0.8682 | 0.7682 | True | True | False | False |
| source_B_email_attachment/intake_batch_001.pdf | 11 | source_C_scanned_mail/intake_batch_004.pdf | 12 | 0.8513 | 0.7513 | True | True | False | False |
| source_C_scanned_mail/intake_batch_005.pdf | 2 | source_C_scanned_mail/intake_batch_002.pdf | 12 | 0.8465 | 0.7465 | True | True | False | False |
| source_D_legacy_export/intake_batch_003.pdf | 15 | source_C_scanned_mail/intake_batch_004.pdf | 9 | 0.8451 | 0.7451 | True | True | False | False |
| source_D_legacy_export/intake_batch_004.pdf | 10 | source_D_legacy_export/intake_batch_003.pdf | 15 | 0.8379 | 0.7379 | True | True | False | False |

---
*Schema: `dupe_engine_reranker_sim_v0_10_9`*
