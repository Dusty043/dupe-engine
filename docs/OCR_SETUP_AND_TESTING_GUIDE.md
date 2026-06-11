# OCR Setup and Testing Guide

This guide is for v0.8 OCR validation. The goal is not to make OCR mandatory everywhere; the goal is to prove whether OCR improves duplicate recall, especially for scanned/faxed/rasterized medical-record pages, while keeping provider calls explainable.

## 1. What OCR layers exist

The v0.8 OCR route is:

```text
native PDF text
-> Tesseract OCR for weak/missing native text
-> selected OpenAI-compatible OCR fallback for high-value weak-OCR candidate pages
```

Native PDF text is always attempted first by PyMuPDF. Tesseract is the cheap local worker tier. In v0.9.3, OpenAI OCR fallback is required for production-style local review/calibration runs, but it remains policy-gated to selected deterministic candidates where local text/OCR is not enough.

## 2. Install local dependencies

### Python dependencies

From the project root:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e '.[ocr,dev]'
```

On Windows PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e '.[ocr,dev]'
```

The `ocr` extra installs `pytesseract`. You still need the system `tesseract` executable separately.

### Tesseract engine

Linux / Debian / Ubuntu:

```bash
sudo apt update
sudo apt install tesseract-ocr
```

macOS with Homebrew:

```bash
brew install tesseract
```

Windows:

1. Install a current Tesseract Windows build.
2. Add the install folder containing `tesseract.exe` to `PATH`, or set `DUPE_TESSERACT_CMD` to the full path.
3. Example environment setting:

```powershell
$env:DUPE_TESSERACT_CMD = "C:\Program Files\Tesseract-OCR\tesseract.exe"
```

Validate the executable:

```bash
tesseract --version
```

Validate Python wrapper access:

```bash
python - <<'PY'
import pytesseract
print(pytesseract.get_tesseract_version())
print(pytesseract.get_languages(config='')[:10])
PY
```

## 3. Capability check

Run:

```bash
dupe-engine doctor --ocr
```

Expected healthy local OCR shape:

```text
tesseract_ocr: available
ocr: available
openai_ocr_fallback: disabled
```

Machine-readable check:

```bash
dupe-engine doctor --ocr --json
```

If Tesseract is missing, the engine should not crash by default. It should report the unavailable tier and continue unless `--require-ocr` is used.

Strict check:

```bash
dupe-engine doctor --ocr --require-ocr
```

## 4. Small OCR smoke run

Use one bundled scanned-image example first. This is a route/capability check, not the final accuracy benchmark.

```bash
mkdir -p output/small_ocr_input
cp ./examples/synthetic_medical_pdf_corpus/pdfs/case06_ocr_scanned_image_only_pages.pdf output/small_ocr_input/

dupe-engine compare-all output/small_ocr_input \
  --dpi 72 \
  --ocr \
  --out output/small_ocr_results.json \
  --pages-out output/small_ocr_pages.json \
  --ocr-validation-out output/small_ocr_validation.json \
  --ocr-route-csv output/small_ocr_routes.csv \
  --ocr-candidate-csv output/small_ocr_candidates.csv
```

Use `--dpi 72` here only to make the smoke run quick. Use a stronger DPI such as `--dpi 150` for the actual OCR validation benchmark.

Read these first:

```text
output/small_ocr_validation.json
output/small_ocr_routes.csv
```

What to look for:

```text
native_weak_or_missing_pages
tesseract_attempted_pages
tesseract_usable_pages
tesseract_improved_pages
pages_remaining_weak_after_ocr
total_ocr_word_gain
```

## 5. Synthetic v2 medium OCR validation

Recommended local command for a real v0.8 benchmark:

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

Use `--dpi 72` only for a quick smoke run. Use `--dpi 150` or a calibrated production DPI for OCR validation numbers.

## 6. Optional OpenAI OCR dry-run

Dry-run records which pages would be escalated and why, without sending images to a provider:

```bash
dupe-engine eval-all ./synthetic_corpus_v2_medium/pdfs \
  --truth ./synthetic_corpus_v2_medium/synthetic_v2_truth_pairs.json \
  --dpi 150 \
  --ocr \
  --openai-ocr \
  --openai-ocr-dry-run \
  --openai-ocr-max-pages 25 \
  --openai-ocr-min-candidate-confidence 0.60 \
  --out output/v08_ocr_dry_results.json \
  --eval-out output/v08_ocr_dry_eval.json \
  --ocr-validation-out output/v08_ocr_dry_validation.json \
  --ocr-route-csv output/v08_ocr_dry_routes.csv \
  --ocr-candidate-csv output/v08_ocr_dry_candidates.csv
```

Expected dry-run behavior:

```text
openai_ocr_selected_pages > 0 if weak OCR pages were selected
openai_ocr_attempted_pages = 0
openai_ocr_skip_reason = dry_run
openai_ocr_selection_reason populated per selected page
```

