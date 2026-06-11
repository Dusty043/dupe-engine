# Dupe Engine v0.10.1 Handoff

v0.10.1 focuses on source-safe evidence and candidate formation. It does not add another OCR phase or adjudicator step.

## Why

Recent rescue runs showed that the engine often had OCR or visual evidence available but failed to turn that evidence into candidate pairs. v0.10.1 therefore keeps extraction stable and improves how candidate generation consumes existing evidence.

The goal is to address cases where pages are OCR-ready but not candidate-generated.

## Main changes

1. OpenAI OCR is source-safe by default.
   - Accepted OpenAI OCR is retained as sidecar evidence.
   - It no longer replaces canonical `best_text` / `comparison_text` when `source_safe_ocr_merge_enabled` is enabled.
   - Native and Tesseract text remain primary evidence when they are already strong.

2. Text candidate generation is multi-view.
   - The deterministic matcher now considers `primary_text`, `native_text`, `tesseract_text`, `openai_ocr_text`, and `combined_text` views.
   - Source-side exact text hashes are also considered.
   - Key-token overlap can generate bounded source-safe candidates without persisting additional raw text views.

3. Sequence-neighbor candidates are promoted deterministically.
   - Strong anchor matches can promote adjacent page pairs within a bounded window.
   - Promotion requires source-view text overlap and can use visual support to lower the text threshold.

4. Visual candidate expansion is still bounded.
   - Visual loose candidates remain restricted.
   - OCR-weak pages can now enter the bounded visual pass without enabling full visual all-pairs.

5. Diagnostics now expose candidate-formation misses.
   - OCR validation reports include `ocr_ready_but_not_candidate_generated_count`.
   - Missed rows are listed in `ocr_ready_missed_candidate_rows` when truth pairs are supplied.
   - Fallback audit distinguishes OpenAI OCR sidecar evidence from canonical text replacement.

## Key config defaults

```text
source_safe_ocr_merge_enabled = true
multiview_text_candidates_enabled = true
multiview_key_token_candidates_enabled = true
bounded_visual_ocr_weak_enabled = true
sequence_candidate_promotion_enabled = true
sequence_neighbor_window = 1
sequence_anchor_min_confidence = 0.86
sequence_min_text_similarity = 0.42
sequence_min_text_similarity_with_visual = 0.25
sequence_visual_support_phash_threshold = 24
```

## Useful CLI switches

```bash
--disable-source-safe-ocr-merge
--disable-multiview-text-candidates
--disable-multiview-key-token-candidates
--disable-bounded-visual-ocr-weak
--disable-sequence-candidates
--sequence-anchor-min-confidence 0.86
--sequence-neighbor-window 1
--sequence-min-text-similarity 0.42
--sequence-min-text-similarity-with-visual 0.25
--sequence-visual-support-phash-threshold 24
```

## Recommended tests

Run v3 and v4 with the default v0.10.1 settings first. Then isolate sequence promotion only if needed.

```bash
PYTHONPATH=src python -m dupe_engine.cli eval-all \
  ./examples/synthetic_v3/medium_calibration \
  --truth ./examples/synthetic_v3/medium_calibration/synthetic_v3_truth_pairs.json \
  --out ./output/v0101_v3/results.json \
  --ocr-validation-out ./output/v0101_v3/ocr_validation.json \
  --fallback-audit-out ./output/v0101_v3/fallback_audit.json
```

For ablation:

```bash
--disable-sequence-candidates
--disable-multiview-key-token-candidates
--disable-multiview-text-candidates
```

## Regression status

```text
PYTHONPATH=src pytest -q
98 passed
```

## Notes

This version deliberately avoids adjudication. The expected benefit is better candidate formation before any LLM labeling layer is added.
