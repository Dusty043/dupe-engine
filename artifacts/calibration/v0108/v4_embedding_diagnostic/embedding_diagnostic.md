# v0.10.9 Pure Embedding Candidate Diagnostic

Source: `/Users/oreo/code-work/dupe check/dupe-engine-v0108/artifacts/calibration/v0108/v4_candidate_summary.csv`

## Cohort Overview

- Total rows in candidate_summary.csv: **8104**
- Pure embedding rows (candidate_category=semantic_recall): **2141**
- Other candidates: **5963**

| Group | Count |
|---|---:|
| TP (truth_label=duplicate) | **49** |
| KN (truth_label=not_duplicate) | **0** |
| Partial overlap | 12 |
| Unlabeled | 2080 |

### Match Type Breakdown (pure embedding cohort)

- `embedding_similarity_candidate`: 2141

### Stage Breakdown (pure embedding cohort)

- `vector_recall`: 2141

## Feature Comparison: TP vs KN

> Native / Tesseract / OpenAI word counts are not written to candidate_summary.csv.
> Only best_word_count (the selected final word count) is available here.

### Numeric Features

| Feature | TP n | TP min | TP median | TP mean | TP max | KN n | KN min | KN median | KN mean | KN max |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `embedding_confidence` | 49 | 0.7801 | 0.8776 | 0.8774 | 0.9400 | 0 | n/a | n/a | n/a | n/a |
| `a_best_word_count` | 49 | 27.0000 | 54.0000 | 56.9388 | 93.0000 | 0 | n/a | n/a | n/a | n/a |
| `b_best_word_count` | 49 | 31.0000 | 42.0000 | 47.9184 | 84.0000 | 0 | n/a | n/a | n/a | n/a |
| `min_word_count` | 49 | 27.0000 | 41.0000 | 43.2857 | 83.0000 | 0 | n/a | n/a | n/a | n/a |
| `combined_word_count` | 49 | 64.0000 | 102.0000 | 104.8571 | 167.0000 | 0 | n/a | n/a | n/a | n/a |

### Boolean / Evidence Features

| Feature | TP rate | TP count | KN rate | KN count | Separation |
|---|---:|---:|---:|---:|---:|
| `has_supporting_evidence` | 0.0000 | 0/49 | n/a | 0/0 | n/a |
| `has_det_pass_matched` | 0.0000 | 0/49 | n/a | 0/0 | n/a |
| `has_non_embedding_signal` | 0.0000 | 0/49 | n/a | 0/0 | n/a |
| `has_key_token_signal` | 0.0000 | 0/49 | n/a | 0/0 | n/a |
| `has_rare_token_signal` | 0.0000 | 0/49 | n/a | 0/0 | n/a |
| `has_perceptual_support` | 0.0000 | 0/49 | n/a | 0/0 | n/a |
| `has_sequence_signal` | 0.0000 | 0/49 | n/a | 0/0 | n/a |
| `same_document` | 0.0000 | 0/49 | n/a | 0/0 | n/a |
| `a_tesseract_attempted` | 0.9796 | 48/49 | n/a | 0/0 | n/a |
| `b_tesseract_attempted` | 0.8571 | 42/49 | n/a | 0/0 | n/a |
| `a_tesseract_usable` | 0.5510 | 27/49 | n/a | 0/0 | n/a |
| `b_tesseract_usable` | 0.5714 | 28/49 | n/a | 0/0 | n/a |
| `a_openai_ocr_selected` | 0.4286 | 21/49 | n/a | 0/0 | n/a |
| `b_openai_ocr_selected` | 0.2857 | 14/49 | n/a | 0/0 | n/a |
| `a_low_information` | 0.0000 | 0/49 | n/a | 0/0 | n/a |
| `b_low_information` | 0.0000 | 0/49 | n/a | 0/0 | n/a |

### Categorical: Review Bucket

| Bucket | TP | KN |
|---|---:|---:|
| `possible_duplicate` | 49 | 0 |

### Categorical: Text Source

#### a_text_source

| Source | TP | KN |
|---|---:|---:|
| `native` | 1 | 0 |
| `ocr` | 48 | 0 |

#### b_text_source

| Source | TP | KN |
|---|---:|---:|
| `native` | 19 | 0 |
| `ocr` | 30 | 0 |

## Signal Analysis

| Signal | TP presence | TP mean score | KN presence | KN mean score | Separation |
|---|---:|---:|---:|---:|---:|
| `embedding_similarity` | 1.0000 | 0.8779 | n/a | n/a | n/a |

## Separating Features (ranked by |TP - KN|)

| Rank | Feature | Separation | TP value | KN value |
|---:|---|---:|---:|---:|

---
*Schema: `dupe_engine_embedding_diagnostic_v0_10_9`*