If dry-run selects zero pages, that can be valid: it usually means no high-value weak-OCR deterministic candidates were found. For a pure routing smoke test only, you can temporarily loosen candidate policy on a tiny synthetic input:

```bash
mkdir -p output/openai_ocr_dryrun_input
cp ./examples/synthetic_medical_pdf_corpus/pdfs/case04_same_page_different_scan_quality.pdf output/openai_ocr_dryrun_input/

dupe-engine compare-all output/openai_ocr_dryrun_input \
  --dpi 72 \
  --ocr \
  --openai-ocr \
  --openai-ocr-dry-run \
  --openai-ocr-min-candidate-confidence 0.0 \
  --multipass-visual-all-pages \
  --loose-phash-threshold 64 \
  --disable-low-info-filter \
  --disable-low-info-suppression \
  --out output/openai_ocr_dryrun_results.json \
  --pages-out output/openai_ocr_dryrun_pages.json \
  --ocr-validation-out output/openai_ocr_dryrun_validation.json \
  --ocr-route-csv output/openai_ocr_dryrun_routes.csv \
  --ocr-candidate-csv output/openai_ocr_dryrun_candidates.csv
```

Do not use those loosened thresholds as production settings. They are only a forced-path smoke test to prove selected pages, escalation reasons, and dry-run skip reasons are recorded.

## 7. Optional OpenAI OCR live run

Only use this after approval for the data being processed.

```bash
export DUPE_OPENAI_API_KEY="..."
# or export DUPE_OPENAI_OCR_API_KEY="..."
```

Then run without `--openai-ocr-dry-run`:

```bash
dupe-engine eval-all ./synthetic_corpus_v2_medium/pdfs \
  --truth ./synthetic_corpus_v2_medium/synthetic_v2_truth_pairs.json \
  --dpi 150 \
  --ocr \
  --openai-ocr \
  --openai-ocr-max-pages 25 \
  --out output/v08_openai_ocr_results.json \
  --eval-out output/v08_openai_ocr_eval.json \
  --ocr-validation-out output/v08_openai_ocr_validation.json \
  --ocr-route-csv output/v08_openai_ocr_routes.csv \
  --ocr-candidate-csv output/v08_openai_ocr_candidates.csv
```

Provider images and extracted text can contain PHI in real use. Keep `DUPE_INCLUDE_TEXT_PREVIEW=false` unless there is explicit approval to log text previews.

## 8. Interpreting v0.8 OCR outputs

### `ocr_validation.json`

Main sections:

```text
summary
ocr_route_rows
ocr_candidate_rows
openai_ocr_escalation_rows
ocr_truth_pairs
ocr_false_negative_rows
```

Key summary fields:

```text
native_weak_or_missing_pages
tesseract_attempted_pages
tesseract_usable_pages
tesseract_improved_pages
openai_ocr_selected_pages
openai_ocr_attempted_pages
openai_ocr_usable_pages
openai_ocr_improved_pages
truth_ocr_dependent_duplicate_count
truth_ocr_dependent_true_positive_count
truth_ocr_dependent_false_negative_count
truth_ocr_dependent_recall
overall_recall_on_must_match
```

### `ocr_routes.csv`

One row per page. Use it to inspect OCR routing and text improvements without opening huge JSON.

Important columns:

```text
native_text_status
native_word_count
best_text_source
best_word_count
best_word_gain_over_native
ocr_route
tesseract_attempted
tesseract_usable
tesseract_confidence
tesseract_profile
openai_ocr_selected
openai_ocr_attempted
openai_ocr_selection_reason
openai_ocr_skip_reason
```

### `ocr_candidates.csv`

Only candidates where OCR or weak text is relevant. Use it to check whether OCR pages are creating useful duplicate candidates or just noise.

## 9. Pass/fail questions for v0.8

v0.8 is successful if the run answers these questions clearly:

```text
Was Tesseract installed and available?
How many pages had weak/missing native text?
How many weak/missing pages did Tesseract improve?
Which duplicate truth pairs are OCR-dependent?
Did OCR recover any OCR-dependent truth pairs?
Which pages would OpenAI OCR escalate, and why?
Did OpenAI OCR improve matching when run live?
What is the candidate/noise impact after OCR?
```

v0.8 does not need to hit final v1 recall. It needs to prove whether OCR is the correct next lever and identify exactly where it helps or fails.

## 10. v0.8.1 AI route ledger during OCR tests

When testing OpenAI-compatible OCR fallback, add the route ledger outputs:

```bash
--ai-ledger-out output/ai_ledger.json \
--ai-ledger-csv output/ai_ledger.csv
```

The ledger separates `vision_ocr_extraction` from later `text_embedding` and adjudication routes. This matters when one approved OpenAI key is used for multiple logical AI layers.

For dry-run OCR tests, the expected ledger status is usually:

```text
route=vision_ocr_extraction
status=dry_run_skipped
selected=true
attempted=false
```

For live OCR tests, the useful validation columns are:

```text
attempted
succeeded
changed_evidence
error
reason
model
metadata_json
```

The ledger does not write extracted page text by default.
