# v0.8 Handoff: OCR Validation Harness

## Summary

v0.8 adds an OCR validation harness on top of the v0.7.6 reviewer-aligned output contract.

This is still a human-review assist engine. v0.8 does not auto-remove duplicates and does not make OpenAI OCR mandatory. It makes OCR behavior measurable.

## Main additions

- New OCR validation JSON output:
  - `--ocr-validation-out`
- New OCR per-page route CSV:
  - `--ocr-route-csv`
- New OCR-relevant candidate CSV:
  - `--ocr-candidate-csv`
- OpenAI OCR dry-run now records selected pages and escalation reasons without calling the provider.
- Page records now include:
  - `openai_ocr_selected`
  - `openai_ocr_selection_reason`
  - `openai_ocr_skip_reason`
  - `openai_ocr_error`
- Capability report now includes detected Tesseract version when available.
- Added setup/testing documentation:
  - `docs/OCR_SETUP_AND_TESTING_GUIDE.md`
  - `docs/V0_8_OCR_VALIDATION.md`

## Validation

Unit test suite:

```text
34 passed
```

Local environment used for smoke validation has:

```text
tesseract 5.5.0
pytesseract importable
```

Small Tesseract route smoke, using the bundled scanned-image example at `--dpi 72`:

```text
Total pages: 2
Tesseract attempted/usable/improved: 2/1/1
weak/missing native pages: 2
total OCR word gain: 64
```

OpenAI OCR dry-run selection smoke, using an intentionally loose local candidate policy to verify routing without provider calls:

```text
Total pages: 2
Matches: 1
OpenAI OCR selected/attempted/usable: 2/0/0
openai_ocr_skip_reason: dry_run
```

## Recommended next local benchmark

Run the medium corpus with real OCR at production-intended DPI:

```bash
dupe-engine eval-all ./synthetic_corpus_v2_medium/pdfs \
  --truth ./synthetic_corpus_v2_medium/synthetic_v2_truth_pairs.json \
  --dpi 150 \
  --ocr \
  --out output/v08_ocr_results.json \
  --eval-out output/v08_ocr_eval.json \
  --pages-out output/v08_ocr_pages.json \
  --calibration-out output/v08_ocr_calibration.json \
  --candidate-summary-csv output/v08_ocr_candidate_summary.csv \
  --false-positive-csv output/v08_ocr_false_positive_review.csv \
  --false-negative-csv output/v08_ocr_false_negative_review.csv \
  --threshold-sweep-csv output/v08_ocr_threshold_sweep.csv \
  --ocr-validation-out output/v08_ocr_validation.json \
  --ocr-route-csv output/v08_ocr_routes.csv \
  --ocr-candidate-csv output/v08_ocr_candidates.csv
```

Then inspect:

```text
output/v08_ocr_validation.json
output/v08_ocr_routes.csv
output/v08_ocr_candidates.csv
```

## How to judge the run

Look for:

```text
truth_ocr_dependent_recall
truth_ocr_dependent_false_negative_count
tesseract_improved_pages
pages_remaining_weak_after_ocr
openai_ocr_selected_pages
known_negative_hit_count
candidate volume per 100 pages
main review list recall
```

If Tesseract improves weak pages but recall remains low, try OpenAI OCR dry-run to inspect fallback candidates. If OCR improves text but not candidates, the next issue is probably text matching/top-k or embeddings.
