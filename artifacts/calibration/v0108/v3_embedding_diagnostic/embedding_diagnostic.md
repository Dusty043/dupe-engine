# v0.10.9 Pure Embedding Candidate Diagnostic

Source: `/Users/oreo/code-work/dupe check/dupe-engine-v0108/artifacts/calibration/v0108/v3_candidate_summary.csv`

## Cohort Overview

- Total rows in candidate_summary.csv: **9344**
- Pure embedding rows (candidate_category=semantic_recall): **3669**
- Other candidates: **5675**

| Group | Count |
|---|---:|
| TP (truth_label=duplicate) | **33** |
| KN (truth_label=not_duplicate) | **54** |
| Partial overlap | 4 |
| Unlabeled | 3578 |

### Match Type Breakdown (pure embedding cohort)

- `embedding_similarity_candidate`: 3669

### Stage Breakdown (pure embedding cohort)

- `vector_recall`: 3669

## Feature Comparison: TP vs KN

> Native / Tesseract / OpenAI word counts are not written to candidate_summary.csv.
> Only best_word_count (the selected final word count) is available here.

### Numeric Features

| Feature | TP n | TP min | TP median | TP mean | TP max | KN n | KN min | KN median | KN mean | KN max |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `embedding_confidence` | 33 | 0.7581 | 0.9168 | 0.9021 | 0.9400 | 54 | 0.6929 | 0.8653 | 0.8519 | 0.9309 |
| `a_best_word_count` | 33 | 31.0000 | 42.0000 | 45.8182 | 93.0000 | 54 | 27.0000 | 63.5000 | 58.4074 | 107.0000 |
| `b_best_word_count` | 33 | 31.0000 | 51.0000 | 52.6364 | 104.0000 | 54 | 31.0000 | 47.0000 | 52.3333 | 89.0000 |
| `min_word_count` | 33 | 31.0000 | 38.0000 | 39.9394 | 63.0000 | 54 | 27.0000 | 41.0000 | 46.9630 | 87.0000 |
| `combined_word_count` | 33 | 66.0000 | 101.0000 | 98.4545 | 155.0000 | 54 | 61.0000 | 104.5000 | 110.7407 | 180.0000 |

### Boolean / Evidence Features

| Feature | TP rate | TP count | KN rate | KN count | Separation |
|---|---:|---:|---:|---:|---:|
| `has_supporting_evidence` | 0.0000 | 0/33 | 0.0000 | 0/54 | 0.0000 |
| `has_det_pass_matched` | 0.0000 | 0/33 | 0.0000 | 0/54 | 0.0000 |
| `has_non_embedding_signal` | 0.0000 | 0/33 | 0.0000 | 0/54 | 0.0000 |
| `has_key_token_signal` | 0.0000 | 0/33 | 0.0000 | 0/54 | 0.0000 |
| `has_rare_token_signal` | 0.0000 | 0/33 | 0.0000 | 0/54 | 0.0000 |
| `has_perceptual_support` | 0.0000 | 0/33 | 0.0000 | 0/54 | 0.0000 |
| `has_sequence_signal` | 0.0000 | 0/33 | 0.0000 | 0/54 | 0.0000 |
| `same_document` | 0.3636 | 12/33 | 0.0370 | 2/54 | 0.3266 |
| `a_tesseract_attempted` | 0.7879 | 26/33 | 0.9074 | 49/54 | 0.0000 |
| `b_tesseract_attempted` | 0.9394 | 31/33 | 0.9630 | 52/54 | 0.0000 |
| `a_tesseract_usable` | 0.6364 | 21/33 | 0.3148 | 17/54 | 0.0000 |
| `b_tesseract_usable` | 0.6364 | 21/33 | 0.4815 | 26/54 | 0.0000 |
| `a_openai_ocr_selected` | 0.1515 | 5/33 | 0.5926 | 32/54 | 0.0000 |
| `b_openai_ocr_selected` | 0.3030 | 10/33 | 0.4815 | 26/54 | 0.0000 |
| `a_low_information` | 0.0000 | 0/33 | 0.0000 | 0/54 | 0.0000 |
| `b_low_information` | 0.0000 | 0/33 | 0.0000 | 0/54 | 0.0000 |

### Categorical: Review Bucket

| Bucket | TP | KN |
|---|---:|---:|
| `possible_duplicate` | 33 | 54 |

### Categorical: Text Source

#### a_text_source

| Source | TP | KN |
|---|---:|---:|
| `native` | 7 | 5 |
| `ocr` | 26 | 49 |

#### b_text_source

| Source | TP | KN |
|---|---:|---:|
| `native` | 2 | 4 |
| `ocr` | 31 | 50 |

## Signal Analysis

| Signal | TP presence | TP mean score | KN presence | KN mean score | Separation |
|---|---:|---:|---:|---:|---:|
| `embedding_similarity` | 1.0000 | 0.9066 | 1.0000 | 0.8519 | 1.0718 |

## Separating Features (ranked by |TP - KN|)

| Rank | Feature | Separation | TP value | KN value |
|---:|---|---:|---:|---:|
| 1 | `signal:embedding_similarity` | 1.0718 | 0.9066 | 0.8519 |
| 2 | `embedding_confidence` | 1.0242 | 0.9021 | 0.8519 |
| 3 | `a_best_word_count` | 0.7414 | 45.8182 | 58.4074 |
| 4 | `min_word_count` | 0.5450 | 39.9394 | 46.9630 |
| 5 | `combined_word_count` | 0.4680 | 98.4545 | 110.7407 |
| 6 | `same_document` | 0.3266 | 0.3636 | 0.0370 |
| 7 | `b_best_word_count` | 0.0169 | 52.6364 | 52.3333 |
| 8 | `has_key_token_signal` | 0.0000 | 0.0000 | 0.0000 |
| 9 | `has_rare_token_signal` | 0.0000 | 0.0000 | 0.0000 |
| 10 | `has_perceptual_support` | 0.0000 | 0.0000 | 0.0000 |
| 11 | `has_sequence_signal` | 0.0000 | 0.0000 | 0.0000 |
| 12 | `has_non_embedding_signal` | 0.0000 | 0.0000 | 0.0000 |
| 13 | `has_det_pass_matched` | 0.0000 | 0.0000 | 0.0000 |
| 14 | `has_supporting_evidence` | 0.0000 | 0.0000 | 0.0000 |
| 15 | `a_tesseract_attempted` | 0.0000 | 0.7879 | 0.9074 |
| 16 | `b_tesseract_attempted` | 0.0000 | 0.9394 | 0.9630 |
| 17 | `a_tesseract_usable` | 0.0000 | 0.6364 | 0.3148 |
| 18 | `b_tesseract_usable` | 0.0000 | 0.6364 | 0.4815 |
| 19 | `a_openai_ocr_selected` | 0.0000 | 0.1515 | 0.5926 |
| 20 | `b_openai_ocr_selected` | 0.0000 | 0.3030 | 0.4815 |

---
*Schema: `dupe_engine_embedding_diagnostic_v0_10_9`*
